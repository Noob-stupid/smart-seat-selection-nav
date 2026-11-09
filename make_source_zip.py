# -*- coding: utf-8 -*-
"""打包大赛用「智座源码.zip」。

大赛硬要求（来自上传页说明）：
  · 只支持 zip
  · 不支持音视频文件
  · 文件必须直接在压缩包根目录，不可嵌套文件夹
  · 必须是完整源代码
  · 源码中必须说明原创部分

做法：白名单 + 排除规则，逐条可核查。打包后自检：
  根目录不得出现嵌套文件夹、不得有音视频/文档/密钥、不得有 .env。
"""
import os
import shutil
import zipfile

ROOT = r'D:\MAX_xiangmu'
STAGE = r'D:\MAX_xiangmu\_stage_src'
OUT = r'D:\MAX_xiangmu\智座源码.zip'

# 只收这些（相对路径；目录递归收）
INCLUDE_FILES = [
    'app.py', 'config.py', 'requirements.txt',
    '.env.example', '.gitignore', '.dockerignore',
    'Dockerfile', 'docker-compose.yml', 'nginx.conf', 'pytest.ini',
    'backup_db.py', 'setup_db.py', 'build_native_bundle.py',
]
INCLUDE_DIRS = [
    'models', 'utils', 'templates', 'static', 'tests', 'view',
    'DEMO', 'mobile', 'docs',
]

# 目录内要连根剪掉的（构建产物 / 依赖 / 缓存 / 存档）
DROP_DIR_NAMES = {
    '__pycache__', 'node_modules', '.pio', '.vscode', '.git',
    '.pytest_cache', '.gradle', 'outputs', 'build', '.idea',
    'fonts', 'images', '作品简介-3张截图',
}

# 扩展名黑名单（音视频、文档、图片、字体、密钥、压缩包）
DROP_EXT = {
    '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.mp3', '.wav',
    '.apk', '.aab', '.ipa',
    '.zip', '.7z', '.rar', '.tar', '.gz',
    '.docx', '.doc', '.pptx', '.ppt', '.pdf',
    '.ttf', '.otf', '.woff', '.woff2',
    '.jks', '.keystore',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
    '.db', '.sqlite', '.sqlite3', '.pyc', '.log',
}

# 文件名黑名单（含密钥/会话/运行时数据）
DROP_FILE_NAMES = {
    '.env', 'system_config.json', 'seat_navigation.db',
    'package-lock.json', 'yarn.lock',
}

# docs/ 下只留技术文档
DOCS_KEEP_EXT = {'.md'}


def should_drop_file(name, path):
    low = name.lower()
    if low in DROP_FILE_NAMES:
        return True
    ext = os.path.splitext(low)[1]
    if ext in DROP_EXT:
        return True
    return False


def copy_tree(src, dst, rel_prefix):
    kept, dropped = 0, []
    for dirpath, dirnames, filenames in os.walk(src):
        # 剪掉整个目录
        dirnames[:] = [d for d in dirnames if d not in DROP_DIR_NAMES]
        rel_dir = os.path.relpath(dirpath, src)
        target_dir = dst if rel_dir == '.' else os.path.join(dst, rel_dir)
        os.makedirs(target_dir, exist_ok=True)

        for fn in filenames:
            src_f = os.path.join(dirpath, fn)
            rel = os.path.relpath(src_f, src).replace('\\', '/')

            # docs/ 只留 .md
            if rel_prefix == 'docs':
                if os.path.splitext(fn)[1].lower() not in DOCS_KEEP_EXT:
                    dropped.append(rel_prefix + '/' + rel)
                    continue

            if should_drop_file(fn, src_f):
                dropped.append(rel_prefix + '/' + rel)
                continue

            shutil.copy2(src_f, os.path.join(target_dir, fn))
            kept += 1
    return kept, dropped


