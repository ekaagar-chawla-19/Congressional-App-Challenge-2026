// Hemlock Sentinel field sensor node: its own Wi-Fi network + a small JSON API (ESP32, Arduino core 3.x).
//
// The node is a Wi-Fi access point. The phone joins it like any Wi-Fi network and talks HTTP to it,
// which works in Expo Go and any browser (Bluetooth needed a native build or Web Bluetooth).
//
//   Wi-Fi name:  HS-ESP32-xxxx    (xxxx = this board's ID; printed on the serial monitor at boot)
//   password:    AP_PASS below
//   node:        http://192.168.4.1        (also http://hemlock.local where mDNS works, e.g. iPhone)
//
// API (JSON; CORS open so a web page can call it too). Contract shared with
// src/hemlock_sentinel/esp32/wifi.py (laptop client + simulated node) and mobile/src/esp32.ts.
//   GET  /api/v1/status          {"v":1,"device","firmware","uptime_s","simulated","clients",
//                                 "battery_pct","battery_v","latest_seq","log_count","log_every_s"}
//                                (battery_pct / battery_v: null without a battery divider, see power.h)
//   GET  /api/v1/reading         latest reading (see reading_json.h), measured every READ_EVERY_MS
//   POST /api/v1/measure         measure now and return that reading (takes up to ~2.5 s)
//   GET  /api/v1/readings?since=N  logged readings with seq > N, oldest first, at most 50:
//                                 {"readings":[...],"latest_seq","uptime_s","more":bool}
//                                 (kept in RAM, one per LOG_EVERY_MS; lost on power-off)
// Errors: {"error":{"code","message"}} with a 4xx status.
// USB serial (115200): one JSON line per reading; send "r" to measure now.
//
// Demo tip: the computer running hemlock-api can join this network too (it gets 192.168.4.x). Then the
// phone reaches both the node and the backend without switching Wi-Fi.
//
// Board: "ESP32 Dev Module", default partition scheme. Libraries and wiring: see sensors.h. Battery: power.h.

#include <Arduino.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <WiFi.h>

#include "power.h"
#include "sensors.h"

// ------------------------------------------------------------------ config
#define FIRMWARE_VERSION "wifi-1.1.0"
#define AP_PASS "hemlock-sentinel"   // at least 8 characters
#define AP_CHANNEL 6
#define AP_MAX_CLIENTS 4
#define MDNS_NAME "hemlock"          // http://hemlock.local
#define READ_EVERY_MS 10000UL        // refresh the latest reading
#define LOG_EVERY_MS 60000UL         // add one reading to the log
#define LOG_SIZE 360                 // 6 h at one per minute
#define PAGE_MAX 50

WebServer server(80);
String deviceName;
Reading latest;
bool haveLatest = false;
unsigned long nextSeq = 1, lastRead = 0, lastLog = 0;
Reading logBuf[LOG_SIZE];
int logHead = 0, logCount = 0;  // ring buffer: logHead = next write slot
float battV = NAN;              // refreshed with each reading

Reading takeReading() {
  Reading r = sensorsRead();
  battV = batteryVolts();
  r.seq = nextSeq++;
  r.uptime_s = millis() / 1000;
  latest = r;
  haveLatest = true;
  lastRead = millis();
  Serial.println(readingJson(r, deviceName));
  return r;
}

void logReading(const Reading &r) {
  logBuf[logHead] = r;
  logHead = (logHead + 1) % LOG_SIZE;
  if (logCount < LOG_SIZE) logCount++;
  lastLog = millis();
}

// ------------------------------------------------------------------ HTTP
void sendJson(int code, const String &body) {
  server.sendHeader("Cache-Control", "no-store");
  server.send(code, "application/json", body);
}

void sendError(int code, const char *errCode, const String &message) {
  sendJson(code, String("{\"error\":{\"code\":\"") + errCode + "\",\"message\":\"" + message + "\"}}");
}

