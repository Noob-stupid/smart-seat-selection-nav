/**
 * 功能一：物联网感知 —— ESP32 座椅占用检测设备端
 *
 * 硬件方案：
 * - 两个红外传感器交叉放置（例如座椅左前方 45° 与右后方 45°），
 *   任意一个传感器检测到人体即认为“当前扫描有人”，消除单一角度盲区。
 * - 默认适配红外避障模块（检测到物体时输出 LOW）。
 *   若使用 PIR 人体感应模块（检测到人体时输出 HIGH），把 IR_ACTIVE_HIGH 改为 true。
 *
 * 软件逻辑：
 * 1. 每 SCAN_INTERVAL_MS 扫描一次两个传感器。
 * 2. 单次扫描有人不会立刻上报；只有连续 VACANT_CONFIRM_SCANS 次扫描都无人，
 *    设备才把状态由“有人”切换为“无人”，降低误判率。
 * 3. 检测到有人占用时立即通过 HTTP POST 上报 Flask 后端；
 *    无人状态确认后也立即上报，同时周期发送心跳保持在线。
 * 4. 锁定操作由客户端调用 Flask API 发起，后端根据 m/n 参数自动检测与解除。
 *    设备端只需要持续扫描和上报，锁定状态机统一放在后端维护。
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ==================== 网络配置 ====================
const char* WIFI_SSID       = "输入网路名称";
const char* WIFI_PASSWORD   = "输入网路密码";
const char* SEAT_ID         = "seat-001";                    // 当前座椅编号，多个设备不可重复
const char* FLASK_BASE_URL = "http://192.168.1.7:5000";   // Flask 服务器地址

// ==================== 传感器引脚配置 ====================
// 两个红外传感器交叉放置，分别接两个 GPIO
//IR_SENSOR_A_PIN = 26：红外传感器 A 连接到 ESP32 的 GPIO 233 引脚。
//IR_SENSOR_B_PIN = 27：红外传感器 B 连接到 ESP32 的 GPIO 27 引脚。
const uint8_t IR_SENSOR_A_PIN = 23;
const uint8_t IR_SENSOR_B_PIN = 27;

// true  = 传感器检测到人时输出 HIGH（如 PIR 人体感应模块）
// false = 传感器检测到物体时输出 LOW（如红外避障模块，推荐用于座椅占用）
const bool IR_ACTIVE_HIGH = false;

// ==================== 扫描与上报策略 ====================
const unsigned long SCAN_INTERVAL_MS      = 3000UL;  // 每隔 3 秒扫描一次
const int           VACANT_CONFIRM_SCANS  = 2;       // 连续 2 次无人后才判定空闲
const unsigned long HEARTBEAT_INTERVAL_MS = 30000UL; // 每 30 秒向后端发一次心跳
const unsigned long RETRY_INTERVAL_MS     = 10000UL; // 上报失败后 10 秒重试

// ==================== 座椅状态机 ====================
enum SeatState {
    STATE_IDLE,      // 当前判定为空闲
    STATE_OCCUPIED   // 当前判定为有人
};

SeatState currentState = STATE_IDLE;
int emptyScanCount = 0;                 // 已连续检测到无人的次数
bool pendingUpload = false;             // 是否有未成功上报的状态

unsigned long lastScanMs = 0;
unsigned long lastHeartbeatMs = 0;
unsigned long lastRetryMs = 0;

/**
 * 读取一个红外传感器。
 * 返回 true 表示该传感器检测到人体。
 */
bool readSensor(uint8_t pin) {
    const uint8_t activeLevel = IR_ACTIVE_HIGH ? HIGH : LOW;
    return digitalRead(pin) == activeLevel;
}

/**
 * 上传当前扫描结果到 Flask。
 * 成功返回 true，失败返回 false（上层会安排重试）。
 */
