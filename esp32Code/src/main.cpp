#include <WiFi.h>
#include <HTTPClient.h>
#include <ESPmDNS.h>
#include <Arduino.h>
#include <NewPing.h>  // <-- install via Library Manager

// ===== Wi-Fi (edit these) =====
const char* WIFI_SSID = "KS";
const char* WIFI_PASS = "12345679812";

// ===== Flask server via mDNS =====
const char* HOSTNAME = "KS.local";   // from your Flask log
const int   PORT     = 5000;

// ===== Bin controlled by this ESP32 =====
const int   BIN_ID   = 1;            // <-- only bin #1
const unsigned long SEND_PERIOD_MS = 5000;

// ===== Ultrasonic (one-pin mode) =====
const uint8_t US_PIN = 15;           // Trig & Echo on the same pin
const uint16_t MAX_DIST_CM = 400;    // sensor max range (safety cap)
NewPing sonar(US_PIN, US_PIN, MAX_DIST_CM);

// ===== Bin geometry =====
const int BIN_HEIGHT_CM = 100;       // 1 meter bin

unsigned long lastSend = 0;
int fullness = 0;  // computed from ultrasonic

// ---------------- Utilities ----------------
int clampi(int x, int lo, int hi){ return x<lo?lo : (x>hi?hi:x); }

// Read several pings and return median distance in cm (0 if no echo)
uint16_t readDistanceCm() {
    // NewPing’s ping_median does 5 pings and returns microseconds
    unsigned int uS = sonar.ping_median(5);
    if (uS == 0) return 0;                   // no echo
    uint16_t cm = uS / US_ROUNDTRIP_CM;      // convert to centimeters
    return cm;
}

// Map distance (lid-to-trash) to fill %
// 100 cm -> 0% ; 70 cm -> 30% ; 0 cm -> 100%
int distanceToFillPercent(uint16_t dist_cm) {
    if (dist_cm == 0) return -1;             // signal "invalid"
    // Clamp to bin height so anything farther than bin height = 0% full
    dist_cm = (dist_cm > BIN_HEIGHT_CM) ? BIN_HEIGHT_CM : dist_cm;
    int pct = 100 - dist_cm;                 // linear map
    return clampi(pct, 0, 100);
}

void connectWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.printf("\n✅ WiFi connected. IP: %s\n", WiFi.localIP().toString().c_str());

    // Start mDNS responder (nice to have)
    if (!MDNS.begin("esp32")) {
        Serial.println("⚠️ mDNS start failed; continuing.");
    } else {
        Serial.println("mDNS responder started as esp32.local");
    }
}

bool patchFullness(int value) {
    String url = "http://" + String(HOSTNAME) + ":" + String(PORT) + "/bins/" + String(BIN_ID);

    HTTPClient http;
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    String payload = String("{\"fullness\":") + value + "}";
    int code = http.sendRequest("PATCH", (uint8_t*)payload.c_str(), payload.length());

    if (code > 0) {
        Serial.printf("PATCH %s -> %d\n", url.c_str(), code);
    } else {
        Serial.printf("PATCH %s -> error: %s\n", url.c_str(), http.errorToString(code).c_str());
    }
    http.end();
    return (code == 204 || code == 200);
}

void setup() {
    Serial.begin(115200);
    delay(300);
    randomSeed(esp_random());
    connectWifi();
    lastSend = millis();
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) connectWifi();

    unsigned long now = millis();
    if (now - lastSend >= SEND_PERIOD_MS) {
        lastSend = now;

        // --- Read ultrasonic and compute fill% ---
        uint16_t dcm = readDistanceCm();
        int newFill = distanceToFillPercent(dcm);

        if (newFill < 0) {
            Serial.println("❌ No echo from ultrasonic (out of range or wiring). Keeping last value.");
        } else {
            fullness = newFill;
        }

        Serial.printf("Bin %d: distance=%ucm => fullness=%d%%\n", BIN_ID, dcm, fullness);

        if (!patchFullness(fullness)) {
            // Debug: try resolving hostname manually
            IPAddress ip;
            if (WiFi.hostByName(HOSTNAME, ip)) {
                String ipUrl = "http://" + ip.toString() + ":" + String(PORT) + "/bins/" + String(BIN_ID);
                Serial.printf("Retry via IP %s\n", ipUrl.c_str());
                HTTPClient http;
                http.begin(ipUrl);
                http.addHeader("Content-Type", "application/json");
                String payload = String("{\"fullness\":") + fullness + "}";
                int code = http.sendRequest("PATCH", (uint8_t*)payload.c_str(), payload.length());
                Serial.printf("Retry -> %d\n", code);
                http.end();
            } else {
                Serial.println("❌ mDNS/DNS resolve failed");
            }
        }
    }

    delay(50);
}
