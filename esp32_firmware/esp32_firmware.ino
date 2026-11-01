#include <WiFi.h>
#include "CommandExpiryStatus.h"
#include <HTTPClient.h>
#include <time.h>
#include <sys/time.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "secrets.h"

// ===== SMART FARM PRO CONFIG =====
#define DEVICE_ID   "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
#define FARM_ID     "farm_001"
#define ZONE_ID     "zone_01"

#define DHT_PIN     4
#define DHT_TYPE    DHT22  // AM2305B: ใช้โปรโตคอลตระกูล DHT22
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

bool relayState[RELAY_COUNT] = {false, false, false, false};


// ===== Durable command processing (separate from telemetry) =====
Preferences commandPrefs;
unsigned long lastCommandPoll = 0;
unsigned long lastCommandProcess = 0;
const unsigned long COMMAND_POLL_INTERVAL_MS = 5000;
const unsigned long COMMAND_RETRY_INTERVAL_MS = 2000;
// Runtime safety latch: prevent retries after a rejected result.
bool resultRejectedThisBoot = false;

String prefString(const char* key) {
  return commandPrefs.getString(key, "");
}

void clearStoredCommand() {
  commandPrefs.clear();
  commandPrefs.putString("phase", "idle");
}



static time_t utcToEpoch(const struct tm &utc) {
  const int year = utc.tm_year + 1900;
  const int month = utc.tm_mon + 1;
  const int day = utc.tm_mday;

  const int adjustedYear = year - (month <= 2 ? 1 : 0);
  const int era = adjustedYear / 400;
  const int yearOfEra = adjustedYear - era * 400;
  const int adjustedMonth = month + (month > 2 ? -3 : 9);
  const int dayOfYear =
      (153 * adjustedMonth + 2) / 5 + day - 1;
  const int dayOfEra =
      yearOfEra * 365 + yearOfEra / 4 -
      yearOfEra / 100 + dayOfYear;

  const int64_t days =
      (int64_t)era * 146097 + dayOfEra - 719468;

  const int64_t seconds =
      days * 86400LL +
      utc.tm_hour * 3600LL +
      utc.tm_min * 60LL +
      utc.tm_sec;

  return (time_t)seconds;
}

