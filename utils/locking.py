# （核心3★核心创新）动态锁定防抢座机制
# 典型用户流转时序（关键——澄清“人在座位上为何还要锁定”的歧义）：

# ① 用户入座 → 传感器检测到占用 → 前端显示红色（占用）
# ② 座位被连续占用满 m 分钟后 → 前端“锁定”按钮变为可用
# ③ 用户需暂离（如接水、去洗手间）→ 点击“锁定”按钮 → 座位变为黄色（锁定）
# ④ 锁定后系统每 n 分钟自动检测一次座椅状态：
#    ├ 若检测到无人 → 自动解除锁定，座位恢复空闲（绿色）
#    └ 若检测到有人 → 保持锁定状态，重新计时 n 分钟
# ⑤ 锁定期间用户返回 → 正常入座 → 座位状态维持黄色（锁定标记），用户手动“结束锁定”或等待超时自动切换为占用（红色）
import time
from typing import Optional
from datetime import timedelta,datetime
import json

class Timer:
  def __init__(self):
    self.start_time: Optional[float]=None
    self.end_time: Optional[float]=None
    self.is_running=False
  def time_begin(self):
    self.start_time=time.perf_counter()
    self.is_running=True
    return self
  def time_end(self):
    self.end_time=time.perf_counter()
    self.is_running=False
    return self
  def time_boom(self):
    if self.start_time and self.end_time:
      return self.end_time -self.start_time
    elif self.is_running:
      return time.perf_counter()-self.start_time
class SearchSignal:
  """传感器检测类。sens_occupied=True 表示有人，None/False 表示无人。生产环境需对接真实传感器"""
  def __init__(self, sens_occupied: bool = True):
    self.sens_occupied = sens_occupied
  def search(self):
    return self.sens_occupied  # True=有人, None=False=无人

# ============================================================
# 功能一：最短有效回归时长机制
# ============================================================
def validate_return(signal: SearchSignal, min_duration: float = 30.0) -> bool:#验证返回值
    """
    检测用户回归是否有效（连续占用时间 >= min_duration 秒）
    防止用户每 n-1 分钟回来"晃一下"规避检测
    """
    zhan_yong_kai_shi = time.perf_counter()   # 记录本次回归检测的开始时刻
    while time.perf_counter() - zhan_yong_kai_shi < min_duration:
        time.sleep(1)                          # 每秒检测一次
        if not signal.search():
            return False                       # 中途人又走了，视为无效回归
    return True                                # 连续有人超过最短时长，视为有效回归


