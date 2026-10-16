// Hemlock Sentinel field sensor node (ESP32, Arduino core 3.x).
//
// Reads: capacitive soil-moisture probe (ESP32 ADC), DHT11 air temperature + humidity,
// BH1750 light. Makes the latest reading available three ways:
//   1. Bluetooth Low Energy: the phone app (or `hemlock-esp32 read` on a laptop) reads it
//      and sends it to the backend together with the tree photos.            [default]
//   2. USB serial: one JSON line per reading (115200 baud); send "r\n" to read now.
//   3. Wi-Fi (optional, WIFI_UPLOAD 1): posts the reading as a visit of one tree straight
//      to the backend, e.g. through the phone's hotspot.
//
// Reading JSON (any sensor that fails is null -> shown as N/A in the app):
//   {"v":1,"device":"HS-ESP32-xxxx","soil_moisture_pct":23.4,"air_temp_c":21.0,
//    "humidity_pct":64,"light_lux":5400,"soil_raw":2210,"uptime_s":42}
//
// Wiring (change the pins below for your board):
//   soil probe AOUT -> GPIO34 (ADC1; ADC2 pins don't work while Wi-Fi is on), VCC 3.3V
//   DHT11 DATA      -> GPIO4 (10k pull-up to 3.3V if your module has none)
//   BH1750          -> SDA GPIO21, SCL GPIO22, VCC 3.3V
// Board: "ESP32 Dev Module" (esp32 core 3.x). With WIFI_UPLOAD 1, BLE + Wi-Fi no longer fit the
// default flash layout: choose Tools > Partition Scheme > "Huge APP (3MB No OTA/1MB SPIFFS)".
// (Checked: compiles with arduino-cli for esp32:esp32:esp32, core 3.0.7, both modes.)
// Libraries (Library Manager): "DHT sensor library" (Adafruit) + "Adafruit Unified Sensor",
// "BH1750" (Christopher Laws). BLE, Wi-Fi and HTTP come with the ESP32 core.
//
// Soil calibration: hold the probe in air, note soil_raw -> SOIL_RAW_DRY; put it in a
// glass of water up to the line, note soil_raw -> SOIL_RAW_WET. The DHT11 reads
// 0-50 C (+-2 C) and 20-90 % RH (+-5 %); it cannot see winter lows below freezing.

#include <Arduino.h>
#include <BH1750.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <DHT.h>
#include <Wire.h>

// ------------------------------------------------------------------ config
#define PIN_SOIL 34
#define PIN_DHT 4
#define PIN_SDA 21
#define PIN_SCL 22
#define SOIL_RAW_DRY 3200   // ADC reading in dry air        (calibrate!)
#define SOIL_RAW_WET 1350   // ADC reading in water          (calibrate!)
#define READ_EVERY_MS 10000

#define WIFI_UPLOAD 0       // 1 = also POST each reading to the backend over Wi-Fi
#define WIFI_SSID "your-hotspot"
#define WIFI_PASS "password"
#define API_BASE "http://192.168.1.20:8000"   // the computer running hemlock-api
#define API_TOKEN "paste-token-from-/api/v1/auth/login"  // expires after 30 days
#define FOREST_ID "1"
#define TREE_ID "H-001"     // the tree this node is installed at
#define UPLOAD_EVERY_MS 3600000UL

// Must match hemlock_sentinel/esp32/bridge.py and client/src/esp32.ts
#define SERVICE_UUID "6e1f0001-6d6c-4f2b-9a35-1c3a5e6b7d01"
#define READING_UUID "6e1f0002-6d6c-4f2b-9a35-1c3a5e6b7d01"  // read + notify: reading JSON
#define COMMAND_UUID "6e1f0003-6d6c-4f2b-9a35-1c3a5e6b7d01"  // write "r" = measure now

#if WIFI_UPLOAD
#include <HTTPClient.h>
#include <WiFi.h>
#endif

