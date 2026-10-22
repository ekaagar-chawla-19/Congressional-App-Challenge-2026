# Offline web app (GitHub Pages, `final` branch)

The phone-only version of HemlockID runs in Safari. You open a link once on Wi‑Fi and add it to the Home
Screen. From then on it runs with no internet and no Mac: both models run inside the browser on the phone.
Nothing is installed through Xcode and Developer Mode is not needed.

## What is here

| Path | What it is |
| --- | --- |
| `web/lib/engine.js` | Photo decoding, the server's preprocessing in JavaScript, and running Model Delta/Gamma with ONNX Runtime Web |
| `web/sw.js` | Service worker: keeps the site and both models on the phone so it works offline |
| `web/speedtest/` | Offline test page: speed per photo, and whether the phone's output matches the server's |
| `web/build.sh` | Builds the site: `web/` + both models + ONNX Runtime Web 1.30.0 (downloaded at build time) |
| `scripts/web_reference.py` | Records what the Python server computes for the test image (`web/speedtest/reference.json`) |
| `.github/workflows/pages.yml` | Builds and publishes the site on every push to `final` |

## How it matches the server

`engine.js` follows `preprocessing.py` and `pipeline/runtime.py` step by step:

* JPEG draft scaling (1/2, 1/4, 1/8 while the short side stays ≥ 640 px).
* OpenCV's INTER_AREA when shrinking, rounded like OpenCV's 8-bit output.
* Python's round-half-to-even when computing sizes.
* The same centre crop (Delta, 322 px) and the same five 448 px crops (Gamma).

The test page compares the phone's embedding with the server's for the same image. In Chromium here, both
models matched at 100.00% cosine similarity, online and with the network switched off.

## Publishing (one-time setup by the repo owner)

GitHub Pages only publishes from a **public** repo on a free account (private repos need GitHub Pro, which
students can get free with the GitHub Student Developer Pack).

1. Make the repo public: Settings → General → Danger Zone → Change visibility.
   Everything in the repo becomes public, including both models.
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Re-run the latest "Web app (GitHub Pages)" workflow (Actions tab), or push to `final`.

The site is then at `https://ekaagar-chawla-19.github.io/Congressional-App-Challenge-2026/`. The test page is
at `…/speedtest/`.

## Limits

* **Bluetooth:** iPhone browsers have no Web Bluetooth, so ESP32 readings are typed or pasted.
* **First load:** it downloads about 175 MB of models; do it on Wi‑Fi.
* **Storage:** iOS can still clear website data when the phone is almost out of space.
