"""
传感器模拟器 - 用于开发/演示环境模拟红外传感器数据
实际部署时由 ESP32/STM32 硬件上报数据替代此模块
"""
import random
import time
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
        self.callback: Optional[Callable] = None
        self.seat_states = {}  # 座位状态表 {座位id: {'ir_front': 0/1, 'ir_back': 0/1}}

        # 初始化座位状态（全为空闲）
        for i in self.seat_ids:
            self.seat_states[i] = {'ir_front': 0, 'ir_back': 0}

    def set_callback(self, callback: Callable[[int, int, int], None]):
        """
        设置数据回调函数
        回调参数: (seat_id, ir_front, ir_back)
        """
        self.callback = callback

    def simulate_occupancy(self, seat_id: int, occupied: bool = True):
        """手动模拟座位占用/释放"""
        if seat_id in self.seat_states:
            self.seat_states[seat_id]['ir_front'] = 1 if occupied else 0
            self.seat_states[seat_id]['ir_back'] = 1 if occupied else 0
            if self.callback:
                self.callback(seat_id, self.seat_states[seat_id]['ir_front'],
                              self.seat_states[seat_id]['ir_back'])
            return True
        return False

    def start(self):
        """启动模拟器"""
        if self.running:
            return False
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f'[传感器模拟器] 已启动，扫描间隔 {self.scan_interval}s，共 {self.seat_count} 个座位')
        return True

    def stop(self):
        """停止模拟器"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print('[传感器模拟器] 已停止')

    def _run_loop(self):
        """模拟扫描循环"""
        while self.running:
            # 随机变换一些座位状态（模拟真实场景）
            self._random_flip()

            # 上报所有座位状态
            for seat_id, state in self.seat_states.items():
                if self.callback:
                    self.callback(seat_id, state['ir_front'], state['ir_back'])

            time.sleep(self.scan_interval)

    def _random_flip(self):
        """随机改变少量座位状态（模拟真实使用）"""
        # 20% 概率有座位变化
        if random.random() < 0.2:
            change_count = random.randint(1, max(1, self.seat_count // 10))
            for _ in range(change_count):
                seat_id = random.randint(1, self.seat_count)
                # 随机翻转
                self.seat_states[seat_id]['ir_front'] = random.randint(0, 1)
                self.seat_states[seat_id]['ir_back'] = random.randint(0, 1)
