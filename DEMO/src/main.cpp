/**
 * 智能选座与导航系统 —— ESP32 座位占用传感器（可视化配置版）
 *
 * 相比旧版（每次改代码重烧），本版接入“服务器下发配置 + 设备注册”：
 *   1) 首次上电：开启热点 `ESP32-Config`(192.168.4.1)，手机连它、打开 192.168.4.1 网页表单，
 *      填 WiFi 名称/密码 + 服务器地址（存到设备 Flash，一次即可）。
 *   2) 用 WiFi MAC 作 device_id，启动时向服务器注册 —— 管理面板「硬件/传感器调试」会提示“已注册成功”。
 *   3) 启动 + 周期从服务器拉取配置（seat_label / 传感器电平 / 上报间隔），
 *      管理员在面板改这些配置，设备拉取即生效，免重烧。
 *   4) 上报逻辑不变：POST {server}/api/sensor/report 上报原始 ir_front / ir_back，
 *      占用状态机由主系统维护。
 *
 * 依赖（built-in，无需额外库）：WiFi.h / WebServer.h / HTTPClient.h / ArduinoJson(已有) / Preferences(NVS)
 * ⚠️ 本固件需在真机上烧录验证；具体接线/烧录见 docs/hardware-live-demo.md。
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>

// ---------------- 传感器硬件引脚 ----------------
const uint8_t IR_SENSOR_A_PIN = 23;   // ir_front
const uint8_t IR_SENSOR_B_PIN = 27;   // ir_back

// ---------------- 本地(写到Flash)配置 ----------------
// 通过设备热点网页表单写入；之后可改 WiFi/服务器，但需重新走一次 AP 配置。
Preferences prefs;
String wifi_ssid = "";
String wifi_pass = "";
String server_url = "";
bool configured_flag = false;

// ---------------- 服务器下发的运行配置 ----------------
bool   cfg_ir_active_high   = true;    // true=HC-SR501(PIR 高电平)  false=红外避障(低电平)
String cfg_seat_label       = "";      // 绑定座位标签
int    cfg_seat_id          = 0;       // 绑定座位数字 id（二选一）
unsigned long cfg_report_interval_ms = 5000UL;
String cfg_sensor_type      = "pir";   // pir / ir / ultrasonic(HC-SR04P)
int    cfg_distance_threshold_cm = 50; // 超声波“距离小于该值视为有人”(cm)

const uint8_t ULTRASONIC_TRIG_PIN = 25;   // HC-SR04P TRIG
const uint8_t ULTRASONIC_ECHO_PIN = 26;   // HC-SR04P ECHO

// 配置热点参数
const char* AP_SSID = "ESP32-Config";
const char* AP_PASS  = "";             // 留空=无密码，首次配置更省事；可自行加密

WebServer server(80);
unsigned long lastReportMs = 0;
unsigned long lastConfigMs = 0;
const unsigned long CONFIG_REFRESH_MS = 60000UL;   // 周期拉配置间隔

// ---------------- 工具 ----------------
void logLine(const String& s) { Serial.println(s); }
String deviceId() { return WiFi.macAddress(); }      // 用 MAC 作唯一 device_id（不用手填）

bool readSensor(uint8_t pin) {
    uint8_t active = cfg_ir_active_high ? HIGH : LOW;
    return digitalRead(pin) == active;
}

// 超声波测距（HC-SR04P）：发脉冲→读回波脉宽→返回距离(cm)；失败返回 -1
float measureDistanceCm() {
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(ULTRASONIC_TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    unsigned long us = pulseIn(ULTRASONIC_ECHO_PIN, HIGH, 30000UL);  // 30ms 超时
    if (us == 0) return -1.0f;
    float cm = us / 58.0f;   // 声速换算：距离(cm)=脉宽(us)/58
    return cm;
}

// 判定座位是否“有人”（按传感器类型）
bool isOccupied() {
    if (cfg_sensor_type == "ultrasonic") {
        float d = measureDistanceCm();
        if (d < 0) return false;                        // 测距失败，按无人处理
        logLine("[US] dist=" + String(d) + "cm thr=" + String(cfg_distance_threshold_cm));
        return d < cfg_distance_threshold_cm;           // 距离小于阈值 => 有人
    }
    // pir / ir：两束交叉判定
    return readSensor(IR_SENSOR_A_PIN) && readSensor(IR_SENSOR_B_PIN);
}

// ---------------- 配置门户（AP 模式） ----------------
void handleRoot() {
    String html = R"HTML(<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ESP32 配置</title>
<style>body{font-family:sans-serif;max-width:420px;margin:40px auto;padding:16px}
input{width:100%;margin:8px 0;padding:8px;box-sizing:border-box}
button{width:100%;padding:10px;background:#1a73e8;color:#fff;border:0;border-radius:6px}
h2{color:#1a73e8}.tip{font-size:13px;color:#555}</style></head><body>
<h2>ESP32 配置</h2>
<form method="POST" action="/save">
<p>WiFi 名称：<input name="ssid" required></p>
<p>WiFi 密码：<input name="pass" type="password"></p>
<p>服务器地址(含端口)：<input name="server" placeholder="http://192.168.1.7:5800" required></p>
<button type="submit">保存并连接</button></form>
<p class="tip">保存后设备会自动连接并注册到主系统，请到管理后台「硬件 / 传感器调试」查看并绑定座位。</p>
</body></html>)HTML";
    server.send(200, "text/html; charset=utf-8", html);
}

void handleSave() {
    if (!server.hasArg("ssid") || !server.hasArg("server")) {
        server.send(400, "text/plain", "缺少参数");
        return;
    }
    String ssid = server.arg("ssid"); ssid.trim();
    String pass = server.arg("pass"); pass.trim();
    String srv  = server.arg("server"); srv.trim();
    if (!ssid.length() || !srv.length()) {
        server.send(400, "text/html; charset=utf-8", "<meta charset='utf-8'><p>WiFi 名称或服务器地址为空</p>");
        return;
    }
    prefs.begin("hwcfg", false);
    prefs.putString("ssid", ssid);
    prefs.putString("pass", pass);
    prefs.putString("server", srv);
    prefs.putBool("configured", true);
    prefs.end();
    server.send(200, "text/html; charset=utf-8",
                "<meta charset='utf-8'><h3 style='font-family:sans-serif'>已保存，正在连接 WiFi…</h3>");
    logLine("[CFG] 配置已保存，重启连接");
    delay(600);
    ESP.restart();
}

void startConfigPortal() {
    logLine("[CFG] 开启配置热点 " + String(AP_SSID) + "，请用手机连接后访问 192.168.4.1");
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
    server.on("/", handleRoot);
    server.on("/save", HTTP_POST, handleSave);
    server.begin();
}

// ---------------- 本地配置读写（NVS） ----------------
void loadLocalConfig() {
    prefs.begin("hwcfg", false);
    wifi_ssid   = prefs.getString("ssid", "");
    wifi_pass   = prefs.getString("pass", "");
    server_url  = prefs.getString("server", "");
    configured_flag = prefs.getBool("configured", false);
    prefs.end();
}

// ---------------- WiFi ----------------
void connectWiFi() {
    if (WiFi.status() == WL_CONNECTED) return;
    logLine("[WiFi] 连接 " + wifi_ssid);
    WiFi.mode(WIFI_STA);
    WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 15000UL) {
        delay(250);
        Serial.print(".");
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {
        logLine("[WiFi] 已连接 IP=" + WiFi.localIP().toString());
    } else {
        logLine("[WiFi] 连接失败，稍后重试");
    }
}

// ---------------- 应用服务器下发的配置 ----------------
void applyServerConfig(String body) {
    JsonDocument d;
    if (deserializeJson(d, body)) { logLine("[CFG] 配置解析失败"); return; }
    JsonObject cfg = d["data"]["config"];
    if (cfg.isNull()) { logLine("[CFG] 尚未绑定配置"); return; }
    if (cfg["ir_active_high"].is<bool>())      cfg_ir_active_high = cfg["ir_active_high"].as<bool>();
    if (cfg["report_interval_ms"].is<int>() &&
        cfg["report_interval_ms"].as<int>() > 0) cfg_report_interval_ms = cfg["report_interval_ms"].as<int>();
    if (cfg["seat_label"].is<const char*>())   cfg_seat_label = String(cfg["seat_label"].as<const char*>());
    if (cfg["seat_id"].is<int>())              cfg_seat_id = cfg["seat_id"].as<int>();
    if (cfg["sensor_type"].is<const char*>())  cfg_sensor_type = String(cfg["sensor_type"].as<const char*>());
    if (cfg["distance_threshold_cm"].is<int>() &&
        cfg["distance_threshold_cm"].as<int>() > 0) cfg_distance_threshold_cm = cfg["distance_threshold_cm"].as<int>();
    logLine("[CFG] seat_label=" + cfg_seat_label + " type=" + cfg_sensor_type +
            " ulthr=" + String(cfg_distance_threshold_cm) +
            " ir_high=" + String(cfg_ir_active_high ? "true" : "false") +
            " interval=" + String(cfg_report_interval_ms));
}

// ---------------- 注册 + 拉配置 ----------------
bool registerAndConfig() {
    if (server_url.length() == 0 || WiFi.status() != WL_CONNECTED) return false;
    String url = server_url + "/api/sensor/device/register";
    HTTPClient http;
    http.begin(url); http.setTimeout(5000);
    http.addHeader("Content-Type", "application/json");
    JsonDocument doc;
    doc["device_id"] = deviceId();
    String payload; serializeJson(doc, payload);
    int code = http.POST(payload);
    String body = http.getString();
    http.end();
    logLine("[REG] HTTP " + String(code));
    if (code >= 200 && code < 300) { applyServerConfig(body); return true; }
    return false;
}

void refreshConfig() {
    if (server_url.length() == 0 || WiFi.status() != WL_CONNECTED) return;
    String url = server_url + "/api/sensor/device_config?device_id=" + deviceId();
    HTTPClient http;
    http.begin(url); http.setTimeout(5000);
    int code = http.GET();
    String body = http.getString();
    http.end();
    if (code >= 200 && code < 300) applyServerConfig(body);
}

// ---------------- 上报 ----------------
bool reportSeat() {
    if (WiFi.status() != WL_CONNECTED) return false;
    int ir_front, ir_back;
    if (cfg_sensor_type == "ultrasonic") {
        float d = measureDistanceCm();
        int occ = (d >= 0 && d < cfg_distance_threshold_cm) ? 1 : 0;
        ir_front = ir_back = occ;
    } else {
        ir_front = readSensor(IR_SENSOR_A_PIN) ? 1 : 0;
        ir_back  = readSensor(IR_SENSOR_B_PIN) ? 1 : 0;
    }

    String url = server_url + "/api/sensor/report";
    HTTPClient http;
    http.begin(url); http.setTimeout(5000);
    http.addHeader("Content-Type", "application/json");
    JsonDocument doc;
    if (cfg_seat_id > 0)                doc["seat_id"] = cfg_seat_id;
    else if (cfg_seat_label.length())   doc["seat_label"] = cfg_seat_label;
    else { logLine("[HTTP] 未绑定座位，跳过上报"); return false; }
    doc["ir_front"] = ir_front;
    doc["ir_back"]  = ir_back;
    doc["device_id"] = deviceId();
    String payload; serializeJson(doc, payload);
    int code = http.POST(payload);
    String body = http.getString();
    http.end();
    bool ok = (code >= 200 && code < 300);
    logLine("[HTTP] " + String(code) + " ir=(" + String(ir_front) + "," + String(ir_back) + ")" +
            (ok ? "" : " body=" + body));
    return ok;
}

// ---------------- setup / loop ----------------
void setup() {
    Serial.begin(115200);
    delay(200);
    pinMode(IR_SENSOR_A_PIN, INPUT_PULLUP);
    pinMode(IR_SENSOR_B_PIN, INPUT_PULLUP);

    Serial.println();
    Serial.println("=== ESP32 座位占用传感器（可视化配置版）启动 ===");
    loadLocalConfig();

    if (!configured_flag) {
        startConfigPortal();          // 未配置 -> 进 AP 配置页
    } else {
        logLine("[CFG] 服务器: " + server_url + "  device_id: " + deviceId());
        connectWiFi();
        registerAndConfig();
    }
    lastReportMs = millis();
    lastConfigMs = millis();
}

unsigned long _connectFailures = 0;
const unsigned long MAX_CONNECT_FAILURES = 5;
unsigned long _registerFailures = 0;
unsigned long _lastRegisterMs = 0;
const unsigned long REGISTER_RETRY_MS = 10000UL;

void loop() {
    if (!configured_flag) {
        server.handleClient();        // AP 配置页保持响应
        delay(20);
        return;
    }

    unsigned long now = millis();

    if (WiFi.status() != WL_CONNECTED) {
        connectWiFi();
        if (WiFi.status() == WL_CONNECTED) {
            _connectFailures = 0;
        } else {
            _connectFailures++;
            if (_connectFailures >= MAX_CONNECT_FAILURES) {
                logLine("[CFG] WiFi 连接失败多次（多半是 5G 网络或密码错），清空配置回到配置页，请重新填写");
                prefs.begin("hwcfg", false);
                prefs.clear();
                prefs.end();
                configured_flag = false;
                _connectFailures = 0;
                startConfigPortal();
            }
        }
    }

    // 已连WiFi：周期重试注册；服务器不可达(地址错)多次则清配置回配置页
    if (WiFi.status() == WL_CONNECTED && now - _lastRegisterMs >= REGISTER_RETRY_MS) {
        _lastRegisterMs = now;
        if (registerAndConfig()) {
            _registerFailures = 0;
        } else {
            _registerFailures++;
            if (_registerFailures >= MAX_CONNECT_FAILURES) {
                logLine("[CFG] 服务器不可达（多半地址填错），清空配置回到配置页，请重新填写");
                prefs.begin("hwcfg", false);
                prefs.clear();
                prefs.end();
                configured_flag = false;
                _registerFailures = 0;
                startConfigPortal();
            }
        }
    }

    if (now - lastReportMs >= cfg_report_interval_ms) {
        lastReportMs = now;
        reportSeat();
    }
    if (now - lastConfigMs >= CONFIG_REFRESH_MS) {
        lastConfigMs = now;
        refreshConfig();
    }
    delay(20);
}
