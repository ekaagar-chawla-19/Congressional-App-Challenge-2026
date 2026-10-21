"""Digital twin: sensor history, the fused environment sentence, what changed, and the next action."""

from hemlock_sentinel.api.twin import twin


def visit(i, sensors=None, severity=None, signs=(), findings=()):
    return {"observation_id": f"o{i}", "timestamp": f"2026-0{i}-01T12:00:00Z", "sensors": sensors, "severity": severity,
            "signs": list(signs), "findings": [{"condition": c, "likelihood": p, "level": lv} for c, p, lv in findings]}


def test_history_is_newest_first_with_vpd_and_skips_visits_without_readings():
    obs = [visit(1, {"soil_moisture_pct": 30, "air_temp_c": 20, "humidity_pct": 70, "light_lux": 5000}),
           visit(2), visit(3, {"soil_moisture_pct": 18, "air_temp_c": 30, "humidity_pct": 30, "light_lux": None})]
    t = twin(obs, [])
    assert [h["observation_id"] for h in t["sensor_history"]] == ["o3", "o1"]
    assert t["sensor_history"][0]["vpd_kpa"] > 2.5 and t["sensor_history"][1]["vpd_kpa"] < 1
    env = t["environment"]
    assert env["water_stress"] == "high" and env["summary"].startswith("High water stress")
    assert any("drier by 12 points" in c for c in env["changes"])
    assert any("thirstier" in c for c in env["changes"]) and any("10 °C warmer" in c for c in env["changes"])


def test_no_reading_and_steady_reading():
    assert twin([visit(1)], [])["environment"] is None
    s = {"soil_moisture_pct": 35, "air_temp_c": 18, "humidity_pct": 75, "light_lux": 4000}
    env = twin([visit(1, s), visit(2, {**s, "soil_moisture_pct": 33})], [])["environment"]
    assert env["water_stress"] == "low" and env["changes"] == ["Conditions about the same as last reading"]


def test_since_last_visit_and_next_action():
    a = visit(1, severity=0, findings=[("hwa", 0.2, "low")])
    b = visit(2, severity=2, signs=["hwa_wool", "needle_loss"], findings=[("hwa", 0.95, "likely")])
    t = twin([a, b], [{"condition": "hwa", "likelihood": 0.95, "level": "likely"}])
    assert t["since_last_visit"][0] == "Health worse: healthy → moderate decline"
    assert any("adelgid" in line and "20% → 95%" in line for line in t["since_last_visit"])
    assert "2 new signs recorded" in t["since_last_visit"]
    assert "adelgid" in t["next_action"]
    assert twin([a], [])["since_last_visit"] == []
    # a photo-only rescan afterwards: still compares the two visits that were assessed
    assert twin([a, b, visit(3)], [])["since_last_visit"][0] == "Health worse: healthy → moderate decline"
    t = twin([visit(1, severity=0)], [{"condition": "hwa", "likelihood": 0.0, "level": "unknown"}])
    assert "twigs" in t["next_action"]
