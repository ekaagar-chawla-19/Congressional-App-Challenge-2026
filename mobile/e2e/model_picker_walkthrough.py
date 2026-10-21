"""Phone-size walkthrough (python mobile/e2e/model_picker_walkthrough.py, Playwright) of the model picker against the real hemlock-api (both real models loaded):
pick gamma -> AI-guided scan -> result says gamma + species not checked -> explainer -> health check with a pasted ESP32 reading ->
diagnosis -> add another ESP32 reading from the tree page -> rescan with delta (switch mid-scan) -> same tree -> add a forest."""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import os

# BARK: a folder with visit1_0..2.jpg and visit2_0..2.jpg, two sets of bark photos of ONE hemlock (e.g. BarkNet
# PRU photos of one tree). APP: the Expo web app (npx expo start --web); hemlock-api must run with both models.
BARK = Path(os.environ.get("BARK", "e2e/bark"))
APP = os.environ.get("APP", "http://localhost:8081")
SHOTS = Path(os.environ.get("SHOTS", "e2e/shots"))
SHOTS.mkdir(parents=True, exist_ok=True)
CHROMIUM = os.environ.get("CHROMIUM")  # e.g. /opt/pw-browsers/chromium; default: Playwright's own
errors, notes = [], []
DRY = json.dumps({"v": 1, "device": "HS-ESP32-1A2B", "soil_moisture_pct": 8.5, "air_temp_c": 31.4, "humidity_pct": 36,
                  "light_lux": 25000, "soil_raw": 3050})
WET = json.dumps({"v": 1, "device": "HS-ESP32-1A2B", "soil_moisture_pct": 44, "air_temp_c": 18.2, "humidity_pct": 83,
                  "light_lux": 2100})


def shot(page, name):
    page.wait_for_timeout(700)
    page.screenshot(path=str(SHOTS / f"{name}.png"))
    print("shot", name, flush=True)


def vis(page, text, exact=False):
    return page.get_by_text(text, exact=exact).locator("visible=true").first


def label(page, name):
    return page.get_by_label(name, exact=True).locator("visible=true").first


def pick(page, files):
    with page.expect_file_chooser() as fc:
        label(page, "Choose photos from library").or_(vis(page, "Use photos from the library")).first.click()
    fc.value.set_files([str(BARK / f) for f in files])


def choose_model(page, name):
    page.get_by_role("radio", name=re.compile(f"^{name}")).locator("visible=true").first.click()
    page.get_by_role("button", name=f"Scan with {name}").locator("visible=true").first.click()


