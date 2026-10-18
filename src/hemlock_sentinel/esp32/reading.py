"""The ESP32 sensor node's reading format and BLE identifiers (see firmware/esp32_sensors)."""

from __future__ import annotations

import json

SERVICE_UUID = "6e1f0001-6d6c-4f2b-9a35-1c3a5e6b7d01"
READING_UUID = "6e1f0002-6d6c-4f2b-9a35-1c3a5e6b7d01"  # read / notify: reading JSON
COMMAND_UUID = "6e1f0003-6d6c-4f2b-9a35-1c3a5e6b7d01"  # write b"r": measure now
NAME_PREFIX = "HS-ESP32"

SENSOR_KEYS = ("soil_moisture_pct", "air_temp_c", "humidity_pct", "light_lux")
RANGES = {"soil_moisture_pct": (0, 100), "air_temp_c": (-40, 60), "humidity_pct": (0, 100),
          "light_lux": (0, 200_000)}


class BadReading(ValueError):
    pass


def parse_reading(raw: bytes | str) -> dict:
    """Firmware JSON -> {"device", "sensors": {4 keys, None = sensor failed}, "raw": dict}."""
    try:
        text = raw.decode() if isinstance(raw, bytes | bytearray) else raw
        # BLE stacks can pad a characteristic value with NUL bytes; serial lines end in \r\n
        d = json.loads(text.strip().strip("\x00").strip())
    except (ValueError, UnicodeDecodeError) as e:
        raise BadReading(f"not a sensor reading: {raw!r:.80}") from e
    if not isinstance(d, dict) or d.get("v") != 1:
        raise BadReading("not a v1 Hemlock Sentinel reading")
    sensors = {}
    for k in SENSOR_KEYS:
        v = d.get(k)
        if v is not None:
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = None
            lo, hi = RANGES[k]
            if v is not None and not lo <= v <= hi:  # also rejects NaN
                v = None  # a broken sensor reading: report N/A rather than nonsense
        sensors[k] = v
    return {"device": d.get("device"), "sensors": sensors, "raw": d}
