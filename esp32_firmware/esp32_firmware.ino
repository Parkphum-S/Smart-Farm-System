#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include "secrets.h"

// ===== SMART FARM PRO CONFIG =====
#define DEVICE_ID   "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
#define FARM_ID     "farm_001"
#define ZONE_ID     "zone_01"

#define DHT_PIN     4
#define DHT_TYPE    DHT22
#define SOIL_PIN    35

#define RELAY_ACTIVE_LOW true

const uint8_t relayPins[] = {18, 19, 22, 23};
const char* actuatorIds[] = {
  "relay_01", "relay_02", "relay_03", "relay_04"
};
const int RELAY_COUNT = 4;

// ===== SOIL CALIBRATION =====
const int SOIL_DRY_RAW = 3100;
const int SOIL_WET_RAW = 1350;

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastSensorPublish = 0;
const unsigned long SENSOR_INTERVAL_MS = 30000;

unsigned long lastCommandPoll = 0;
const unsigned long COMMAND_POLL_INTERVAL_MS = 5000;

bool relayState[RELAY_COUNT] = {false, false, false, false};

String timestampUTC() {
  struct tm t;
  if (!getLocalTime(&t, 1000) || t.tm_year < 124) {
    return "1970-01-01T00:00:00Z";
  }
  char buffer[25];
  strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &t);
  return String(buffer);
}

void setRelay(int index, bool on) {
  if (index < 0 || index >= RELAY_COUNT) return;
  relayState[index] = on;
  uint8_t level = RELAY_ACTIVE_LOW ? (on ? LOW : HIGH) : (on ? HIGH : LOW);
  digitalWrite(relayPins[index], level);
}

void sendSensorData(float temperature, float humidity, int moisturePercent) {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClient client;
  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/v1/telemetry";

  if (http.begin(client, url)) {
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Device-ID", DEVICE_ID);
    http.addHeader("X-API-Key", DEVICE_API_KEY);
    http.addHeader("x-device-id", DEVICE_ID);
    http.addHeader("x-api-key", DEVICE_API_KEY);

    JsonDocument doc;
    doc["event_id"] = "123e4567-e89b-12d3-a456-426614174000"; // หรือ UUID จำลองที่ถูกต้องตามรูปแบบ
    doc["device_id"] = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"; // หรือ UUID ของ Device ที่ลงทะเบียนไว้
    doc["observed_at"] = timestampUTC();

    JsonArray readings = doc["readings"].to<JsonArray>();

    // 1. อุณหภูมิ (Temperature)
    JsonObject r1 = readings.add<JsonObject>();
    r1["sensor_id"] = "123e4567-e89b-12d3-a456-426614174001"; // ต้องเป็น UUID format
    r1["metric"] = "temperature";
    r1["value"] = temperature;
    r1["unit"] = "celsius";

    // 2. ความชื้นสัมพัทธ์ (Humidity)
    JsonObject r2 = readings.add<JsonObject>();
    r2["sensor_id"] = "123e4567-e89b-12d3-a456-426614174002"; // ต้องเป็น UUID format
    r2["metric"] = "humidity";
    r2["value"] = humidity;
    r2["unit"] = "percent";

    // 3. ความชื้นในดิน (Soil Moisture)
    JsonObject r3 = readings.add<JsonObject>();
    r3["sensor_id"] = "123e4567-e89b-12d3-a456-426614174003"; // ต้องเป็น UUID format
    r3["metric"] = "soil_moisture";
    r3["value"] = moisturePercent;
    r3["unit"] = "percent";

    String payload;
    serializeJson(doc, payload);

    int httpResponseCode = http.POST(payload);

    if (httpResponseCode > 0) {
      Serial.printf("Sensor data sent successfully, Response code: %d\n", httpResponseCode);
      String response = http.getString();
      Serial.println("Server Response: " + response); // เพิ่มบรรทัดนี้เพื่อดูข้อความเต็มๆ
    } else {
      Serial.printf("Error sending sensor data, code: %d (%s)\n", httpResponseCode, http.errorToString(httpResponseCode).c_str());
    }
    http.end();
  } else {
    Serial.println("HTTP Begin failed");
  }
}

void pollCommands() {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClient client;
  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/v1/commands/pending?device_id=" + DEVICE_ID;

  if (http.begin(client, url)) {
    http.addHeader("X-Device-ID", DEVICE_ID);
    http.addHeader("X-API-Key", DEVICE_API_KEY);

    int httpResponseCode = http.GET();

    if (httpResponseCode == HTTP_CODE_OK) {
      String payload = http.getString();
      JsonDocument doc;
      DeserializationError error = deserializeJson(doc, payload);

      if (!error) {
        JsonArray commands = doc["commands"];
        for (JsonObject cmd : commands) {
          const char* actuatorId = cmd["actuator_id"];
          const char* command = cmd["command"];

          int targetIndex = -1;
          for (int i = 0; i < RELAY_COUNT; i++) {
            if (strcmp(actuatorIds[i], actuatorId) == 0) {
              targetIndex = i;
              break;
            }
          }

          if (targetIndex >= 0) {
            bool newState = (strcmp(command, "on") == 0);
            setRelay(targetIndex, newState);
            Serial.printf("Command executed: %s -> %s\n", actuatorId, command);
          }
        }
      }
    }
    http.end();
  }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.printf("\nWiFi connected, IP: %s\n", WiFi.localIP().toString().c_str());
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
}

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < RELAY_COUNT; i++) {
    pinMode(relayPins[i], OUTPUT);
    setRelay(i, false);
  }

  analogReadResolution(12);
  analogSetPinAttenuation(SOIL_PIN, ADC_11db);

  dht.begin();
  connectWiFi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(500);
    return;
  }

  unsigned long now = millis();

  if (now - lastSensorPublish >= SENSOR_INTERVAL_MS) {
    lastSensorPublish = now;

    float temperature = dht.readTemperature();
    float humidity = dht.readHumidity();

    if (!isnan(temperature) && !isnan(humidity)) {
      int soilRaw = analogRead(SOIL_PIN);
      int moisturePercent = map(soilRaw, SOIL_DRY_RAW, SOIL_WET_RAW, 0, 100);
      moisturePercent = constrain(moisturePercent, 0, 100);

      sendSensorData(temperature, humidity, moisturePercent);
    } else {
      Serial.println("DHT reading failed");
    }
  }

  if (now - lastCommandPoll >= COMMAND_POLL_INTERVAL_MS) {
    lastCommandPoll = now;
    pollCommands();
  }
}