def scan(page, files, name):
    pick(page, files)
    # the AI-guided card says what the evidence needs; with 3 good photos it says to identify (or asks for one more)
    page.get_by_text(re.compile("Tap Identify|One more view|Close-up next|save it for review")).locator("visible=true").first \
        .wait_for(timeout=120_000)
    notes.append(f"{name} guidance: " + " | ".join(l for l in page.inner_text("body").split("\n") if l.strip())[:220])
    shot(page, f"guide_{name}")
    vis(page, "Identify", exact=True).click()
    page.get_by_text("Hemlock check").locator("visible=true").first.wait_for(timeout=180_000)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROMIUM, args=["--no-proxy-server"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("PAGEERROR " + str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(APP, timeout=180_000)
    vis(page, "Get started").wait_for(timeout=180_000)
    vis(page, "Get started").click()
    vis(page, "Trying it out?").click()
    vis(page, "Sign in", exact=True).click()
    vis(page, "Cooper Creek Scenic Area, Chattahoochee NF").wait_for(timeout=60_000)
    vis(page, "Cooper Creek Scenic Area, Chattahoochee NF").click()
    vis(page, "Scan a tree").wait_for()

    # 1. The picker opens before the first photo
    vis(page, "Scan a tree").click()
    vis(page, "Choose a model").wait_for(timeout=30_000)
    page.get_by_role("radio", name=re.compile("^Model Gamma")).locator("visible=true").first.wait_for(timeout=30_000)
    shot(page, "01_picker_default")
    page.get_by_role("radio", name=re.compile("^Model Gamma")).locator("visible=true").first.click()
    shot(page, "02_picker_gamma_selected")
    page.get_by_role("button", name="Scan with Model Gamma").locator("visible=true").first.click()
    page.wait_for_timeout(3000)
    shot(page, "03_camera_gamma")
    label(page, "Model: Model Gamma. Change model").wait_for(timeout=30_000)

    # 2. Scan with gamma
    scan(page, ["visit1_0.jpg", "visit1_1.jpg", "visit1_2.jpg"], "gamma")
    shot(page, "04_result_gamma")
    body = page.inner_text("body")
    assert "Model Gamma" in body and "Not checked" in body, body[:400]
    page.mouse.wheel(0, 700)
    shot(page, "05_result_gamma_lower")
    # the explainer: three story steps, tap to advance, segmented bar
    vis(page, "How did it match?").or_(vis(page, "How does matching work?")).first.click()
    vis(page, "Bark becomes a fingerprint").wait_for(timeout=30_000)
    shot(page, "05a_explainer_1")
    label(page, "Next step").click()
    vis(page, "The same ridges line up").wait_for()
    shot(page, "05b_explainer_2")
    vis(page, "Next", exact=True).click()
    vis(page, "Match, new tree, or one more photo").wait_for()
    shot(page, "05c_explainer_3")
    vis(page, "Done", exact=True).click()
    page.wait_for_timeout(1000)
    first = vis(page, "Register new tree").or_(page.get_by_role("button", name=re.compile("^Yes, this is"))).first
    first.click()

    # 3. Health check with a pasted ESP32 reading
    vis(page, "How does it look?").wait_for(timeout=30_000)
    vis(page, "Paste reading").click()
    label(page, "ESP32 reading JSON").fill(DRY)
    vis(page, "Use reading").click()
    vis(page, "Reading from HS-ESP32-1A2B").wait_for()
    assert label(page, "Soil moisture").input_value() == "8.5"
    vis(page, "Browning in a dry spell").click()
    page.mouse.wheel(0, 900)
    shot(page, "06_health_esp32_filled")
    vis(page, "Save and see diagnosis").click()
    page.get_by_text("Possible causes").locator("visible=true").first.wait_for(timeout=60_000)
    tree_id = page.inner_text("body").split("\n")
    shot(page, "07_tree_after_health")
    body = page.inner_text("body")
    assert "Drought stress" in body, body[:600]

    # 4. Add more data later: another ESP32 reading from the tree page
    vis(page, "Add ESP32 reading").scroll_into_view_if_needed()
    vis(page, "Add ESP32 reading").click()
    vis(page, "Add an ESP32 reading").wait_for()
    vis(page, "Paste reading").click()
    label(page, "ESP32 reading JSON").fill(WET)
    vis(page, "Use reading").click()
    shot(page, "08_add_reading")
    vis(page, "Save and update diagnosis").click()
    vis(page, "Updated diagnosis").wait_for(timeout=60_000)
    shot(page, "09_updated_diagnosis")
    vis(page, "Back to the tree").click()
    page.get_by_text("Possible causes").locator("visible=true").first.wait_for(timeout=30_000)
    # the digital twin: what changed, the next action, the fused environment and the sensor history
    vis(page, "Next action").wait_for(timeout=30_000)
    shot(page, "09a_tree_twin")
    vis(page, "Sensor history").scroll_into_view_if_needed()
    shot(page, "09b_sensor_history")
    body = page.inner_text("body")
    assert "Low water stress" in body and "wetter by" in body and "VPD" in body, body[:1500]

    # 5. Rescan with delta; switch models after one photo (the scan restarts)
    vis(page, "Scan this tree again").scroll_into_view_if_needed()
    vis(page, "Scan this tree again").click()
    vis(page, "Choose a model").wait_for(timeout=30_000)
    shot(page, "10_picker_remembers_gamma")
    choose_model(page, "Model Gamma")
    label(page, "Model: Model Gamma. Change model").wait_for(timeout=30_000)
    pick(page, ["visit2_0.jpg"])
    page.wait_for_timeout(6000)
    label(page, "Model: Model Gamma. Change model").click()
    page.get_by_role("radio", name=re.compile("^Model Delta")).locator("visible=true").first.click()
    vis(page, "starts this scan again").wait_for()
    shot(page, "11_switch_warning")
    page.get_by_role("button", name="Scan with Model Delta").locator("visible=true").first.click()
    label(page, "Model: Model Delta. Change model").wait_for(timeout=30_000)
    shot(page, "12_camera_delta")
    scan(page, ["visit2_0.jpg", "visit2_1.jpg", "visit2_2.jpg"], "delta")
    shot(page, "13_result_delta")
    body = page.inner_text("body")
    assert "Model Delta" in body, body[:400]
    notes.append("delta result: " + " | ".join(body.split("\n")[:8]))
    page.mouse.wheel(0, 700)
    shot(page, "14_result_delta_lower")

    # 6. Add a forest
    page.goto(APP + "/forests")
    vis(page, "New forest").wait_for(timeout=60_000)
    vis(page, "New forest").click()
    label(page, "Forest name").fill("Walkthrough Woods")
    page.get_by_role("checkbox").locator("visible=true").first.click()  # no location in the browser
    shot(page, "15_new_forest")
    vis(page, "Add forest").click()
    page.wait_for_timeout(3000)
    shot(page, "16_after_new_forest")
    page.goto(APP + "/forests")
    vis(page, "Walkthrough Woods").wait_for(timeout=30_000)
    shot(page, "17_forest_list")

    b.close()

print("NOTES:", *notes, sep="\n  ")
print("ERRORS:", errors[:12])
sys.exit(1 if [e for e in errors if "401" not in e] else 0)
