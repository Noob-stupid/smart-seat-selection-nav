# 智能选座与导航 · 移动端 App（Capacitor）

> 本目录是**独立的移动端工程**，不影响项目原有的 Web 端（Flask + Jinja 模板）。

---

## 一、定位（答辩口径）

**这是「混合应用（Hybrid App）」，不是纯原生，也不是普通网页套壳。**

核心技术点：**通过 Capacitor 的原生插件桥，调用浏览器拿不到的能力**。

| 能力 | Web 浏览器 | 本 App |
|------|-----------|--------|
| 扫码 | 需 https 且体验差 | ✅ 原生相机 |
| 语音识别 | 部分浏览器不支持 | ✅ 原生麦克风 |
| 后台定位 / 地理围栏 | ❌ 拿不到 | ✅ 原生定位 |
| 本地通知 | 需 https + 用户常驻 | ✅ 原生通知 |
| 离线存储 | localStorage（易失） | ✅ 原生 Preferences |
| 震动反馈 | 部分支持 | ✅ 原生 |

**答辩话术（建议）：**

> "我们的 App 是基于 Capacitor 的**混合应用**。它复用了已有的云端服务，
> 但**通过原生插件桥接，实现了浏览器无法稳定提供的移动端能力**：
> 扫码占座（原生相机）、语音选座（原生麦克风）、地理围栏（后台定位）、
> 本地通知、离线缓存。这才是移动端应用区别于网页的价值。"

---

## 二、当前已实现

| 功能 | 状态 | 说明 |
|------|------|------|
| 扫码签到 | ✅ | 预约页「签到」输入框旁自动出现「📷 扫码」按钮 |
| 扫码占座 | ✅ | 座位图页浮动按钮「扫码占座」，扫码后跳转预约 |
| 语音提问 | ✅ | AI 助手浮窗内出现「🎤 语音」按钮 |
| 本地通知 | ✅ | `Native.notify(title, body)`，演示时可直接调 |
| 原生定位 | ✅ | `Native.getPosition()`，不受 http 安全上下文限制 |
| 离线缓存 | ✅ | 自动缓存座位/建筑接口响应，断网时提示 |
| 震动反馈 | ✅ | 扫码成功后震动 |
| App 模式标识 | ✅ | 左下角绿色小标，演示时可直接指出 |

---

## 三、目录结构

```
mobile/
├── package.json              依赖与脚本
├── capacitor.config.json     核心配置（server.url 指向云端）
├── www/                      内置网页（用 server.url 时基本用不到）
│   ├── index.html            启动占位页
│   ├── native-bridge.js      原生能力桥（window.Native）
│   └── native-features.js    页面自动增强层
└── android/                  Android 原生工程（由 cap add android 生成）
    └── app/src/main/AndroidManifest.xml   权限声明
```

> `native-bridge.js` 与 `native-features.js` 同时复制到了项目
> `static/js/` 下 —— 因为 App 加载的是云端页面，这两个脚本必须由云端提供。

---

## 四、常用命令

```bash
cd mobile

npm install                 # 安装依赖（国内用 --registry=https://registry.npmmirror.com）

npx cap sync android        # 把 www 与插件同步进 Android 工程
npx cap open android        # 用 Android Studio 打开

# 命令行直接出 APK
cd android
gradlew.bat assembleDebug   # 产物：android/app/build/outputs/apk/debug/app-debug.apk

# 装到手机
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

---

## 五、改云端地址

编辑 `capacitor.config.json`：

```json
"server": {
  "url": "http://zhinengzuo.site",    ← 改这里
  "cleartext": true                    ← 用 https 时改成 false
}
```

改完执行 `npx cap sync android` 重新打包。

> **配好 HTTPS 后**：把 url 改成 `https://zhinengzuo.site`，
> `cleartext` 改 `false`，`AndroidManifest.xml` 里的
> `android:usesCleartextTraffic` 也可以删掉。

---

## 六、网页侧怎么调原生能力

任何页面（只要引入了 `native-bridge.js`）都可以直接用：

```javascript
// 当前是否运行在 App 内
if (window.Native.available) { ... }

// 扫码
const text = await Native.scanQrCode();

// 语音（返回识别文本）
const text = await Native.listenOnce('zh-CN');

// 通知
await Native.notify('座位已释放', 'A-4 现在空出来了');

// 定位（原生，不受 http 限制）
const pos = await Native.getPosition();   // {lat, lng, accuracy}

// 离线缓存
await Native.cacheSet('seats', data);
const data = await Native.cacheGet('seats');

// 震动
Native.vibrate(60);
```

**在浏览器里打开时 `Native.available === false`**，
所有方法都会安全降级（返回 null 或走浏览器原生 API），
**同一套页面在网页和 App 里都能跑，不会报错。**

---

## 七、部署清单（App 用的云端文件）

App 加载的是云端页面，所以以下文件**必须传到服务器**：

```
static/js/native-bridge.js        新增
static/js/native-features.js      新增
templates/**/*.html               19 个页面（已注入两行 script）
```

---

## 八、已知限制

| 项 | 说明 |
|----|------|
| 网页版定位 | `navigator.geolocation` 需要 **https 安全上下文**；http 下只能用 `Native.getPosition()`（原生插件） |
| 语音识别 | Android 需装 Google 语音服务；部分国产 ROM 可能不可用，已在代码里做可用性检测 |
| 扫码 | 首次使用会弹相机权限，需用户同意 |
| 后台定位 | Android 10+ 需额外申请「始终允许」，系统会二次弹窗 |
| 混合内容 | 若云端是 https 而接口是 http，需 `allowMixedContent: true`（已配） |
