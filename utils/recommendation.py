"""
AI 加权评分推荐模型
Score = w₁·dist + w₂·(1−heat) + w₃·pref + w₄·crowd

权重默认值: [0.35, 0.25, 0.25, 0.15]
"""
from typing import List, Optional
from models import db
from models.building import Seat, Floor, Building


class RecommendationEngine:
    """AI 座位推荐引擎"""

    def __init__(self, weights: Optional[List[float]] = None):
        self.weights = weights or [0.35, 0.25, 0.25, 0.15]

    def get_recommendations(self, user_id: int, building_id: int,
                            floor_id: Optional[int] = None,
                            user_x: float = 0, user_y: float = 0,
                            top_k: int = 10) -> List[dict]:
        """
        获取推荐座位列表

        Args:
            user_id: 用户ID
            building_id: 建筑物ID
            floor_id: 可选，指定楼层
            user_x: 用户当前位置X
            user_y: 用户当前位置Y
            top_k: 返回前K个推荐

        Returns:
            排序后的推荐座位列表
        """
        from models.user import User

        # 获取用户偏好
        user = User.query.get(user_id)
        user_prefs = user.preferences or {} if user else {}

        # 查询符合条件的座位
        query = Seat.query.join(Floor).filter(
            Floor.building_id == building_id,
            Seat.is_active == True,
            Seat.status == 'free'  # 只推荐空闲座位
        )

        if floor_id:
            query = query.filter(Seat.floor_id == floor_id)

        free_seats = query.all()

        if not free_seats:
            return []

        # 计算各维度数据
        scores = []
        for seat in free_seats:
            score, details = self._calculate_score(
                seat, user_x, user_y, user_prefs, building_id
            )
            scores.append((seat, score, details))

        # 按得分降序排列
        scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for seat, score, details in scores[:top_k]:
            seat_dict = seat.to_dict()
            seat_dict['floor_name'] = seat.floor.name or f'{seat.floor.floor_number}F'
            seat_dict['building_name'] = seat.floor.building.name if seat.floor.building else None
            seat_dict['recommend_score'] = round(score, 4)
            seat_dict['score_details'] = details
            results.append(seat_dict)

        return results

    def _calculate_score(self, seat: Seat, user_x: float, user_y: float,
                         user_prefs: dict, building_id: int) -> tuple:
        """计算单个座位的加权评分"""
        w_dist, w_heat, w_pref, w_crowd = self.weights

        # 1. 距离分数 (dist) - 归一化距离，越近值越小
        dist = self._calc_distance(user_x, user_y, seat.x, seat.y)
        # 假设最大距离为 2000px，归一化到 [0, 1]
        dist_norm = min(dist / 2000.0, 1.0)

        # 2. 区域热度 (heat) - 目标区域被占比例
        heat = self._calc_area_heat(seat.floor_id, building_id)

        # 3. 偏好匹配 (pref) - 与用户历史偏好匹配度
        pref = self._calc_preference_match(seat, user_prefs)

        # 4. 场所拥挤度 (crowd) - 目标场所整体空闲占比
        crowd = self._calc_crowdedness(building_id)

        # 加权计算
        score = w_dist * (1 - dist_norm) + w_heat * (1 - heat) + w_pref * pref + w_crowd * crowd

        details = {
            'dist_raw': round(dist, 1),
            'dist_norm': round(dist_norm, 4),
            'heat': round(heat, 4),
            'pref': round(pref, 4),
            'crowd': round(crowd, 4),
        }

        return score, details

    def _calc_distance(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """欧几里得距离"""
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

    def _calc_area_heat(self, floor_id: int, building_id: int) -> float:
        """计算区域热度 = 已占用座位数 / 总座位数"""
        total = Seat.query.filter_by(floor_id=floor_id, is_active=True).count()
        if total == 0:
            return 0.0
        occupied = Seat.query.filter_by(floor_id=floor_id, is_active=True).filter(
            Seat.status.in_(['occupied', 'locked'])
        ).count()
        return occupied / total

    def _calc_preference_match(self, seat: Seat, user_prefs: dict) -> float:
        """计算偏好匹配度"""
        if not user_prefs:
            return 0.5  # 无偏好时中性值

        match_count = 0
        total_checks = 0

        # 靠窗偏好
        if 'window' in user_prefs:
            total_checks += 1
            if user_prefs['window'] and seat.seat_type == 'window':
                match_count += 1

        # 安静区偏好
        if 'quiet' in user_prefs:
            total_checks += 1
            if user_prefs['quiet'] and seat.seat_type == 'quiet':
                match_count += 1

        # 电源偏好
        if 'power' in user_prefs:
            total_checks += 1
            if user_prefs['power'] and seat.seat_type == 'power':
                match_count += 1

        if total_checks == 0:
            return 0.5

        return match_count / total_checks

    def _calc_crowdedness(self, building_id: int) -> float:
        """计算场所拥挤度 = 空闲座位占比"""
        total = Seat.query.join(Floor).filter(
            Floor.building_id == building_id,
            Seat.is_active == True
        ).count()

        if total == 0:
            return 0.5

        free = Seat.query.join(Floor).filter(
            Floor.building_id == building_id,
            Seat.is_active == True,
            Seat.status == 'free'
        ).count()

        return free / total

    def update_weights(self, new_weights: List[float]):
        """动态更新权重（管理员配置）"""
        if len(new_weights) != 4:
            raise ValueError('权重数组必须为4个元素')
        if abs(sum(new_weights) - 1.0) > 0.01:
            raise ValueError('权重之和必须为1')
        self.weights = new_weights
