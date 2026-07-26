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
        self._build_adjacency()

    def _build_adjacency(self):
        """构建邻接表"""
        self.adj = {}
        for node_id in self.network.nodes:
            self.adj[node_id] = []

        for edge in self.network.edges:
            frm = edge['from']
            to = edge['to']
            if frm in self.adj and to in self.adj:
                self.adj[frm].append(to)
                self.adj[to].append(frm)

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

        open_set = [(0, start_node)]
        came_from = {}
        g_score = {start_node: 0.0}
        f_score = {start_node: self.heuristic(start_node, end_node)}

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == end_node:
                # 重建路径
                path = []
                while current in came_from:
                    path.append(current)
                    current = came_from[current]
                path.append(start_node)
                path.reverse()
                return path, g_score[end_node]

            for neighbor in self.adj.get(current, []):
                tentative_g = g_score[current] + self.heuristic(current, neighbor)
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + self.heuristic(neighbor, end_node)
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        return [], 0.0  # 无路径

    def find_nearest_node(self, x: float, y: float,
                          node_type: Optional[str] = None) -> Optional[str]:
        """找到离坐标最近的路网节点"""
        nearest_id = None
        nearest_dist = float('inf')

        for node_id, node_data in self.network.nodes.items():
            if node_type and node_data.get('type') != node_type:
                continue
            dx = node_data['x'] - x
            dy = node_data['y'] - y
            dist = dx * dx + dy * dy
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_id = node_id

        return nearest_id


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
        finder = self.get_path_finder(floor_id)
        if not finder:
            return {'error': '路网未加载', 'path': [], 'distance': 0}

        path, distance = finder.find_path(start_node, end_node)

        # 返回路径坐标
        network = self.networks[floor_id]
        path_coords = []
        for node_id in path:
            node = network.nodes.get(node_id, {})
            path_coords.append({
                'node_id': node_id,
                'x': node.get('x', 0),
                'y': node.get('y', 0),
                'type': node.get('type', 'normal'),
            })

        return {
            'floor_id': floor_id,
            'path': path_coords,
            'distance': round(distance, 1),
            'node_count': len(path),
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
            stair_from = stair_nodes.get(from_floor_id)
            if stair_from:
                seg1, dist1 = finder_from.find_path(from_node, stair_from)
                path_coords_1 = self._nodes_to_coords(from_floor_id, seg1)
                result['segments'].append({
                    'floor_id': from_floor_id,
                    'path': path_coords_1,
                    'distance': round(dist1, 1),
                    'label': f'从起点到楼梯口',
                })
                result['total_distance'] += dist1

        # 第二段：目标楼层楼梯口 → 终点
        finder_to = self.get_path_finder(to_floor_id)
        if finder_to:
            stair_to = stair_nodes.get(to_floor_id)
            if stair_to:
                seg2, dist2 = finder_to.find_path(stair_to, to_node)
                path_coords_2 = self._nodes_to_coords(to_floor_id, seg2)
                result['segments'].append({
                    'floor_id': to_floor_id,
                    'path': path_coords_2,
                    'distance': round(dist2, 1),
                    'label': f'从楼梯口到目标座位',
                })
                result['total_distance'] += dist2

        floor_diff = to_floor_id - from_floor_id
        direction = '上楼' if floor_diff > 0 else '下楼'
        result['cross_floor_hint'] = f'请{direction}至{abs(floor_diff)}层（走楼梯/电梯至{to_floor_id}F）'
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
        nearest = finder.find_nearest_node(click_x, click_y)
        if not nearest:
            return {'error': '未找到附近路网节点'}

        node = network.nodes[nearest]
        return {
            'floor_id': floor_id,
            'node_id': nearest,
            'x': node['x'],
            'y': node['y'],
            'position_name': node.get('name', '已吸附到路网'),
            'original_click': {'x': click_x, 'y': click_y},
        }

    def _nodes_to_coords(self, floor_id: int, node_ids: List[str]) -> list:
        """将节点ID列表转换为坐标列表"""
        network = self.networks.get(floor_id)
        if not network:
            return []
        coords = []
        for nid in node_ids:
            node = network.nodes.get(nid, {})
            coords.append({
                'node_id': nid,
                'x': node.get('x', 0),
                'y': node.get('y', 0),
                'type': node.get('type', 'normal'),
            })
        return coords
