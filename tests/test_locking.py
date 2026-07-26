"""核心锁定机制测试"""
import pytest
from utils.locking import SearchSignal, Timer, validate_return, BehaviorTracker


class TestTimer:
    def test_start_stop(self):
        import time
        t = Timer()
        t.time_begin()
        time.sleep(0.1)
        t.time_end()
        elapsed = t.time_boom()
        assert 0.05 < elapsed < 0.5

    def test_running_elapsed(self):
        import time
        t = Timer()
        t.time_begin()
        time.sleep(0.1)
        elapsed = t.time_boom()
        assert 0.05 < elapsed < 0.5
        assert t.is_running


class TestSearchSignal:
    def test_occupied(self):
        s = SearchSignal(sens_occupied=True)
        assert s.search() is True

    def test_unoccupied(self):
        s = SearchSignal(sens_occupied=False)
        assert s.search() is False


class TestValidateReturn:
    def test_immediate_leave(self):
        """立即离开视为虚假回归"""
        s = SearchSignal(sens_occupied=False)
        result = validate_return(s, min_duration=1)
        assert result is False

    def test_valid_return(self):
        """一直有人在视为有效回归"""
        s = SearchSignal(sens_occupied=True)
        result = validate_return(s, min_duration=0.5)
        assert result is True


class TestBehaviorTracker:
    def test_initial_state(self):
        bt = BehaviorTracker(user_id='1')
        assert bt.return_rate == 0.0
        assert bt.absence_rate == 0.0
        assert not bt.is_abnormal()

    def test_record_and_rate(self):
        bt = BehaviorTracker(user_id='1')
        import time
        now = time.perf_counter()
        bt.record_lock_session(
            start=now, end=now + 100,
            detections=10, returns=2,
            unoccupied_time=80
        )
        assert bt.return_rate == 0.2  # 2/10
        assert bt.absence_rate == 0.8  # 80/100
        assert bt.is_abnormal()  # 离座率80%>60% 且 回归率20%<30%

    def test_dynamic_params(self):
        bt = BehaviorTracker(user_id='1', m_default=10, n_default=5)
        import time
        now = time.perf_counter()
        bt.record_lock_session(now, now + 100, 10, 2, 80)
        assert bt.is_abnormal()
        assert bt.get_dynamic_m() > 10  # m 应提高
        assert bt.get_dynamic_n() < 5   # n 应缩短

    def test_report(self):
        bt = BehaviorTracker(user_id='1')
        import time
        now = time.perf_counter()
        bt.record_lock_session(now, now + 60, 5, 3, 10)
        report = bt.get_report()
        assert report['user_id'] == '1'
        assert report['total_lock_count'] == 1
        assert 'return_rate' in report
        assert 'absence_rate' in report
