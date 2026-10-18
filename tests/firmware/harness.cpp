// Runs the firmware's measure() for a list of sensor scenarios and prints one JSON line each.
#include "arduino_stub.h"

int g_adc = 0;
float g_temp = 0, g_hum = 0, g_lux = 0;
int g_dht_fail_reads = 0;
unsigned long g_millis = 0;

DHT dht(4, DHT11);
BH1750 lightMeter;
bool lightOk = true;
String deviceName = "HS-ESP32-1A2B";

#include "extracted.inc"  // firmware defines + soilPct(), num(), measure() copied verbatim by the test

struct Scenario { const char *name; int adc; float t, h, lux; int dht_fail; bool light_ok; };

int main() {
  Scenario sc[] = {
      {"normal", 2210, 21.0f, 64.0f, 5400.0f, 0, true},
      {"dry_soil", 3000, 30.5f, 35.0f, 25000.0f, 0, true},
      {"wet_soil", 1300, 18.0f, 88.0f, 300.0f, 0, true},
      {"probe_disconnected_high", 4095, 21.0f, 60.0f, 5000.0f, 0, true},
      {"probe_disconnected_low", 0, 21.0f, 60.0f, 5000.0f, 0, true},
      {"dht_fails_once_then_ok", 2500, 22.0f, 70.0f, 5000.0f, 1, true},
      {"dht_dead", 2500, 0, 0, 5000.0f, 99, true},
      {"no_light_sensor", 2500, 22.0f, 70.0f, 0, 0, false},
      {"light_sensor_error", 2500, 22.0f, 70.0f, -2.0f, 0, true},
      {"freezing_edge", 2600, 0.0f, 95.0f, 12.0f, 0, true},
  };
  for (auto &s : sc) {
    g_adc = s.adc; g_temp = s.t; g_hum = s.h; g_lux = s.lux; g_dht_fail_reads = s.dht_fail; lightOk = s.light_ok;
    printf("%s\t%s\n", s.name, measure().c_str());
  }
}
