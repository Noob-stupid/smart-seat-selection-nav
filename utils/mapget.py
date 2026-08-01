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
        hui_du_tu = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. 图像预处理 - 增强对比度
        dui_bi_zeng_qiang = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        zeng_qiang_tu = dui_bi_zeng_qiang.apply(hui_du_tu)

        # 3. 二值化 - 尝试多种阈值策略分离通道区域和障碍物
        #    先尝试自适应 Otsu 阈值（适用于大多数平面图）
        #    再尝试固定阈值 200（适用于浅色通道、深色墙的 CAD 导出图）
        #    最后尝试反色阈值（适用于白底黑线的 CAD 图）
        er_zhi_tu = None
        ce_lue_lie_biao = []
        # 策略1: Otsu 自动阈值
        _, er_zhi_otsu = cv2.threshold(zeng_qiang_tu, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        ce_lue_lie_biao.append(('otsu', er_zhi_otsu))
        # 策略2: 固定阈值 200（浅色通道）
        _, er_zhi_gu_ding = cv2.threshold(zeng_qiang_tu, 200, 255, cv2.THRESH_BINARY)
        ce_lue_lie_biao.append(('fixed200', er_zhi_gu_ding))
        # 策略3: 固定阈值 128（中性）
        _, er_zhi_zhong_xing = cv2.threshold(zeng_qiang_tu, 128, 255, cv2.THRESH_BINARY)
        ce_lue_lie_biao.append(('fixed128', er_zhi_zhong_xing))
        # 策略4: 反色 Otsu（适用于 CAD 白底黑线导出图）
        _, er_zhi_fan_otsu = cv2.threshold(zeng_qiang_tu, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ce_lue_lie_biao.append(('otsu_inv', er_zhi_fan_otsu))

        # 选择白色区域占比最合理的策略（30%-70% 白色 = 合理的通道比例）
        zui_jia_ce_lue = None
        zui_jia_de_fen = float('inf')
        for _, ce_lue_er_zhi in ce_lue_lie_biao:
            bai_se_bi_li = cv2.countNonZero(ce_lue_er_zhi) / (width * height)
            # 越接近 50% 白色区域越好
            de_fen = abs(bai_se_bi_li - 0.5)
            if de_fen < zui_jia_de_fen and 0.15 < bai_se_bi_li < 0.85:
                zui_jia_de_fen = de_fen
                zui_jia_ce_lue = ce_lue_er_zhi
        er_zhi_tu = zui_jia_ce_lue if zui_jia_ce_lue is not None else ce_lue_lie_biao[0][1]

        # 4. 形态学操作 - 去除噪声，连接断裂区域
        he_zi = np.ones((3, 3), np.uint8)
        qing_li_tu = cv2.morphologyEx(er_zhi_tu, cv2.MORPH_CLOSE, he_zi, iterations=2)
        qing_li_tu = cv2.morphologyEx(qing_li_tu, cv2.MORPH_OPEN, he_zi, iterations=1)

        # 5. 提取骨架（可行走区域中心线）
        gu_jia = self._ti_qu_gu_jia(qing_li_tu)

        # 6. 从骨架提取路网节点和边
        nodes, edges = self._gu_jia_zhuan_tu(gu_jia)

        # 7. 补充座位节点连接
        if seat_positions:
            nodes, edges = self._lian_jie_zuo_wei(nodes, edges, seat_positions, gu_jia)

        # 8. 识别特殊节点（门、楼梯口）
        nodes = self._shi_bie_te_shu_jie_dian(nodes, zeng_qiang_tu)

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
        zuo_wei_jie_dian = []                  # 记录所有座位节点id
        for i, seat in enumerate(seat_positions):
            zuo_wei_id = f'seat_{seat.get("label", i)}'
            nodes[zuo_wei_id] = {
                'x': int(seat['x']),
                'y': int(seat['y']),
                'type': 'seat',
                'name': seat.get('label', ''),
            }
            zuo_wei_jie_dian.append(zuo_wei_id)

        # 按距离连接相邻座位（曼哈顿距离 < 150px 的添加通道节点）
        for i in range(len(zuo_wei_jie_dian)):
            for j in range(i + 1, len(zuo_wei_jie_dian)):
                jie_dian_jia = nodes[zuo_wei_jie_dian[i]]
                jie_dian_yi = nodes[zuo_wei_jie_dian[j]]
                ju_li = abs(jie_dian_jia['x'] - jie_dian_yi['x']) + abs(jie_dian_jia['y'] - jie_dian_yi['y'])
                if ju_li < 150:
                    zhong_jian_id = f'm_{i}_{j}'   # 中间通道节点
                    if zhong_jian_id not in nodes:
                        nodes[zhong_jian_id] = {
                            'x': (jie_dian_jia['x'] + jie_dian_yi['x']) // 2,
                            'y': (jie_dian_jia['y'] + jie_dian_yi['y']) // 2,
                            'type': 'normal',
                            'name': None,
                        }
                    edges.append({'from': zuo_wei_jie_dian[i], 'to': zhong_jian_id})
                    edges.append({'from': zhong_jian_id, 'to': zuo_wei_jie_dian[j]})

        return {
            'nodes': nodes,
            'edges': edges,
            'floor_info': {
                'width': width,
                'height': height,
            }
        }

    def _ti_qu_gu_jia(self, binary_img: np.ndarray) -> np.ndarray:
        """提取二值图像的骨架（可行走区域中心线）"""
        # 优先使用 Zhang-Suen 细化算法，若 ximgproc 不可用则回退到形态学方法
        if self.skeleton_method == 'zhang-suen':
            try:
                gu_jia = cv2.ximgproc.thinning(binary_img, cv2.ximgproc.THINNING_ZHANGSUEN)
                return gu_jia
            except AttributeError:
                # ximgproc 不可用，回退到形态学方法
                pass

        # 形态学骨架提取（备选方案，不依赖 ximgproc）
        gu_jia = np.zeros_like(binary_img)
        lin_shi_tu = binary_img.copy()          # 临时图像，每轮腐蚀后更新
        he_zi = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))

        while True:
            fu_shi_tu = cv2.erode(lin_shi_tu, he_zi)          # 腐蚀：缩小前景
            peng_zhang_tu = cv2.dilate(fu_shi_tu, he_zi)      # 膨胀：还原被缩小的部分
            gu_jia_pian_duan = cv2.subtract(lin_shi_tu, peng_zhang_tu)  # 两者差值即骨架片段
            gu_jia = cv2.bitwise_or(gu_jia, gu_jia_pian_duan)
            lin_shi_tu = fu_shi_tu.copy()
            if cv2.countNonZero(lin_shi_tu) == 0:
                break

        return gu_jia

    def _gu_jia_zhuan_tu(self, skeleton: np.ndarray,
                         min_node_dist: int = 20) -> Tuple[dict, list]:
        """
        将骨架转换为图结构（节点 + 边）

        Returns:
            (nodes_dict, edges_list)
        """
        # 找到所有骨架像素
        ys, xs = np.where(skeleton > 0)
        suo_you_dian = list(zip(xs, ys))

        if not suo_you_dian:
            return {}, []

        # 通过连通组件分析找到交叉点和端点
        # 简化：以一定间隔采样作为节点
        nodes = {}
        edges = []
        jie_dian_bian_hao = 0                  # 节点编号计数器

        # 对骨架进行细化采样
        cai_yang_tu = np.zeros_like(skeleton)  # 采样标记图
        jian_ge = min_node_dist                # 采样间隔（像素）

        for y in range(0, skeleton.shape[0], jian_ge):
            for x in range(0, skeleton.shape[1], jian_ge):
                qu_yu = skeleton[max(0, y - jian_ge // 2):min(skeleton.shape[0], y + jian_ge // 2),
                                 max(0, x - jian_ge // 2):min(skeleton.shape[1], x + jian_ge // 2)]
                if np.any(qu_yu > 0):
                    # 找到区域内的骨架中心
                    ju_bu_y, ju_bu_x = np.where(qu_yu > 0)
                    zhong_xin_x = x - jian_ge // 2 + int(np.mean(ju_bu_x))
                    zhong_xin_y = y - jian_ge // 2 + int(np.mean(ju_bu_y))

                    jie_dian_id = f'n{jie_dian_bian_hao}'
                    nodes[jie_dian_id] = {
                        'x': int(zhong_xin_x),
                        'y': int(zhong_xin_y),
                        'type': 'normal',
                        'name': None,
                    }
                    cai_yang_tu[zhong_xin_y, zhong_xin_x] = 255
                    jie_dian_bian_hao += 1

        # 连接相邻节点（基于距离）
        jie_dian_lie_biao = list(nodes.keys())
        for i in range(len(jie_dian_lie_biao)):
            for j in range(i + 1, len(jie_dian_lie_biao)):
                jie_dian_jia = nodes[jie_dian_lie_biao[i]]
                jie_dian_yi = nodes[jie_dian_lie_biao[j]]
                ju_li = ((jie_dian_jia['x'] - jie_dian_yi['x']) ** 2 + (jie_dian_jia['y'] - jie_dian_yi['y']) ** 2) ** 0.5

                # 距离在合理范围内且路径在骨架内
                if ju_li < jian_ge * 1.5:
                    # 检查两点之间是否有骨架连接
                    if self._you_wu_gu_jia_lu_jing(skeleton, jie_dian_jia['x'], jie_dian_jia['y'], jie_dian_yi['x'], jie_dian_yi['y']):
                        edges.append({'from': jie_dian_lie_biao[i], 'to': jie_dian_lie_biao[j]})

        return nodes, edges

    def _you_wu_gu_jia_lu_jing(self, skeleton: np.ndarray, x1: int, y1: int,
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

    def _lian_jie_zuo_wei(self, nodes: dict, edges: list,
                          seat_positions: List[dict],
                          skeleton: np.ndarray) -> Tuple[dict, list]:
        """将座位节点连接到最近的路网节点"""
        for seat in seat_positions:
            zuo_biao_x, zuo_biao_y = seat['x'], seat['y']
            label = seat.get('label', '')

            # 找到最近的路网节点
            zui_jin_jie_dian = None
            zui_jin_ju_li = float('inf')
            for jie_dian_id, jie_dian_shu_ju in nodes.items():
                ju_li = (jie_dian_shu_ju['x'] - zuo_biao_x) ** 2 + (jie_dian_shu_ju['y'] - zuo_biao_y) ** 2
                if ju_li < zui_jin_ju_li:
                    zui_jin_ju_li = ju_li
                    zui_jin_jie_dian = jie_dian_id

            if zui_jin_jie_dian:
                zuo_wei_jie_dian_id = f'seat_{label}' if label else f'seat_{zuo_biao_x}_{zuo_biao_y}'
                nodes[zuo_wei_jie_dian_id] = {
                    'x': int(zuo_biao_x),
                    'y': int(zuo_biao_y),
                    'type': 'seat',
                    'name': label or None,
                }
                edges.append({'from': zuo_wei_jie_dian_id, 'to': zui_jin_jie_dian})

        return nodes, edges

    def _shi_bie_te_shu_jie_dian(self, nodes: dict,
                                 zeng_qiang_tu: np.ndarray) -> dict:
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

        for tiao_zheng in adjustments:
            if tiao_zheng['type'] == 'move':
                # 拖拽节点
                jie_dian_id = tiao_zheng['node_id']
                if jie_dian_id in nodes:
                    nodes[jie_dian_id]['x'] = tiao_zheng.get('x', nodes[jie_dian_id]['x'])
                    nodes[jie_dian_id]['y'] = tiao_zheng.get('y', nodes[jie_dian_id]['y'])

            elif tiao_zheng['type'] == 'add':
                # 添加节点
                xin_jie_dian_id = f'n{len(nodes)}'
                nodes[xin_jie_dian_id] = {
                    'x': tiao_zheng['x'],
                    'y': tiao_zheng['y'],
                    'type': tiao_zheng.get('type', 'normal'),
                    'name': tiao_zheng.get('name'),
                }
                # 连接到指定的节点
                if tiao_zheng.get('connect'):
                    for lian_jie_jie_dian in tiao_zheng['connect']:
                        edges.append({'from': xin_jie_dian_id, 'to': lian_jie_jie_dian})

            elif tiao_zheng['type'] == 'delete':
                jie_dian_id = tiao_zheng['node_id']
                if jie_dian_id in nodes:
                    del nodes[jie_dian_id]
                    # 删除相关边
                    edges = [e for e in edges
                             if e['from'] != jie_dian_id and e['to'] != jie_dian_id]
                    network['edges'] = edges

            elif tiao_zheng['type'] == 'rename':
                jie_dian_id = tiao_zheng['node_id']
                if jie_dian_id in nodes:
                    nodes[jie_dian_id]['name'] = tiao_zheng.get('name', nodes[jie_dian_id]['name'])

        network['nodes'] = nodes
        network['edges'] = edges
        return network

    def generate_floor_overlay(self, image_path: str, network: dict,
                                 output_path: str):
        """
        生成带路网叠加的预览图（供管理员微调使用）
        无平面图时自动创建空白画布
        """
        lou_ceng_xin_xi = network.get('floor_info', {})
        w = lou_ceng_xin_xi.get('width', 800)
        h = lou_ceng_xin_xi.get('height', 600)

        if image_path and os.path.exists(image_path):
            img = cv2.imread(image_path)
            if img is None:
                img = 255 * np.ones((h, w, 3), dtype=np.uint8)
        else:
            img = 255 * np.ones((h, w, 3), dtype=np.uint8)

        die_jia_tu = img.copy()                # 叠加图层
        nodes = network.get('nodes', {})
        edges = network.get('edges', [])

        # 绘制边
        for edge in edges:
            qi_dian = nodes.get(edge['from'])
            zhong_dian = nodes.get(edge['to'])
            if qi_dian and zhong_dian:
                cv2.line(die_jia_tu, (qi_dian['x'], qi_dian['y']),
                         (zhong_dian['x'], zhong_dian['y']), (0, 255, 0), 2)

        # 绘制节点
        for nid, jie_dian_shu_ju in nodes.items():
            yan_se = (0, 0, 255) if jie_dian_shu_ju.get('type') == 'seat' else (255, 0, 0)
            cv2.circle(die_jia_tu, (jie_dian_shu_ju['x'], jie_dian_shu_ju['y']), 5, yan_se, -1)
            if jie_dian_shu_ju.get('name'):
                cv2.putText(die_jia_tu, jie_dian_shu_ju['name'],
                           (jie_dian_shu_ju['x'] + 8, jie_dian_shu_ju['y'] + 8),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, yan_se, 1)

        # 半透明叠加
        jie_guo = cv2.addWeighted(img, 0.7, die_jia_tu, 0.3, 0)
        cv2.imwrite(output_path, jie_guo)
