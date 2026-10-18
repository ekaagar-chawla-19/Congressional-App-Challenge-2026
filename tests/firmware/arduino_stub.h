// Minimal host stand-ins for the Arduino core and sensor libraries used by
// firmware/esp32_sensors/esp32_sensors.ino, so its measurement and JSON code can be compiled
// and run on a computer (tests/integration/test_esp32_simulated.py). Values come from globals
// that the test harness sets per scenario.
#pragma once
#include <cmath>
#include <cstdio>
#include <string>

struct String {
  std::string s;
  String() {}
  String(const char *c) : s(c) {}
  String(const std::string &x) : s(x) {}
  String(int v) : s(std::to_string(v)) {}
  String(unsigned long v) : s(std::to_string(v)) {}
  String(float v, int decimals) {  // Arduino: fixed-point with `decimals` digits
    char b[64];
    snprintf(b, sizeof b, "%.*f", decimals, (double)v);
    s = b;
  }
  String operator+(const String &o) const { return String(s + o.s); }
  String operator+(const char *o) const { return String(s + o); }
  String &operator+=(const String &o) { s += o.s; return *this; }
  String &operator+=(const char *o) { s += o; return *this; }
  const char *c_str() const { return s.c_str(); }
};
inline String operator+(const char *a, const String &b) { return String(std::string(a) + b.s); }

#define NAN_F NAN
inline float constrain(float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; }
using std::isnan;

// sensor inputs for the current scenario
extern int g_adc;
extern float g_temp, g_hum, g_lux;
extern int g_dht_fail_reads;  // first N DHT reads return NaN
extern unsigned long g_millis;
inline int analogRead(int) { return g_adc; }
inline void delay(unsigned long ms) { g_millis += ms; }
inline unsigned long millis() { return g_millis; }

struct DHT {
  DHT(int, int) {}
  float readTemperature() { return g_dht_fail_reads > 0 ? (g_dht_fail_reads--, NAN) : g_temp; }
  float readHumidity() { return g_dht_fail_reads > 0 ? NAN : g_hum; }
};
#define DHT11 11
struct BH1750 {
  float readLightLevel() { return g_lux; }
};