CommandExpiryStatus checkCommandExpiry(const String& iso) {
  const int len = iso.length();
  if (len < 20) return COMMAND_EXPIRED;

  // Accept Z or a numeric timezone offset such as +07:00 or -05:30.
  int suffixLength = 0;
  int offsetSeconds = 0;

  if (iso.endsWith("Z")) {
    suffixLength = 1;
  } else {
    if (len < 25) return COMMAND_EXPIRED;

    const int signPos = len - 6;
    const char sign = iso.charAt(signPos);

    if ((sign != '+' && sign != '-') ||
        iso.charAt(signPos + 3) != ':') {
      return COMMAND_EXPIRED;
    }

    for (int i : {signPos + 1, signPos + 2,
                  signPos + 4, signPos + 5}) {
      if (iso.charAt(i) < '0' || iso.charAt(i) > '9') {
        return COMMAND_EXPIRED;
      }
    }

    const int offsetHour =
        (iso.charAt(signPos + 1) - '0') * 10 +
        (iso.charAt(signPos + 2) - '0');
    const int offsetMinute =
        (iso.charAt(signPos + 4) - '0') * 10 +
        (iso.charAt(signPos + 5) - '0');

    if (offsetHour > 14 || offsetMinute > 59 ||
        (offsetHour == 14 && offsetMinute != 0)) {
      return COMMAND_EXPIRED;
    }

    offsetSeconds = (offsetHour * 60 + offsetMinute) * 60;
    if (sign == '-') offsetSeconds = -offsetSeconds;
    suffixLength = 6;
  }

  const int timestampEnd = len - suffixLength;
  if (timestampEnd < 19 || timestampEnd > 26) {
    return COMMAND_EXPIRED;
  }

  if (timestampEnd > 19) {
    if (iso.charAt(19) != '.' || timestampEnd < 21) {
      return COMMAND_EXPIRED;
    }

    for (int i = 20; i < timestampEnd; ++i) {
      if (iso.charAt(i) < '0' || iso.charAt(i) > '9') {
        return COMMAND_EXPIRED;
      }
    }
  }

  struct tm parsed = {};
  char text[20];
  iso.substring(0, 19).toCharArray(text, sizeof(text));

  char extra = '\0';
  if (sscanf(text, "%4d-%2d-%2dT%2d:%2d:%2d%c",
             &parsed.tm_year, &parsed.tm_mon, &parsed.tm_mday,
             &parsed.tm_hour, &parsed.tm_min, &parsed.tm_sec,
             &extra) != 6) {
    return COMMAND_EXPIRED;
  }

  const int year = parsed.tm_year;
  const int month = parsed.tm_mon;
  const int day = parsed.tm_mday;
  const int hour = parsed.tm_hour;
  const int minute = parsed.tm_min;
  const int second = parsed.tm_sec;

  if (year < 2023 || month < 1 || month > 12 ||
      day < 1 || day > 31 || hour < 0 || hour > 23 ||
      minute < 0 || minute > 59 || second < 0 || second > 59) {
    return COMMAND_EXPIRED;
  }

  parsed.tm_year -= 1900;
  parsed.tm_mon -= 1;
  parsed.tm_isdst = 0;

  // The device clock must be synchronized before expiry decisions.
  struct timeval currentTime = {};
  if (gettimeofday(&currentTime, nullptr) != 0 ||
      currentTime.tv_sec < 1700000000) {
    return COMMAND_CLOCK_UNSYNCED;
  }
  const time_t now = currentTime.tv_sec;

  const time_t localAsUtc = utcToEpoch(parsed);
  if (localAsUtc <= 0) return COMMAND_EXPIRED;

  // Reject dates that utcToEpoch() would otherwise normalize.
  struct tm normalized = {};
  if (gmtime_r(&localAsUtc, &normalized) == nullptr ||
      normalized.tm_year != year - 1900 ||
      normalized.tm_mon != month - 1 ||
      normalized.tm_mday != day ||
      normalized.tm_hour != hour ||
      normalized.tm_min != minute ||
      normalized.tm_sec != second) {
    return COMMAND_EXPIRED;
  }

  // ISO 8601: +07:00 means local time is 7 hours ahead of UTC.
  const time_t expiry = localAsUtc - offsetSeconds;
  if (expiry <= 0) return COMMAND_EXPIRED;

  // Preserve fractional seconds, right-padding to microsecond precision.
  long expiryMicros = 0;
  if (timestampEnd > 19) {
    long scale = 100000;
    for (int i = 20; i < timestampEnd; ++i) {
      expiryMicros += (iso.charAt(i) - '0') * scale;
      scale /= 10;
    }
  }

  if (now > expiry ||
      (now == expiry && currentTime.tv_usec >= expiryMicros)) {
    return COMMAND_EXPIRED;
  }
  return COMMAND_NOT_EXPIRED;
}


int postCommandEvent(
    const String& commandId,
    const String& eventId,
    const String& eventType,
    const String& occurredAt,
    const String& message) {
  if (WiFi.status() != WL_CONNECTED) return -1;

  WiFiClient client;
  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/v1/commands/" +
               commandId + "/events";

  if (!http.begin(client, url)) return -1;
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + DEVICE_API_KEY);

  JsonDocument doc;
  doc["event_id"] = eventId;
  doc["event_type"] = eventType;
  doc["occurred_at"] = occurredAt;
  doc["details"]["message"] = message;

  String payload;
  serializeJson(doc, payload);
  int code = http.POST(payload);
  http.end();
  return code;
}

void prepareResult(const String& eventType, const String& message) {
  // Persist the result intent before advancing the state machine.
  if (commandPrefs.putString("resultType", eventType) == 0) {
    Serial.println("Command result deferred: failed to persist result type");
    return;
  }
  if (commandPrefs.putString("resultMsg", message) == 0) {
    Serial.println("Command result deferred: failed to persist result message");
    return;
  }
  if (commandPrefs.putString("phase", "result_waiting_time") == 0) {
    Serial.println("Command result deferred: failed to persist phase");
    return;
  }

  finalizePendingResult();
}

void finalizePendingResult() {
  if (prefString("phase") != "result_waiting_time") return;

  // Reuse any partially persisted event identity after an interrupted write.
  String eventId = prefString("resultId");
  if (eventId.isEmpty()) {
    eventId = generateEventId();
    if (commandPrefs.putString("resultId", eventId) == 0) {
      Serial.println("Command result deferred: failed to persist event ID");
      return;
    }
  }

  String occurredAt = prefString("resultAt");
  if (occurredAt.isEmpty()) {
    occurredAt = timestampUTC();
    if (occurredAt.isEmpty()) {
      Serial.println("Command result deferred: UTC time not synchronized");
      return;
    }
    if (commandPrefs.putString("resultAt", occurredAt) == 0) {
      Serial.println("Command result deferred: failed to persist timestamp");
      return;
    }
  }

  // Advance only after the event ID and timestamp are persisted.
  if (commandPrefs.putString("phase", "result_pending") == 0) {
    Serial.println("Command result deferred: failed to persist pending phase");
    return;
  }
}




