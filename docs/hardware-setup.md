# 硬件连接操作手册（ESP32 座位占用传感器）

> 本文覆盖：烧录 → 配网 → 注册 → 绑定座位 → 验证。
> 按顺序做，每步都有"怎么确认成功"。

---

## 0. 一句话原理

```
ESP32(HC-SR04) --WiFi--> Flask(:5800) --> MySQL --> 座位状态 --> 网页/终端/AI
```

设备用 **MAC 地址**作唯一 ID，开机自动向服务器注册；
管理员在**硬件调试面板**把它**绑定到某个座位**；
设备每 60 秒拉一次配置，拿到座位号后按 `report_interval_ms` 周期上报。

---

## 1. 接线（已实测跑通的方案）

HC-SR04 超声波模块 → ESP32：

| 模块引脚 | 接到 ESP32 | 说明 |
|---------|-----------|------|
| VCC | **3V3** | ⚠️ **不要接 5V**（曾因此短路，且 5V 需分压） |
| GND | GND | |
| TRIG | **GPIO 16** | |
| ECHO | **GPIO 27** | **直连，不用分压电阻** |

> **为什么是 3V3**：HC-SR04 标称 5V，但实测 3.3V 也能稳定工作，
> 且 ECHO 输出电平自动变成 3.3V —— **免去了分压电路**，接线最简单、最不容易出错。
> 代价是量程缩短到约 1~2 米，对 50cm 的座位检测完全够用。

**⚠️ 安全提示**：改动接线**必须先拔掉 USB 电源**，接好检查无误后再上电。

---

## 2. 启动服务器（必须先做）

```bash
cd D:\MAX_xiangmu
python app.py 0.0.0.0 5800
```

**必须是 `0.0.0.0`**（监听所有网卡），否则 ESP32 连不上（只监听 127.0.0.1 时外部设备访问不到）。

**确认成功**：
```powershell
netstat -ano -p TCP | Select-String ":5800.*LISTENING"
# 应看到  0.0.0.0:5800  ...  LISTENING
```

---

## 3. 查当前局域网 IP（每次换网络都会变！）

```powershell
ipconfig | Select-String "IPv4"
```

或：
```powershell
[System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
  Where-Object { $_.AddressFamily -eq 'InterNetwork' }
```

> **ESP32 的服务器地址必须填这个 IP**，例如 `http://10.140.232.124:5800`。
> 家里的 WiFi、学校 WiFi、手机热点 —— **每换一次网络，IP 都可能变**，
> 变了就要重新配置 ESP32（见第 4 步）。

**注意**：ESP32 只支持 **2.4G WiFi**，5G 频段连不上。

---

## 4. 给 ESP32 配网 + 填服务器地址（免重烧）

1. **上电**。如果它连不上 WiFi 或连不上服务器（连续失败 5 次），
   会**自动进入配置热点模式**：
   ```
   热点名：ESP32-Config   （无密码）
   ```
2. 手机/电脑连上这个热点
3. 浏览器打开 **`http://192.168.4.1`**
4. 填写：
   - **WiFi 名称 / 密码**（必须是 2.4G）
   - **服务器地址**：`http://<你的局域网IP>:5800`
     - ⚠️ 必须是 `http://`，**不要用 https**（固件用明文 HTTPClient，不支持 TLS）
     - 不要带结尾斜杠
5. 保存 → 设备自动重启并连接

**也可以用内网穿透地址**（不在同一局域网时）：
```
http://xxxx.r6.cpolar.top
```
> ⚠️ cpolar 免费版的公网地址**每次重启都会变**，变了就要重新配。
> **本地测试优先用局域网 IP，更稳定。**

---

## 5. 确认设备已注册

1. 浏览器登录系统（超级管理员）
2. 打开 **`/admin/hardware.html`**（硬件 / 传感器调试）
3. 设备列表里应出现一条 MAC 记录，标记为「**新设备**」

