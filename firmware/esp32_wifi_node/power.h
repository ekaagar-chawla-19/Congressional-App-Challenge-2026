// Battery level and power saving. See docs/esp32_wifi.md, "Run it on a battery".
//
// Battery level: a 1-cell Li-ion/LiPo (3.0-4.2 V) through a divider of two equal resistors
// (100k + 100k: battery + -> 100k -> GPIO36 -> 100k -> GND), so the pin sees half the voltage.
// BATTERY_PIN -1: no divider fitted (USB or a power bank), battery_pct is null.
//
// Power saving (about 100 mA awake with the access point on; a 2000 mAh cell lasts ~18 h awake):
//   * the CPU runs at 80 MHz (plenty for the web server and sensors)
//   * IDLE_SLEEP_MIN minutes with no phone joined -> deep sleep (~10 uA for the chip; the board's USB chip and
//     regulator add a few mA). Press EN (also labelled RST) to wake it: the network is back in ~2 s.
//     (Not BOOT: GPIO0 held low while the chip wakes would start the flasher instead.)
//   * battery below BATTERY_CUTOFF_V -> deep sleep, so the cell is not run flat (wake: EN, after charging)
#pragma once
#include <math.h>

#define BATTERY_PIN -1          // 36 (VP) with the divider fitted; -1 without
#define BATTERY_DIVIDER 2.0f    // battery volts / pin volts
#define BATTERY_CUTOFF_V 3.30f  // sleep below this (on battery only)
#define IDLE_SLEEP_MIN 30       // sleep after this long with no phone joined; 0 = never
#define LED_PIN 2               // on-board LED: a short blink every 3 s while awake; -1 = off

// Resting Li-ion voltage -> charge, piecewise linear (typical 1-cell curve, ~0.5 C or less).
inline float batteryPct(float volts) {
  static const float V[] = {3.30f, 3.50f, 3.61f, 3.69f, 3.76f, 3.84f, 3.92f, 4.02f, 4.10f, 4.20f};
  static const float P[] = {0, 5, 12, 25, 40, 55, 70, 83, 92, 100};
  if (isnan(volts)) return NAN;
  if (volts <= V[0]) return 0;
  for (int i = 1; i < 10; i++)
    if (volts < V[i]) return P[i - 1] + (P[i] - P[i - 1]) * (volts - V[i - 1]) / (V[i] - V[i - 1]);
  return 100;
}

#ifdef ARDUINO
#include <WiFi.h>
#include <esp_sleep.h>

// Battery volts, or NAN without a divider (or when what the pin reads can't be a cell: nothing connected).
inline float batteryVolts() {
#if BATTERY_PIN < 0
  return NAN;
#else
  uint32_t mv = 0;
  for (int i = 0; i < 16; i++) mv += analogReadMilliVolts(BATTERY_PIN);  // factory-calibrated ADC
  float v = mv / 16 / 1000.0f * BATTERY_DIVIDER;
  return v < 2.5f || v > 4.5f ? NAN : v;
#endif
}

inline void powerBegin() {
  setCpuFrequencyMhz(80);
#if BATTERY_PIN >= 0
  analogSetPinAttenuation(BATTERY_PIN, ADC_11db);
#endif
#if LED_PIN >= 0
  pinMode(LED_PIN, OUTPUT);
#endif
}

inline void sleepUntilButton(const char *why) {
  Serial.printf("{\"event\":\"sleep\",\"why\":\"%s\",\"wake\":\"press EN\"}\n", why);
  Serial.flush();
#if LED_PIN >= 0
  digitalWrite(LED_PIN, LOW);
#endif
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_OFF);
  esp_deep_sleep_start();  // no wake source: only EN (a reset) starts it again
}

// Call from loop(): blink, idle sleep, low-battery sleep.
inline void powerLoop(float battVolts) {
  static unsigned long lastPhone = 0, lastBlink = 0;
  unsigned long now = millis();
#if LED_PIN >= 0
  bool low = !isnan(battVolts) && batteryPct(battVolts) < 15;
  if (now - lastBlink >= (low ? 1000UL : 3000UL)) lastBlink = now;  // low battery: blinks every second
  digitalWrite(LED_PIN, now - lastBlink < 30 ? HIGH : LOW);
#endif
  if (WiFi.softAPgetStationNum() > 0) lastPhone = now;
  if (IDLE_SLEEP_MIN > 0 && now - lastPhone >= IDLE_SLEEP_MIN * 60000UL) sleepUntilButton("no phone joined");
  if (!isnan(battVolts) && battVolts < BATTERY_CUTOFF_V) sleepUntilButton("battery low");
}
#endif
