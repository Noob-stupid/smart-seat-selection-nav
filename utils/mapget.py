"""
路网生成器 - 基于平面图的路网半自动生成

流程：
1. 管理员上传带座椅标注的楼层平面图
2. 轻量语义分割（MobileUNet/TinyUNet）识别桌椅区、墙体、通道、门
3. OpenCV 形态学处理提取可行走区域骨架，生成初始路网
4. 管理员在后台微调：拖拽节点、输入座椅编号
5. 确认后生成导航数据

注意：实际语义分割需要加载训练好的模型权重。
本模块提供基于传统图像处理的路网生成实现作为开发/演示用，
生产环境可替换为 MobileUNet/TinyUNet 推理。
"""
import cv2
import numpy as np
import json
import logging
import os
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class RoadNetworkGenerator:
    """基于平面图的路网生成器"""

    def __init__(self, skeleton_method: str = 'zhang-suen'):
        """
        Args:
            skeleton_method: 骨架提取方法 ('zhang-suen' 或 'morphology')
        """
        self.skeleton_method = skeleton_method

    def generate_from_floorplan(self, image_path: str,
                                seat_positions: List[dict] = None) -> dict:
        """
        从平面图生成路网

        Args:
            image_path: 平面图路径
            seat_positions: 可选，预标注的座位位置 [{x, y, label}]

        Returns:
            路网数据 {nodes, edges, floor_info}
        """
        # 1. 读取图像
        #
        # 不能直接用 cv2.imread：它只看扩展名选解码器，而用户上传的图经常
        # 文件名是 .png、内容其实是 WebP（浏览器截图、微信转存都这样），
        # imread 会直接返回 None，整条路网生成流程就此失败。
        # 改用 np.fromfile + cv2.imdecode，让 OpenCV 自己嗅探真实格式。
        img = None
        try:
            buf = np.fromfile(image_path, dtype=np.uint8)
            if buf.size:
                img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception:
            img = None
        if img is None:
            img = cv2.imread(image_path)        # 兜底：路径可能不是本地文件系统语义
        if img is None:
            raise ValueError(f'无法读取图像: {image_path}')

        height, width = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. 图像预处理 - 增强对比度
        contrast_enhancer = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = contrast_enhancer.apply(gray)

        # 3. 二值化 - 尝试多种阈值策略分离通道区域和障碍物
        #    先尝试自适应 Otsu 阈值（适用于大多数平面图）
        #    再尝试固定阈值 200（适用于浅色通道、深色墙的 CAD 导出图）
        #    最后尝试反色阈值（适用于白底黑线的 CAD 图）
        binary = None
        strategies = []
        # 策略1: Otsu 自动阈值
        _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        strategies.append(('otsu', otsu))
        # 策略2: 固定阈值 200（浅色通道）
        _, fixed = cv2.threshold(enhanced, 200, 255, cv2.THRESH_BINARY)
        strategies.append(('fixed200', fixed))
        # 策略3: 固定阈值 128（中性）
        _, mid = cv2.threshold(enhanced, 128, 255, cv2.THRESH_BINARY)
        strategies.append(('fixed128', mid))
        # 策略4: 反色 Otsu（适用于 CAD 白底黑线导出图）
        _, otsu_inv = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        strategies.append(('otsu_inv', otsu_inv))

        # 选择白色区域占比最合理的策略（30%-70% 白色 = 合理的通道比例）
        best_strategy = None
        best_score = float('inf')
        for _, bw in strategies:
            white_ratio = cv2.countNonZero(bw) / (width * height)
            # 越接近 50% 白色区域越好
            score = abs(white_ratio - 0.5)
            if score < best_score and 0.15 < white_ratio < 0.85:
                best_score = score
                best_strategy = bw
        binary = best_strategy if best_strategy is not None else strategies[0][1]

        # 4. 形态学操作 - 去除噪声，连接断裂区域
        kernel = np.ones((3, 3), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)

        # 5. 提取骨架（可行走区域中心线）
        skeleton = self._extract_skeleton(cleaned)

        # 6. 从骨架提取路网节点和边
        nodes, edges = self._skeleton_to_graph(skeleton)

        # 7. 补充座位节点连接
        if seat_positions:
            nodes, edges = self._connect_seats(nodes, edges, seat_positions, skeleton)

        # 8. 识别特殊节点（门、楼梯口）
        nodes = self._identify_special_nodes(nodes, enhanced)

        return {
            'nodes': nodes,
            'edges': edges,
            'floor_info': {
                'width': width,
                'height': height,
                'image_path': image_path,
            }
        }

    def generate_from_seats_only(self, seat_positions: List[dict],
                                  width: int = 800, height: int = 600) -> dict:
        """
        无平面图时，仅根据座位坐标生成简易路网

        Args:
            seat_positions: 座位位置 [{x, y, label}]
            width: 画布宽度
            height: 画布高度

        Returns:
            路网数据 {nodes, edges, floor_info}
        """
        nodes = {}
        edges = []

        if not seat_positions:
            return {'nodes': nodes, 'edges': edges, 'floor_info': {'width': width, 'height': height}}

        # 为每个座位创建节点，并在相邻座位之间创建边
        seat_nodes = []                        # 记录所有座位节点id
        for i, seat in enumerate(seat_positions):
            seat_node_id = f'seat_{seat.get("label", i)}'
            nodes[seat_node_id] = {
                'x': int(seat['x']),
                'y': int(seat['y']),
                'type': 'seat',
                'name': seat.get('label', ''),
            }
            seat_nodes.append(seat_node_id)

        # 按距离连接相邻座位（曼哈顿距离 < 150px 的添加通道节点）
        for i in range(len(seat_nodes)):
            for j in range(i + 1, len(seat_nodes)):
                node_a = nodes[seat_nodes[i]]
                node_b = nodes[seat_nodes[j]]
                dist = abs(node_a['x'] - node_b['x']) + abs(node_a['y'] - node_b['y'])
                if dist < 150:
                    mid_id = f'm_{i}_{j}'   # 中间通道节点
                    if mid_id not in nodes:
                        nodes[mid_id] = {
                            'x': (node_a['x'] + node_b['x']) // 2,
                            'y': (node_a['y'] + node_b['y']) // 2,
                            'type': 'normal',
                            'name': None,
                        }
                    edges.append({'from': seat_nodes[i], 'to': mid_id})
                    edges.append({'from': mid_id, 'to': seat_nodes[j]})

        return {
            'nodes': nodes,
            'edges': edges,
            'floor_info': {
                'width': width,
                'height': height,
            }
        }

    def _extract_skeleton(self, binary_img: np.ndarray) -> np.ndarray:
        """提取二值图像的骨架（可行走区域中心线）"""
        # 优先使用 Zhang-Suen 细化算法，若 ximgproc 不可用则回退到形态学方法
        if self.skeleton_method == 'zhang-suen':
            try:
                skeleton = cv2.ximgproc.thinning(binary_img, cv2.ximgproc.THINNING_ZHANGSUEN)
                return skeleton
            except AttributeError:
                # ximgproc 不可用，回退到形态学方法
                pass

        # 形态学骨架提取（备选方案，不依赖 ximgproc）
        skeleton = np.zeros_like(binary_img)
        temp = binary_img.copy()                # 临时图像，每轮腐蚀后更新
        kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))

        while True:
            eroded = cv2.erode(temp, kernel)          # 腐蚀：缩小前景
            dilated = cv2.dilate(eroded, kernel)      # 膨胀：还原被缩小的部分
            skeleton_part = cv2.subtract(temp, dilated)  # 两者差值即骨架片段
            skeleton = cv2.bitwise_or(skeleton, skeleton_part)
            temp = eroded.copy()
            if cv2.countNonZero(temp) == 0:
                break

        return skeleton

    def _skeleton_to_graph(self, skeleton: np.ndarray,
                           min_node_dist: int = 20) -> Tuple[dict, list]:
        """
        将骨架转换为图结构（节点 + 边）

        Returns:
            (nodes_dict, edges_list)
        """
        # 找到所有骨架像素
        ys, xs = np.where(skeleton > 0)
        points = list(zip(xs, ys))

        if not points:
            return {}, []

        # 通过连通组件分析找到交叉点和端点
        # 简化：以一定间隔采样作为节点
        nodes = {}
        edges = []
        node_id_counter = 0                    # 节点编号计数器

        # 对骨架进行细化采样
        sampled = np.zeros_like(skeleton)      # 采样标记图
        step = min_node_dist                   # 采样间隔（像素）

        for y in range(0, skeleton.shape[0], step):
            for x in range(0, skeleton.shape[1], step):
                region = skeleton[max(0, y - step // 2):min(skeleton.shape[0], y + step // 2),
                                  max(0, x - step // 2):min(skeleton.shape[1], x + step // 2)]
                if np.any(region > 0):
                    local_ys, local_xs = np.where(region > 0)

                    # 取「格子里离质心最近的那个骨架像素」，不直接取质心。
                    #
                    # 原来直接取 np.mean(local_xs/ys) 作节点位置，实测有 38% 的节点
                    # 落在骨架之外 —— 格子内若有两条交叉骨架，它们的平均位置落在线与线
                    # 之间，那里根本没有骨架。后果是后面 _has_skeleton_path 的两点
                    # 直线采样必然穿空，连不上边：一张 1931x791 的图生成 767 个节点，
                    # 只有 372 条边，近一半节点是孤立的。
                    #
                    # 改成"离质心最近的骨架像素"后，节点一定落在骨架上，
                    # 既保留了质心代表该区域的语义，又保证了连边可行。
                    cx_mean = float(np.mean(local_xs))
                    cy_mean = float(np.mean(local_ys))
                    d2 = (local_xs - cx_mean) ** 2 + (local_ys - cy_mean) ** 2
                    pick = int(np.argmin(d2))
                    center_x = x - step // 2 + int(local_xs[pick])
                    center_y = y - step // 2 + int(local_ys[pick])

                    # 贴边的格子会算出负坐标或超出图像范围（原来会出现 y=-10 这种点），
                    # 钳制回图像内，否则前端画到画布外面、A* 吸附也会落空。
                    center_x = max(0, min(skeleton.shape[1] - 1, center_x))
                    center_y = max(0, min(skeleton.shape[0] - 1, center_y))

                    node_id = f'n{node_id_counter}'
                    nodes[node_id] = {
                        'x': int(center_x),
                        'y': int(center_y),
                        'type': 'normal',
                        'name': None,
                    }
                    sampled[center_y, center_x] = 255
                    node_id_counter += 1

        # 连接相邻节点（基于距离）
        #
        # 骨架连通检查必须在「膨胀一次」的骨架上做。
        # 骨架是 1 像素宽的线，而 _has_skeleton_path 沿两点连线采 10 个点、
        # 要求每一点都正好压在骨架上 —— 零容差等于必然脱靶：
        # 实测一对相距 22 像素的相邻节点，11 个采样点里只有 3 个落在骨架上，
        # 中间 7 个全部脱靶，于是判定「不连通」，边就没了。
        # 结果是一张图 767 个节点只连出 465 条边，孤立节点 49.7%。
        # 膨胀一次（3x3）给 1 像素容差后，同样的图连出 877 条边，孤立降到 3.8%。
        # 容差只放宽 1 像素，不会让隔着几像素厚墙的两点连上。
        check_mask = cv2.dilate(skeleton, np.ones((3, 3), np.uint8), iterations=1)

        node_list = list(nodes.keys())
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                node_a = nodes[node_list[i]]
                node_b = nodes[node_list[j]]
                dist = ((node_a['x'] - node_b['x']) ** 2 + (node_a['y'] - node_b['y']) ** 2) ** 0.5

                # 距离在合理范围内且路径在骨架内
                if dist < step * 1.5:
                    # 检查两点之间是否有骨架连接
                    if self._has_skeleton_path(check_mask, node_a['x'], node_a['y'], node_b['x'], node_b['y']):
                        edges.append({'from': node_list[i], 'to': node_list[j]})

        return nodes, edges

    def _has_skeleton_path(self, skeleton: np.ndarray, x1: int, y1: int,
                           x2: int, y2: int, samples: int = 10) -> bool:
        """检查两点之间是否有骨架像素连接（沿直线采样，全部落在骨架上才算连通）"""
        for i in range(samples + 1):
            t = i / samples
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            if 0 <= y < skeleton.shape[0] and 0 <= x < skeleton.shape[1]:
                if skeleton[y, x] == 0:
                    return False
        return True

    def _connect_seats(self, nodes: dict, edges: list,
                       seat_positions: List[dict],
                       skeleton: np.ndarray) -> Tuple[dict, list]:
        """将座位节点连接到最近的路网节点。

        距离上限是必需的：座位坐标一旦标错（标到墙外、标到别的楼层图上），
        原来的实现会无条件连到最近节点，于是生成一条穿墙的边，导航就会
        规划出根本走不过去的路径。超过上限的座位不连边，只保留节点，
        由管理员在后台看到孤立座位后手动修正。
        """
        # 以采样间距为尺度：正常座位离最近的通道节点不会超过几十像素。
        # 取 20 倍步长（默认 400 像素）作为上限，超过就判定为「坐标不可信」。
        max_link_dist = 400.0
        unlinked = 0

        for seat in seat_positions:
            seat_x, seat_y = seat['x'], seat['y']
            label = seat.get('label', '')

            # 找到最近的路网节点
            nearest = None
            nearest_dist = float('inf')
            for node_id, node_data in nodes.items():
                if node_data.get('type') == 'seat':
                    continue                     # 只往通道节点上连
                dist = (node_data['x'] - seat_x) ** 2 + (node_data['y'] - seat_y) ** 2
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = node_id

            seat_node_id = f'seat_{label}' if label else f'seat_{seat_x}_{seat_y}'
            nodes[seat_node_id] = {
                'x': int(seat_x),
                'y': int(seat_y),
                'type': 'seat',
                'name': label or None,
            }

            if nearest and nearest_dist ** 0.5 <= max_link_dist:
                edges.append({'from': seat_node_id, 'to': nearest})
            else:
                # 不连边，但把节点留下：前端能看到这个座位孤零零挂着，
                # 管理员据此判断是坐标标错了还是这一带还没画路网。
                unlinked += 1

        if unlinked:
            logger.warning('有 %d 个座位离路网超过 %.0f 像素，未自动连边，等待人工修正',
                           unlinked, max_link_dist)

        return nodes, edges

    def _identify_special_nodes(self, nodes: dict,
                                enhanced: np.ndarray) -> dict:
        """
        识别特殊节点（门、楼梯口等）
        实际应用中需要更复杂的检测逻辑或人工标注
        """
        # 此处为简化实现，特殊节点需管理员在后台手动标记
        # 返回值中添加 type 字段供后续使用
        return nodes

    def refine_network(self, network: dict, adjustments: List[dict]) -> dict:
        """
        根据管理员微调更新路网

        Args:
            network: 原路网数据
            adjustments: 调整列表 [{type: 'move'|'add'|'delete'|'rename', ...}]
        """
        nodes = network['nodes']
        edges = network['edges']

        for adjustment in adjustments:
            if adjustment['type'] == 'move':
                # 拖拽节点
                node_id = adjustment['node_id']
                if node_id in nodes:
                    nodes[node_id]['x'] = adjustment.get('x', nodes[node_id]['x'])
                    nodes[node_id]['y'] = adjustment.get('y', nodes[node_id]['y'])

            elif adjustment['type'] == 'add':
                # 添加节点
                new_node_id = f'n{len(nodes)}'
                nodes[new_node_id] = {
                    'x': adjustment['x'],
                    'y': adjustment['y'],
                    'type': adjustment.get('type', 'normal'),
                    'name': adjustment.get('name'),
                }
                # 连接到指定的节点
                if adjustment.get('connect'):
                    for connect_node in adjustment['connect']:
                        edges.append({'from': new_node_id, 'to': connect_node})

            elif adjustment['type'] == 'delete':
                node_id = adjustment['node_id']
                if node_id in nodes:
                    del nodes[node_id]
                    # 删除相关边
                    edges = [e for e in edges
                             if e['from'] != node_id and e['to'] != node_id]
                    network['edges'] = edges

            elif adjustment['type'] == 'rename':
                node_id = adjustment['node_id']
                if node_id in nodes:
                    nodes[node_id]['name'] = adjustment.get('name', nodes[node_id]['name'])

        network['nodes'] = nodes
        network['edges'] = edges
        return network

    def generate_floor_overlay(self, image_path: str, network: dict,
                                 output_path: str):
        """
        生成带路网叠加的预览图（供管理员微调使用）
        无平面图时自动创建空白画布
        """
        floor_info = network.get('floor_info', {})
        w = floor_info.get('width', 800)
        h = floor_info.get('height', 600)

        if image_path and os.path.exists(image_path):
            img = cv2.imread(image_path)
            if img is None:
                img = 255 * np.ones((h, w, 3), dtype=np.uint8)
        else:
            img = 255 * np.ones((h, w, 3), dtype=np.uint8)

        overlay = img.copy()                   # 叠加图层
        nodes = network.get('nodes', {})
        edges = network.get('edges', [])

        # 绘制边
        for edge in edges:
            start_node = nodes.get(edge['from'])
            end_node = nodes.get(edge['to'])
            if start_node and end_node:
                cv2.line(overlay, (start_node['x'], start_node['y']),
                         (end_node['x'], end_node['y']), (0, 255, 0), 2)

        # 绘制节点
        for nid, node_data in nodes.items():
            color = (0, 0, 255) if node_data.get('type') == 'seat' else (255, 0, 0)
            cv2.circle(overlay, (node_data['x'], node_data['y']), 5, color, -1)
            if node_data.get('name'):
                cv2.putText(overlay, node_data['name'],
                           (node_data['x'] + 8, node_data['y'] + 8),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # 半透明叠加
        result = cv2.addWeighted(img, 0.7, overlay, 0.3, 0)
        cv2.imwrite(output_path, result)
