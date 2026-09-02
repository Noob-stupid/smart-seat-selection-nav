/**
 * 智能选座与导航系统 —— ESP32 座位占用传感设备（主系统接入版）
 *
 * 本固件由 DEMO 版改造而来：不再对接 DEMO 自带的小后端（/api/scan），
 * 而是作为“真实传感器”直接接入主系统（smart-seat-selection-nav）：
 * - 上报接口：POST {SERVER_URL}/api/sensor/report
 * - 上报内容：原始红外读数 ir_front / ir_back，不做本地占用判定；
 *   占用状态机统一由主系统维护（两束同时遮挡 → 有人；
 *   连续两次“无人”上报 → 空闲，预约时段内保持占用），
 *   行为与后台 utils/sensor_simulator.py 的模拟器回调完全一致。
 * - 座位标识：按座位标签 seat_label（推荐）或数据库数字 id seat_id 上报，
 *   主系统 /api/sensor/report 已支持这两种定位方式（含 floor_id 消歧）。
 *
 * 硬件方案（与演示版一致）：
 * - 两个红外避障传感器交叉放置（座椅左前方 45° 与右后方 45°），
 *   人坐下时两束同时被遮挡 → 上报 (ir_front=1, ir_back=1) → 主系统置为占用。
 * - IR_SENSOR_A_PIN 与 IR_SENSOR_B_PIN 分别接 ESP32 的 GPIO。
 * - 红外避障模块默认“检测到物体时输出 LOW”（IR_ACTIVE_HIGH=false）；
 *   若改用 PIR 人体感应模块（检测到人体时输出 HIGH），把 IR_ACTIVE_HIGH 改为 true。
 *
 * 软件逻辑：
 * 1. 每 REPORT_INTERVAL_MS 读取一次两个传感器并上报主系统；
 *    主系统以“连续两次无人上报”释放座位，因此该周期即离座后的释放延迟。
 * 2. 上报失败时每隔 RETRY_INTERVAL_MS 重试，直到成功（防止断网期间丢状态）。
 * 3. WiFi 断开自动重连；主系统若 24 小时收不到本设备上报，
 *    会把对应座位标记为“异常”，故保持周期上报即可维持在线。
 * 4. 锁定防抢座（m/n 动态参数）由 Web 端调用主系统 /api/lock/* 完成，
 *    设备端只负责持续上报红外读数。
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ==================== 网络配置（按实际环境修改） ====================
const char* WIFI_SSID     = "输入路由器名称";
const char* WIFI_PASSWORD = "输入路由器密码";
// 主系统地址：以 `python app.py 0.0.0.0 5800` 启动后，
// 填运行主系统的电脑局域网 IP（Windows: ipconfig 查询），默认端口 5800
const char* SERVER_URL    = "http://192.168.1.7:5800";

// ==================== 座位标识（二选一） ====================
// true  → 按座位标签 seat_label 上报（推荐：与管理端平面图显示的标签一致、可读）
// false → 按数据库座位数字 id 上报（主系统 seats 表主键）
const bool IDENTIFY_BY_SEAT_LABEL = true;
const char* SEAT_LABEL = "A区-12";  // 主系统 seats.seat_label，如 "A区-12"、"3F-08"
const int   FLOOR_ID   = 0;         // 仅标签歧义消歧用：>0 时随请求携带 floor_id
const int   SEAT_ID    = 1;         // IDENTIFY_BY_SEAT_LABEL=false 时使用（seats.id）

// ==================== 传感器引脚配置 ====================
const uint8_t IR_SENSOR_A_PIN = 23;   // 红外传感器 A → 上报字段 ir_front
const uint8_t IR_SENSOR_B_PIN = 27;   // 红外传感器 B → 上报字段 ir_back
// true  = 传感器检测到人时输出 HIGH（如 PIR 人体感应模块）
// false = 传感器检测到物体时输出 LOW（红外避障模块，推荐用于座椅占用检测）
const bool IR_ACTIVE_HIGH = false;

// ==================== 上报策略 ====================
const unsigned long REPORT_INTERVAL_MS = 5000UL;   // 上报周期（毫秒）
const unsigned long RETRY_INTERVAL_MS  = 10000UL;  // 上报失败后的重试间隔

unsigned long lastReportMs = 0;
unsigned long lastRetryMs  = 0;
bool pendingReport = false;

/**
 * 读取一个红外传感器。返回 true 表示该传感器检测到人/物。
 */