DHT dht(PIN_DHT, DHT11);
BH1750 lightMeter;
bool lightOk = false;
BLECharacteristic *readingChar = nullptr;
volatile bool measureNow = true;
String deviceName;
String lastJson = "{}";
unsigned long lastRead = 0, lastUpload = 0;

String num(float v, int decimals) { return isnan(v) ? String("null") : String(v, decimals); }

float soilPct(int raw) {
  if (raw <= 0 || raw >= 4095) return NAN;  // disconnected probe reads at the rails
  float pct = 100.0f * (SOIL_RAW_DRY - raw) / float(SOIL_RAW_DRY - SOIL_RAW_WET);
  return constrain(pct, 0.0f, 100.0f);
}

String measure() {
  int raw = 0;
  for (int i = 0; i < 8; i++) raw += analogRead(PIN_SOIL);  // average out ADC noise
  raw /= 8;
  float t = dht.readTemperature(), h = dht.readHumidity();
  if (isnan(t) || isnan(h)) { delay(2100); t = dht.readTemperature(); h = dht.readHumidity(); }
  float lux = lightOk ? lightMeter.readLightLevel() : NAN;
  if (lux < 0) lux = NAN;
  String j = "{\"v\":1,\"device\":\"" + deviceName + "\"";
  j += ",\"soil_moisture_pct\":" + num(soilPct(raw), 1);
  j += ",\"air_temp_c\":" + num(t, 1);
  j += ",\"humidity_pct\":" + num(h, 0);
  j += ",\"light_lux\":" + num(lux, 0);
  j += ",\"soil_raw\":" + String(raw);
  j += ",\"uptime_s\":" + String(millis() / 1000) + "}";
  return j;
}

class CommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override { measureNow = true; }
};

class ServerCallbacks : public BLEServerCallbacks {
  void onDisconnect(BLEServer *s) override { BLEDevice::startAdvertising(); }
};

#if WIFI_UPLOAD
void uploadVisit(const String &reading) {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.begin(String(API_BASE) + "/api/v1/trees/" + TREE_ID + "/visits");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + API_TOKEN);
  http.addHeader("X-Forest-Id", FOREST_ID);
  int code = http.POST("{\"sensors\":" + reading + "}");  // backend ignores the extra keys
  Serial.printf("upload -> HTTP %d\n", code);
  http.end();
}
#endif

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_SOIL, ADC_11db);  // full 0-3.3 V range
  dht.begin();
  Wire.begin(PIN_SDA, PIN_SCL);
  lightOk = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);

  char id[8];
  snprintf(id, sizeof(id), "%04X", (uint16_t)(ESP.getEfuseMac() >> 32));
  deviceName = String("HS-ESP32-") + id;

  BLEDevice::init(deviceName.c_str());
  BLEDevice::setMTU(247);  // whole JSON fits one notification once the phone agrees
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());
  BLEService *svc = server->createService(SERVICE_UUID);
  readingChar = svc->createCharacteristic(
      READING_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  readingChar->addDescriptor(new BLE2902());
  BLECharacteristic *cmd = svc->createCharacteristic(
      COMMAND_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  cmd->setCallbacks(new CommandCallbacks());
  svc->start();
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();

#if WIFI_UPLOAD
  WiFi.begin(WIFI_SSID, WIFI_PASS);
#endif
  Serial.println("{\"event\":\"ready\",\"device\":\"" + deviceName + "\"}");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'r') measureNow = true;
  }
  if (measureNow || millis() - lastRead >= READ_EVERY_MS) {
    measureNow = false;
    lastRead = millis();
    lastJson = measure();
    readingChar->setValue(lastJson.c_str());
    readingChar->notify();
    Serial.println(lastJson);
  }
#if WIFI_UPLOAD
  if (WiFi.status() == WL_CONNECTED && (lastUpload == 0 || millis() - lastUpload >= UPLOAD_EVERY_MS)) {
    lastUpload = millis();
    uploadVisit(lastJson);
  }
#endif
  delay(50);
}
