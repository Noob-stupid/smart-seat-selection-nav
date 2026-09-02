# 硬件接入：ESP32 红外占座传感器 ↔ 主系统

> DEMO（`DEMO/` 目录）原本是"硬件 + 独立小后端"的演示工程：
> ESP32 固件只把数据上报给 `DEMO/backend/app.py`（自带 sqlite，接口 `/api/scan`）。
> 深度集成后，**固件改为直接对接主系统**，DEMO 里的小后端仅保留作离线演示，
> 真实数据链路为：
>
> ```
> ESP32（两个红外传感器）
>   └─ HTTP POST /api/sensor/report（原始 ir_front / ir_back）
>        └─ 主系统 Flask：Seat 状态机（占用/空闲/锁定/异常）+ 落库 + WebSocket 推送
>              └─ 前端实时刷新：座位图 / 占用统计 / 锁定入口
> ```

## 1. 接口映射（DEMO 小后端 → 主系统）

| DEMO 小后端 | 主系统 smart-seat-selection-nav | 说明 |
| --- | --- | --- |
| `POST /api/scan` | `POST /api/sensor/report` | 红外扫描上报（主系统按**原始双光束**判定占用，逻辑见第 3 节） |
| `POST /api/seat/<seat_id>/lock` | `POST /api/lock/start`（需登录） | 发起座位锁定 |
| `GET /api/seat/status` | `GET /api/seats`、`GET /api/status` | 查询座位状态 / 统计 |
| `GET /api/users/<user_id>` | `GET /api/behavior/report/<user_id>` | 用户锁定行为 |
| `GET /api/health` | —（可用 `GET /api/status` 探活） | 健康检查 |

设备端**只需要**调用 `POST /api/sensor/report`；
锁定（m/n 动态防抢座）、预约、签到等交互由 Web 前端调用主系统完成，
与旧版设计一致——设备端只做"持续扫描 + 上报"。

## 2. 上报协议

`POST {SERVER_URL}/api/sensor/report`，JSON：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `seat_id` | int | 数据库座位 id（`seats.id`）。与 `seat_label` 二选一，**优先** |
| `seat_label` | string | 座位标签（`seats.seat_label`，如 `A区-12`，与平面图一致）。未传 `seat_id` 时使用 |
| `floor_id` | int | 可选。同名标签跨楼层存在时用于消歧 |
| `ir_front` | int | 前方红外读数 0/1（ESP32 传感器 A） |
| `ir_back` | int | 后方红外读数 0/1（ESP32 传感器 B） |

示例（按标签上报）：

```json
{ "seat_label": "A区-12", "ir_front": 1, "ir_back": 1 }
```

成功返回：

```json
{ "success": true, "data": { "seat_id": 3, "status": "occupied", "consecutive_empty": 0 } }
```

失败：`404` = 座位不存在（标签写错 / 座位已删除）；`400` = 参数错误，
或标签匹配到多个座位（提示携带 `floor_id` 或改用 `seat_id`）。

> 说明：固件默认**不做本地占用判定**，直接上报原始双光束读数；
> 占用状态机统一在主系统维护，避免“设备端一套、后台一套”的判定漂移。
> （历史 DEMO 固件曾在设备端自行判断 `有人/无人` 并附 `scan_type`，已不需要。）

## 3. 主系统状态判定规则（设备端需理解）

来源：`app.py` → `sensor_report()` / `_build_sensor_simulator()` 回调。

1. **占用**：一次上报中 `ir_front=1 且 ir_back=1` → 座位置为`occupied`（红），
   记录 `occupied_since`；若座位处于`free/error`，同时点亮锁定按钮可用时间。
2. **释放**：连续**两次** `ir_front=0 或 ir_back=0` 的"无人"上报 →
   若座位处于`occupied/error`且**无进行中的预约**，置为`free`（绿）。
   预约时段内物理无人不会释放座位（防预约占位被传感器误清）。
3. **异常**：超过 `SEAT_OFFLINE_HOURS`（默认 24h，管理员可在设置页改）未收到
   该座位任何上报 → 标记`error`（设备疑似掉线/故障）；收到一次正常间隔上报自动恢复。

固件每 `REPORT_INTERVAL_MS`（默认 5s）上报一次，正好满足"释放需两次无人"的判定，
且天然充当心跳，避免被误判离线。

## 4. 座位标识绑定（一机一座）

每台 ESP32 烧录前，在 `DEMO/src/main.cpp` 顶部配置区指定它负责的座位：

```cpp
const bool IDENTIFY_BY_SEAT_LABEL = true;   // 推荐按标签
const char* SEAT_LABEL = "A区-12";          // 与管理端平面图显示的座位标签一致
const int   FLOOR_ID   = 0;                 // 标签跨楼层重复时才需要填（>0）
```

- 标签怎么查：管理端「楼层平面图」页面上的座位编号，就是 `seat_label`。
- 若后台 `seat_label` 命名是纯数字（如 `12`），同样按字符串填写即可。
- 数据库数字 id 方式：把 `IDENTIFY_BY_SEAT_LABEL` 改 `false`，填 `SEAT_ID = <seats.id>`；
  数字 id 可由管理员在「管理端 → 座位二维码 / 平面图接口」处查到，一般无需使用。
