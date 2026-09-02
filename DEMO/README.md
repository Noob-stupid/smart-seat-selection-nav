# DEMO —— ESP32 红外占座传感器（硬件演示）

本目录是“物联网感知：ESP32 座椅占用检测”的硬件演示工程，位于主系统仓库内。

## 目录结构

```
DEMO/
├── src/main.cpp          ESP32 固件（默认对接主系统，见「两条数据链路」）
├── platformio.ini        PlatformIO 工程配置（Arduino 框架 + ArduinoJson 7）
├── include/ lib/ test/   PlatformIO 默认目录（占位）
├── backend/              离线小后端（Flask + sqlite，自带 seat_state.db）
└── .vscode/              调试/扩展配置
```

## 两条数据链路（先分清）

| 链路 | 固件上报接口 | 端口 | 写入数据库 | 用途 |
| --- | --- | --- | --- | --- |
| A：对接主系统（默认） | `POST /api/sensor/report` | 5800 | 主系统 MySQL `seat_navigation`（或 fallback `seat_navigation.db`） | 真实生产 / 演示 |
| B：离线演示 | `POST /api/scan` | 5000 | `backend/seat_state.db` | 纯离线验证 |

`src/main.cpp` 当前默认是**链路 A**：上报 `ir_front`/`ir_back` 到主系统，
**不写 `seat_state.db`**。所以用默认固件遮挡传感器，`seat_state.db` 不会变化——
这是预期行为，并非遮挡没生效。

## 让物理遮挡后 `seat_state.db` 变化（链路 B / 情况3）

要让「用手遮挡传感器 → `seat_state.db` 里 `occupied` 变化」，按下面 4 步做：

### 步骤 1：启动离线小后端

```bash
cd DEMO/backend
pip install -r requirements.txt
python app.py          # 监听 0.0.0.0:5000
```

### 步骤 2：把固件改回 `/api/scan` 模式

编辑 `DEMO/src/main.cpp`，做三处改动：

1. `SERVER_URL` 指向后端端口 **5000**：

```cpp
const char* SERVER_URL = "http://192.168.1.7:5000";   // backend/app.py 所在电脑的局域网 IP
```

2. 座位标识：后端 `seats.id` 是**文本主键**，直接填字符串：

```cpp
const char* SEAT_ID = "A区-12";   // 任意字符串，首次上报会自动建记录
```

3. 把上报函数替换为「本地判定两束同时遮挡 → 上报 `/api/scan`」：

```cpp
bool reportSeat() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[HTTP] WiFi 未连接，上报暂缓");
        return false;
    }

    int a = readSensor(IR_SENSOR_A_PIN) ? 1 : 0;  // 1 = 检测到人/物
    int b = readSensor(IR_SENSOR_B_PIN) ? 1 : 0;
    bool occupied = (a == 1 && b == 1);            // 两束同时遮挡 → 有人

    String url = String(SERVER_URL) + "/api/scan";
    HTTPClient http;
    http.begin(url);
    http.setTimeout(5000);
    http.addHeader("Content-Type", "application/json");

    JsonDocument doc;
    doc["seat_id"]   = SEAT_ID;
    doc["occupied"]  = occupied;
    doc["sensor_a"]  = a;
    doc["sensor_b"]  = b;

    String payload;
    serializeJson(doc, payload);
    Serial.printf("[HTTP] POST %s -> %s\n", url.c_str(), payload.c_str());

    int code = http.POST(payload);
    bool ok = (code >= 200 && code < 300);
    Serial.printf("[HTTP] 上报 %s HTTP %d\n", ok ? "成功" : "失败", code);
    http.end();
    return ok;
}
```

（其余 `setup()` / `loop()` / `connectWiFi()` 保持不变，`loop()` 里的周期上报逻辑照常工作。）

### 步骤 3：烧录

```bash
cd DEMO
pio run -t upload
pio device monitor    # 波特率 115200，应看到 POST .../api/scan
```

### 步骤 4：验证

- **遮挡**：两束同时被遮 → 串口打印 `{"occupied":true,"sensor_a":1,"sensor_b":1}`
  → `seat_state.db` 该座位的 `occupied` 变为 1。
- **拿开**：`occupied=false` 需**连续两次**上报才释放（后端防抖逻辑）。

快速用 curl 验证后端（无需硬件）：

```bash
curl -X POST http://127.0.0.1:5000/api/scan -H "Content-Type: application/json" \
  -d "{\"seat_id\":\"A区-12\",\"occupied\":true,\"sensor_a\":1,\"sensor_b\":1}"
curl http://127.0.0.1:5000/api/seat/status
```

## 对接主系统（链路 A，默认）

`src/main.cpp` 默认已改造成**主系统客户端**：`POST {主系统}/api/sensor/report`，
上报原始 `ir_front`/`ir_back`，占用判定由主系统状态机完成。完整接入说明见
[`docs/hardware-integration.md`](../docs/hardware-integration.md)。

## 快速烧录

```bash
pio run -t upload     # 在 DEMO/ 目录下执行
pio device monitor    # 波特率 115200
```

烧录前务必先编辑 `src/main.cpp` 顶部的 WiFi / 服务器地址 / 座位标识。
