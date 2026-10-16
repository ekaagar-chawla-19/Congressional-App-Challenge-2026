"""Read the Raspberry Pi field sensors.

Wiring assumed (change the constants for your build):
* DHT11 temperature + humidity  -> data pin GPIO4            (adafruit-circuitpython-dht)
* capacitive soil-moisture probe -> ADS1115 ADC channel A0    (adafruit-circuitpython-ads1x15; the Pi has no analog input)
* BH1750 light sensor           -> I2C (SDA/SCL)              (adafruit-circuitpython-bh1750)

  pip install adafruit-circuitpython-dht adafruit-circuitpython-ads1x15 adafruit-circuitpython-bh1750

Any sensor that is missing or fails is reported as None (shown as N/A in the app);
the others still work. Soil moisture is converted from the probe's voltage with a
two-point calibration: measure the probe in air (dry) and in a glass of water (wet)
and set SOIL_DRY_V / SOIL_WET_V. The DHT11 reads 0-50 °C (+-2 °C) and 20-90 % RH
(+-5 %): it cannot measure winter lows below freezing.
"""

from __future__ import annotations

import time

DHT_PIN = "D4"
SOIL_CHANNEL = 0
SOIL_DRY_V = 2.80   # probe voltage in dry air   (calibrate!)
SOIL_WET_V = 1.20   # probe voltage in water     (calibrate!)


def soil_pct_from_voltage(v: float, dry: float = SOIL_DRY_V, wet: float = SOIL_WET_V) -> float:
    return round(max(0.0, min(100.0, 100 * (dry - v) / (dry - wet))), 1)


def _dht() -> tuple[float | None, float | None]:
    try:
        import adafruit_dht
        import board
    except ImportError:
        return None, None
    dev = adafruit_dht.DHT11(getattr(board, DHT_PIN))
    try:
        for _ in range(5):  # DHT reads fail often; retry
            try:
                t, h = dev.temperature, dev.humidity
                if t is not None and h is not None:
                    return float(t), float(h)
            except RuntimeError:
                pass
            time.sleep(2)
        return None, None
    finally:
        dev.exit()


def _soil() -> float | None:
    try:
        import adafruit_ads1x15.ads1115 as ADS
        import board
        import busio
        from adafruit_ads1x15.analog_in import AnalogIn
    except ImportError:
        return None
    try:
        ads = ADS.ADS1115(busio.I2C(board.SCL, board.SDA))
        return soil_pct_from_voltage(AnalogIn(ads, SOIL_CHANNEL).voltage)
    except (OSError, ValueError):
        return None


def _light() -> float | None:
    try:
        import adafruit_bh1750
        import board
        import busio
    except ImportError:
        return None
    try:
        return round(float(adafruit_bh1750.BH1750(busio.I2C(board.SCL, board.SDA)).lux), 0)
    except (OSError, ValueError):
        return None


def read_all() -> dict:
    t, h = _dht()
    return {"soil_moisture_pct": _soil(), "air_temp_c": t, "humidity_pct": h, "light_lux": _light()}


if __name__ == "__main__":
    print(read_all())
