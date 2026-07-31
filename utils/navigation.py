"""
轻量 AI + 人工微调半自动室内导航系统

路网生成：语义分割 → 形态学处理 → 骨架提取 → 人工微调
路径规划：A* 算法
用户定位：扫码定位 / 手动选点 + 路网吸附
跨层导航：楼梯口/电梯口节点拼接
"""
import json
import os
from typing import List, Tuple, Optional
import heapq


class RoadNetwork:
    """路网数据结构"""

    def __init__(self, nodes: dict = None, edges: list = None):
        self.nodes = nodes or {}  # {node_id: {"x": float, "y": float, "type": str}}
        self.edges = edges or []  # [{ "from": node_id, "to": node_id }]

    def to_dict(self) -> dict:
        return {
            'nodes': self.nodes,
            'edges': self.edges,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'RoadNetwork':
        return cls(nodes=data.get('nodes', {}), edges=data.get('edges', []))

    def save(self, filepath: str):
        """保存路网数据到JSON文件"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: str) -> Optional['RoadNetwork']:
        """从JSON文件加载路网数据"""
        if not os.path.exists(filepath):
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)


class PathFinder:
    """路径规划器（A*算法）"""

    def __init__(self, network: RoadNetwork):
        self.network = network
        self._jian_lian_jie_biao()   # 构建邻接表

    def _jian_lian_jie_biao(self):
        """构建邻接表（记录每个节点与哪些节点直接相连）"""
        self.lian_jie_biao = {}                    # 邻接表：{节点id: [相连节点id列表]}
        for node_id in self.network.nodes:
            self.lian_jie_biao[node_id] = []

        for edge in self.network.edges:
            frm = edge['from']
            to = edge['to']
            if frm in self.lian_jie_biao and to in self.lian_jie_biao:
                self.lian_jie_biao[frm].append(to)
                self.lian_jie_biao[to].append(frm)

    def heuristic(self, node_a: str, node_b: str) -> float:
        """欧几里得距离启发函数"""
        pos_a = self.network.nodes.get(node_a, {})
        pos_b = self.network.nodes.get(node_b, {})
        dx = pos_a.get('x', 0) - pos_b.get('x', 0)
        dy = pos_a.get('y', 0) - pos_b.get('y', 0)
        return (dx ** 2 + dy ** 2) ** 0.5

    def find_path(self, start_node: str, end_node: str) -> Tuple[List[str], float]:
        """
        A* 寻路

        Returns:
            (路径节点列表, 总距离)
        """
        if start_node not in self.network.nodes or end_node not in self.network.nodes:
            return [], 0.0

        dai_kao_cha = [(0, start_node)]                        # 待考察节点堆（按估算总代价排序）
        qian_qu = {}                                           # 前驱表：记录每个节点是从哪个节点走来的
        shi_ji_dai_jia = {start_node: 0.0}                     # 起点到该节点的实际已走代价
        gu_suan_dai_jia = {start_node: self.heuristic(start_node, end_node)}  # 起点经该节点到终点的估算总代价

        while dai_kao_cha:
            _, dang_qian = heapq.heappop(dai_kao_cha)          # 取出估算代价最小的节点

            if dang_qian == end_node:
                # 重建路径
                lu_jing = []
                while dang_qian in qian_qu:
                    lu_jing.append(dang_qian)
                    dang_qian = qian_qu[dang_qian]
                lu_jing.append(start_node)
                lu_jing.reverse()
                return lu_jing, shi_ji_dai_jia[end_node]

            for lin_jie in self.lian_jie_biao.get(dang_qian, []):
                chang_shi_dai_jia = shi_ji_dai_jia[dang_qian] + self.heuristic(dang_qian, lin_jie)
                if lin_jie not in shi_ji_dai_jia or chang_shi_dai_jia < shi_ji_dai_jia[lin_jie]:
                    qian_qu[lin_jie] = dang_qian
                    shi_ji_dai_jia[lin_jie] = chang_shi_dai_jia
                    gu_suan_dai_jia[lin_jie] = chang_shi_dai_jia + self.heuristic(lin_jie, end_node)
                    heapq.heappush(dai_kao_cha, (gu_suan_dai_jia[lin_jie], lin_jie))

        return [], 0.0  # 无路径

    def find_nearest_node(self, x: float, y: float,
                          node_type: Optional[str] = None) -> Optional[str]:
        """找到离坐标最近的路网节点"""
        zui_jin_jie_dian = None                  # 最近节点id
        zui_jin_ju_li = float('inf')             # 最近距离的平方（初始为无穷大）

        for node_id, node_data in self.network.nodes.items():
            if node_type and node_data.get('type') != node_type:
                continue
            dx = node_data['x'] - x
            dy = node_data['y'] - y
            ju_li = dx * dx + dy * dy            # 距离平方（免开方，仅用于比较大小）
            if ju_li < zui_jin_ju_li:
                zui_jin_ju_li = ju_li
                zui_jin_jie_dian = node_id

        return zui_jin_jie_dian


class NavigationService:
    """导航服务 - 整合路径规划、跨层导航、用户定位"""

    def __init__(self):
        self.networks = {}  # {floor_id: RoadNetwork}

    def load_network(self, floor_id: int, filepath: str):
        """加载楼层路网"""
        network = RoadNetwork.load(filepath)
        if network:
            self.networks[floor_id] = network
        return network

    def get_path_finder(self, floor_id: int) -> Optional[PathFinder]:
        """获取楼层路径规划器"""
        network = self.networks.get(floor_id)
        if not network:
            return None
        return PathFinder(network)

    def plan_intra_floor(self, floor_id: int, start_node: str,
                         end_node: str) -> dict:
        """单楼层路径规划"""
        finder = self.get_path_finder(floor_id)              # 本楼层路径规划器
        if not finder:
            return {'error': '路网未加载', 'path': [], 'distance': 0}

        path, distance = finder.find_path(start_node, end_node)

        network = self.networks[floor_id]
        qi_dian_wei_zhi = network.nodes.get(start_node, {})   # 起点坐标
        zhong_dian_wei_zhi = network.nodes.get(end_node, {})  # 终点坐标

        # 没找到路径 → 返回错误（不走直线回退）
        if not path:
            return {
                'error': f'起点 {start_node} 和终点 {end_node} 之间没有连通路径，请检查路网是否连续',
                'path': [], 'distance': 0, 'node_count': 0,
                'start_node': {'id': start_node, 'x': qi_dian_wei_zhi.get('x', 0), 'y': qi_dian_wei_zhi.get('y', 0)},
                'end_node': {'id': end_node, 'x': zhong_dian_wei_zhi.get('x', 0), 'y': zhong_dian_wei_zhi.get('y', 0)},
            }

        # 返回路径坐标
        lu_jing_zuo_biao = []                     # 路径上每个节点的坐标列表
        for node_id in path:
            node = network.nodes.get(node_id, {})
            lu_jing_zuo_biao.append({
                'node_id': node_id,
                'x': node.get('x', 0),
                'y': node.get('y', 0),
                'type': node.get('type', 'normal'),
            })

        return {
            'floor_id': floor_id,
            'path': lu_jing_zuo_biao,
            'distance': round(distance, 1),
            'node_count': len(path),
            'start_node': {'id': start_node, 'x': qi_dian_wei_zhi.get('x', 0), 'y': qi_dian_wei_zhi.get('y', 0)},
            'end_node': {'id': end_node, 'x': zhong_dian_wei_zhi.get('x', 0), 'y': zhong_dian_wei_zhi.get('y', 0)},
        }

    def plan_cross_floor(self, from_floor_id: int, to_floor_id: int,
                          from_node: str, to_node: str,
                          stair_nodes: dict) -> dict:
        """
        跨层导航

        Args:
            from_floor_id: 起始楼层
            to_floor_id: 目标楼层
            from_node: 起点节点
            to_node: 终点节点
            stair_nodes: {floor_id: stair_node_id} 楼梯口节点映射
        """
        result = {
            'segments': [],
            'total_distance': 0,
            'cross_floor_hint': '',
        }

        # 第一段：起点 → 楼梯口
        finder_from = self.get_path_finder(from_floor_id)
        if finder_from:
            lou_ti_kou_qi = stair_nodes.get(from_floor_id)      # 起点楼层的楼梯口节点
            if lou_ti_kou_qi:
                duan_lu_jing_1, ju_li_1 = finder_from.find_path(from_node, lou_ti_kou_qi)
                lu_jing_zuo_biao_1 = self._jie_dian_zhuan_zuo_biao(from_floor_id, duan_lu_jing_1)
                result['segments'].append({
                    'floor_id': from_floor_id,
                    'path': lu_jing_zuo_biao_1,
                    'distance': round(ju_li_1, 1),
                    'label': f'从起点到楼梯口',
                })
                result['total_distance'] += ju_li_1

        # 第二段：目标楼层楼梯口 → 终点
        finder_to = self.get_path_finder(to_floor_id)
        if finder_to:
            lou_ti_kou_zhong = stair_nodes.get(to_floor_id)     # 目标楼层的楼梯口节点
            if lou_ti_kou_zhong:
                duan_lu_jing_2, ju_li_2 = finder_to.find_path(lou_ti_kou_zhong, to_node)
                lu_jing_zuo_biao_2 = self._jie_dian_zhuan_zuo_biao(to_floor_id, duan_lu_jing_2)
                result['segments'].append({
                    'floor_id': to_floor_id,
                    'path': lu_jing_zuo_biao_2,
                    'distance': round(ju_li_2, 1),
                    'label': f'从楼梯口到目标座位',
                })
                result['total_distance'] += ju_li_2

        ceng_shu_cha = to_floor_id - from_floor_id
        fang_xiang = '上楼' if ceng_shu_cha > 0 else '下楼'
        result['cross_floor_hint'] = f'请{fang_xiang}至{abs(ceng_shu_cha)}层（走楼梯/电梯至{to_floor_id}F）'
        result['total_distance'] = round(result['total_distance'], 1)

        return result

    def locate_user_by_qr(self, floor_id: int, node_id: str) -> dict:
        """扫码定位 - 将用户定位到指定节点"""
        network = self.networks.get(floor_id)
        if not network or node_id not in network.nodes:
            return {'error': '无效的定位节点'}

        node = network.nodes[node_id]
        return {
            'floor_id': floor_id,
            'node_id': node_id,
            'x': node['x'],
            'y': node['y'],
            'position_name': node.get('name', '未知位置'),
        }

    def locate_user_by_click(self, floor_id: int, click_x: float,
                              click_y: float) -> dict:
        """手动选点定位 - 吸附到最近路网节点"""
        network = self.networks.get(floor_id)
        if not network:
            return {'error': '路网未加载'}

        finder = PathFinder(network)
        zui_jin_jie_dian = finder.find_nearest_node(click_x, click_y)
        if not zui_jin_jie_dian:
            return {'error': '未找到附近路网节点'}

        node = network.nodes[zui_jin_jie_dian]
        return {
            'floor_id': floor_id,
            'node_id': zui_jin_jie_dian,
            'x': node['x'],
            'y': node['y'],
            'position_name': node.get('name', '已吸附到路网'),
            'original_click': {'x': click_x, 'y': click_y},
        }

    def _jie_dian_zhuan_zuo_biao(self, floor_id: int, node_ids: List[str]) -> list:
        """将节点ID列表转换为坐标列表（供前端绘制路径）"""
        network = self.networks.get(floor_id)
        if not network:
            return []
        zuo_biao_lie_biao = []
        for jie_dian_id in node_ids:
            node = network.nodes.get(jie_dian_id, {})
            zuo_biao_lie_biao.append({
                'node_id': jie_dian_id,
                'x': node.get('x', 0),
                'y': node.get('y', 0),
                'type': node.get('type', 'normal'),
            })
        return zuo_biao_lie_biao