bool readSensor(uint8_t pin) {
    const uint8_t activeLevel = IR_ACTIVE_HIGH ? HIGH : LOW;
    return digitalRead(pin) == activeLevel;
}

/**
 * 上报一次原始红外读数到主系统 /api/sensor/report。
 * 成功返回 true；失败返回 false（上层会安排重试）。
 */
bool reportSeat() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[HTTP] WiFi 未连接，上报暂缓");
        return false;
    }

    int ir_front = readSensor(IR_SENSOR_A_PIN) ? 1 : 0;
    int ir_back  = readSensor(IR_SENSOR_B_PIN) ? 1 : 0;

    String url = String(SERVER_URL) + "/api/sensor/report";
    HTTPClient http;
    http.begin(url);
    http.setTimeout(5000);
    http.addHeader("Content-Type", "application/json");

    JsonDocument doc;
    if (IDENTIFY_BY_SEAT_LABEL) {
        doc["seat_label"] = SEAT_LABEL;
        if (FLOOR_ID > 0) {
            doc["floor_id"] = FLOOR_ID;
        }
    } else {
        doc["seat_id"] = SEAT_ID;
    }
    doc["ir_front"] = ir_front;
    doc["ir_back"]  = ir_back;

    String payload;
    serializeJson(doc, payload);

    Serial.printf("[HTTP] POST %s -> ", url.c_str());
    Serial.println(payload);

    int httpCode = http.POST(payload);
    bool ok = (httpCode >= 200 && httpCode < 300);
    if (ok) {
        Serial.printf("[HTTP] 上报成功 HTTP %d（ir=(%d,%d)）\n",
                      httpCode, ir_front, ir_back);
    } else {
        String body = http.getString();
        Serial.printf("[HTTP] 上报失败 HTTP %d body=%s\n",
                      httpCode, body.c_str());
    }
    http.end();
    return ok;
}

/**
 * 连接 WiFi，最多阻塞 15 秒；失败会在 loop 中持续重试。
 */
void connectWiFi() {
    if (WiFi.status() == WL_CONNECTED) {
        return;
    }

    Serial.printf("[WiFi] 连接 %s ...\n", WIFI_SSID);
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED &&
           millis() - start < 15000UL) {
        delay(200);
        Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.print("[WiFi] 已连接，IP = ");
        Serial.println(WiFi.localIP());
    } else {
        Serial.println("[WiFi] 连接失败，将在 loop 中重试");
    }
}

void setup() {
    Serial.begin(115200);
    delay(200);

    pinMode(IR_SENSOR_A_PIN, INPUT_PULLUP);
    pinMode(IR_SENSOR_B_PIN, INPUT_PULLUP);

    Serial.println();
    Serial.println("=== ESP32 座位占用传感器（主系统接入版）启动 ===");
    if (IDENTIFY_BY_SEAT_LABEL) {
        Serial.printf("座位标签: %s\n", SEAT_LABEL);
    } else {
        Serial.printf("座位ID: %d\n", SEAT_ID);
    }
    Serial.printf("上报间隔: %lu ms\n", REPORT_INTERVAL_MS);

    connectWiFi();
    lastReportMs = millis();
    lastRetryMs = millis();
}

void loop() {
    unsigned long now = millis();

    // WiFi 断开时尝试重连
    if (WiFi.status() != WL_CONNECTED) {
        connectWiFi();
    }

    // 固定周期上报：每次都会更新原始红外读数与主系统的 last_scan_time
    if (now - lastReportMs >= REPORT_INTERVAL_MS) {
        lastReportMs = now;
        if (!reportSeat()) {
            pendingReport = true;
            lastRetryMs = now;
        } else {
            pendingReport = false;
        }
    }

    // 上报失败后按重试间隔补报（重试时读取最新读数）
    if (pendingReport && (now - lastRetryMs >= RETRY_INTERVAL_MS)) {
        lastRetryMs = now;
        if (reportSeat()) {
            pendingReport = false;
            Serial.println("[HTTP] 补报成功，清空待上报标记");
        }
    }

    delay(50);  // 小延时，避免空转占用 CPU
}
