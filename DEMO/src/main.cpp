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

const uint8_t ULTRASONIC_TRIG_PIN = 16;   // HC-SR04P TRIG（接 D16）
const uint8_t ULTRASONIC_ECHO_PIN = 27;   // HC-SR04P ECHO（接 D27）

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

// ---------------- 超声波接线诊断（中断捕获 ECHO 边沿） ----------------
// 为什么需要它：pulseIn 只能"等待上升沿"，若脉冲在调用前已结束就测不到，
// 因此无法用于回环自检。中断捕获不受这个时序限制，可区分三种故障：
//   ① ECHO 恒高      -> 分压中点悬空/接错（正常静态应为低）
//   ② 完全无任何边沿  -> 信号未到达 GPIO27（线不通 / 传感器无回波 / 模块损坏）
//   ③ 捕获到极短脉宽  -> D16 与 D27 被短接（回环自检特征）
// 用 US_DIAG 开关控制，排查完可置 0 关闭。
#define US_DIAG 1

volatile unsigned long _echoRiseUs    = 0;
volatile unsigned long _echoWidthUs   = 0;
volatile unsigned long _echoEdgeCount = 0;
volatile uint8_t       _isrPin        = 27;   // 由探测函数设置，ISR 依据它读引脚

void IRAM_ATTR _echoIsr() {
    unsigned long now = micros();
    if (digitalRead(_isrPin)) {
        _echoRiseUs = now;                     // 上升沿：记录起点
    } else if (_echoRiseUs) {
        _echoWidthUs = now - _echoRiseUs;      // 下降沿：算出脉宽
        _echoEdgeCount++;
        _echoRiseUs = 0;
    }
}

// ---------------- TRIG/ECHO 组合自动探测 ----------------
// 起因：TRIG 与 ECHO 接反是这类故障最常见的原因，而远程看不到实物接线。
// 这里把两种组合都试一遍（各发一次 TRIG 脉冲 + 中断捕获 ECHO），
// 直接报告哪一种能测到回波 —— 使用者无需改动任何接线。
// 注意：探测结束会把引脚恢复成固件正常使用的角色，避免影响后续运行。
void ultrasonicAutoDetect() {
#if US_DIAG
    struct Combo { uint8_t trig; uint8_t echo; const char* name; };
    const Combo combos[2] = {
        { 16, 27, "A: TRIG=D16(16)  ECHO=D27(27)" },
        { 27, 16, "B: TRIG=D27(27)  ECHO=D16(16)  <- 与固件相反" },
    };

    logLine("[探测] 开始尝试两种 TRIG/ECHO 组合…");
    for (uint8_t i = 0; i < 2; i++) {
        const uint8_t tp = combos[i].trig;
        const uint8_t ep = combos[i].echo;

        pinMode(tp, OUTPUT);
        digitalWrite(tp, LOW);
        pinMode(ep, INPUT);
        delayMicroseconds(300);

        const int idle = digitalRead(ep);
        _isrPin = ep;
        _echoRiseUs = 0; _echoWidthUs = 0; _echoEdgeCount = 0;
        attachInterrupt(digitalPinToInterrupt(ep), _echoIsr, CHANGE);

        digitalWrite(tp, LOW);  delayMicroseconds(2);
        digitalWrite(tp, HIGH); delayMicroseconds(10);
        digitalWrite(tp, LOW);

        delay(60);   // 留足回波时间

        detachInterrupt(digitalPinToInterrupt(ep));

        String msg = String("[探测] ") + combos[i].name
                   + "  静态=" + String(idle)
                   + " 边沿=" + String(_echoEdgeCount)
                   + " 脉宽=" + String(_echoWidthUs) + "us";
        if (_echoWidthUs > 0) {
            msg += " 距离=" + String(_echoWidthUs / 58.0f, 1) + "cm";
        }
        logLine(msg);
    }

    // 恢复固件正常使用的引脚角色
    pinMode(ULTRASONIC_TRIG_PIN, OUTPUT);
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    pinMode(ULTRASONIC_ECHO_PIN, INPUT);
    logLine("[探测] 结束（若 A 有回波=B 无 -> 接线与固件一致；反之则需要改接线）");
#endif
}

void ultrasonicDiagnose() {
#if US_DIAG
    pinMode(ULTRASONIC_ECHO_PIN, INPUT);       // 确保无内部上拉
    delayMicroseconds(100);
    int idleLevel = digitalRead(ULTRASONIC_ECHO_PIN);

    _echoRiseUs = 0; _echoWidthUs = 0; _echoEdgeCount = 0;
    _isrPin = ULTRASONIC_ECHO_PIN;
    attachInterrupt(digitalPinToInterrupt(ULTRASONIC_ECHO_PIN), _echoIsr, CHANGE);

    // 发一次标准 TRIG 脉冲
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(ULTRASONIC_TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);

    delay(60);                                  // 留足回波时间（可覆盖约 10m 往返）

    detachInterrupt(digitalPinToInterrupt(ULTRASONIC_ECHO_PIN));

    String msg = "[DIAG] ECHO静态=" + String(idleLevel)
               + " TRIG脚=" + String(ULTRASONIC_TRIG_PIN)
               + " ECHO脚=" + String(ULTRASONIC_ECHO_PIN)
               + " 边沿=" + String(_echoEdgeCount)
               + " 脉宽=" + String(_echoWidthUs) + "us";
    if (_echoWidthUs > 0) msg += " 距离=" + String(_echoWidthUs / 58.0f, 1) + "cm";
    logLine(msg);

    if (_echoEdgeCount == 0 && idleLevel == 1) {
        logLine("[DIAG] ① ECHO 恒高 -> 分压中点悬空或接错（正常静态应为 0）");
    } else if (_echoEdgeCount == 0) {
        logLine("[DIAG] ② 无任何边沿 -> 信号没到 GPIO27：查这根线是否插实/换插孔，或模块已损坏");
    } else if (_echoWidthUs > 0 && _echoWidthUs < 50) {
        logLine("[DIAG] ③ 极短脉宽 -> 检测到 D16 与 D27 短接（回环自检特征），引脚通路正常");
    } else {
        logLine("[DIAG] ④ 捕获到正常回波脉宽，测距通路正常");
    }
#endif
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
        ultrasonicDiagnose();          // 打印接线诊断（中断捕获 ECHO 边沿）
        float d = measureDistanceCm();
        int occ = (d >= 0 && d < cfg_distance_threshold_cm) ? 1 : 0;
        ir_front = ir_back = occ;
        logLine("[US] dist=" + String(d) + "cm thr=" + String(cfg_distance_threshold_cm) + " -> occupied=" + String(occ));
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
    pinMode(ULTRASONIC_TRIG_PIN, OUTPUT);   // 超声波 TRIG
    pinMode(ULTRASONIC_ECHO_PIN, INPUT);    // 超声波 ECHO

    Serial.println();
    Serial.println("=== ESP32 座位占用传感器（可视化配置版）启动 ===");

    // 开机自动探测 TRIG/ECHO 组合：两种接法都试一次，直接报告哪种有回波。
    // 不需要 WiFi/服务器，也不要求使用者改动接线。
    ultrasonicAutoDetect();

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
