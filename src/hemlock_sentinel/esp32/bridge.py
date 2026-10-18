"""Laptop side of the ESP32 sensor node: read it over Bluetooth LE or USB and send to hemlock-api.

The phone app reads the ESP32 itself (Bluetooth button on the survey screen); this
command is for laptops, testing and USB-connected nodes.

    hemlock-esp32 scan                                   # find nodes (HS-ESP32-xxxx)
    hemlock-esp32 read                                   # nearest node over BLE
    hemlock-esp32 read --serial /dev/cu.usbserial-0001   # over USB (macOS name; COM3 on Windows)
    hemlock-esp32 visit H-012 --forest 1 --email demo@hemlock.test --password hemlock-demo
    hemlock-esp32 identify p1.jpg p2.jpg p3.jpg --forest 1 --email ... --password ... [--lat .. --lon ..]

BLE uses `bleak` (macOS, Windows, Linux), USB uses `pyserial`:
    pip install -e ".[esp32]"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from .api_client import ApiCallError, ApiClient
from .reading import COMMAND_UUID, NAME_PREFIX, READING_UUID, SERVICE_UUID, BadReading, parse_reading

MEASURE_WAIT_S = 6.0  # longest wait for a fresh reading (the DHT11 may need a ~2 s retry)


# ------------------------------------------------------------------ USB serial
def read_serial_stream(stream, timeout: float = 8.0) -> dict:
    """``stream``: an open pyserial port (or any object with write/readline)."""
    stream.write(b"r\n")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        line = stream.readline()
        if not line:
            continue
        try:
            return parse_reading(line.strip())
        except BadReading:
            continue  # boot messages, upload logs, ...
    raise TimeoutError("no reading from the ESP32 on this port (is the firmware flashed? 115200 baud)")


def read_serial(port: str, timeout: float = 8.0) -> dict:
    try:
        import serial
    except ImportError:
        raise SystemExit('USB needs pyserial: pip install -e ".[esp32]"') from None
    with serial.Serial(port, 115200, timeout=1) as s:
        time.sleep(0.5)
        s.reset_input_buffer()
        return read_serial_stream(s, timeout)


# ------------------------------------------------------------------ Bluetooth LE
def _bleak():
    try:
        import bleak
    except ImportError:
        raise SystemExit('Bluetooth needs bleak: pip install -e ".[esp32]"') from None
    return bleak


async def scan(timeout: float = 6.0) -> list[tuple[str, str, int | None]]:
    bleak = _bleak()
    found = await bleak.BleakScanner.discover(timeout=timeout, return_adv=True)
    out = []
    for dev, adv in found.values():
        name = dev.name or adv.local_name or ""
        if name.startswith(NAME_PREFIX) or SERVICE_UUID in [u.lower() for u in adv.service_uuids]:
            out.append((dev.address, name, adv.rssi))
    return sorted(out, key=lambda d: -(d[2] or -999))


async def read_ble(address: str | None = None, timeout: float = 10.0) -> dict:
    bleak = _bleak()
    if address is None:
        nodes = await scan(timeout)
        if not nodes:
            raise TimeoutError("no Hemlock Sentinel ESP32 found nearby (powered on? within ~10 m?)")
        address = nodes[0][0]  # strongest signal = nearest
    async with bleak.BleakClient(address, timeout=timeout) as client:
        # The node notifies when the new reading is ready; reading at a fixed delay could return the
        # previous one. Without a notification in time, read the characteristic as a fallback.
        fresh: asyncio.Future = asyncio.get_running_loop().create_future()

        def on_notify(_char, data: bytearray) -> None:
            if not fresh.done():
                try:
                    fresh.set_result(parse_reading(bytes(data)))
                except BadReading:
                    pass  # e.g. truncated by a small MTU; the read below gets the whole value

        try:
            await client.start_notify(READING_UUID, on_notify)
            subscribed = True
        except Exception:  # noqa: BLE001  (some stacks refuse notify; reading still works)
            subscribed = False
        await client.write_gatt_char(COMMAND_UUID, b"r", response=False)
        try:
            return await asyncio.wait_for(fresh, MEASURE_WAIT_S)
        except asyncio.TimeoutError:
            return parse_reading(bytes(await client.read_gatt_char(READING_UUID)))
        finally:
            if subscribed:
                try:
                    await client.stop_notify(READING_UUID)
                except Exception:  # noqa: BLE001
                    pass


def read_node(args) -> dict:
    return read_serial(args.serial) if args.serial else asyncio.run(read_ble(args.address))


# ------------------------------------------------------------------ CLI
def _show(reading: dict) -> None:
    s = reading["sensors"]
    fmt = {"soil_moisture_pct": "%", "air_temp_c": " °C", "humidity_pct": "%", "light_lux": " lux"}
    print(f"{reading['device'] or 'ESP32'}: " + ", ".join(
        f"{k}={'N/A' if v is None else f'{v:g}{fmt[k]}'}" for k, v in s.items()))


def _findings(res: dict) -> list[str]:
    return [f"  {f['name']}: {f['level']} ({f['likelihood']:.0%})" for f in res.get("findings", [])
            if f["level"] != "unknown"]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="list nearby ESP32 sensor nodes")
    for name in ("read", "visit", "identify"):
        p = sub.add_parser(name)
        p.add_argument("--address", help="BLE address (default: nearest node)")
        p.add_argument("--serial", metavar="PORT", help="read over USB instead, e.g. /dev/cu.usbserial-0001 or COM3")
        if name != "read":
            p.add_argument("--api", default="http://localhost:8000")
            p.add_argument("--email", required=True)
            p.add_argument("--password", required=True)
            p.add_argument("--forest", type=int, required=True)
            p.add_argument("--severity", type=int, choices=[0, 1, 2, 3])
            p.add_argument("--signs", help="comma-separated, e.g. hwa_wool,needle_loss")
            p.add_argument("--lat", type=float)
            p.add_argument("--lon", type=float)
        if name == "visit":
            p.add_argument("tree_id")
        if name == "identify":
            p.add_argument("photos", nargs="+", type=Path, help="3 trunk photos (north, +90°, +180°)")
            p.add_argument("--no-sensors", action="store_true", help="photos only")
    args = ap.parse_args(argv)

    if args.cmd == "scan":
        nodes = asyncio.run(scan())
        for addr, name, rssi in nodes:
            print(f"{addr}  {name}  RSSI {rssi}")
        if not nodes:
            print("no nodes found")
        return

    reading = None
    if not getattr(args, "no_sensors", False):
        reading = read_node(args)
        _show(reading)
    if args.cmd == "read":
        return

    api = ApiClient(args.api, args.email, args.password)
    signs = [x.strip() for x in args.signs.split(",")] if args.signs else []
    try:
        if args.cmd == "visit":
            payload = {"sensors": reading["sensors"], "signs": signs, "severity": args.severity}
            if args.lat is not None and args.lon is not None:
                payload["location"] = {"lat": args.lat, "lon": args.lon}
            res = api.visit(args.tree_id, payload, args.forest)
            print(f"visit stored for {res['tree_id']}")
        else:
            fields = {"lat": args.lat, "lon": args.lon, "severity": args.severity,
                      "signs": ",".join(signs) or None, **(reading["sensors"] if reading else {})}
            res = api.identify([p.read_bytes() for p in args.photos], fields, args.forest)
            who = res["tree_id"] or (res.get("best_guess") or {}).get("note") or res["message"]
            print(f"{res['status']}: {who}")
        print("\n".join(_findings(res)))
    except ApiCallError as e:
        print(f"ERROR {e.error.get('code')}: {e.error.get('message')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
