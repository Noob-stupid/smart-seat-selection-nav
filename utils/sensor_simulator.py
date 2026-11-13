"""
传感器模拟器 - 用于开发/演示环境模拟红外传感器数据
实际部署时由 ESP32/STM32 硬件上报数据替代此模块
"""
import random
import threading
from datetime import datetime
from typing import Callable, Optional


class SensorSimulator:
    """红外传感器模拟器"""

    def __init__(self, seat_ids=None, seat_count: int = 50, scan_interval: int = 30):
        if seat_ids is None:
            seat_ids = list(range(1, seat_count + 1))
        self.seat_ids = list(seat_ids)
        self.seat_count = len(self.seat_ids)
        self.scan_interval = scan_interval
        self.running = False
        self.thread: Optional[threading.Thread] = None
        # 用 Event 代替裸 sleep：stop() 能立刻把正在等待的线程唤醒，
        # 否则线程卡在 time.sleep(30) 里，join(timeout=5) 超时返回，
        # 调用方以为停了、其实线程还活着，还会继续写数据库。
        self._stop_evt = threading.Event()
        self.callback: Optional[Callable] = None
        self.seat_states = {}  # 座位状态表 {座位id: {'ir_front': 0/1, 'ir_back': 0/1}}

        # 初始化座位状态（全为空闲）
        #
        # manual 标记这一路状态是不是「用户手动模拟」出来的。手动设置过的座位
        # 不再被随机翻转覆盖 —— 否则点「模拟占用」之后，下一轮扫描就把它随机
        # 改回去，看起来就像"模拟上报不生效"。
        for i in self.seat_ids:
            self.seat_states[i] = {'ir_front': 0, 'ir_back': 0, 'manual': False}

    def set_callback(self, callback: Callable[..., None]):
        """
        设置数据回调函数
        回调参数: (seat_id, ir_front, ir_back, simulated=True)

        simulated 是关键字参数，由模拟器自己补上，回调不用传。它只表示
        「这条读数不是真机来的」—— 在线状态只能由真实硬件决定，否则一开
        模拟器整层楼的座位全变「在线」，把「这里其实没装设备」盖掉。
        """
        self.callback = callback

    def _emit(self, seat_id: int, ir_front: int, ir_back: int):
        """把一次读数交给回调，并标明来源是模拟。

        统一走这里（而不是各处直接 self.callback(...)），是为了保证
        每个模拟读数都带上 simulated=True —— 漏一处就会让那一路数据
        被当成真机上报，在线判定又恢复成「开模拟器全都上线」。
        """
        if not self.callback:
            return
        self.callback(seat_id, ir_front, ir_back, simulated=True)

    def simulate_occupancy(self, seat_id: int, occupied: bool = True):
        """手动模拟座位占用/释放。

        两路一起设：判占规则是「两路同时命中才算占用」，只设一路的话
        系统会把它当成"有人路过"，座位仍然是空闲 —— 这就是之前手动模拟
        看起来没反应的原因。

        同时打上 manual 标记，防止下一轮随机扫描把它覆盖掉。
        """
        if seat_id in self.seat_states:
            v = 1 if occupied else 0
            self.seat_states[seat_id]['ir_front'] = v
            self.seat_states[seat_id]['ir_back'] = v
            self.seat_states[seat_id]['manual'] = True
            if occupied:
                self._emit(seat_id, 1, 1)
            else:
                # 释放要连报两次：后端判空闲的条件是「连续 2 次无人」
                # （真机也是这样，防止有人起身一晃就释放座位）。
                # 这里只报一次的话，点了「模拟空闲」座位还是红的，
                # 得等下一轮 30 秒扫描才变绿，看起来就像点了没反应。
                self._emit(seat_id, 0, 0)
                self._emit(seat_id, 0, 0)
            return True
        return False

    def clear_manual(self, seat_id: int = None):
        """清除手动标记，让座位重新参与随机模拟。传 None 清除全部。"""
        targets = ([seat_id] if seat_id is not None
                   else list(self.seat_states.keys()))
        for sid in targets:
            if sid in self.seat_states:
                self.seat_states[sid]['manual'] = False

    def start(self):
        """启动模拟器"""
        if self.running:
            return False
        self._stop_evt.clear()
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f'[传感器模拟器] 已启动，扫描间隔 {self.scan_interval}s，共 {self.seat_count} 个座位')
        return True

    def stop(self):
        """停止模拟器。

        除了置 running=False，还要 set 停止事件 —— 线程正卡在等待里时
        会被立刻唤醒，不会再多跑一轮写库。
        """
        self.running = False
        self._stop_evt.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        print('[传感器模拟器] 已停止')

    def _run_loop(self):
        """模拟扫描循环"""
        while self.running and not self._stop_evt.is_set():
            # 随机变换一些座位状态（模拟真实场景）
            self._random_flip()

            # 上报所有座位状态
            for seat_id, state in self.seat_states.items():
                # 每一轮里也要检查，避免停止后还把这一轮刷完（60 个座位 × commit 要一两秒）
                if self._stop_evt.is_set():
                    return
                self._emit(seat_id, state['ir_front'], state['ir_back'])

            # 可中断的等待：stop() 一调用就醒，不用等满 30 秒
            if self._stop_evt.wait(self.scan_interval):
                return

    def _random_flip(self):
        """随机改变少量座位状态（模拟真实使用）。

        两个要点：
        · 两路必须同时翻转。判占规则是「两路同时命中才算占用」，
          分别 random 的话大概率出现一路 1 一路 0，系统会当成
          「有人路过」，座位永远变不红。
        · 跳过手动模拟过的座位（manual=True）。用户点了「模拟占用」，
          就不该被下一轮随机改回去。
        """
        if not self.seat_states:
            return
        candidates = [sid for sid, st in self.seat_states.items()
                      if not st.get('manual')]
        if not candidates:
            return
        # 20% 概率有座位变化
        if random.random() < 0.2:
            change_count = random.randint(1, max(1, len(candidates) // 10))
            for seat_id in random.sample(candidates,
                                         k=min(change_count, len(candidates))):
                v = random.randint(0, 1)      # 两路取同一个值
                self.seat_states[seat_id]['ir_front'] = v
                self.seat_states[seat_id]['ir_back'] = v
