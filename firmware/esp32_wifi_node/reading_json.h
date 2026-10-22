// The reading as JSON: the same v1 format the BLE node (firmware/esp32_sensors) prints, plus "seq".
// Parsed by src/hemlock_sentinel/esp32/reading.py and mobile/src/esp32reading.ts; any sensor that
// failed is null (shown as N/A). Only uses String, so tests/firmware compiles it on a computer.
#pragma once

struct Reading {
  float soil_moisture_pct;  // NAN = sensor failed / not fitted
  float air_temp_c;
  float humidity_pct;
  float light_lux;
  int soil_raw;             // raw ADC value, -1 = none
  unsigned long seq;        // counts up from 1 since power-on
  unsigned long uptime_s;   // when it was taken (the node has no clock)
  int light_raw;            // raw ADC value of the light sensor, -1 = none (0 if left out of an initializer)
};

inline String jsonNum(float v, int decimals) { return isnan(v) ? String("null") : String(v, decimals); }

inline String readingJson(const Reading &r, const String &device) {
  String j = "{\"v\":1,\"device\":\"" + device + "\"";
  j += ",\"seq\":" + String(r.seq);
  j += ",\"soil_moisture_pct\":" + jsonNum(r.soil_moisture_pct, 1);
  j += ",\"air_temp_c\":" + jsonNum(r.air_temp_c, 1);
  j += ",\"humidity_pct\":" + jsonNum(r.humidity_pct, 0);
  j += ",\"light_lux\":" + jsonNum(r.light_lux, 0);
  j += ",\"soil_raw\":" + (r.soil_raw < 0 ? String("null") : String(r.soil_raw));
  j += ",\"light_raw\":" + (r.light_raw < 0 ? String("null") : String(r.light_raw));
  j += ",\"uptime_s\":" + String(r.uptime_s) + "}";
  return j;
}
