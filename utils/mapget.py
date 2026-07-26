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
import os
from typing import List, Tuple, Optional


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
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f'无法读取图像: {image_path}')

        height, width = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. 图像预处理 - 增强对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 3. 二值化 - 分离通道区域（浅色）和障碍物（深色）
        _, binary = cv2.threshold(enhanced, 200, 255, cv2.THRESH_BINARY)

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

    def _extract_skeleton(self, binary_img: np.ndarray) -> np.ndarray:
        """提取二值图像的骨架"""
        # 确保前景为白色（255），背景为黑色（0）
        if self.skeleton_method == 'zhang-suen':
            # Zhang-Suen 细化算法
            skeleton = cv2.ximgproc.thinning(binary_img, cv2.ximgproc.THINNING_ZHANGSUEN)
        else:
            # 形态学骨架提取
            skeleton = np.zeros_like(binary_img)
            temp = binary_img.copy()
            kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))

            while True:
                eroded = cv2.erode(temp, kernel)
                dilated = cv2.dilate(eroded, kernel)
                skeleton_part = cv2.subtract(temp, dilated)
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
        node_id_counter = 0

        # 建立像素邻域关系
        # 对骨架进行细化采样
        sampled = np.zeros_like(skeleton)
        step = min_node_dist

        for y in range(0, skeleton.shape[0], step):
            for x in range(0, skeleton.shape[1], step):
                region = skeleton[max(0, y - step // 2):min(skeleton.shape[0], y + step // 2),
                                  max(0, x - step // 2):min(skeleton.shape[1], x + step // 2)]
                if np.any(region > 0):
                    # 找到区域内的骨架中心
                    local_ys, local_xs = np.where(region > 0)
                    cx = x - step // 2 + int(np.mean(local_xs))
                    cy = y - step // 2 + int(np.mean(local_ys))

                    node_id = f'n{node_id_counter}'
                    nodes[node_id] = {
                        'x': int(cx),
                        'y': int(cy),
                        'type': 'normal',
                        'name': None,
                    }
                    sampled[cy, cx] = 255
                    node_id_counter += 1

        # 连接相邻节点（基于距离）
        node_list = list(nodes.keys())
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                ni = nodes[node_list[i]]
                nj = nodes[node_list[j]]
                dist = ((ni['x'] - nj['x']) ** 2 + (ni['y'] - nj['y']) ** 2) ** 0.5

                # 距离在合理范围内且路径在骨架内
                if dist < step * 1.5:
                    # 检查两点之间是否有骨架连接
                    if self._has_skeleton_path(skeleton, ni['x'], ni['y'], nj['x'], nj['y']):
                        edges.append({'from': node_list[i], 'to': node_list[j]})

        return nodes, edges

    def _has_skeleton_path(self, skeleton: np.ndarray, x1: int, y1: int,
                           x2: int, y2: int, samples: int = 10) -> bool:
        """检查两点之间是否有骨架像素连接"""
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
        """将座位节点连接到最近的路网节点"""
        for seat in seat_positions:
            sx, sy = seat['x'], seat['y']
            label = seat.get('label', '')

            # 找到最近的路网节点
            nearest = None
            nearest_dist = float('inf')
            for nid, ndata in nodes.items():
                dist = (ndata['x'] - sx) ** 2 + (ndata['y'] - sy) ** 2
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = nid

            if nearest:
                seat_node_id = f'seat_{label}' if label else f'seat_{sx}_{sy}'
                nodes[seat_node_id] = {
                    'x': int(sx),
                    'y': int(sy),
                    'type': 'seat',
                    'name': label or None,
                }
                edges.append({'from': seat_node_id, 'to': nearest})

        return nodes, edges

    def _identify_special_nodes(self, nodes: dict,
                                 enhanced_img: np.ndarray) -> dict:
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

        for adj in adjustments:
            if adj['type'] == 'move':
                # 拖拽节点
                node_id = adj['node_id']
                if node_id in nodes:
                    nodes[node_id]['x'] = adj.get('x', nodes[node_id]['x'])
                    nodes[node_id]['y'] = adj.get('y', nodes[node_id]['y'])

            elif adj['type'] == 'add':
                # 添加节点
                nid = f'n{len(nodes)}'
                nodes[nid] = {
                    'x': adj['x'],
                    'y': adj['y'],
                    'type': adj.get('type', 'normal'),
                    'name': adj.get('name'),
                }
                # 连接到最近的2个节点
                if adj.get('connect'):
                    for conn in adj['connect']:
                        edges.append({'from': nid, 'to': conn})

            elif adj['type'] == 'delete':
                node_id = adj['node_id']
                if node_id in nodes:
                    del nodes[node_id]
                    # 删除相关边
                    network['edges'] = [e for e in edges
                                        if e['from'] != node_id and e['to'] != node_id]

            elif adj['type'] == 'rename':
                node_id = adj['node_id']
                if node_id in nodes:
                    nodes[node_id]['name'] = adj.get('name', nodes[node_id]['name'])

        network['nodes'] = nodes
        return network

    def generate_floor_overlay(self, image_path: str, network: dict,
                                 output_path: str):
        """
        生成带路网叠加的预览图（供管理员微调使用）
        """
        img = cv2.imread(image_path)
        if img is None:
            return

        overlay = img.copy()
        nodes = network.get('nodes', {})
        edges = network.get('edges', [])

        # 绘制边
        for edge in edges:
            frm = nodes.get(edge['from'])
            to = nodes.get(edge['to'])
            if frm and to:
                cv2.line(overlay, (frm['x'], frm['y']),
                         (to['x'], to['y']), (0, 255, 0), 2)

        # 绘制节点
        for nid, ndata in nodes.items():
            color = (0, 0, 255) if ndata.get('type') == 'seat' else (255, 0, 0)
            cv2.circle(overlay, (ndata['x'], ndata['y']), 5, color, -1)
            if ndata.get('name'):
                cv2.putText(overlay, ndata['name'],
                           (ndata['x'] + 8, ndata['y'] + 8),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # 半透明叠加
        result = cv2.addWeighted(img, 0.7, overlay, 0.3, 0)
        cv2.imwrite(output_path, result)