void processStoredCommand() {
  unsigned long now = millis();
  if (now - lastCommandProcess < COMMAND_RETRY_INTERVAL_MS) return;
  lastCommandProcess = now;
  String phase = prefString("phase");
  if (phase.isEmpty() || phase == "idle") return;


  // Do not retry or actuate after a rejected result.
  // The RAM latch protects this boot even if the NVS write failed.
  if (phase == "result_blocked" || resultRejectedThisBoot) {
    Serial.println(
        "Command result remains blocked; stored event retained; "
        "manual recovery required");
    return;
  }


  String id = prefString("id");
  if (id.isEmpty()) {
    clearStoredCommand();
    return;
  }

  if (phase == "prepared") {
    int code = postCommandEvent(
        id, prefString("ackId"), "acknowledged",
        prefString("ackAt"), "Command accepted by device");

    if (code >= 200 && code < 300) {
      if (commandPrefs.putString("phase", "action_pending") == 0) {
        Serial.println(
            "Command acknowledged but action_pending persistence failed; "
            "relay action deferred");
        return;
      }
      Serial.printf("Command acknowledged: HTTP %d\n", code);
    } else if (code == 409 || code == 404 || code == 422) {
      // The server rejected the acknowledgement; never actuate this command.
      Serial.printf("Command acknowledgement rejected: HTTP %d\n", code);
      clearStoredCommand();
    }
    // Network errors and 5xx retain the exact event for idempotent retry.
    return;
  }

  if (phase == "action_pending") {
    int relay = commandPrefs.getInt("relay", 0);
    String target = prefString("target");
    String expires = prefString("expires");

    if (relay < 1 || relay > RELAY_COUNT ||
        (target != "on" && target != "off")) {
      prepareResult("failed", "Invalid persisted relay parameters");
      return;
    }

    CommandExpiryStatus expiryStatus = checkCommandExpiry(expires);
    if (expiryStatus == COMMAND_CLOCK_UNSYNCED) {
      Serial.println("Command deferred: waiting for synchronized UTC clock");
      return;
    }
    if (expiryStatus == COMMAND_EXPIRED) {
      prepareResult("failed", "Command expired before relay action");
      return;
    }

    // Setting an explicit target is idempotent; do not toggle the relay.
    setRelay(relay - 1, target == "on");
    printRelayStates();

    prepareResult("succeeded", "Relay target state applied");
    return;
  }

  if (phase == "result_waiting_time") {
    finalizePendingResult();
    return;
  }

  if (phase == "result_pending") {
    String resultType = prefString("resultType");

    // Restore the persisted target after reboot before retrying success.
    if (resultType == "succeeded") {
      int relay = commandPrefs.getInt("relay", 0);
      String target = prefString("target");

      if (relay < 1 || relay > RELAY_COUNT ||
          (target != "on" && target != "off")) {
        Serial.println("Command result blocked: invalid persisted target");
        return;
      }

      setRelay(relay - 1, target == "on");
      printRelayStates();
    }

    int code = postCommandEvent(
        id, prefString("resultId"), resultType,
        prefString("resultAt"), prefString("resultMsg"));

    if (code >= 200 && code < 300) {
      Serial.printf("Command result accepted: HTTP %d\n", code);
      clearStoredCommand();

    } else if (code == 404 || code == 409 || code == 422) {
      // Block further processing even if NVS persistence fails.
      resultRejectedThisBoot = true;

      String resultId = prefString("resultId");
      if (commandPrefs.putString("phase", "result_blocked") == 0) {
        Serial.printf(
            "Command result rejected: HTTP %d; could not persist "
            "result_blocked; runtime processing blocked; "
            "stored result retained; command=%s event=%s\n",
            code, id.c_str(), resultId.c_str());
      } else {
        Serial.printf(
            "Command result blocked: HTTP %d; command=%s event=%s "
            "type=%s. Stored result retained for manual recovery.\n",
            code, id.c_str(), resultId.c_str(), resultType.c_str());
      }

    } else {
      // Network errors and 5xx retry using the same persisted event.
      Serial.printf(
          "Command result pending: HTTP %d; retrying same event.\n", code);
    }
  }
}