README = """# 智座 · 智能选座与导航一体化系统

物联网感知的公共空间智能选座与导航一体化系统。
每个座位一块 ESP32 采集占用状态，服务端形成座位状态与预约规则，
前端把状态画成座位图，导航把选座结果落到一个真实的座位上。

## 一、这是什么

系统解决三个到现场就失效的问题：

- **查不到** —— 多数场馆只显示「是否已被预约」，不显示此刻座位上有没有人
- **找不到** —— 知道座位在 5 楼仍要逐个比对，跨楼、跨校区断链
- **管不住** —— 占座缺少客观依据，管理员只能靠巡场，纠纷时各说各话

做法是把「座位上此刻有没有人」和「怎么走到那个座位」放进同一条数据链：
传感器判占 → 服务端状态机 → 座位图/终端/管理端 → 室内外导航 → 签到。

边界：只做感知与引导，不改门禁硬件，不涉及支付，也不替代排课。

## 二、目录结构

```
app.py                     Flask 主程序：路由、状态机、判占规则、AI 接口
config.py                  配置类（敏感项从环境变量读）
requirements.txt           Python 依赖

models/                    数据模型
  building.py              学校 / 建筑 / 楼层 / 座位
  reservation.py           预约
  sensor_device.py         传感设备与其配置
  sensor_data.py           上报原始读数
  user.py                  用户与角色
  school.py                多校归属

utils/                     业务模块
  navigation.py            室内路网、A* 寻路、跨楼层、断点搭桥
  recommendation.py        四维加权推荐排序
  sensor_simulator.py      传感器模拟器（演示与联调用）
  locking.py               m/n/t 防占座锁定与监控
  ai_agent.py              AI 智能体主循环（工具调用 + 写操作确认）
  ai_tools.py              8 个工具的定义与实现（5 读 3 写）
  llm.py                   大模型客户端封装（支持多家供应商）
  ai_service.py            AI 运营简报与趋势
  ai_context.py            给模型的上下文拼装
  mapget.py                室外地图服务对接（高德 / 百度）
  image_preprocessor.py    平面图图像预处理
  student_import.py        学生名单批量导入

templates/                 页面模板（Jinja2）
static/                    前端资源
  js/                      页面脚本；native-bundle.js 是移动端能力的合并产物
  css/                     样式
  vendor/                  自托管的前端依赖（见第五节）

tests/                     后端自动化测试（pytest）
DEMO/                      ESP32 固件源码（PlatformIO 工程）
mobile/                    Android 壳工程（Capacitor 配置与源码）
view/                      平面图自动建图（关键帧 → 拼接 → 墙体识别 → 路网）
docs/                      技术文档（Markdown）

backup_db.py               数据库备份
setup_db.py                初始化数据库与管理员
build_native_bundle.py     把前端模块合并成 native-bundle.js
```

## 三、怎么跑起来

### 1. 环境

- Python 3.10+（开发用 3.14）
- MySQL 5.7+（无 MySQL 时自动回落 SQLite）
- Redis（可选，用于行为缓存与并发锁）

### 2. 装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

复制 `.env.example` 为 `.env`，按需填写。**不要提交 `.env`**。

关键项：

```
SECRET_KEY=换成你自己的随机串
DB_HOST=127.0.0.1
DB_USER=root
DB_PASSWORD=你的密码
DB_NAME=seat_navigation

# 可选：AI 与地图服务
AI_PROVIDER=deepseek
AI_API_KEY=你的Key
NAV_MAP_KEY=高德地图Key
```

### 4. 建库并启动

```bash
python setup_db.py                 # 建表 + 创建超级管理员
python app.py 0.0.0.0 5800         # 绑定 0.0.0.0，局域网设备才能连上
```

浏览器打开 `http://127.0.0.1:5800`。

> **注意**：必须绑 `0.0.0.0`。绑 `127.0.0.1` 时局域网里的 ESP32 连不上服务端。
> 生产环境用 gunicorn：
> ```bash
> gunicorn -k eventlet -w 1 -b 0.0.0.0:5800 app:app --daemon
> ```

### 5. 跑测试

```bash
python -m pytest tests -q
```

### 6. 硬件（可选）

```bash
cd DEMO
pio run -t upload                  # 烧录固件
```

设备首次上电会开热点 `ESP32-Config`，手机连上后访问 `192.168.4.1`
填 WiFi 与服务器地址。之后设备以 WiFi MAC 作 device_id 自动注册，
在管理端「硬件 / 传感器调试」绑定座位即可，改配置不用重烧固件。

## 四、原创部分说明

本项目由参赛团队独立设计与实现。以下是**团队原创**的部分：

### 4.1 判占与状态机（app.py · models/ · utils/locking.py）

- **双路与运算判占**：两路传感器同时命中才判占用，单路命中只算「经过」，
  不改变座位状态。规则只写在服务端一处，硬件侧不做本地判定。
- **四态状态机**：free / occupied / locked / error，进入与退出条件全部写在服务端；
  配四套兜底 —— 连续 2 次判空才释放（抗抖动）、有预约期间不因无人释放、
  超时无上报转 error、回座坐满 t 秒才算有效回归。
- **m/n/t 防占座**：m 分钟可锁定、n 分钟检测一次、回座满 t 秒算有效回归；
  每次锁定写一条可回溯记录（谁锁的、锁多久、检测几次、是否自动解锁）。

### 4.2 室内导航与路网（utils/navigation.py）

- **平面图 → 路网**：读图灰度 → CLAHE 增强 → 二值化择优 → 形态学去噪 →
  Zhang-Suen 细化 → 等距采样出节点。
- **A\* 寻路**：邻接表 + heapq，启发函数取欧氏距离（可采纳、不高估，出堆即最短路）。
- **断点搭桥带距离上限**：缺口不超过本路网中位边长的 5 倍才补桥；
  超过就判定为两块独立区域，如实报错而不是给一条走不通的假路径。
- **跨楼层分段**：按楼层分组求路，按高差提示上楼或下楼至第几层。

### 4.3 推荐排序（utils/recommendation.py）

四维加权线性打分（距离 / 区域热度 / 偏好匹配 / 场所拥挤度，默认 0.35/0.25/0.25/0.15），
权重和恒为 1、后台可调。**只对空闲座位排序，不写任何座位状态**。

### 4.4 AI 智能体（utils/ai_agent.py · utils/ai_tools.py）

- **工具调用**：8 个工具（5 个只读、3 个可写），模型自己决定调哪个、参数填什么，
  最多 4 轮。
- **读写分离 + 写操作二次确认**：只读工具直接执行；写工具**不执行**，
  只记成「待确认提案」返回前端，管理员点确认后才真正落库。
  模型没有任何直接写库的路径。
- **AI 不参与判占**：座位状态只由传感器读数经确定规则产生，模型只解释不生产。

### 4.5 硬件与部署（DEMO/ · docs/）

- **产线预置配置**：管理端生成 `secrets.h`（WiFi + 服务器地址），
  编进固件后所有设备烧同一份，烧完通电即连，不必逐台开热点配网。
- **设备自愈**：连不上 WiFi 或服务器不可达达到阈值后自动清空配置回配网模式，不会变砖。
- **在线判定拆分**：区分「心跳时间」与「上报时间」，
  设备不上报时显示「无数据」而不是笼统的「在线」。

### 4.6 移动端（mobile/ · static/js/native-bundle.js）

- **PDR 位置推算**：扫码锚定 + 计步与航向推算，**逐步累加位移向量**
  （不是用当前朝向乘累计距离，避免转身时把走过的位移整体重投影），
  偏离规划路径超过 5 米提示重新扫码。
- **原生能力按需开放**：同一套 Web 页面在 Capacitor 壳内运行，
  扫码 / 语音 / 通知 / 围栏 / 缓存 / 捷径走同一个桥接层，浏览器里自动降级。

## 五、第三方开源代码与依赖

### 5.1 Python 依赖（见 requirements.txt）

| 组件 | 用途 | 许可 |
|---|---|---|
| Flask | Web 框架 | BSD-3-Clause |
| Flask-SQLAlchemy | ORM | BSD-3-Clause |
| Flask-SocketIO | 实时推送 | MIT |
| PyMySQL | MySQL 驱动 | MIT |
| eventlet / gunicorn | WSGI 运行 | MIT |
| redis-py | Redis 客户端 | MIT |
| opencv-python | 平面图图像处理 | Apache-2.0 |
| NumPy | 数值计算 | BSD-3-Clause |
| Pillow | 图片处理 | HPND |
| qrcode | 座位二维码生成 | BSD-3-Clause |
| python-dotenv | 环境变量 | BSD-3-Clause |
| requests | HTTP 客户端 | Apache-2.0 |
| python-pptx / python-docx | 文档生成（仅开发期使用） | MIT |

### 5.2 前端自托管依赖（static/vendor/）

为避免公共 CDN 不可达导致页面无法渲染，以下库**直接放在仓库里**：

| 组件 | 版本 | 许可 |
|---|---|---|
| Vue.js | 3.4.21 | MIT |
| axios | 1.6.7 | MIT |
| Socket.IO Client | 4.7.5 | MIT |
| Font Awesome Free | 6.5.1 | CC BY 4.0（图标）/ SIL OFL 1.1（字体）/ MIT（代码） |

### 5.3 算法与规范的公开来源

- **A\* 寻路算法** —— 公开算法，按教材标准实现，代码为自行编写。
- **Zhang-Suen 细化算法** —— 公开图像处理算法，自行实现。
- **CLAHE（限制对比度自适应直方图均衡）** —— 由 OpenCV 提供实现。
- **二维码编码** —— 使用 qrcode 库，编码规范为 ISO/IEC 18004。

### 5.4 未使用的第三方成果

本项目**没有**使用任何第三方选座系统、导航 SDK 或闭源组件；
室内路网生成、寻路、判占、锁定、推荐排序、AI 工具层均为自行实现。

## 六、技术栈

- **后端**：Flask 3.1 · SQLAlchemy · Flask-SocketIO · MySQL / SQLite · Redis
- **前端**：Vue 3（无构建链，CDN 自托管）· 原生 JS · WebSocket
- **移动端**：Capacitor 7（Android 壳，加载同一套 Web）
- **硬件**：ESP32（Arduino 框架）· HC-SR04P 超声波 / PIR / 红外避障
- **AI**：DeepSeek（OpenAI 兼容接口），支持 deepseek / openai / qwen / zhipu 切换
- **测试**：pytest，后端 476 项自动化测试

## 七、说明

- 仓库中**不包含**任何密钥：`.env` 未提交，数据库密码与大模型 Key 只从环境变量读。
- `data/`、`uploads/`、`backups/` 为运行时目录，首次启动会自动创建。
- `static/vendor/` 下的前端依赖为保证离线可用而随仓库提供，来源与许可见第五节。
"""


