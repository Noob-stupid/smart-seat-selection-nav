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
        self._build_adjacency()      # 构建邻接表
        # 路网断成多块时自动搭桥（只改内存邻接表，不写盘）
        self.bridges = self._bridge_components()

    def _build_adjacency(self):
        """构建邻接表（记录每个节点与哪些节点直接相连）"""
        self.adjacency = {}                        # 邻接表：{节点id: [相连节点id列表]}
        for node_id in self.network.nodes:
            self.adjacency[node_id] = []

        for edge in self.network.edges:
            frm = edge['from']
            to = edge['to']
            if frm in self.adjacency and to in self.adjacency:
                self.adjacency[frm].append(to)
                self.adjacency[to].append(frm)

    def components(self) -> List[list]:
        """把节点按连通性分组，返回若干连通块。"""
        seen = set()
        comps = []
        for n in self.network.nodes:
            if n in seen:
                continue
            stack = [n]
            seen.add(n)
            comp = []
            while stack:
                x = stack.pop()
                comp.append(x)
                for y in self.adjacency.get(x, []):
                    if y not in seen:
                        seen.add(y)
                        stack.append(y)
            comps.append(comp)
        return comps

    def _bridge_components(self) -> list:
        """把互不相连的子路网用最短的一条边连起来，返回补上的桥。

        为什么需要这个：
          手动绘制路网时很容易画成几段独立的笔画 —— 主通道画一段、
          某个教室再画一段，中间忘了接上。此时起点和终点会分别吸附到
          不同的子网，A* 自然找不到路径，用户看到的是「没有连通路径，
          请检查路网是否连续」，可他明明画了线，只会一头雾水。

          与其让他去后台一处处排查缺口，不如在规划时把最近的缺口补上：
          反复找出「离主块最近的那一块」，在两者距离最近的一对节点间加一条边。

        安全边界：
          · 只作用于内存里的邻接表，绝不写回磁盘 —— 管理员画的线一根不动
          · 补的是一条直线段，不插入虚拟节点，渲染出来的路径形状不受影响
          · 补了哪几处会通过 bridges 上报，前端可以如实告知用户
        """
        comps = self.components()
        if len(comps) <= 1:
            return []

        bridges = []
        main = max(comps, key=len)
        rest = [c for c in comps if c is not main]

        while rest:
            best = None                      # (距离, 主块节点, 待并入节点, 该块)
            for comp in rest:
                for a in main:
                    pa = self.network.nodes.get(a, {})
                    ax, ay = pa.get('x', 0), pa.get('y', 0)
                    for b in comp:
                        pb = self.network.nodes.get(b, {})
                        dx = ax - pb.get('x', 0)
                        dy = ay - pb.get('y', 0)
                        d = (dx * dx + dy * dy) ** 0.5
                        if best is None or d < best[0]:
                            best = (d, a, b, comp)
            if best is None:
                break
            d, a, b, comp = best
            self.adjacency[a].append(b)
            self.adjacency[b].append(a)
            bridges.append({'from': a, 'to': b, 'gap': round(d, 1)})
            main = main + comp
            rest = [c for c in rest if c is not comp]

        return bridges

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

        open_set = [(0, start_node)]                           # 待考察节点堆（按估算总代价排序）
        came_from = {}                                         # 前驱表：记录每个节点是从哪个节点走来的
        g_score = {start_node: 0.0}                            # 起点到该节点的实际已走代价
        f_score = {start_node: self.heuristic(start_node, end_node)}  # 起点经该节点到终点的估算总代价

        while open_set:
            _, current = heapq.heappop(open_set)               # 取出估算代价最小的节点

            if current == end_node:
                # 重建路径
                path = []
                while current in came_from:
                    path.append(current)
                    current = came_from[current]
                path.append(start_node)
                path.reverse()
                return path, g_score[end_node]

            for neighbor in self.adjacency.get(current, []):
                candidate_cost = g_score[current] + self.heuristic(current, neighbor)
                if neighbor not in g_score or candidate_cost < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = candidate_cost
                    f_score[neighbor] = candidate_cost + self.heuristic(neighbor, end_node)
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        return [], 0.0  # 无路径

    def find_nearest_node(self, x: float, y: float,
                          node_type: Optional[str] = None) -> Optional[str]:
        """找到离坐标最近的路网节点"""
        nearest_node = None                      # 最近节点id
        nearest_dist = float('inf')              # 最近距离的平方（初始为无穷大）

        for node_id, node_data in self.network.nodes.items():
            if node_type and node_data.get('type') != node_type:
                continue
            dx = node_data['x'] - x
            dy = node_data['y'] - y
            dist = dx * dx + dy * dy             # 距离平方（免开方，仅用于比较大小）
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_node = node_id

        return nearest_node


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

    def unload_network(self, floor_id: int):
        """卸载指定楼层的路网缓存。

        删除平面图时调用 —— 路网文件已被删除，若内存里还留着旧对象，
        前端刷新后仍可能拿到已失效的路网。
        """
        return self.networks.pop(floor_id, None)

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
        start_pos = network.nodes.get(start_node, {})   # 起点坐标
        end_pos = network.nodes.get(end_node, {})       # 终点坐标

        # 路网有断点时如实说明：路径已经能走通，但这是补出来的，
        # 让用户知道该去后台把线连上，而不是默默替他掩盖。
        note = None
        if getattr(finder, 'bridges', None):
            pairs = '、'.join('%s→%s' % (b['from'], b['to']) for b in finder.bridges[:3])
            note = ('路网存在 %d 处断点，已自动连接（%s）后规划成功。'
                    '建议在「平面图与路网配置」里把路线画通，以免绕行。'
                    % (len(finder.bridges), pairs))

        # 没找到路径 → 返回错误（不走直线回退）
        if not path:
            return {
                'error': (f'起点 {start_node} 和终点 {end_node} 之间没有连通路径'
                          + ('（路网已有断点且自动连接后仍不通）' if note else '')
                          + '，请检查路网是否连续'),
                'path': [], 'distance': 0, 'node_count': 0,
                'network_note': note,
                'start_node': {'id': start_node, 'x': start_pos.get('x', 0), 'y': start_pos.get('y', 0)},
                'end_node': {'id': end_node, 'x': end_pos.get('x', 0), 'y': end_pos.get('y', 0)},
            }

        # 返回路径坐标
        path_coords = []                          # 路径上每个节点的坐标列表
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
            'bridged': bool(note),
            'network_note': note,
            'start_node': {'id': start_node, 'x': start_pos.get('x', 0), 'y': start_pos.get('y', 0)},
            'end_node': {'id': end_node, 'x': end_pos.get('x', 0), 'y': end_pos.get('y', 0)},
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
            stair_from = stair_nodes.get(from_floor_id)      # 起点楼层的楼梯口节点
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
            stair_to = stair_nodes.get(to_floor_id)      # 目标楼层的楼梯口节点
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
        """将节点ID列表转换为坐标列表（供前端绘制路径）"""
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
