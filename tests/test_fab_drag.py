# -*- coding: utf-8 -*-
"""悬浮按钮长按拖动（AI 助手气泡 / 扫码占座按钮）。

需求：这两个按钮长按可以拖动换位置，**只改手机端**。
做法：新增 static/js/drag-fab.js，打包进 native-bundle.js；
     CSS 全部挂在 body.app-mode 下 —— 网页版一点不受影响。
"""
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..')


def read(rel):
    return io.open(os.path.join(ROOT, rel.replace('/', os.sep)), encoding='utf-8').read()


JS = 'static/js/drag-fab.js'
CSS = 'static/css/mobile-app.css'
BUNDLE = 'static/js/native-bundle.js'


# ---------------------------------------------------------------------------
# 1. 只在 App 内生效
# ---------------------------------------------------------------------------

def test_drag_fab_only_runs_in_app():
    src = read(JS)
    assert re.search(r'if \(!window\.Native \|\| !window\.Native\.available\) return;', src), \
        'drag-fab.js 必须在非 App 环境直接返回，网页版不能受影响'


def test_drag_css_scoped_to_app_mode():
    css = read(CSS)
    body = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    seg = body[body.index('fab-dragging') - 200:]
    # 拖动相关规则必须都带 body.app-mode 前缀
    for m in re.finditer(r'([^{}]+)\{', body):
        sel = m.group(1).strip()
        if sel.startswith('@') or not sel:
            continue
        for one in sel.split(','):
            one = one.strip()
            if not one or re.match(r'^(from|to|\d+(\.\d+)?%)$', one):
                continue
            assert one.startswith('body.app-mode') or one.startswith('.app-'), \
                '选择器未限定在 App 模式内，会污染网页版: %s' % one


# ---------------------------------------------------------------------------
# 2. 两个目标按钮
# ---------------------------------------------------------------------------

def test_drag_targets_are_the_two_buttons():
    src = read(JS)
    assert "'.aias-root'" in src, '缺少 AI 助手气泡'
    assert "'#feat-scan-fab'" in src, '缺少扫码占座按钮'


def test_ai_bubble_class_name_matches_ai_assistant():
    """选择器必须跟 ai-assistant.js 里创建的真实类名一致，否则永远找不到。"""
    ai = read('static/js/ai-assistant.js')
    assert 'aias-root' in ai, 'ai-assistant.js 里没有 aias-root'
    assert "'.aias-root'" in read(JS)


def test_scan_fab_id_matches_native_features():
    nf = read('static/js/native-features.js')
    assert "fab.id = 'feat-scan-fab'" in nf, 'native-features.js 里没有 feat-scan-fab'
    assert "'#feat-scan-fab'" in read(JS)


# ---------------------------------------------------------------------------
# 3. 长按 + 拖动 + 记忆
# ---------------------------------------------------------------------------

def test_long_press_threshold_and_jitter_tolerance():
    src = read(JS)
    assert 'HOLD_MS' in src and 'setTimeout' in src
    m = re.search(r'HOLD_MS\s*=\s*(\d+)', src)
    assert m and 250 <= int(m.group(1)) <= 800, '长按阈值应在 0.25~0.8 秒之间'
    assert 'MOVE_TOL' in src, '要有抖动容差，否则手指抖一下就取消长按'


def test_position_persisted_and_restored():
    src = read(JS)
    assert 'localStorage' in src
    assert 'fab_pos_v1' in src
    assert 'applySaved' in src, '缺少「打开时沿用上次位置」'
    assert 'save(' in src


def test_drag_beats_stylesheet_important():
    """样式表里有 bottom:...!important（给底部 Tab 让位），
    内联样式必须也带 important 才盖得住，否则拖了不动。"""
    src = read(JS)
    assert "setProperty('left', left + 'px', 'important')" in src
    assert "setProperty('bottom', 'auto', 'important')" in src


def test_drag_is_clamped_inside_viewport():
    src = read(JS)
    seg = src.split('function moveTo')[1].split('function applySaved')[0]
    assert 'window.innerWidth' in seg and 'window.innerHeight' in seg
    assert 'Math.max' in seg and 'Math.min' in seg


def test_click_swallowed_after_drag():
    """拖完那一下不能顺带触发扫码/打开 AI。"""
    src = read(JS)
    assert 'swallow' in src
    seg = src.split("el.addEventListener('click'")[1]
    assert 'stopPropagation' in seg and 'preventDefault' in seg
    assert "true)" in seg, '要在捕获阶段拦截，先于按钮自己的处理'


def test_short_press_still_works():
    """短按行为不变：没进入拖动模式就不拦 click。"""
    src = read(JS)
    assert 'dragging' in src
    seg = src.split("el.addEventListener('click'")[1].split('}, true);')[0]
    assert 'if (st.swallow)' in seg, '只吞掉拖动之后的那一次 click'


# ---------------------------------------------------------------------------
# 4. 复位入口 + 打包
# ---------------------------------------------------------------------------

def test_reset_button_in_settings_panel():
    src = read(JS)
    assert 'data-fab-reset' in src, '设置面板里应有「复位悬浮按钮位置」'
    assert '复位悬浮按钮位置' in src
    assert 'resetAll' in src


def test_drag_module_is_in_the_bundle():
    b = read(BUNDLE)
    assert 'FabDrag' in b, 'drag-fab.js 没打进 native-bundle.js'
    assert 'fab_pos_v1' in b
    assert '复位悬浮按钮位置' in b


# ---------------------------------------------------------------------------
# 5. 真实指针事件行为（用 Playwright 风格的合成测试在浏览器里跑，
#    这里退化为对关键逻辑的静态断言，浏览器实测见对话记录）
# ---------------------------------------------------------------------------

def test_long_press_uses_pointer_events():
    """用 pointer 事件而不是 touch/mouse —— Capacitor WebView 里 pointer 最稳。"""
    src = read(JS)
    for evt in ('pointerdown', 'pointermove', 'pointerup', 'pointercancel'):
        assert "'%s'" % evt in src, '缺少 %s 处理' % evt
    assert 'setPointerCapture' in src, '拖动时要捕获指针，手指滑出按钮也能继续拖'