void pollPendingCommands() {
  if (WiFi.status() != WL_CONNECTED) return;

  // Finish a persisted command before fetching another.
  String phase = prefString("phase");
  if (!phase.isEmpty() && phase != "idle") {
    processStoredCommand();
    return;
  }

  WiFiClient client;
  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/v1/commands/pending?limit=10";
  if (!http.begin(client, url)) return;

  http.setTimeout(5000);
  http.addHeader("Authorization", String("Bearer ") + DEVICE_API_KEY);
  int code = http.GET();

  if (code < 200 || code >= 300) {
    Serial.printf("Command poll failed: HTTP %d\n", code);
    http.end();
    return;
  }

  JsonDocument response;
  DeserializationError error = deserializeJson(response, http.getStream());
  http.end();

  if (error) {
    Serial.printf("Command response JSON invalid: %s\n", error.c_str());
    return;
  }

  JsonArray commands = response["commands"].as<JsonArray>();
  if (commands.isNull()) {
    Serial.println("Command poll: JSON has no commands array");
    return;
  }
  Serial.printf("Command poll: received %u command(s)\n",
                (unsigned)commands.size());
  if (commands.size() == 0) return;

  // Persist only one command at a time. Do not execute unknown command types.
  for (JsonObject cmd : commands) {
    const char* type = cmd["command_type"] | "";
    const char* status = cmd["status"] | "";
    const char* id = cmd["id"] | "";
    const char* expires = cmd["expires_at"] | "";
    JsonObject params = cmd["parameters"].as<JsonObject>();
    int relay = params["relay"] | 0;
    const char* target = params["state"] | "";

    if (strcmp(type, "relay.set") != 0 ||
        strcmp(status, "sent") != 0 ||
        strlen(id) == 0 || strlen(expires) < 19 ||
        relay < 1 || relay > RELAY_COUNT ||
        (strcmp(target, "on") != 0 && strcmp(target, "off") != 0)) {
      Serial.printf(
          "Command skipped: type=%s status=%s id_present=%d expiry=%s relay=%d target=%s\n",
          type, status, strlen(id) > 0, expires, relay, target);
      continue;
    }

    Serial.printf("Candidate command: id=%s expiry=%s relay=%d target=%s\n",
                  id, expires, relay, target);

    String expiry = expires;
    CommandExpiryStatus expiryStatus = checkCommandExpiry(expiry);
    if (expiryStatus == COMMAND_CLOCK_UNSYNCED) {
      Serial.println("Command poll deferred: waiting for synchronized UTC clock");
      return;
    }
    if (expiryStatus == COMMAND_EXPIRED) continue;

    String ackAt = timestampUTC();
    if (ackAt.isEmpty()) {
      Serial.println("Command deferred: UTC time not synchronized");
      return;
    }

        // Keep the command idle until every required field is persisted.
    bool saved =
        commandPrefs.putString("id", id) > 0 &&
        commandPrefs.putInt("relay", relay) > 0 &&
        commandPrefs.putString("target", target) > 0 &&
        commandPrefs.putString("expires", expiry) > 0 &&
        commandPrefs.putString("ackId", generateEventId()) > 0 &&
        commandPrefs.putString("ackAt", ackAt) > 0;

    if (!saved) {
      Serial.println(
          "Command deferred: failed to persist command fields");
      return;
    }

    if (commandPrefs.putString("phase", "prepared") == 0) {
      Serial.println(
          "Command deferred: failed to persist prepared phase");
      return;
    }

    processStoredCommand();
    return;
  }
}


String timestampUTC() {
  struct tm t;
  if (!getLocalTime(&t, 1000) || t.tm_year < 124) {
    return "";
  }
  char buffer[25];
  if (strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &t) == 0) {
    return "";
  }
  return String(buffer);
}

String generateEventId() {
  uint8_t uuid[16];
  for (int i = 0; i < 16; i++) {
    uuid[i] = static_cast<uint8_t>(esp_random() & 0xFF);
  }

  // RFC 4122 UUID version 4 and variant bits.
  uuid[6] = (uuid[6] & 0x0F) | 0x40;
  uuid[8] = (uuid[8] & 0x3F) | 0x80;

  char buffer[37];
  snprintf(
    buffer, sizeof(buffer),
    "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
    uuid[0], uuid[1], uuid[2], uuid[3],
    uuid[4], uuid[5], uuid[6], uuid[7],
    uuid[8], uuid[9], uuid[10], uuid[11],
    uuid[12], uuid[13], uuid[14], uuid[15]
  );
  return String(buffer);
}

void setRelay(int index, bool on) {
  if (index < 0 || index >= RELAY_COUNT) return;
  relayState[index] = on;
  uint8_t level = RELAY_ACTIVE_LOW ? (on ? LOW : HIGH) : (on ? HIGH : LOW);
  digitalWrite(relayPins[index], level);
}

