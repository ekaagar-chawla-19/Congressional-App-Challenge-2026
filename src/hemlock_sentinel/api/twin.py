"""A tree's digital twin: its sensor history, what changed since the last visit and the next thing to do.

Everything here is derived from the stored visits (signs, severity, findings and ESP32 readings), with fixed
rules, so each sentence the app shows can be traced back to a number. The environment summary fuses the four
readings into one plain sentence (soil water, evaporative demand from temperature + humidity as VPD, light)
and compares it with the previous reading.
"""

from __future__ import annotations

from .diseases import CONDITIONS, DRY_SOIL_PCT, HIGH_VPD_KPA, LOW_LIGHT_LUX, WARN_SOIL_PCT, vpd_kpa

SEVERITY = {0: "healthy", 1: "light decline", 2: "moderate decline", 3: "severe decline"}
SOIL_STEP = 5.0  # % points: smaller soil-moisture changes are within the probe's noise
VPD_STEP = 0.3   # kPa
TEMP_STEP = 3.0  # degC


def _vpd(s: dict) -> float | None:
    t, h = s.get("air_temp_c"), s.get("humidity_pct")
    return round(vpd_kpa(t, h), 2) if t is not None and h is not None else None


def sensor_history(observations: list[dict]) -> list[dict]:
    """Every visit with an ESP32 reading, newest first."""
    out = []
    for o in reversed(observations):
        s = o.get("sensors")
        if s and any(v is not None for v in s.values()):
            out.append({"observation_id": o["observation_id"], "timestamp": o["timestamp"], "sensors": s,
                        "vpd_kpa": _vpd(s)})
    return out


def environment(history: list[dict]) -> dict | None:
    """The latest reading as one sentence, and how it moved since the reading before."""
    if not history:
        return None
    s, vpd = history[0]["sensors"], history[0]["vpd_kpa"]
    soil, lux = s.get("soil_moisture_pct"), s.get("light_lux")
    parts = []
    if soil is not None:
        parts.append("dry soil" if soil < DRY_SOIL_PCT else "soil getting dry" if soil < WARN_SOIL_PCT else "moist soil")
    if vpd is not None:
        parts.append("thirsty air" if vpd >= HIGH_VPD_KPA else "mild air")
    if lux is not None and lux < LOW_LIGHT_LUX:
        parts.append("low light")
    stress = (soil is not None and soil < WARN_SOIL_PCT) + (vpd is not None and vpd >= HIGH_VPD_KPA)
    verdict = ["Low water stress", "Some water stress", "High water stress"][stress]
    summary = f"{verdict}: {', '.join(parts)}." if parts else "Only a partial reading."

    changes = []
    if len(history) >= 2:
        p, pv = history[1]["sensors"], history[1]["vpd_kpa"]
        if soil is not None and p.get("soil_moisture_pct") is not None:
            d = soil - p["soil_moisture_pct"]
            if abs(d) >= SOIL_STEP:
                changes.append(f"Soil {'wetter' if d > 0 else 'drier'} by {abs(d):.0f} points")
        if vpd is not None and pv is not None and abs(vpd - pv) >= VPD_STEP:
            changes.append(f"Air {'thirstier' if vpd > pv else 'calmer'} (VPD {pv:.1f} → {vpd:.1f} kPa)")
        t, pt = s.get("air_temp_c"), p.get("air_temp_c")
        if t is not None and pt is not None and abs(t - pt) >= TEMP_STEP:
            changes.append(f"{abs(t - pt):.0f} °C {'warmer' if t > pt else 'cooler'}")
        if not changes:
            changes.append("Conditions about the same as last reading")
    return {"summary": summary, "vpd_kpa": vpd, "water_stress": ["low", "some", "high"][stress], "changes": changes}


def _known(o: dict) -> dict[str, float]:
    return {f["condition"]: f["likelihood"] for f in o.get("findings", []) if f["level"] != "unknown"}


def since_last_visit(observations: list[dict]) -> list[str]:
    """Plain lines comparing the last two visits that recorded health or sensor data (oldest-first input), so a
    photo-only rescan does not read as "no change"."""
    assessed = [o for o in observations if o.get("severity") is not None or _known(o) or o.get("sensors")]
    if len(assessed) < 2:
        return []
    a, b = assessed[-2], assessed[-1]
    out = []
    sa, sb = a.get("severity"), b.get("severity")
    if sa is not None and sb is not None and sa != sb:
        out.append(f"Health {'worse' if sb > sa else 'better'}: {SEVERITY.get(sa, sa)} → {SEVERITY.get(sb, sb)}")
    ka, kb = _known(a), _known(b)
    for c in CONDITIONS:
        if c in ka and c in kb and abs(kb[c] - ka[c]) >= 0.15:
            out.append(f"{CONDITIONS[c]['name']} {'more' if kb[c] > ka[c] else 'less'} likely "
                       f"({ka[c]:.0%} → {kb[c]:.0%})")
    new = set(b.get("signs", [])) - set(a.get("signs", [])) - {"twigs_checked_clean"}
    if new:
        out.append(f"{len(new)} new sign{'s' if len(new) > 1 else ''} recorded")
    return out or ["No change in health since the last visit"]


def next_action(observations: list[dict], current: list[dict], env: dict | None) -> str:
    """One line: the most useful next step for this tree. current: the latest finding per condition."""
    likely = [f for f in current if f["level"] == "likely"]
    if any(f["condition"] == "hwa" for f in likely):
        return "Report the adelgid and plan treatment with a licensed applicator."
    if any(f["condition"] == "ehs" for f in likely):
        return "Confirm the scale with a hand lens, then plan treatment."
    unknown = [f for f in current if f["level"] == "unknown" and f["condition"] in ("hwa", "ehs")]
    if unknown:
        return "Check the undersides of a few twigs for wool or scale."
    if any(f["condition"] == "drought_stress" and f["level"] in ("likely", "possible") for f in current):
        return "Water stress: re-check soil moisture after the next dry week."
    if env is None:
        return "Take an ESP32 reading on the next visit."
    if observations and observations[-1].get("severity") is None:
        return "Rate the crown on the next visit."
    return "Re-scan in about 3 months to keep its history going."


def twin(observations: list[dict], current: list[dict]) -> dict:
    hist = sensor_history(observations)
    env = environment(hist)
    return {"sensor_history": hist, "environment": env, "since_last_visit": since_last_visit(observations),
            "next_action": next_action(observations, current, env)}
