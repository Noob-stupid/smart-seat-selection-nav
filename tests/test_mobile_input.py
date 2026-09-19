# -*- coding: utf-8 -*-
"""Capacitor captureInput 配置与登录输入框属性。

背景（真 bug）：
  手机 App 里登录时，切到密码框会把账号重写/清空、输进去的字有时不生效。
  根因是 capacitor.config.json 里 captureInput: true ——
  Capacitor 会用一个桩 InputConnection 取代 WebView 正常的输入通道：

      // CapacitorWebView.java:38
      if (config.isInputCaptured()) return new BaseInputConnection(this, false);

  然后用 dispatchKeyEvent 里的一段 JS 硬写 DOM 来补输入：

      evaluateJavascript("document.activeElement.value = document.activeElement.value + '...'");

  于是：
    · 直接改 .value 不触发 input 事件 -> Vue 的 v-model 收不到
    · 焦点已经移到密码框时，JS 还照 document.activeElement 往上写
      -> 表现为「切到密码框，账号被重写/清空」
    · 桩 InputConnection 不参与 Android autofill 协议 -> 自动填充乱跳

  Capacitor 默认值是 false（CapConfig.java:47），是我们误开的。
"""
import io
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), '..')


def read(rel):
    return io.open(os.path.join(ROOT, rel.replace('/', os.sep)), encoding='utf-8').read()


def test_capture_input_is_off():
    """captureInput 必须是 false —— 开了会破坏 WebView 的输入通道。"""
    cfg = json.loads(read('mobile/capacitor.config.json'))
    assert cfg['android'].get('captureInput') is False, \
        'captureInput: true 会让 Capacitor 换掉正常的 InputConnection，' \
        '导致切字段时文字被写错/清空，且 v-model 收不到输入'


def test_assets_config_matches_source():
    """打包进 APK 的那份配置必须和源文件一致，否则改了也不生效。"""
    src = json.loads(read('mobile/capacitor.config.json'))
    dst = json.loads(read('mobile/android/app/src/main/assets/capacitor.config.json'))
    assert src == dst, 'assets 里的 capacitor.config.json 没同步'


def test_edge_to_edge_still_on():
    """别把之前的修复带回去。"""
    cfg = json.loads(read('mobile/capacitor.config.json'))
    assert cfg['android'].get('adjustMarginsForEdgeToEdge') == 'auto'


def test_login_form_has_proper_autofill_attributes():
    """登录/注册的输入框要有 name + autocomplete，否则浏览器只能靠猜。

    没有这些属性时，Android autofill 会把登录表单当成「注册表单」或认错字段，
    焦点一移动就可能把已填的内容冲掉。
    """
    html = read('templates/login.html')

    # 登录表单
    assert 'name="username"' in html and 'autocomplete="username"' in html
    assert 'name="password"' in html and 'autocomplete="current-password"' in html

    # 注册表单：新密码要用 new-password，避免浏览器去填已存的旧密码
    assert 'autocomplete="new-password"' in html

    # 账号/密码框都要关掉首字母大写与自动纠错（口令区分大小写）
    seg = html[html.index("tab==='login'"):html.index('</form>')]
    for evt in ('autocapitalize="none"', 'autocorrect="off"', 'spellcheck="false"'):
        assert seg.count(evt) == 2, '登录表单的账号和密码框都要有 %s' % evt


def test_capacitor_default_is_false():
    """确认 Capacitor 自己的默认值就是 false —— 我们之前是偏离了默认。"""
    p = os.path.join(ROOT, 'mobile', 'node_modules', '@capacitor', 'android',
                     'capacitor', 'src', 'main', 'java', 'com', 'getcapacitor', 'CapConfig.java')
    if not os.path.exists(p):
        import pytest
        pytest.skip('node_modules 未安装，跳过源码核对')
    src = io.open(p, encoding='utf-8').read()
    assert re.search(r'captureInput\s*=\s*false', src), \
        'Capacitor 默认 captureInput=false，我们不该改成 true'
