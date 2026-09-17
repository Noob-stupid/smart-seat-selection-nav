# -*- coding: utf-8 -*-
"""补一组"前端静态体检"测试。

背景：删除平面图按钮点了没反应 —— 根因是 deleteFloorPlan 里调用了
this.loadFloor()，而该页面根本没有这个方法。调用不存在的方法会抛
TypeError，被 catch 吞掉，表现为"点了没反应"，排查成本很高。

这里用静态分析把这类问题挡在提交前：
  · 每个 .js 里 this.X() 调用的 X，必须在同一文件里定义过
  · Vue 模板里 @click="foo" 引用的方法，必须在对应 JS 里定义过
"""
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..')
JS_DIR = os.path.join(ROOT, 'static', 'js')
TPL_DIR = os.path.join(ROOT, 'templates')

# Vue 内置 / 浏览器内置，不需要在文件里定义
BUILTIN = {
    '$emit', '$refs', '$nextTick', '$set', '$forceUpdate', '$el',
    '$watch', '$mount', '$data', '$options', '$root', '$parent',
    'confirm', 'alert', 'open', 'reload', 'focus', 'blur', 'click',
    'preventDefault', 'stopPropagation', 'push', 'splice', 'filter',
    'forEach', 'map', 'find', 'indexOf', 'includes', 'join', 'split',
    'replace', 'trim', 'toFixed', 'toString', 'getTime', 'toISOString',
    'stringify', 'parse', 'has', 'test', 'exec', 'apply', 'call', 'bind',
    'setAttribute', 'getAttribute', 'querySelector', 'querySelectorAll',
    'removeChild', 'appendChild', 'createElement', 'write', 'close',
}


def _defined(src):
    names = set(re.findall(r'^\s+(?:async\s+)?([a-zA-Z_]\w*)\s*[:(]', src, re.M))
    names |= set(re.findall(r'^\s+([a-zA-Z_]\w*)\s*\([^)]*\)\s*\{', src, re.M))
    names |= set(re.findall(r'\bfunction\s+([a-zA-Z_]\w*)\s*\(', src))
    names |= set(re.findall(r'\bvar\s+([a-zA-Z_]\w*)', src))
    names |= set(re.findall(r'\b(?:const|let)\s+([a-zA-Z_]\w*)', src))
    return names


def _js_files():
    out = []
    for root, d, fs in os.walk(JS_DIR):
        for f in fs:
            if f.endswith('.js') and 'mock-api' not in f:
                out.append(os.path.join(root, f))
    return out


# 模板里引用了、但对应 JS 不打算实现的处理器（需逐个说明为什么安全）
# ------------------------------------------------------------------
# reservation.html 的「选座预约」整卡是 <div class="card" v-if="building"> 包着的，
# 而原版 reservation.js（34 行）只实现「我的预约」列表，从不设置 building ——
# v-if 恒为假，整卡连同 doReserve 按钮都不会被渲染，所以不会出现"点了没反应"。
# 选座入口在「座位图」页，不在这里（用户 2026-09-17 明确说明）。
INTENTIONALLY_ABSENT = {
    ('reservation.html', 'doReserve'),
}


class TestJsSanity:
    def test_no_calls_to_undefined_methods(self):
        """this.X() 调用的方法必须在同文件定义过。

        这条就是删除平面图按钮失效的根因（this.loadFloor 不存在）。
        """
        problems = []
        for path in _js_files():
            src = io.open(path, encoding='utf-8').read()
            called = set(re.findall(r'this\.([a-zA-Z_]\w*)\s*\(', src))
            if not called:
                continue
            miss = sorted(x for x in (called - _defined(src)) if x not in BUILTIN)
            if miss:
                problems.append('%s -> %s'
                                % (os.path.relpath(path, ROOT), ', '.join(miss)))
        assert not problems, (
            '以下文件调用了本文件未定义的方法（运行时会 TypeError，'
            '常被 catch 吞掉表现为"点了没反应"）：\n  ' + '\n  '.join(problems))

    def test_handler_methods_defined_in_js(self):
        """模板里 @click="foo" 引用的方法，必须在同目录的 JS 里定义。

        只检查"看起来是自定义方法名"的（排除 $refs.foo、内置函数等）。
        """
        problems = []
        for root, d, fs in os.walk(TPL_DIR):
            for f in fs:
                if not f.endswith('.html'):
                    continue
                tpl = os.path.join(root, f)
                html = io.open(tpl, encoding='utf-8').read()
                # 只有属性值「恰好是一个标识符/一次调用」才算方法引用；
                # @click="x = null" 这类行内表达式不算（那是数据属性赋值）
                handlers = set(re.findall(
                    r'@(?:click|change|submit)(?:\.\w+)?="\s*([a-zA-Z_]\w*)\s*(?:\(\s*\))?\s*"',
                    html))
                if not handlers:
                    continue
                # 找同目录/同名的 js
                base = f[:-5]
                cands = []
                admin_dir = os.path.join(JS_DIR, 'admin')
                for cand in (os.path.join(JS_DIR, base + '.js'),
                             os.path.join(admin_dir, base + '.js')):
                    if os.path.exists(cand):
                        cands.append(cand)
                if not cands:
                    continue
                defined = set()
                for c in cands:
                    defined |= _defined(io.open(c, encoding='utf-8').read())
                miss = sorted(h for h in handlers
                              if h not in defined and h not in BUILTIN
                              and (f, h) not in INTENTIONALLY_ABSENT)
                if miss:
                    problems.append('%s -> %s'
                                    % (os.path.relpath(tpl, ROOT), ', '.join(miss)))
        assert not problems, ('模板引用了 JS 里没定义的方法：\n  ' + '\n  '.join(problems))

    def test_reservation_seat_card_is_guarded(self):
        """reservation.html 的选座卡必须始终被 v-if 挡住。

        模板里有 doReserve 等引用，但原版 reservation.js 不实现它们。
        只要整卡仍被 v-if="building" 包着（原版从不设置 building），
        就不会渲染出任何"点了没反应"的按钮。
        哪天有人去掉了这个 v-if，这条会失败，提醒把它一起处理掉。
        """
        html = io.open(os.path.join(TPL_DIR, 'reservation.html'), encoding='utf-8').read()
        assert 'v-if="building"' in html, \
            '选座卡的 v-if 守卫没了，doReserve 等未实现的方法会暴露成死按钮'

    def test_delete_plan_calls_existing_method(self):
        """回归：deleteFloorPlan 必须调用本页面真实存在的重载方法。

        它曾经调用不存在的 this.loadFloor()，导致删除成功但界面不刷新。
        """
        p = os.path.join(JS_DIR, 'admin', 'floor_plan.js')
        src = io.open(p, encoding='utf-8').read()
        assert 'deleteFloorPlan' in src
        assert 'this.loadFloor(' not in src, 'loadFloor 不存在，应调用 onFloorChange'
        assert 'this.onFloorChange(' in src
