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
        yong_hu_pian_hao = user.preferences or {} if user else {}

        # 查询符合条件的座位
        query = Seat.query.join(Floor).filter(
            Floor.building_id == building_id,
            Seat.is_active == True,
            Seat.status == 'free'  # 只推荐空闲座位
        )

        if floor_id:
            query = query.filter(Seat.floor_id == floor_id)

        kong_xian_zuo_wei = query.all()

        if not kong_xian_zuo_wei:
            return []

        # 计算各维度数据
        de_fen_bang = []
        for seat in kong_xian_zuo_wei:
            de_fen, xiang_qing = self._ji_suan_de_fen(
                seat, user_x, user_y, yong_hu_pian_hao, building_id
            )
            de_fen_bang.append((seat, de_fen, xiang_qing))

        # 按得分降序排列
        de_fen_bang.sort(key=lambda x: x[1], reverse=True)

        jie_guo = []
        for seat, de_fen, xiang_qing in de_fen_bang[:top_k]:
            zuo_wei_zi_dian = seat.to_dict()
            zuo_wei_zi_dian['floor_name'] = seat.floor.name or f'{seat.floor.floor_number}F'
            zuo_wei_zi_dian['building_name'] = seat.floor.building.name if seat.floor.building else None
            zuo_wei_zi_dian['recommend_score'] = round(de_fen, 4)
            zuo_wei_zi_dian['score_details'] = xiang_qing
            jie_guo.append(zuo_wei_zi_dian)

        return jie_guo

    def _ji_suan_de_fen(self, seat: Seat, user_x: float, user_y: float,
                        yong_hu_pian_hao: dict, building_id: int) -> tuple:
        """计算单个座位的加权评分"""
        quan_zhong_ju_li, quan_zhong_re_du, quan_zhong_pian_hao, quan_zhong_yong_ji = self.weights

        # 1. 距离分数 - 归一化距离，越近值越小
        ju_li = self._ji_suan_ju_li(user_x, user_y, seat.x, seat.y)
        # 假设最大距离为 2000px，归一化到 [0, 1]
        ju_li_gui_yi = min(ju_li / 2000.0, 1.0)

        # 2. 区域热度 - 目标区域被占比例
        re_du = self._ji_suan_qu_yu_re_du(seat.floor_id, building_id)

        # 3. 偏好匹配 - 与用户历史偏好匹配度
        pian_hao_du = self._ji_suan_pian_hao_pi_pei(seat, yong_hu_pian_hao)

        # 4. 场所拥挤度 - 目标场所整体空闲占比
        yong_ji_du = self._ji_suan_yong_ji_du(building_id)

        # 加权计算：得分 = 各项权重 × 对应得分后求和
        de_fen = (quan_zhong_ju_li * (1 - ju_li_gui_yi)
                  + quan_zhong_re_du * (1 - re_du)
                  + quan_zhong_pian_hao * pian_hao_du
                  + quan_zhong_yong_ji * yong_ji_du)

        xiang_qing = {
            'dist_raw': round(ju_li, 1),
            'dist_norm': round(ju_li_gui_yi, 4),
            'heat': round(re_du, 4),
            'pref': round(pian_hao_du, 4),
            'crowd': round(yong_ji_du, 4),
        }

        return de_fen, xiang_qing

    def _ji_suan_ju_li(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """欧几里得距离（两点直线距离）"""
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

    def _ji_suan_qu_yu_re_du(self, floor_id: int, building_id: int) -> float:
        """计算区域热度 = 已占用座位数 / 总座位数"""
        zong_shu = Seat.query.filter_by(floor_id=floor_id, is_active=True).count()
        if zong_shu == 0:
            return 0.0
        zhan_yong_shu = Seat.query.filter_by(floor_id=floor_id, is_active=True).filter(
            Seat.status.in_(['occupied', 'locked'])
        ).count()
        return zhan_yong_shu / zong_shu

    def _ji_suan_pian_hao_pi_pei(self, seat: Seat, yong_hu_pian_hao: dict) -> float:
        """计算偏好匹配度 = 命中偏好项数 / 需检查的偏好项数"""
        if not yong_hu_pian_hao:
            return 0.5  # 无偏好时中性值

        ming_zhong_shu = 0        # 命中的偏好项数
        jian_cha_shu = 0          # 需要检查的偏好项总数

        # 靠窗偏好
        if 'window' in yong_hu_pian_hao:
            jian_cha_shu += 1
            if yong_hu_pian_hao['window'] and seat.seat_type == 'window':
                ming_zhong_shu += 1

        # 安静区偏好
        if 'quiet' in yong_hu_pian_hao:
            jian_cha_shu += 1
            if yong_hu_pian_hao['quiet'] and seat.seat_type == 'quiet':
                ming_zhong_shu += 1

        # 电源偏好
        if 'power' in yong_hu_pian_hao:
            jian_cha_shu += 1
            if yong_hu_pian_hao['power'] and seat.seat_type == 'power':
                ming_zhong_shu += 1

        if jian_cha_shu == 0:
            return 0.5

        return ming_zhong_shu / jian_cha_shu

    def _ji_suan_yong_ji_du(self, building_id: int) -> float:
        """计算场所拥挤度 = 空闲座位占比"""
        zong_shu = Seat.query.join(Floor).filter(
            Floor.building_id == building_id,
            Seat.is_active == True
        ).count()

        if zong_shu == 0:
            return 0.5

        kong_xian_shu = Seat.query.join(Floor).filter(
            Floor.building_id == building_id,
            Seat.is_active == True,
            Seat.status == 'free'
        ).count()

        return kong_xian_shu / zong_shu

    def update_weights(self, new_weights: List[float]):
        """动态更新权重（管理员配置）"""
        if len(new_weights) != 4:
            raise ValueError('权重数组必须为4个元素')
        if abs(sum(new_weights) - 1.0) > 0.01:
            raise ValueError('权重之和必须为1')
        self.weights = new_weights
