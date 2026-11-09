# -*- coding: utf-8 -*-
"""按大赛规则改设计文档 HTML。

规则要求（来自上传页）：
  · PDF 格式、按模板规范
  · 详细介绍软件开发的各个周期的设计过程
  · 提供操作步骤及说明
  · 若软件设置了用户名和密码，必须在显著位置注明测试用户名和密码

四处修改：
  ① 目录之后新增「测试账号与访问方式」独立页（显著位置）
  ② 目录里加对应条目
  ③ 「三、功能与原型设计」里加「（3）开发过程与各阶段设计」
  ④ 「六、其他」里补产线烧录与测试规模
"""
import io
import re
import shutil

SRC = r'D:\MAX_xiangmu\docs\设计文档-智座.html'
BAK = r'D:\MAX_xiangmu\docs\设计文档-智座.bak.html'

# ---------------------------------------------------------------------------
# ① 测试账号页
# ---------------------------------------------------------------------------
ACCOUNT_PAGE = '''
<!-- ==================== 测试账号与访问方式（显著位置） ==================== -->
<div class="page">
  <h2 class="first">测试账号与访问方式</h2>

  <p>系统已预置下列测试账号，<strong>无需注册即可直接登录体验全部功能</strong>。评审期间请使用以下账号。</p>

  <table style="width:100%; margin:14pt 0;">
    <tr>
      <th style="width:18%;">角色</th>
      <th style="width:22%;">用户名</th>
      <th style="width:26%;">密码</th>
      <th>可体验的功能</th>
    </tr>
    <tr>
      <td><strong>超级管理员</strong></td>
      <td><strong>admin</strong></td>
      <td><strong>SuperAdmin@123</strong></td>
      <td>全部功能：后台管理、场所与平面图、传感设备绑定、学校与账号、AI 运营中心</td>
    </tr>
    <tr>
      <td>普通用户</td>
      <td colspan="2">在登录页点「注册」，身份选「普通用户」，注册后直接登录</td>
      <td>选座、预约、室内外导航、签到、AI 助手</td>
    </tr>
  </table>

  <p class="noind" style="padding-left:0; margin-top:16pt;"><strong>访问方式</strong></p>
  <table style="width:100%;">
    <tr><th style="width:22%;">方式</th><th>地址 / 说明</th></tr>
    <tr><td>网页端（推荐）</td><td><strong>https://zhinengzuo.site</strong>　任意浏览器直接打开，无需安装</td></tr>
    <tr><td>Android 应用</td><td>同一套页面运行在 Capacitor 壳内，加载同上地址；未安装时用网页端体验即可</td></tr>
    <tr><td>大厅终端</td><td>https://zhinengzuo.site/terminal　常驻大屏页，无需登录</td></tr>
  </table>

  <p class="noind" style="padding-left:0; margin-top:16pt;"><strong>三步看到效果</strong></p>
  <p>① 用上表账号登录 → 进入「座位图」，看实时座位状态；<br>
     ② 点任意空闲座位 → 选座 →「导航至此」，看室内路径；<br>
     ③ 用管理员账号进「硬件 / 传感器调试」，可看到真实 ESP32 设备的上报与绑定。</p>

  <p style="margin-top:16pt; padding:10pt 12pt; background:#f1f6fe; border-left:4px solid #1a73e8;">
    <strong>说明：</strong>AI 智能体与室外导航依赖第三方 Key（大模型、地图服务），
    若评审时未配置或额度用尽，页面会自动降级为规则文案，其余功能不受影响。
  </p>
</div>
'''

