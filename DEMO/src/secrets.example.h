/*
 * 产线预置配置（示例）—— 复制成 secrets.h 后填自己的值
 * ------------------------------------------------------------------
 * 想实现「烧完通电即连服务器、不用人去开热点填表」，就把这里填好，
 * 编译出来的固件已经带配置：设备上电直接连 WiFi → 注册 → 拉云端配置。
 *
 * 用法：
 *     cp DEMO/src/secrets.example.h DEMO/src/secrets.h
 *     编辑 secrets.h 填 SSID / 密码 / 服务器地址
 *     pio run -t upload          （或把 .bin 交给一拖多烧录器批量烧）
 *
 * ⚠️ secrets.h 已在 .gitignore 里，不会进版本库 —— WiFi 密码不要提交。
 *    仓库里只保留这份 example。
 *
 * ⚠️ 三个值全留空（默认）时，固件行为与以前完全一致：
 *    首次上电开热点 ESP32-Config，等手机来配。
 */
#ifndef SEAT_SECRETS_H
#define SEAT_SECRETS_H

/* WiFi 名称（ESP32 只支持 2.4GHz，5G 热点连不上） */
#define SEAT_DEFAULT_SSID   "StudyRoom_WiFi"

/* WiFi 密码；开放网络留空串 "" */
#define SEAT_DEFAULT_PASS   "12345678"

/* 服务器地址：含端口则带上，不带末尾斜杠
 *
 *   公网（推荐）：https://zhinengzuo.site
 *     云端 nginx 把 http:// 全部 301 跳到 https://，所以必须用 https。
 *     固件用 WiFiClientSecure + setInsecure()（不校验证书）。
 *     服务器同时支持 TLS 1.2 / 1.3，ESP32 会协商到 TLS 1.2。
 *
 *   局域网直连：http://192.168.1.8:5800
 *     内网调试用，固件也支持明文（按 URL 前缀自动选客户端）。
 *
 *   内网穿透：http://xxxx.cpolar.top
 *     仅当该隧道支持明文 HTTP 时可用；现在统一走 https 就不用它了。 */
#define SEAT_DEFAULT_SERVER "https://zhinengzuo.site"

#endif  // SEAT_SECRETS_H