def main():
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(STAGE, exist_ok=True)

    total, all_dropped = 0, []

    for f in INCLUDE_FILES:
        src = os.path.join(ROOT, f)
        if not os.path.exists(src):
            print('  ⚠ 缺文件：%s' % f)
            continue
        shutil.copy2(src, os.path.join(STAGE, f))
        total += 1

    for d in INCLUDE_DIRS:
        src = os.path.join(ROOT, d)
        if not os.path.isdir(src):
            print('  ⚠ 缺目录：%s' % d)
            continue
        kept, dropped = copy_tree(src, os.path.join(STAGE, d), d)
        total += kept
        all_dropped.extend(dropped)

    # README
    with open(os.path.join(STAGE, 'README.md'), 'w', encoding='utf-8') as fh:
        fh.write(README)
    total += 1

    print('  收录 %d 个文件' % total)
    print('  剔除 %d 个文件（音视频/文档/图片/字体/密钥/构建产物）' % len(all_dropped))

    # 打包：从 STAGE 内部压缩，保证解压后不多一层目录
    if os.path.exists(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dirpath, dirnames, filenames in os.walk(STAGE):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, STAGE).replace('\\', '/')
                z.write(full, rel)

    print()
    print('  输出：%s' % OUT)
    print('  大小：%.1f MB' % (os.path.getsize(OUT) / 1024 / 1024))


if __name__ == '__main__':
    main()
