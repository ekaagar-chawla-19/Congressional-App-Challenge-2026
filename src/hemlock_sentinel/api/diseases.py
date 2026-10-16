"""Hemlock health conditions: knowledge base, evidence rules, recommendations.

What can tell us what (sources: docs/research/hemlock_health.md):
* Insects are confirmed by SEEING them: woolly ovisacs (HWA) or scale covers (EHS)
  on twig/needle undersides, by the observer or in a close-up twig photo.
  Trunk-bark photos (what the identity model uses) cannot show either.
* Crown symptoms (gray-green foliage, needle loss, no new growth, dieback) say the
  tree is declining, not why: they are shared by HWA, EHS and drought.
* ESP32 sensors measure conditions, not disease: low soil moisture + heat + dry air
  = drought stress (which speeds decline under HWA); a very cold reading lowers
  HWA winter survival. They raise or lower RISK only, never confirm anything.

assess() combines these into a likelihood per condition with the evidence behind
it, so every number shown in the app can be explained.
"""

from __future__ import annotations

import datetime as dt

SIGNS: dict[str, str] = {
    "hwa_wool": "White cottony/woolly masses (1-3 mm) at the base of needles on twig undersides",
    "ehs_scale": "Small brown, elongated scale covers (or white waxy specks) stuck to needle undersides",
    "needle_yellow_banding": "Yellow banding or mottling on the upper side of needles",
    "gray_green_foliage": "Foliage looks dull gray-green instead of dark glossy green",
    "needle_loss": "Thin crown / premature needle drop (you can see through the crown)",
    "no_new_growth": "Little or no new light-green shoot growth in spring",
    "branch_dieback": "Dead or dying branches (often starting low and inside the crown)",
    "drought_browning": "Needles browning or yellowing during a dry spell, wilted new shoots",
    "borer_holes": "Small oval/D-shaped exit holes (3-5 mm) in the bark, woodpecker flaking, resin streaks",
    "root_rot_signs": "White fungal fans under bark at the base, black shoestring strands, or honey mushrooms",
    "twigs_checked_clean": "I checked the undersides of several twigs and found no wool or scales",
}

# 0-3 severity, as rated by the observer (proposal from docs/research/hemlock_health.md)
SEVERITY_GUIDE = {
    0: "No wool/scales on ~100 tips checked, crown full (<25% see-through), new growth present",
    1: "Up to ~10% of tips infested and/or crown 25-40% see-through",
    2: "~10-50% of tips infested, crown 40-60% see-through, little new growth",
    3: ">50% of tips infested, crown >60% see-through, dieback",
}

CONDITIONS: dict[str, dict] = {
    "hwa": {
        "name": "Hemlock woolly adelgid (HWA)",
        "type": "invasive insect",
        "summary": "Aphid-like insect that feeds at needle bases; kills untreated hemlocks in roughly 4-10 years "
                   "in the southern Appalachians. The main threat to hemlocks in North Georgia.",
        "confirm": "Look at the underside of the outer twigs on several low branches, ideally November-June when "
                   "the white wool is present. Wool at needle bases = HWA (spider egg sacs and spittle are "
                   "found elsewhere and wipe off differently). Report new finds to the Georgia Forestry Commission.",
        "recommendations": [
            "Confirm by checking twig undersides on several branches (Nov-June is easiest); photograph a close-up.",
            "Treat valuable trees with a systemic insecticide applied by a licensed applicator: imidacloprid "
            "(soil or trunk; slow to act on large trees, protects for several years) or dinotefuran (basal bark "
            "spray; acts within weeks, shorter protection). Often combined: dinotefuran first, imidacloprid for "
            "long-term protection. Follow the label; no soil applications near streams or wet soils.",
            "Ask about biological control releases (Laricobius beetles, silver flies) through the Georgia Forestry "
            "Commission or Save Georgia's Hemlocks for larger stands.",
            "Prioritize trees with healthy crowns: heavily declined trees (more than ~50% crown loss) respond poorly.",
            "Avoid moving hemlock branches or nursery stock from infested areas; avoid nitrogen fertilizer "
            "(it favors the adelgid).",
        ],
    },
    "ehs": {
        "name": "Elongate hemlock scale (EHS)",
        "type": "invasive insect",
        "summary": "Armored scale on needle undersides that causes yellow banding and needle drop; often found "
                   "together with HWA and less controlled by imidacloprid.",
        "confirm": "Turn branches over: brown, elongated covers about 1.5-2 mm (females) and smaller white waxy "
                   "covers (males) on needle undersides, with yellow bands on the needle tops. A hand lens helps; "
                   "an extension office can confirm from a sample.",
        "recommendations": [
            "Confirm with a hand lens or send a sample to your county extension office.",
            "Dinotefuran (systemic) is generally more effective against EHS than imidacloprid; horticultural oil "
            "sprays can be used on small reachable trees. Use a licensed applicator for large trees.",
            "If HWA is also present, choose a treatment that covers both (ask the applicator).",
        ],
    },
    "drought_stress": {
        "name": "Drought stress and secondary decline (root rot, borers)",
        "type": "abiotic stress, then fungi/insects",
        "summary": "Hemlocks are shallow-rooted streamside trees; drought weakens them, speeds HWA decline, lowers "
                   "insecticide uptake, and invites Armillaria root rot and hemlock borer. The only threat the ESP32 "
                   "sensors can measure directly.",
        "confirm": "Repeated low soil-moisture readings in a dry season with whole-crown dulling, and no insects on "
                   "the twigs. Check the trunk base for fungal fans/mushrooms and the bark for small exit holes. "
                   "Samples can go to the UGA Plant Disease Clinic through your county extension office. The app "
                   "alone can never confirm this.",
        "recommendations": [
            "Water high-value trees during drought: a slow, deep soak over the root zone about every 1-2 weeks.",
            "Mulch 5-10 cm over the root zone, kept off the trunk; avoid compaction, root damage and grade changes.",
            "Do not apply soil insecticides to drought-stressed trees: water first, treat when soil is moist.",
            "No nitrogen fertilizer.",
            "If root rot or borers are found, or a dying tree stands near trails or buildings, call an "
            "ISA-certified arborist: dead hemlocks fail quickly.",
            "Re-check soil moisture on the next visits; one dry reading is not a diagnosis.",
        ],
    },
}