# ---------------------------------------------------------------------------
# ③ 开发过程与各阶段设计
# ---------------------------------------------------------------------------
DEVCYCLE = '''
  <h3>（3）开发过程与各阶段设计</h3>

  <p>项目按软件工程的常规周期推进，共经历六个阶段。每个阶段的产出都直接决定了下一阶段的做法，
  下面是每个阶段做了什么、遇到什么、怎么调整的。</p>

  <p class="noind" style="padding-left:2em;"><strong>① 需求分析。</strong>
  起点是团队在图书馆的真实使用体验：读者绕行数圈找不到空位，「占座不来」造成隐性浪费。
  据此归纳出三个核心痛点 —— 查不到（只显示「已预约」，不显示此刻有没有人）、
  找不到（知道在五楼仍要逐个比对）、管不住（占座缺客观依据，管理员只能巡场）。
  同时明确服务边界：只做感知与引导，不改门禁硬件、不涉及支付、不替代排课。
  <strong>阶段调整</strong>：最初设想用摄像头做占用识别，评估后放弃 —— 遮挡、隐私、
  每点位一路流的成本都不可控，改为低成本传感器方案。</p>

  <p class="noind" style="padding-left:2em;"><strong>② 概要设计。</strong>
  确定四层架构：感知层（ESP32 + 传感器）、判定层（Flask 状态机）、
  数据层（MySQL / SQLite + Redis）、应用层（Web / 终端 / 管理端）。
  同时立下四条边界：硬件不做本地判定、状态只在服务端维护、变化实时推送、
  AI 不参与判占。<strong>阶段调整</strong>：边界「状态只在服务端」是后来补上的 ——
  早期把判定写进固件，换传感器型号就要改两处代码，规则开始漂移。</p>

  <p class="noind" style="padding-left:2em;"><strong>③ 详细设计。</strong>
  逐模块定接口与数据结构：座位四态状态机（free / occupied / locked / error）的进出条件、
  m/n/t 防占座参数（可锁定门槛 / 检测周期 / 有效回归时长）、
  路网节点与边的存储格式、A* 的启发函数选型、推荐排序的四维权重。
  <strong>阶段调整</strong>：传感器选型在真机阶段从 PIR 改为超声波 ——
  PIR 只能检测移动，人坐着不动会被判为空闲，这是原理性缺陷，只能换方案。</p>

  <p class="noind" style="padding-left:2em;"><strong>④ 编码实现。</strong>
  后端采用 Flask + SQLAlchemy 组织业务，硬件用 Arduino 框架保证生态成熟；
  前端不加构建链，Vue 3 直接引入，降低部署复杂度。
  <strong>阶段调整</strong>：前端依赖原计划走公共 CDN，实测不可达导致整页空白，
  改为把 Vue / axios / Socket.IO / Font Awesome 全部自托管进仓库。</p>

  <p class="noind" style="padding-left:2em;"><strong>⑤ 测试。</strong>
  后端以 pytest 建立自动化回归，覆盖判占规则、状态机转移、锁定流程、
  A* 寻路与断点搭桥、路网生成、接口契约等，目前 <strong>476 项全部通过</strong>。
  测试遵循一条原则：<em>修掉一个缺陷，就把复现它的用例固化成测试</em> ——
  例如「断点相距 9999 像素不应被桥接」「模拟器关闭后不应继续写库」都是这样沉淀下来的。
  硬件侧以真机联调为主：单台原型机跑通注册、绑定、拉配置、上报、
  状态变化、后台可见的完整链路，并用串口诊断区分密码错误、信号问题与协议不匹配。</p>

  <p class="noind" style="padding-left:2em;"><strong>⑥ 部署。</strong>
  云端采用 gunicorn + nginx，数据库 MySQL，静态资源由 nginx 直发；
  设备侧支持产线批量烧录（把 WiFi 与服务器地址预置进固件，烧完通电即连），
  现场只需安装与上电。<strong>阶段调整</strong>：云端启用 HTTPS 后，
  nginx 对 http 全站 301 跳转，而设备端 HTTP 客户端不带 TLS 也不会跟随跳转，
  导致设备全部失联 —— 固件改为按 URL 前缀自动选择 TLS 或明文后恢复。</p>

  <p>六个阶段中有三次因为实测结果推翻原设计（摄像头改传感器、PIR 改超声波、
  CDN 改自托管）。这三次调整都记在第四章「难点」里，因为它们比顺利实现的部分更能说明问题。</p>
'''