**ESP32 串口日志**（115200 波特率）看到这些就是成功了：
```
[WiFi] connected, IP=...
[REG] register ok
[CFG] seat_label=... type=ultrasonic ulthr=50 ...
[US] dist=3.59cm thr=50 -> occupied=1
```

---

## 6. 绑定座位（关键一步）

在硬件面板里给设备设置：

| 项 | 说明 |
|----|------|
| **绑定座位** | 选一个座位（如 A-1） |
| **传感器类型** | 选 `ultrasonic`（超声波） |
| **距离阈值** | 默认 **50** cm —— 小于它判「有人」 |
| **上报间隔** | 默认 **1000** ms |

保存后**最多等 60 秒**，设备拉到新配置即生效，**不需要重烧**。

**验证**：手挡住传感器 → 网页座位图该座位变「占用」；拿开 → 变「空闲」。

---

## 7. 上报逻辑（了解即可）

**超声波模式**（当前使用）：
```
occ = (距离 >= 0 且 距离 < 阈值) ? 1 : 0
ir_front = ir_back = occ
```

**红外模式**（两束红外）：
```
有人 = (ir_front == 1 且 ir_back == 1)     # 两束同时遮挡才算
```

**座位状态判定**（服务端统一逻辑）：
| 条件 | 状态 |
|------|------|
| 两束同时遮挡 | `occupied` 占用 |
| 连续空闲 ≥ 2 次上报 | `free` 空闲 |
| 超过 `SEAT_OFFLINE_HOURS`（默认 1 小时）无上报 | `error` 异常 |

> **注意**：没接传感器的座位长时间无上报也会变成 `error`，
> 这是正常的。AI 会正确区分「**尚未接入传感器**」和「**传感器异常**」。

**面板上的「在线/离线」**用的是另一个更短的阈值
`SEAT_ONLINE_TIMEOUT_MINUTES`（默认 **3 分钟**），设备断电 3 分钟后显示离线。

---

## 8. 常见问题排查

| 现象 | 原因 | 处理 |
|------|------|------|
| 串口一直 `dist=-1.00cm` | TRIG/ECHO 接反，或模块供电不对 | 按第 1 步表格检查；固件带 `[DIAG]` 诊断日志会自动判断 |
| 设备列表一直没有新设备 | 服务器地址填错 / 不是 2.4G / 不是 `0.0.0.0` | 按第 2、3、4 步逐项核对 |
| 设备显示在线但座位不变 | 没绑定座位 | 做第 6 步 |
| 网页打不开 `/admin/hardware.html` | 没登录或不是管理员 | 用超级管理员登录 |
| 换了 WiFi 后设备失联 | 局域网 IP 变了 | 重做第 3、4 步 |
| ESP32 完全没反应 | 可能短路触发过流保护 | **拔掉 USB**，拆除所有杜邦线，等 10 秒再插 |

---

## 9. 快速自检（不接硬件也能验证链路）

```bash
cd D:\MAX_xiangmu
python -c "
import sys; sys.path.insert(0, '.')
from app import app
app.config['TESTING']=True
with app.test_client() as c:
    print('注册:', c.post('/api/sensor/device/register', json={'device_id':'TEST:00'}).status_code)
    r = c.get('/api/sensor/device_config?device_id=TEST:00')
    print('拉配置:', r.status_code, r.get_json()['data']['registered'])
"
```

全部返回 200 / `True` 说明**服务端链路正常**，问题只可能在设备侧（配网或接线）。

---

## 10. 出厂固件位置

| 项 | 路径 |
|----|------|
| 源码 | `DEMO/src/main.cpp` |
| PlatformIO 工程 | `DEMO/platformio.ini` |
| 烧录 | `pio run -t upload --upload-port COM5`（端口号以设备管理器为准） |
| 串口监视 | `pio device monitor --port COM5 -b 115200` |