void printRelayStates() {
  Serial.println("=== Relay reported states (commanded state) ===");
  for (int i = 0; i < RELAY_COUNT; i++) {
    Serial.printf("%s: %s\n", actuatorIds[i],
                  relayState[i] ? "ON" : "OFF");
  }
}

void sendSensorData(float temperature, float humidity, int moisturePercent) {
  if (WiFi.status() != WL_CONNECTED) return;

  String observedAt = timestampUTC();
  if (observedAt.isEmpty()) {
    Serial.println("Telemetry skipped: UTC time is not synchronized");
    return;
  }

  WiFiClient client;
  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/v1/telemetry";

  if (http.begin(client, url)) {
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", String("Bearer ") + DEVICE_API_KEY);

    JsonDocument doc;
    doc["event_id"] = generateEventId();
    doc["device_id"] = DEVICE_ID;
    doc["observed_at"] = observedAt;

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

    if (httpResponseCode >= 200 && httpResponseCode < 300) {
      Serial.printf("Telemetry accepted, HTTP %d\n", httpResponseCode);
    } else if (httpResponseCode > 0) {
      Serial.printf("Telemetry rejected, HTTP %d\n", httpResponseCode);
    } else {
      Serial.printf(
        "Telemetry request failed: %s\n",
        http.errorToString(httpResponseCode).c_str()
      );
    }
    http.end();
  } else {
    Serial.println("HTTP Begin failed");
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

  Serial.println("Waiting for UTC time synchronization...");
  bool timeSynced = false;
  for (int attempt = 0; attempt < 20; ++attempt) {
    time_t now = time(nullptr);
    if (now >= 1700000000) {
      struct tm utc;
      if (gmtime_r(&now, &utc) != nullptr) {
        char buffer[25];
        strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
        Serial.printf("UTC synchronized: %s\n", buffer);
        timeSynced = true;
        break;
      }
    }
    delay(500);
  }
  if (!timeSynced) {
    Serial.println("WARNING: UTC time not synchronized; commands must remain blocked");
  }
}

void setup() {
  Serial.begin(115200);
  commandPrefs.begin("sf_commands", false);
  if (!commandPrefs.isKey("phase")) commandPrefs.putString("phase", "idle");

  // Recover the last commanded relay target before applying fail-safe OFF.
  String startupPhase = prefString("phase");
  String startupResultType = prefString("resultType");
  int startupRelay = commandPrefs.getInt("relay", 0);
  String startupTarget = prefString("target");

  bool recoverSucceededTarget =
      (startupPhase == "result_pending" ||
       startupPhase == "result_waiting_time") &&
      startupResultType == "succeeded" &&
      startupRelay >= 1 && startupRelay <= RELAY_COUNT &&
      (startupTarget == "on" || startupTarget == "off");

  for (int i = 0; i < RELAY_COUNT; i++) {
    pinMode(relayPins[i], OUTPUT);

    bool restoreTarget =
        recoverSucceededTarget &&
        startupRelay == i + 1;

    if (restoreTarget) {
      setRelay(i, startupTarget == "on");
    } else {
      setRelay(i, false);
    }
  }

  printRelayStates();

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
  if (now - lastCommandPoll >= COMMAND_POLL_INTERVAL_MS) {
    lastCommandPoll = now;
    pollPendingCommands();
  }
  processStoredCommand();


  if (now - lastSensorPublish >= SENSOR_INTERVAL_MS) {
    lastSensorPublish = now;

    float temperature = dht.readTemperature();
    float humidity = dht.readHumidity();

    int soilRaw = analogRead(SOIL_PIN);
    int moisturePercent = map(
      soilRaw, SOIL_DRY_RAW, SOIL_WET_RAW, 0, 100
    );
    moisturePercent = constrain(moisturePercent, 0, 100);

    Serial.println("=== Sensor Readings ===");

    if (isnan(temperature) || isnan(humidity)) {
      Serial.println("DHT reading failed");
    } else {
      Serial.printf("Temperature: %.2f C\n", temperature);
      Serial.printf("Humidity: %.2f %%\n", humidity);
    }

    Serial.printf("Soil ADC raw: %d\n", soilRaw);
    Serial.printf(
      "Soil Moisture: %d %% (calibration estimate)\n",
      moisturePercent
    );

    printRelayStates();

    if (!isnan(temperature) && !isnan(humidity)) {
      sendSensorData(temperature, humidity, moisturePercent);
    }
  }
}
