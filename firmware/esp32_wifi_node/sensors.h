// Sensor layer, kept apart from the Wi-Fi API so the sensors can change without touching it.
//
// Wiring (3-pin modules through the 37-kit shield, powered at 3.3 V: shield 5V pin <- ESP32 3V3):
//   soil probe   S -> shield A3 -> GPIO34   (ADC1: still works while Wi-Fi is on)
//   light (LDR)  S -> shield A2 -> GPIO35   (ADC1)
//   DHT11        D -> shield 6  -> GPIO4
// Needs the libraries "DHT sensor library" (Adafruit) + "Adafruit Unified Sensor".
//
// Calibrate with the raw values the node prints (soil_raw, light_raw):
//   soil:  probe in dry air -> SOIL_RAW_DRY, probe in a glass of water -> SOIL_RAW_WET
//   light: covered with a finger -> LIGHT_RAW_DARK, phone flashlight on it -> LIGHT_RAW_BRIGHT
// The light module is a photoresistor, not a lux meter: light_lux is a rough estimate from
// light_pct (0 % ~ 1 lux, 100 % ~ 30,000 lux), good for "too dark" vs "daylight", not for exact lux.
//
// SIMULATE_SENSORS 1: plausible drifting values instead, for testing the link on a bare board.
#pragma once
#include "reading_json.h"

#define SIMULATE_SENSORS 0

#define PIN_SOIL 34
#define PIN_LIGHT 35
#define PIN_DHT 4
// Measured on the HS-ESP32-1C49 kit modules (2026-10-21). Higher raw = wetter / brighter.
#define SOIL_RAW_DRY 0        // probe in open air
#define SOIL_RAW_WET 2400     // probe prongs in a glass of water (read ~2330-2380)
#define LIGHT_RAW_DARK 0      // finger over it
#define LIGHT_RAW_BRIGHT 3900 // phone flashlight on it (room light was ~1550)

// These kit modules legitimately read 0 (dry soil, dark), so an unplugged sensor (pin floats, usually
// near 0) can't be told apart from a real 0: check the wiring if a value never changes.
inline float rawToPct(int raw, int at0, int at100) {
  float pct = 100.0f * (raw - at0) / float(at100 - at0);
  return constrain(pct, 0.0f, 100.0f);
}

#if SIMULATE_SENSORS
static float simSoil = 34, simTemp = 18, simHum = 70, simLux = 6000;

static float drift(float v, float step, float lo, float hi) {
  float r = (esp_random() % 2001) / 1000.0f - 1.0f;  // -1 .. 1
  return constrain(v + r * step, lo, hi);
}

inline void sensorsBegin() {}

inline Reading sensorsRead() {
  simSoil = drift(simSoil, 0.6f, 5, 95);
  simTemp = drift(simTemp, 0.3f, 2, 35);
  simHum = drift(simHum, 1.0f, 25, 95);
  simLux = drift(simLux, 400, 50, 40000);
  Reading r = {};
  r.soil_moisture_pct = simSoil;
  r.air_temp_c = simTemp;
  r.humidity_pct = simHum;
  r.light_lux = simLux;
  r.soil_raw = int(3200 - simSoil / 100.0f * (3200 - 1350));
  r.light_raw = -1;
  return r;
}
#else
#include <DHT.h>
static DHT dht(PIN_DHT, DHT11);

static int readAdc(int pin) {  // average out ADC noise
  long sum = 0;
  for (int i = 0; i < 16; i++) sum += analogRead(pin);
  return sum / 16;
}

inline void sensorsBegin() {
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_SOIL, ADC_11db);  // full 0-3.3 V range
  analogSetPinAttenuation(PIN_LIGHT, ADC_11db);
  dht.begin();
}

inline Reading sensorsRead() {
  Reading r = {};
  r.soil_raw = readAdc(PIN_SOIL);
  r.soil_moisture_pct = rawToPct(r.soil_raw, SOIL_RAW_DRY, SOIL_RAW_WET);
  r.light_raw = readAdc(PIN_LIGHT);
  float lightPct = rawToPct(r.light_raw, LIGHT_RAW_DARK, LIGHT_RAW_BRIGHT);
  r.light_lux = isnan(lightPct) ? NAN : powf(10.0f, lightPct / 100.0f * 4.5f);  // rough, see above
  float t = dht.readTemperature(), h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {  // the DHT11 misses a read now and then: one retry after its 2 s cycle
    delay(2100);
    t = dht.readTemperature();
    h = dht.readHumidity();
  }
  r.air_temp_c = t;
  r.humidity_pct = h;
  return r;
}
#endif

inline bool sensorsSimulated() { return SIMULATE_SENSORS; }