# ============================================================
# 功能二：行为感知演进机制
# ============================================================
class BehaviorTracker:
    """用户行为感知追踪器，用于动态调整锁定参数"""

    def __init__(self, user_id: str, m_default: float = 5, n_default: float = 10):
        """
        初始化行为追踪器。

        参数:
            user_id: 用户唯一标识，用于区分不同用户。
            m_default: 参数 m 的默认基准值（例如“锁定前的连续占用分钟数”）。
            n_default: 参数 n 的默认基准值（例如“锁定后自动检测间隔分钟数”）。
        """
        self.user_id = user_id                     # 用户标识
        self.m_base = m_default                    # m 参数基准值（正常状态下使用）
        self.n_base = n_default                    # n 参数基准值（正常状态下使用）

        # ========== 累计统计变量 ==========
        self.total_lock_count = 0                  # 历史锁屏总次数（会话数）
        self.total_detections = 0                  # 历史总检测次数（所有 record_detection 调用次数）
        self.valid_return_count = 0                # 历史有效回归总次数（回归验证通过次数）
        self.cumulative_unoccupied_time = 0.0      # 锁定期间累计无人时长（秒）
        self.cumulative_locking_time = 0.0         # 锁定期间累计总时长（秒）
        self.lock_history = []                     # list[dict] 每次锁定会话的详细记录（最近20条）
        # 内部辅助：用于自动计算两次检测之间的实际时间差
        self._shang_ci_jian_ce_shi_jian = None     # 上一次调用 record_detection 的时间戳

    def record_detection(self, occupied: bool, elapsed_sec: Optional[float] = None):
        """
        记录一次检测结果。

        参数:
            occupied: 是否有人
            elapsed_sec: 距上次检测的秒数。传 None 则由内部自动计算。
        """
        now = time.perf_counter()
        if elapsed_sec is None:
            if self._shang_ci_jian_ce_shi_jian is not None:
                elapsed_sec = now - self._shang_ci_jian_ce_shi_jian
            else:
                elapsed_sec = 0.0
        self._shang_ci_jian_ce_shi_jian = now

        self.total_detections += 1
        if not occupied:
            self.cumulative_unoccupied_time += elapsed_sec

    def record_return(self, valid: bool):
        """记录一次回归结果"""
        if valid:
            self.valid_return_count += 1

    def record_lock_session(self, start: float, end: float, detections: int,
                            returns: int, unoccupied_time: float):
        """记录一次完整的锁定会话"""
        self.total_lock_count += 1
        self.total_detections += detections
        self.valid_return_count += returns
        self.cumulative_unoccupied_time += unoccupied_time
        chi_xu_shi_jian = end - start            # 本次锁定会话持续时长（秒）
        self.cumulative_locking_time += chi_xu_shi_jian
        self.lock_history.append({
            "start": datetime.fromtimestamp(start).isoformat(),
            "end": datetime.fromtimestamp(end).isoformat(),
            "duration_sec": round(chi_xu_shi_jian, 1),
            "detections": detections,
            "valid_returns": returns,
            "unoccupied_sec": round(unoccupied_time, 1)
        })

    @property
    def return_rate(self) -> float:
        """回归率 = 有效回归次数 / 锁定期间检测次数"""
        # 分母是锁定期间的检测次数，不是全部检测
        if self.total_detections == 0:
            return 0.0
        return self.valid_return_count / self.total_detections

    @property
    def absence_rate(self) -> float:
        """离座率 = 锁定期间无人累计时长 / 锁定总时长"""
        # 反映在锁定状态下，实际无人的时间占比
        if self.cumulative_locking_time == 0:
            return 0.0
        return self.cumulative_unoccupied_time / self.cumulative_locking_time

    def is_abnormal(self) -> bool:
        """
        判断是否存在异常锁定行为
        异常判定规则：离座率 > 0.6 且 回归率 < 0.3
        """
        return self.absence_rate > 0.6 and self.return_rate < 0.3

    def get_dynamic_m(self) -> float:
        """根据行为数据动态计算 m 值（最高提升至 3 倍）"""
        if self.is_abnormal():
            return min(self.m_base * 3, self.m_base * (1 + self.absence_rate * 2))
        return self.m_base

    def get_dynamic_n(self) -> float:
        """根据行为数据动态计算 n 值（最低缩至 1/3）"""
        if self.is_abnormal():
            return max(self.n_base / 3, self.n_base * (1 - self.absence_rate * 0.5))
        return self.n_base

    def get_report(self) -> dict:
        """生成行为分析报告"""
        return {
            "user_id": self.user_id,
            "total_lock_count": self.total_lock_count,
            "total_detections": self.total_detections,
            "valid_return_count": self.valid_return_count,
            "return_rate": round(self.return_rate, 4),
            "absence_rate": round(self.absence_rate, 4),
            "is_abnormal": self.is_abnormal(),
            "dynamic_m": round(self.get_dynamic_m(), 1),
            "dynamic_n": round(self.get_dynamic_n(), 1),
            "lock_history": self.lock_history[-20:]
        }


#可进一步引入行为感知：记录用户历史锁定频次与平均离座时长，对高频锁定却长期不归的用户动态提高m门槛或缩短n，防止恶意锁座。(额外添加手动锁定)
def locking(m,n):
  locked=0
  now_time=0.0
  timer=Timer()
  timer.time_begin()
  Signal=SearchSignal()
  while timer.time_boom() < m * 60:
        time.sleep(1)
        if not Signal.search():
            # 还没到 m 分钟人走了，不锁定
            return {
                "locked": 0,
                "now_time": timer.time_boom(),
                "msg": "占用不足 m 分钟，不锁定"
            }
  if Signal.search():
    locked=1
    last_check = timer.time_boom()
    # n_minutes=timedelta(minutes=n)
    while(locked==1):
      time.sleep(1)#1s检测一次，防止一直不停检测导致CPU占比飙升产生卡顿
      if timer.time_boom()-last_check>=n*60:
        #进行检测，若n分钟后检测无人，自动解除锁定，座位恢复空闲（每n分钟检测一次）
        last_check = timer.time_boom()  
        if not Signal.search():
          locked=0
    timer.time_end()
    now_time= timer.time_boom()
  if locked==0:
    return {
      "locked":0,
      "now_time":now_time,
      "msg":"锁定"
    }
  else:
    return {
      "locked":1,
      "now_time":now_time,
      "msg":"解锁"
    }