- 多台设备绑定到同一座位会互相覆盖状态，**不要复用**。

## 5. 硬件接线

| ESP32 引脚 | 连接 |
| --- | --- |
| `GPIO23`（`IR_SENSOR_A_PIN` → `ir_front`） | 红外传感器 A OUT |
| `GPIO27`（`IR_SENSOR_B_PIN` → `ir_back`） | 红外传感器 B OUT |
| `3.3V` | 两个传感器 VCC |
| `GND` | 两个传感器 GND |

- 默认 `IR_ACTIVE_HIGH=false`：适配**红外避障模块**（检测到物体输出 LOW）。
- 改用 **PIR 人体感应模块**（检测到人体输出 HIGH）时，把 `IR_ACTIVE_HIGH` 改为 `true`。
- 两传感器交叉放置（座椅左前方 45° 与右后方 45°），人坐下时两束同时被遮 → `(1,1)`。

## 6. 固件配置与烧录

`DEMO/` 是 PlatformIO 工程（`platformio.ini`，Arduino 框架 + ArduinoJson 7）。

1. 安装 [PlatformIO](https://platformio.org/)（VSCode 插件或 CLI）。
2. 编辑 `DEMO/src/main.cpp`：WiFi、`SERVER_URL`（主系统电脑的局域网 IP:5800）、
   座位标识（第 4 节）。
3. 烧录 + 串口监视：

   ```bash
   cd DEMO
   pio run -t upload
   pio device monitor          # 波特率 115200
   ```

   串口应能看到周期性的 `POST .../api/sensor/report -> {...}` 与 `上报成功 HTTP 200`。

## 7. 主系统侧准备（让真机接管）

1. **先建好座位**：管理端创建建筑物/楼层/座位（或在平面图上放置座位并保存标签）。
2. **关闭传感器模拟器**（避免随机数据与真机互相覆盖）：
   - 方式 A（推荐，持久生效）：主系统目录下 `.env` 设
     `SENSOR_SIMULATOR_AUTOSTART=False`，再启动；
   - 方式 B（临时）：主系统运行中，由管理员调用
     `POST /api/admin/simulator/stop`（或重启前临时改配置）。
3. **启动主系统监听局域网**（ESP32 才能访问；默认端口 5800）：

   ```bash
   python app.py 0.0.0.0 5800
   ```

   - 启动日志会打印局域网访问地址；`ipconfig` 查到本机 IP 后填进固件 `SERVER_URL`。
   - Windows 防火墙需放行 Python 对端口 5800 的入站访问（首次运行会弹窗，允许即可）。
4. 打开用户端「座位图」页面：真机上报后座位应在 ≤5s 内变红（占用）、
   无人约 10s 后变绿（释放），无需刷新页面（WebSocket 推送）。

## 8. 验收清单

- [ ] 单台 ESP32 上电 → 串口持续输出 `HTTP 200`，无 `座位不存在`
- [ ] 人坐下（两束同时被遮）→ 座位图对应座位 ≤5s 变红
- [ ] 人离开 → 连续两次无人上报后座位变绿（约 10s）
- [ ] 拔掉设备 WiFi/断电 > 24h → 主系统将座位标记为异常；恢复后自动转回正常
- [ ] 锁定流程不受影响：占用满 m 分钟后 Web 端可锁定，锁定期间 n 分钟检测沿用真实上报数据
- [ ] `SENSOR_SIMULATOR_AUTOSTART=False` 生效，无模拟随机数据混入
- [ ] 管理端「行为分析」仍能看到真机上报对应的占用/回归数据

## 9. 常见问题

| 现象 | 排查 |
| --- | --- |
| 串口 `上报失败 HTTP 404` | 座位标签写错 / 该座位不存在；核对第 4 节 |
| 串口 `HTTP 400`，提示标签匹配到多个座位 | 同名标签跨楼层，填 `FLOOR_ID` 消歧 |
| `HTTP -1` / 连接超时 | 主系统是否 `0.0.0.0` 启动；ESP32 与电脑同一局域网；防火墙是否放行 5800 |
| 人坐下了座位不变红 | 传感器活性电平反了（把 `IR_ACTIVE_HIGH` 取反试试）；检查接线与串口打印的 `ir=(1,1)` 是否出现 |
| 座位频繁闪红/绿 | 多半是模拟器还在跑随机翻转，先停模拟器（第 7 节） |
| 座位显示异常（灰/叹号） | 设备断上报超过 `SEAT_OFFLINE_HOURS`；恢复供电即自动恢复 |

## 10. 相关文件

- 固件：`DEMO/src/main.cpp`（主系统客户端）、`DEMO/platformio.ini`
- 主系统接收端：`app.py` → `sensor_report()`（支持 `seat_id` / `seat_label`）
- 状态机参照：`utils/sensor_simulator.py`（模拟器回调与 `/api/sensor/report` 逻辑一致）
- 座位模型：`models/building.py` → `Seat`（`ir_front`/`ir_back`/`ir_enabled`/`last_scan_time`）
- 离线阈值：`config.py` → `SEAT_OFFLINE_HOURS`、`SEAT_SWEEP_INTERVAL_MINUTES`