# ------------------------------------------------------------- sensor rules
# Heuristic thresholds (not published standards): calibrate the soil probe per site.
WARN_SOIL_PCT = 22.0
DRY_SOIL_PCT = 15.0
HOT_C = 32.0
DRY_AIR_PCT = 40.0
HIGH_VPD_KPA = 1.5       # evaporative demand (general plant physiology)
HWA_COLD_KILL_C = -20.0  # substantial HWA mortality at or below; a DHT11 cannot read below 0 degC
LOW_LIGHT_LUX = 1000.0   # too dark for reliable visual checks


def vpd_kpa(temp_c: float, rh_pct: float) -> float:
    """Vapour-pressure deficit (Tetens)."""
    import math

    es = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return es * (1 - rh_pct / 100)


def _level(p: float) -> str:
    return "likely" if p >= 0.7 else "possible" if p >= 0.35 else "low"


def assess(signs: list[str] | None, sensors: dict | None, severity: int | None = None,
           when: float | None = None, has_images: bool = False, ai: dict[str, float] | None = None) -> list[dict]:
    """Per-condition findings for one visit: [{condition, likelihood 0-1, level, evidence[]}].

    level: likely / possible / low, or "unknown" when the visit has no evidence that could show the
    condition (e.g. bark photos only: the insects live on twigs)."""
    s = set(signs or [])
    sensors = sensors or {}
    ai = ai or {}
    month = dt.datetime.fromtimestamp(when, dt.timezone.utc).month if when else None
    summer = month is not None and 6 <= month <= 9
    decline = len(s & {"gray_green_foliage", "needle_loss", "no_new_growth", "branch_dieback"})
    t, hum, soil = sensors.get("air_temp_c"), sensors.get("humidity_pct"), sensors.get("soil_moisture_pct")
    twigs_seen = bool(s & {"hwa_wool", "ehs_scale", "twigs_checked_clean"}) or bool(ai)
    out = []

    def add(cond, p, ev):
        out.append({"condition": cond, "likelihood": round(p, 2), "level": _level(p), "evidence": ev})

    def unknown(cond, why):
        out.append({"condition": cond, "likelihood": 0.0, "level": "unknown", "evidence": [why]})

    # HWA: confirmed only by seeing wool on twig undersides
    ev, p = [], 0.0
    if "hwa_wool" in s:
        p, ev = 0.9, ["observed: white wool at needle bases (diagnostic sign)"]
        if severity is not None and severity >= 2:
            p = 0.95
            ev.append(f"observer severity rating {severity}")
    elif ai.get("hwa_wool", 0) >= 0.3:
        p = 0.35 + 0.4 * ai["hwa_wool"]
        ev.append(f"AI photo check suggests wool at needle bases (confidence {ai['hwa_wool']:.0%}); "
                  "confirm by eye before treating")
    elif "twigs_checked_clean" in s:
        p = 0.25 if summer else 0.08
        ev.append("twig undersides checked, no wool found")
        if summer:
            ev.append("June-September: wool is sparse during summer dormancy, so a clean check is weak evidence; "
                      "re-check November-June")
        if decline:
            p += 0.1
            ev.append(f"crown decline signs ({decline}) present")
    elif decline:
        p = 0.2 + 0.08 * decline
        ev.append(f"crown decline signs ({decline}) fit HWA but are not specific; check twig undersides")
    if t is not None and t <= HWA_COLD_KILL_C and p:
        p = max(0.05, p - 0.15)
        ev.append(f"reading of {t:.0f} °C: cold this severe kills many adelgids")
    if p:
        add("hwa", p, ev)
    elif not twigs_seen:
        unknown("hwa", "not assessed: needs a check of twig undersides" +
                (" (trunk-bark photos cannot show HWA)" if has_images else ""))

    # EHS: confirmed only by seeing scales on needle undersides
    ev, p = [], 0.0
    if "ehs_scale" in s:
        p, ev = 0.85, ["observed: scale covers on needle undersides (diagnostic sign)"]
        if "needle_yellow_banding" in s:
            p = 0.92
            ev.append("observed: yellow banding on needle tops")
    elif ai.get("ehs_scale", 0) >= 0.3:
        p, ev = 0.3 + 0.4 * ai["ehs_scale"], [f"AI photo check suggests scale covers (confidence "
                                              f"{ai['ehs_scale']:.0%}); confirm with a hand lens"]
    elif "needle_yellow_banding" in s or ai.get("needle_yellow_banding", 0) >= 0.5:
        p, ev = 0.4, ["yellow banding is typical of EHS; confirm by finding scales on needle undersides"]
    elif "twigs_checked_clean" in s:
        p, ev = 0.08, ["needle undersides checked, no scales found"]
    if p:
        add("ehs", p, ev)
    elif not twigs_seen:
        unknown("ehs", "not assessed: needs a check of needle undersides")

    # Drought stress + secondary decline: the sensors measure the stress side
    ev, p = [], 0.0
    if soil is not None:
        if soil < DRY_SOIL_PCT:
            p += 0.45
            ev.append(f"soil moisture {soil:.0f}% (dry, below {DRY_SOIL_PCT:.0f}%)")
        elif soil < WARN_SOIL_PCT:
            p += 0.2
            ev.append(f"soil moisture {soil:.0f}% (getting dry)")
    if t is not None and hum is not None:
        v = vpd_kpa(t, hum)
        if v >= HIGH_VPD_KPA:
            p += 0.15
            ev.append(f"high evaporative demand (VPD {v:.1f} kPa from {t:.0f} °C, {hum:.0f}% RH)")
    elif t is not None and t >= HOT_C:
        p += 0.1
        ev.append(f"air temperature {t:.0f} °C")
    if "drought_browning" in s:
        p += 0.3
        ev.append("observed: browning/wilting during a dry spell")
    for k, txt in (("borer_holes", "borer exit holes in bark"), ("root_rot_signs", "root-rot signs at the base")):
        if k in s:
            p += 0.3
            ev.append(f"observed: {txt} (secondary attackers of stressed trees)")
    if p and decline and "twigs_checked_clean" in s:
        p += 0.1
        ev.append("crown decline without insects on the twigs points to abiotic stress")
    if p:
        add("drought_stress", min(0.9, p), ev)
    elif soil is None and not s & {"drought_browning", "borer_holes", "root_rot_signs"}:
        unknown("drought_stress", "not assessed: no soil-moisture reading or stress signs recorded")

    lux = sensors.get("light_lux")
    if lux is not None and lux < LOW_LIGHT_LUX:
        for f in out:
            if f["level"] != "unknown":
                f["evidence"].append(f"low light at the visit ({lux:.0f} lux): small signs are easy to miss")
    return sorted(out, key=lambda f: -f["likelihood"])


