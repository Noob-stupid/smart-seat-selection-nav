# DEMO —— ESP32 红外占座传感器（硬件演示）

本目录是“物联网感知：ESP32 座椅占用检测”的硬件演示工程，位于主系统仓库内。

## 目录结构

```
DEMO/
├── src/main.cpp          ESP32 固件（已接入主系统，见下方说明）
├── platformio.ini        PlatformIO 工程配置（Arduino 框架 + ArduinoJson 7）
├── include/ lib/ test/   PlatformIO 默认目录（占位）
├── backend/              原独立小后端（Flask + sqlite），仅保留作离线演示
└── .vscode/              调试/扩展配置
```

## 固件现在对接谁？

`src/main.cpp` 已被改造为**主系统客户端**：不再上报到 `backend/app.py` 的
`/api/scan`，而是直接 `POST {主系统}/api/sensor/report`（上报原始
`ir_front`/`ir_back`，占用判定由主系统状态机完成），可按**座位标签**或
**数据库 seat_id** 绑定座位。

- 完整接入说明（协议 / 接线 / 烧录 / 主系统侧准备 / 验收清单）见
  [`docs/hardware-integration.md`](../docs/hardware-integration.md)。
- 想跑**纯离线演示**（不依赖主系统）：启动 `backend/app.py` 后，
  把固件改回旧的 `/api/scan` 上报方式（历史版本见 git 记录 `DEMO/src/main.cpp`）。

## 快速烧录

```bash
pio run -t upload     # 在 DEMO/ 目录下执行
pio device monitor    # 波特率 115200
```

烧录前务必先编辑 `src/main.cpp` 顶部的 WiFi / 服务器地址 / 座位标识。