void handleStatus() {
  String j = "{\"v\":1,\"device\":\"" + deviceName + "\"";
  j += ",\"firmware\":\"" FIRMWARE_VERSION "\"";
  j += ",\"uptime_s\":" + String(millis() / 1000);
  j += ",\"simulated\":" + String(sensorsSimulated() ? "true" : "false");
  j += ",\"clients\":" + String(WiFi.softAPgetStationNum());
  j += ",\"battery_pct\":" + jsonNum(batteryPct(battV), 0);
  j += ",\"battery_v\":" + jsonNum(battV, 2);
  j += ",\"latest_seq\":" + String(haveLatest ? latest.seq : 0UL);
  j += ",\"log_count\":" + String(logCount);
  j += ",\"log_every_s\":" + String(LOG_EVERY_MS / 1000) + "}";
  sendJson(200, j);
}

void handleReading() {
  if (!haveLatest) takeReading();
  sendJson(200, readingJson(latest, deviceName));
}

void handleMeasure() { sendJson(200, readingJson(takeReading(), deviceName)); }

void handleReadings() {
  unsigned long since = 0;
  if (server.hasArg("since")) {
    String a = server.arg("since");
    for (unsigned i = 0; i < a.length(); i++)
      if (!isDigit(a[i])) return sendError(400, "bad_since", "since must be a whole number");
    since = strtoul(a.c_str(), nullptr, 10);
  }
  String j = "{\"readings\":[";
  int sent = 0;
  bool more = false;
  int oldest = (logHead - logCount + LOG_SIZE) % LOG_SIZE;
  for (int i = 0; i < logCount; i++) {
    const Reading &r = logBuf[(oldest + i) % LOG_SIZE];
    if (r.seq <= since) continue;
    if (sent == PAGE_MAX) { more = true; break; }
    if (sent++) j += ",";
    j += readingJson(r, deviceName);
  }
  j += "],\"latest_seq\":" + String(haveLatest ? latest.seq : 0UL);
  j += ",\"uptime_s\":" + String(millis() / 1000);
  j += ",\"more\":" + String(more ? "true" : "false") + "}";
  sendJson(200, j);
}

void handleRoot() {
  server.send(200, "text/plain",
              deviceName + " (Hemlock Sentinel sensor node, " FIRMWARE_VERSION ")\n"
              "GET /api/v1/status\nGET /api/v1/reading\nPOST /api/v1/measure\nGET /api/v1/readings?since=0\n");
}

void handleNotFound() {
  if (server.method() == HTTP_OPTIONS) {  // CORS preflight
    server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
    return server.send(204);
  }
  sendError(404, "not_found", "no such endpoint: " + server.uri());
}

// ------------------------------------------------------------------ main
void setup() {
  Serial.begin(115200);
  powerBegin();
  sensorsBegin();

  char id[8];
  snprintf(id, sizeof(id), "%04X", (uint16_t)(ESP.getEfuseMac() >> 32));
  deviceName = String("HS-ESP32-") + id;

  WiFi.mode(WIFI_AP);
  WiFi.softAP(deviceName.c_str(), AP_PASS, AP_CHANNEL, 0, AP_MAX_CLIENTS);  // 192.168.4.1
  if (MDNS.begin(MDNS_NAME)) MDNS.addService("http", "tcp", 80);

  server.enableCORS(true);
  server.on("/", HTTP_GET, handleRoot);
  server.on("/api/v1/status", HTTP_GET, handleStatus);
  server.on("/api/v1/reading", HTTP_GET, handleReading);
  server.on("/api/v1/measure", HTTP_POST, handleMeasure);
  server.on("/api/v1/readings", HTTP_GET, handleReadings);
  server.onNotFound(handleNotFound);
  server.begin();

  Serial.println("{\"event\":\"ready\",\"device\":\"" + deviceName + "\",\"ssid\":\"" + deviceName +
                 "\",\"ip\":\"" + WiFi.softAPIP().toString() + "\",\"firmware\":\"" FIRMWARE_VERSION "\"}");
  logReading(takeReading());
}

void loop() {
  server.handleClient();
  while (Serial.available())
    if (Serial.read() == 'r') takeReading();
  if (millis() - lastRead >= READ_EVERY_MS) takeReading();
  if (millis() - lastLog >= LOG_EVERY_MS) logReading(latest);
  powerLoop(battV);
  delay(2);
}