def recommendations(condition_counts: dict[str, int]) -> list[dict]:
    """Recommendations for the conditions present, most common first."""
    return [{"condition": c, "name": CONDITIONS[c]["name"], "trees_affected": n,
             "steps": CONDITIONS[c]["recommendations"], "how_to_confirm": CONDITIONS[c]["confirm"]}
            for c, n in sorted(condition_counts.items(), key=lambda kv: -kv[1]) if n and c in CONDITIONS]


GENERAL_ADVICE = [
    "Confirm any suspected pest with a 10x hand lens and report new finds to the Georgia Forestry Commission or "
    "your UGA Extension county office; Save Georgia's Hemlocks offers treatment guidance and volunteer help.",
    "The app never gives pesticide doses: follow the product label and use a licensed applicator, especially "
    "near streams (imidacloprid is highly toxic to aquatic life) and for trees over ~15 in DBH.",
    "Don't move hemlock branches, firewood or nursery stock from infested areas; visit infested trees last and "
    "clean gear (birds, deer and people carry crawlers in spring).",
]


def guide() -> dict:
    return {"conditions": CONDITIONS, "signs": SIGNS, "severity_scale": SEVERITY_GUIDE,
            "general_advice": GENERAL_ADVICE,
            "sensor_thresholds": {"warn_soil_pct": WARN_SOIL_PCT, "dry_soil_pct": DRY_SOIL_PCT, "hot_c": HOT_C,
                                  "high_vpd_kpa": HIGH_VPD_KPA, "hwa_cold_kill_c": HWA_COLD_KILL_C},
            "note": "Insects are confirmed by seeing them on twig/needle undersides. Sensors indicate stress and "
                    "risk, never a diagnosis. Trunk-bark photos cannot show HWA or EHS, so with bark photos only "
                    "their status is unknown, never healthy. Thresholds are heuristic; see "
                    "docs/research/hemlock_health.md."}