bool uploadScan(bool occupied, bool sensorA, bool sensorB, const char* scanType) {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[HTTP] WiFi 未连接，上报暂缓");
        return false;
    }

    String url = String(FLASK_BASE_URL) + "/api/scan";
    HTTPClient http;
    http.begin(url);
    http.setTimeout(5000);
    http.addHeader("Content-Type", "application/json");

    JsonDocument doc;
    doc["seat_id"]   = SEAT_ID;
    doc["occupied"]  = occupied;
    doc["sensor_a"]  = sensorA;
    doc["sensor_b"]  = sensorB;
    doc["scan_type"] = scanType;
    doc["rssi"]      = WiFi.RSSI();

    String payload;
    serializeJson(doc, payload);

    Serial.printf("[HTTP] POST %s -> ", url.c_str());
    Serial.println(payload);

    int httpCode = http.POST(payload);
    bool ok = (httpCode >= 200 && httpCode < 300);

    if (ok) {
        Serial.printf("[HTTP] 上报成功 HTTP %d\n", httpCode);
    } else {
        Serial.printf("[HTTP] 上报失败 HTTP %d\n", httpCode);
    }

    http.end();
    return ok;
}

/**
 * 按当前状态构造一次上报。
 * scanType 用于后端日志区分：occupied / vacant / heartbeat / retry。
 */
void sendCurrentState(const char* scanType) {
    bool occupied = (currentState == STATE_OCCUPIED);
    bool sensorA = readSensor(IR_SENSOR_A_PIN);
    bool sensorB = readSensor(IR_SENSOR_B_PIN);

    if (!uploadScan(occupied, sensorA, sensorB, scanType)) {
        pendingUpload = true;  // 失败后稍后重试
        lastRetryMs = millis();
    } else {
        pendingUpload = false; // 成功后清除待上报标记
    }
}

/**
 * 核心扫描逻辑。
 * 交叉传感器的两个输入做“或”合并：任一检测到人，本次扫描判定有人。
 * 无人必须连续出现 VACANT_CONFIRM_SCANS 次，才允许状态机切到空闲。
 */
void scanSeat() {
    bool sensorA = readSensor(IR_SENSOR_A_PIN);
    bool sensorB = readSensor(IR_SENSOR_B_PIN);
    bool occupiedNow = sensorA || sensorB;

    Serial.printf("[SCAN] A=%d B=%d => %s\n",
                  sensorA ? 1 : 0,
                  sensorB ? 1 : 0,
                  occupiedNow ? "有人" : "无人");

    if (occupiedNow) {
        // 有人：清零连续无人计数
        emptyScanCount = 0;
        if (currentState != STATE_OCCUPIED) {
            currentState = STATE_OCCUPIED;
            Serial.println("[STATE] 切换到有人，立即上报");
            sendCurrentState("occupied");
        }
    } else {
        // 无人：累计计数，只有连续多次无人才能切换为空闲
        emptyScanCount++;
        if (currentState == STATE_OCCUPIED &&
            emptyScanCount >= VACANT_CONFIRM_SCANS) {
            currentState = STATE_IDLE;
            Serial.println("[STATE] 连续无人达到阈值，切换到空闲");
            sendCurrentState("vacant");
        }
    }
}

/**
 * 连接 WiFi，最多阻塞 15 秒；成功后打印 IP。
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
    Serial.println("=== ESP32 座椅占用传感器启动 ===");
    Serial.printf("座椅编号: %s\n", SEAT_ID);
    Serial.printf("扫描间隔: %lu ms, 空闲确认次数: %d\n",
                  SCAN_INTERVAL_MS, VACANT_CONFIRM_SCANS);

    connectWiFi();
    lastScanMs = millis();
    lastHeartbeatMs = millis();
}

void loop() {
    unsigned long now = millis();

    // WiFi 断开时尝试重连
    if (WiFi.status() != WL_CONNECTED) {
        connectWiFi();
    }

    // 固定间隔扫描一次座椅
    if (now - lastScanMs >= SCAN_INTERVAL_MS) {
        lastScanMs = now;
        scanSeat();
    }

    // 周期心跳：让后端持续收到状态，也用于锁定机制按 n 分钟自动检测
    if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
        lastHeartbeatMs = now;
        sendCurrentState("heartbeat");
    }

    // 上报失败时自动重试，避免断网期间丢状态
    if (pendingUpload && (now - lastRetryMs >= RETRY_INTERVAL_MS)) {
        lastRetryMs = now;
        sendCurrentState("retry");
        if (!pendingUpload) {
            Serial.println("[HTTP] 补报成功，清空待上报标记");
        }
    }

    delay(50);  // 小延时，避免空转占用 CPU
}