# ---------------------------------------------------------------------------
# ④ 六、其他 补产线烧录 + 测试规模
# ---------------------------------------------------------------------------
EXTRA = '''
  <h3>（6）设备批量部署与测试规模</h3>

  <p><strong>产线批量部署。</strong>逐台开热点配网在一层楼几十个座位的规模上不可行，
  因此固件支持把配置预置进固件：管理后台填写 WiFi 名称、密码与服务器地址后生成
  <code>secrets.h</code>，编进固件即可。所有设备烧同一份二进制，烧完通电自动连接并注册，
  不需要人工逐台配置。预置值在编译期写入，NVS 为空时回落使用；
  现场配网过的设备优先使用 NVS 中的配置，换 WiFi 时现场配一次即可，不必重烧。</p>

  <p><strong>设备自愈。</strong>设备连不上 WiFi 或服务器不可达达到阈值后，
  会自动清空配置并重新开启配网热点等待人工配置，不会因为配置失效而变成无法使用的砖机。</p>

  <p><strong>在线状态判定。</strong>设备每 60 秒会注册一次并拉取配置，
  这些心跳不能等同于「数据在更新」。系统因此把「最后心跳时间」与「最后上报时间」
  分成两个字段独立记录，面板上区分三种状态：在线（数据在更新）、
  无数据（心跳正常但不上报，多为未绑定座位或传感器未接好）、离线（心跳也断了）。
  这样可以避免设备不上报数据却长期显示「在线」的误导。</p>

  <p><strong>测试规模。</strong>后端自动化测试 <strong>476 项全部通过</strong>，
  覆盖判占与状态机、锁定与有效回归、A* 与断点搭桥、路网生成、
  推荐排序、接口契约、前端产物校验等。硬件侧以单台原型机完成全链路真机联调；
  百台级的并发能力尚未做压力测试，这一点在第四章「难点与局限」中如实说明。</p>
'''


def main():
    shutil.copyfile(SRC, BAK)
    s = io.open(SRC, encoding='utf-8').read()
    orig_len = len(s)

    # ① 目录之后插入测试账号页
    anchor = '<!-- ==================== 一、作品概述 ==================== -->'
    assert anchor in s, '找不到「一、作品概述」锚点'
    s = s.replace(anchor, ACCOUNT_PAGE.strip() + '\n\n' + anchor, 1)
    print('  ① 已插入「测试账号与访问方式」页')

    # ② 目录加条目（放在第一条之前）
    toc_anchor = '    <li><span class="t">一、作品概述</span>'
    assert toc_anchor in s, '找不到目录第一条'
    s = s.replace(toc_anchor,
                  '    <li><span class="t">测试账号与访问方式</span><span class="dots"></span>'
                  '<span class="pg" data-h="测试账号与访问方式">4</span></li>\n' + toc_anchor, 1)
    print('  ② 目录已加「测试账号与访问方式」')

    # ③ 三、功能与原型设计 里加开发过程
    #    插在「四、作品实现」那一页之前（即第三章末尾）
    cyc_anchor = '<!-- ==================== 四、作品实现'
    if cyc_anchor not in s:
        cyc_anchor = '<!-- ==================== 四、'
    assert cyc_anchor in s, '找不到第四章锚点'
    idx = s.index(cyc_anchor)
    # 从该位置往前找最近的 </div>，把内容插在它前面
    close = s.rindex('</div>', 0, idx)
    s = s[:close] + DEVCYCLE + '\n' + s[close:]
    print('  ③ 已加「（3）开发过程与各阶段设计」')

    # 目录里也加上
    toc3 = '    <li><span class="t">四、作品实现、难点及特色分析</span>'
    assert toc3 in s
    s = s.replace(toc3,
                  '    <li class="lv2"><span class="t">（3）开发过程与各阶段设计</span>'
                  '<span class="dots"></span><span class="pg" data-h="（3）开发过程与各阶段设计">9</span></li>\n'
                  + toc3, 1)
    print('  ③b 目录已加对应条目')

    # ④ 六、其他 末尾补内容（在「七、致谢」那页之前）
    end_anchor = '<!-- ==================== 七、致谢'
    if end_anchor not in s:
        end_anchor = '<div class="page">\n  <h2>七、致谢</h2>'
    assert end_anchor in s, '找不到致谢锚点'
    idx = s.index(end_anchor)
    close = s.rindex('</div>', 0, idx)
    s = s[:close] + EXTRA + '\n' + s[close:]
    print('  ④ 已补「（6）设备批量部署与测试规模」')

    io.open(SRC, 'w', encoding='utf-8', newline='').write(s)
    print()
    print('  原 %d 字节 → 新 %d 字节（+%.0f KB）'
          % (orig_len, len(s), (len(s) - orig_len) / 1024))
    print('  备份：%s' % BAK)


if __name__ == '__main__':
    main()
