"""
路网生成质量诊断（规则判事实，大模型写人话）
============================================

为什么要有这个模块
------------------
「自动生成路网」走的是图片处理链：
`utils/mapget.py` 的 `RoadNetworkGenerator.generate_from_floorplan`：
读图 → 二值化（在 4 个阈值策略里挑一个）→ 形态学去噪 → 提骨架 → 按 20 像素
网格把骨架采样成节点 → 按骨架连通性连边。

这条链在示意图上还能糊弄，在真实 CAD 图上经常给出没法用的结果（实测一张
6600x4474 的一层平面图生成出 4231 个节点、5403 条边），而管理员只能看到
一堆散点，看不出「为什么不好、该改哪里」。本模块把一次生成的结果整理成
**结构化事实**（`collect_facts`），再让大模型把这些事实翻译成人话
（`diagnose`）；模型没配置 / 超时 / 返回空时，用规则拼出一段**同样带真实
数字**的中文，绝不返回空文本。

设计约束（沿用 `utils/ai_service.py` 的做法）
--------------------------------------------
1. **事实归规则**：节点数、边数、孤立比例、骨架占比这些都由本模块算，
   模型不许编。
2. **规则能独立完成诊断**：AI 只负责「翻译成人话」，不是「判断」。所以
   AI 挂了，结论不降级，只是语气不同。
3. **只读**：本模块不改路网、不改图、不落盘，纯计算 + 一次可选的文本生成。
4. **绝不抛异常**：读不到图也要能给出诊断（报 `image_unreadable`），
   因为「图打不开」本身就是管理员最需要知道的那条结论。

实测样本（本机跑出来的，阈值就是照这两个 + 一张干净平面图定的）
--------------------------------------------------------------
* `uploads/plane_room_0276db07.jpg`（1931x791 示意图）：fixed200，白色占
  61.6%，骨架占 0.87%，767 节点 / 877 边，孤立 3.8%。图上带 "PLAN-A"
  文字、浅灰家具块、底部大片黑底 —— 报「节点偏多」「浅灰填充被判成可行走」
  「骨架断头多」三条。
* `library_cad/图书馆一层平面图.png`（6600x4474，真 PNG，路径带中文）：
  生成器先缩到长边 2000 再处理，otsu，白色占 94.5%，骨架占 0.57%，
  1083 节点 / 982 边，孤立 14.8%。整页（图框、标题栏、房间表）都成了可行走
  区，这是节点数压不下来的根因。（同一张图不走下采样、全尺寸生成时是
  4231 节点 / 5403 边——所以本模块必须跟着生成器的尺度算，见 ANALYSIS_MAX_SIDE。）
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from utils.llm import get_llm
from utils.mapget import RoadNetworkGenerator

logger = logging.getLogger(__name__)


# ============================================================== 阈值（集中放置）
# 说明：所有阈值都放这里，方便按实际图源再调。判据一律用「事实字典里的数字」
# 去比，保证 anomalies 与 facts 永远自洽（看到什么数就按什么数判）。

# 一层楼的路网节点通常在几十到几百个；超过这个量级基本可以断定图上的文字、
# 尺寸标注、图框被当成了通道（实测 CAD 图出过 4231 个）。
MAX_REASONABLE_NODES = 1500
MIN_REASONABLE_NODES = 30

# 节点密度：每万像素的节点数。
#
# ⚠ 这个 0.15 是需求里给的原始阈值，照字面用会发现问题：0.15 个/万像素 ≈
# 「每 6.7 万个像素才允许有 1 个节点」，而实测任何真实平面图都远超它
# （本机 1931x791 的示意图 5.02、6600x4474 的 CAD 图 0.37，干净合成的平面图
# 4.27）。也就是说这条判据现在近似等于「只要有路网就算偏多」。这里保持需求给
# 的数值不动，配套两个动作：① message 里把真实密度和阈值一起写出来，让人能
# 自己判断；② 想让它真正有区分度，把这个常量调到 2.0~3.0 即可（一行改动）。
# 注意：调高会改变验收结果——CAD 图现在节点数是 1083（生成器缩到长边 2000 后
# 的产物），低于 1500 的绝对阈值，它的 too_many_nodes 完全靠密度这一条触发。
NODE_DENSITY_LIMIT = 0.15

# 孤立节点（度数为 0）比例上限。超过四分之一的路网是碎片，导航基本不可用。
MAX_ISOLATED_RATIO = 0.25
# 孤立比例高到这个程度就直接算 error：不是「质量差」，是「不能用」。
ISOLATED_RATIO_ERROR = 0.5

# 平均度数下限：连通良好的路网接近 2（链状）到 3（网格状），低于 1.5 说明
# 节点之间没连起来。
MIN_AVG_DEGREE = 1.5

# 骨架像素占整图比例：低于 0.5% 说明几乎没提取到可行走区，高于 25% 说明
# 墙体没被识别出来（几乎整张图都是可行走区）。
MIN_SKELETON_COVERAGE = 0.005
MAX_SKELETON_COVERAGE = 0.25

# 二值化后白色（可行走区）占比的合理区间。平面图里通道+房间面积一般在
# 20%~80%，跑出区间说明这张图不是标准平面图（大片留白 / 满页文字表格）。
WHITE_RATIO_LOW = 0.2
WHITE_RATIO_HIGH = 0.8

# 浅灰填充（家具、地面色块、填充标注）的灰度区间与判定门槛。
# 200 以上是「白」、60 以下算「线/墙」，中间这段既可能是家具也可能是阴影，
# 二值化策略一旦把阈值放在它下面，整块家具就变成了通道。
GRAY_FILL_LOW = 195
GRAY_FILL_HIGH = 250
GRAY_FILL_MIN_AREA = 0.01        # 这类像素不足 1% 时不判（图上本来就没有填充）
GRAY_FILL_WALKABLE = 0.5         # 一半以上被判成可行走才算问题

# 骨架悬空断头（只有 1 个邻居的骨架像素）密度：每千骨架像素几个。
# 干净平面图实测约 4 个/千像素；带文字标注的图实测 28~38 个/千像素。
# 断头的来源是文字、尺寸标注、箭头、噪点被细化后留下的短枝。
MAX_ENDPOINTS_PER_KPX = 10.0

# 分析尺度：跟随生成器的下采样。
#
# `mapget.generate_from_floorplan` 会把长边超过 MAX_DIM(2000) 的图先缩到 2000
# 再二值化提骨架（避免 gunicorn 30 秒超时），最后把节点坐标乘回原尺度。
# 诊断必须用**同一个尺度**去算白色占比和骨架覆盖率，否则报出来的数字跟这次
# 生成用的那张图对不上（实测同一张 6600x4474 的 CAD 图：全尺寸骨架占 0.20%，
# 缩到 2000 长边后是 0.39%）。
# 那边的 MAX_DIM 是函数内的局部常量，本模块又约定「不改现有文件」，所以只能
# 在这里同步一份：**mapget 的 MAX_DIM 改了，这里要跟着改**。
# 是否真的需要缩，看 floor_info 里那个 'downsampled' 标志（新版 mapget 才有）。
ANALYSIS_MAX_SIDE = 2000


# ============================================================== 读图
def _sniff_format(path: str) -> str:
    """按文件头判断真实格式。

    为什么不用扩展名也不用 imghdr：`imghdr` 在 3.13 已被移除；而扩展名恰恰
    不可信——用户上传的图经常是 .png 里装 JPEG/WebP。
    """
    try:
        with open(path, 'rb') as fh:
            head = fh.read(16)
    except OSError:
        return 'unknown'
    if head[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    if head[:2] == b'BM':
        return 'bmp'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if head[:4] in (b'II*\x00', b'MM\x00*'):
        return 'tiff'
    return 'unknown'


def _read_image(path: str) -> Optional[np.ndarray]:
    """按内容解码图片（先 imdecode、失败再退回 cv2.imread）。

    与 `mapget.generate_from_floorplan` 用同一套读法：np.fromfile + imdecode
    让 OpenCV 按内容嗅探解码器，扩展名不可信时不至于整条链断掉。
    """
    img = None
    try:
        buf = np.fromfile(path, dtype=np.uint8)
        if buf.size:
            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:                       # noqa: BLE001 - 读图失败不该炸诊断
        img = None
    if img is not None:
        return img
    try:
        return cv2.imread(path)
    except Exception:                       # noqa: BLE001
        return None


def _readable_by_path(path: str) -> bool:
    """能不能「按路径」直接读到图（即 cv2.imread 那条路通不通）。

    用 `cv2.haveImageReader` 探：它只读文件头，不像 imread 那样整图解码。
    这条线索值钱是因为 `mapget.generate_floor_overlay`（后台的叠加预览图）
    用的就是 cv2.imread —— 在 Windows 上 imread 打不开**非 ASCII 路径**
    （实测 `library_cad\\图书馆一层平面图.png` 直接返回 None），于是一张好图
    的预览会静默退化成空白画布。
    """
    try:
        if hasattr(cv2, 'haveImageReader'):
            return bool(cv2.haveImageReader(path))
        return cv2.imread(path) is not None
    except Exception:                       # noqa: BLE001
        return False


def _file_size_kb(path: str) -> int:
    try:
        return int(round(os.path.getsize(path) / 1024))
    except OSError:
        return 0


# ============================================================== 二值化 / 骨架
def _pick_binary(gray: np.ndarray) -> Tuple[str, np.ndarray, float]:
    """复刻 `mapget.generate_from_floorplan` 挑二值化策略的那段逻辑。

    为什么在这里重写一遍而不是从 mapget 调：那段挑选逻辑是写在生成函数体里
    的内联代码，没有独立函数可调；本模块又约定「只读、不改现有文件」。所以
    这里逐行照抄，并在上面注明出处——以后 mapget 改了策略集，这里要同步。

    Returns:
        (策略名, 二值图, 白色占比)
    """
    height, width = gray.shape[:2]
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

    strategies: List[Tuple[str, np.ndarray]] = []
    _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    strategies.append(('otsu', otsu))
    _, fixed200 = cv2.threshold(enhanced, 200, 255, cv2.THRESH_BINARY)
    strategies.append(('fixed200', fixed200))
    _, fixed128 = cv2.threshold(enhanced, 128, 255, cv2.THRESH_BINARY)
    strategies.append(('fixed128', fixed128))
    _, otsu_inv = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    strategies.append(('otsu_inv', otsu_inv))

    # 与 mapget 一致：白色占比越接近 50% 越好，且必须在 15%~85% 之间。
    best_name, best_binary, best_score = 'otsu', strategies[0][1], float('inf')
    total = float(width * height) or 1.0
    for name, bw in strategies:
        white_ratio = cv2.countNonZero(bw) / total
        score = abs(white_ratio - 0.5)
        if score < best_score and 0.15 < white_ratio < 0.85:
            best_score, best_name, best_binary = score, name, bw

    white_ratio = cv2.countNonZero(best_binary) / total
    return best_name, best_binary, white_ratio


def _clean_binary(binary: np.ndarray) -> np.ndarray:
    """与 mapget 相同的形态学去噪（先闭后开）。"""
    kernel = np.ones((3, 3), np.uint8)
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    return cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)


def _extract_skeleton(binary: np.ndarray) -> np.ndarray:
    """取骨架。

    直接复用 `RoadNetworkGenerator._extract_skeleton`，而不是自己写一份：
    骨架算法一旦和生成时用的不一致（ximgproc 有没有装、走 zhang-suen 还是
    形态学），骨架像素数和覆盖率就跟这次生成对不上，诊断也就失去意义了。
    """
    try:
        return RoadNetworkGenerator()._extract_skeleton(binary)
    except Exception:                       # noqa: BLE001 - 骨架失败不该炸诊断
        logger.warning('骨架提取失败，骨架相关事实将记为 0', exc_info=True)
        return np.zeros_like(binary)


def _skeleton_topology(skeleton: np.ndarray) -> Tuple[int, int, float]:
    """统计骨架的悬空断头数与碎段数。

    Returns:
        (端点数, 连通段数, 每千骨架像素的端点数)

    为什么要这两项：断头（8 邻域里只有 1 个骨架邻居的像素）就是短枝的尽头。
    干净平面图实测约 4 个/千像素；带文字标注的图里，文字笔画被细化后留下的
    短线两端都是断头，实测能到 18~29 个/千像素。它是「文字/标注/噪点被当成
    通道」的可计算代理指标——直接找文字块做不到，因为字形经常和墙线连成
    一整块（实测一张图上 4 个字母只有 2 个能被当独立块分离出来）。
    """
    on = (skeleton > 0).astype(np.uint8)
    total = int(on.sum())
    if not total:
        return 0, 0, 0.0
    neighbor_kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.uint8)
    neighbors = cv2.filter2D(on, -1, neighbor_kernel, borderType=cv2.BORDER_CONSTANT)
    endpoints = int(((neighbors == 1) & (on > 0)).sum())
    _, _, stats, _ = cv2.connectedComponentsWithStats(on, connectivity=8)
    components = max(int(stats.shape[0]) - 1, 0)
    return endpoints, components, round(endpoints / total * 1000.0, 1)


# ============================================================== 路网统计
def _node_ids(nodes: Any) -> List[str]:
    """兼容 {id: {...}} 与 [{id:..., x:...}, ...] 两种存法。"""
    if isinstance(nodes, dict):
        return [str(k) for k in nodes.keys()]
    if isinstance(nodes, (list, tuple)):
        ids = []
        for index, node in enumerate(nodes):
            if isinstance(node, dict):
                ids.append(str(node.get('id', node.get('node_id', index))))
            else:
                ids.append(str(index))
        return ids
    return []


def _network_stats(network: Dict[str, Any], width: int, height: int) -> Dict[str, Any]:
    """把 network 压成几个判断用的数字。

    度数按无向图算：生成器连边时 `_has_skeleton_path` 是对称判断，A→B 通则
    B→A 也通，所以一条边给两端各加 1。
    """
    nodes = (network or {}).get('nodes') or {}
    edges = (network or {}).get('edges') or []
    ids = _node_ids(nodes)

    degree: Dict[str, int] = {node_id: 0 for node_id in ids}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for key in ('from', 'to'):
            end = edge.get(key)
            if isinstance(end, str) and end in degree:
                degree[end] += 1

    node_count = len(ids)
    edge_count = len(edges)
    isolated = sum(1 for value in degree.values() if value == 0)
    pixels = float(width * height) or 0.0

    return {
        'node_count': node_count,
        'edge_count': edge_count,
        'avg_degree': round(sum(degree.values()) / node_count, 3) if node_count else 0.0,
        'isolated': isolated,
        'isolated_ratio': round(isolated / node_count, 4) if node_count else 0.0,
        # 每万像素多少节点（分母用图像尺寸；读不到图时退回 floor_info）
        'node_density': round(node_count / pixels * 10000.0, 3) if pixels else 0.0,
    }


def _count_unlinked_seat_nodes(network: Dict[str, Any]) -> int:
    """数一下「座位节点里有几个没连到任何通道」。"""
    nodes = (network or {}).get('nodes') or {}
    if not isinstance(nodes, dict):
        return 0
    linked = set()
    for edge in ((network or {}).get('edges') or []):
        if isinstance(edge, dict):
            for key in ('from', 'to'):
                end = edge.get(key)
                if isinstance(end, str):
                    linked.add(end)
    return sum(
        1 for node_id, node in nodes.items()
        if isinstance(node, dict) and node.get('type') == 'seat' and node_id not in linked
    )


# ============================================================== 异常规则
def _anomaly(code: str, level: str, message: str, suggestion: str) -> Dict[str, str]:
    return {'code': code, 'level': level, 'message': message, 'suggestion': suggestion}


def _detect_anomalies(facts: Dict[str, Any], seats: Optional[list]) -> List[Dict[str, str]]:
    """把事实字典过一遍规则，返回异常列表（顺序 = 建议的展示顺序）。

    顺序规则：先「路网还能不能用」，再「数字异常」，最后「图上细节」。
    兜底文案会拿第一条当主要问题，所以最要紧的排在前面。
    """
    image = facts['image']
    binary = facts['binary']
    skeleton = facts['skeleton']
    network = facts['network']

    node_count = network['node_count']
    edge_count = network['edge_count']
    avg_degree = network['avg_degree']
    isolated = network['isolated']
    isolated_ratio = network['isolated_ratio']
    node_density = network['node_density']
    coverage = skeleton['coverage']
    white_ratio = binary['white_ratio']
    # 图没读到时 binary/skeleton 都是占位 0，拿它们判会得出「白色占 0%」
    # 「骨架占 0%」这种假问题 —— 一条 image_unreadable 就够了。
    image_ok = bool(facts.get('_image_ok'))

    result: List[Dict[str, str]] = []

    # ---------------------------------------------------------- 读图失败
    if not image_ok:
        result.append(_anomaly(
            'image_unreadable', 'error',
            f'这张图打不开（{image["file_size_kb"]} KB，按内容嗅探也解不出图像）：'
            f'文件可能已损坏，或者根本不是图片。',
            '重新从 CAD/绘图软件导出一次再上传；另存时选标准 PNG 或 JPEG，不要直接改扩展名。',
        ))

    # ---------------------------------------------------------- 数量级
    if node_count < MIN_REASONABLE_NODES:
        result.append(_anomaly(
            'too_few_nodes', 'error',
            f'只生成 {node_count} 个节点（正常一层楼是几十到几百个，下限取 {MIN_REASONABLE_NODES}）：'
            f'整张图几乎没提取到可行走区。',
            '检查图片是不是纯色、过暗、或只剩线框（没有封闭空间）；'
            '换一张对比度正常、墙体清晰的平面图再试。',
        ))

    if node_count > MAX_REASONABLE_NODES or node_density > NODE_DENSITY_LIMIT:
        # 只陈述事实与判据，不替用户下「密得多」这种结论：密度判据本身很敏感
        # （见 NODE_DENSITY_LIMIT 处的说明），把数字摊开让人自己判断更可靠。
        reason = (
            f'节点数 {node_count} 个，超过一层楼正常的几十到几百个'
            if node_count > MAX_REASONABLE_NODES else
            f'节点数 {node_count} 个、密度 {node_density:.2f} 个/万像素'
            f'（判据上限 {NODE_DENSITY_LIMIT}）'
        )
        result.append(_anomaly(
            'too_many_nodes', 'warn',
            f'{reason}；通常意味着图上的文字、尺寸标注、图框或标题栏被当成了通道。',
            '生成前把图裁到建筑轮廓内（去掉图框、标题栏、房间名称表、尺寸标注），'
            '只留墙体与门的线稿；仍偏多就改用 DXF 走矢量路网。',
        ))

    # ---------------------------------------------------------- 连通性
    if isolated_ratio > MAX_ISOLATED_RATIO:
        result.append(_anomaly(
            'high_isolation', 'error' if isolated_ratio > ISOLATED_RATIO_ERROR else 'warn',
            f'孤立节点 {isolated} 个，占 {isolated_ratio:.1%}（上限 {MAX_ISOLATED_RATIO:.0%}）：'
            f'{edge_count} 条边连不起这些点，路网是碎的，路径规划走到这些点上就会失败。',
            '碎片化多来自骨架断裂，建议改用手工绘制，或提供 DXF 让路网走矢量而不是像素骨架。',
        ))

    if avg_degree < MIN_AVG_DEGREE and node_count >= MIN_REASONABLE_NODES:
        result.append(_anomaly(
            'low_degree', 'warn',
            f'平均每个节点只有 {avg_degree:.2f} 条边（低于 {MIN_AVG_DEGREE}）：节点之间基本没连起来。',
            '在这张图上手工补几条主通道节点，或换一张墙体连续、断口少的图重新生成。',
        ))

    # ---------------------------------------------------------- 骨架密度
    if image_ok and 0 < coverage < MIN_SKELETON_COVERAGE:
        result.append(_anomaly(
            'low_skeleton', 'warn',
            f'骨架只占画面 {coverage:.2%}（下限 {MIN_SKELETON_COVERAGE:.1%}）：'
            f'要么二值化把可用区域判成了墙，要么反过来几乎整页都是白色、'
            f'骨架被稀释成稀疏的细线（本次白色占 {white_ratio:.1%}）。',
            '先裁到建筑轮廓内再生成；若整页确实大面积留白，说明它不是标准平面图。',
        ))
    elif image_ok and coverage > MAX_SKELETON_COVERAGE:
        result.append(_anomaly(
            'high_skeleton', 'warn',
            f'骨架占画面 {coverage:.1%}（上限 {MAX_SKELETON_COVERAGE:.0%}）：'
            f'几乎整张图都被当成可行走区，墙体没被识别出来。',
            '检查原图墙体是否清晰、二值化是否把墙也判成了白色；换成黑墙白底的线稿再生成。',
        ))

    # ---------------------------------------------------------- 二值化合理性
    if image_ok and (white_ratio < WHITE_RATIO_LOW or white_ratio > WHITE_RATIO_HIGH):
        result.append(_anomaly(
            'binary_ratio_extreme', 'warn',
            f'二值化后白色（可行走区）占 {white_ratio:.1%}，跑出 '
            f'{WHITE_RATIO_LOW:.0%}~{WHITE_RATIO_HIGH:.0%} 的合理区间'
            f'（采用的是 {binary["strategy"]} 策略）：这张图可能不是标准平面图，'
            f'标题栏、表格、大面积留白都会被当成空间。',
            '裁剪掉图框外的留白与标题栏区域，或改用只含建筑主体的二值线稿。',
        ))

    # ---------------------------------------------------------- 图上细节（本项目实测踩过的坑）
    gray_fill = facts.get('_gray_fill') or {}
    if (image_ok
            and gray_fill.get('area_ratio', 0.0) >= GRAY_FILL_MIN_AREA
            and gray_fill.get('walkable_ratio', 0.0) >= GRAY_FILL_WALKABLE):
        result.append(_anomaly(
            'gray_fill_walkable', 'warn',
            f'有 {gray_fill["area_ratio"]:.1%} 的像素是浅灰填充（家具、地面色块或填充标注），'
            f'其中 {gray_fill["walkable_ratio"]:.0%} 被判成了可行走区，'
            f'骨架有 {gray_fill["skeleton_on_ratio"]:.1%} 直接压在它们上面。',
            '灰阶填充块多半是家具/讲台而不是通道；生成前把它们去掉或提高白色阈值，否则路径会穿家具。',
        ))

    endpoints = int((facts.get('_topology') or {}).get('endpoints', 0))
    per_kpx = float((facts.get('_topology') or {}).get('endpoints_per_kpx', 0.0))
    fragments = int((facts.get('_topology') or {}).get('fragments', 0))
    if image_ok and per_kpx > MAX_ENDPOINTS_PER_KPX:
        result.append(_anomaly(
            'spur_skeleton', 'warn',
            f'骨架上有 {endpoints} 个悬空断头（每千骨架像素 {per_kpx:.1f} 个，'
            f'干净平面图通常不到 5 个），骨架被碎成 {fragments} 段：'
            f'图上的文字、尺寸标注、箭头或噪点被细化成了短线。',
            '文字标注也会变成"通道"；生成前抹掉文字标注区（或只导出墙体/门图层），'
            '生成后在后台删掉这些短枝节点。',
        ))

    unlinked_seats = _count_unlinked_seat_nodes(facts.get('_network_raw') or {})
    if seats and unlinked_seats:
        result.append(_anomaly(
            'unlinked_seats', 'warn',
            f'有 {unlinked_seats} 个座位节点没连到任何通道（离最近节点超过 400 像素），导航到不了这些座位。',
            '检查这些座位的坐标是不是标到墙外或别的楼层图上了，重新标点后再生成。',
        ))

    read_hint = facts.get('_read_hint') or {}
    if read_hint.get('imread_failed'):
        result.append(_anomaly(
            'imread_fallback', 'warn',
            f'cv2.imread 打不开这张图（本次靠 np.fromfile + cv2.imdecode 才读到；'
            f'实际格式 {read_hint.get("real_format")}、扩展名 {read_hint.get("extension")}）：'
            f'实测环境中 imread 对任何格式都可能失败（失败在「按路径打开文件」这一步，'
            f'不在解码 —— PNG/JPEG 解码器确实编译进去了），也可能是路径含非 ASCII '
            f'字符或扩展名与内容不符。后台用它生成叠加预览图时会读不到，退化成空白画布。',
            '统一改成按文件内容解码（np.fromfile + cv2.imdecode）即可 —— '
            '本项目的路网生成已经这么做了。',
        ))

    return result


# ============================================================== 收集事实
def collect_facts(image_path: str, network: dict, seats: list = None,
                  max_analysis_side: Optional[int] = None) -> dict:
    """收集诊断事实。不调模型，纯计算。

    Args:
        image_path: 生成时用的平面图路径。
        network: `generate_from_floorplan` 的返回值 {nodes, edges, floor_info}。
        seats: 可选，预标注的座位位置；用来判「座位有没有连上路网」。
        max_analysis_side: 可选，强制把二值化/骨架的重算限制在长边不超过这么多像素的图上。
            **默认 None = 自动**：生成器把图缩过了（floor_info['downsampled'] 为真）
            就跟着缩到 `ANALYSIS_MAX_SIDE`，没缩就按全尺寸算——只有跟生成器同尺度，
            报出来的白色占比和骨架覆盖率才是「这次生成真正用的那张图」的数字。
            手工传更小的值能再省点时间，但细线会在缩放里消失/变粗，数字就不再对得上。

    Returns:
        {
          'image': {'width', 'height', 'file_size_kb', 'format'},
          'binary': {'strategy', 'white_ratio'},          # 二值化选了哪个策略、白色占比
          'skeleton': {'pixel_count', 'coverage'},        # 骨架像素数与占图比例
          'network': {'node_count', 'edge_count', 'avg_degree',
                      'isolated', 'isolated_ratio', 'node_density'},
          'anomalies': [{'code', 'level', 'message', 'suggestion'}, ...],
        }

    绝不抛异常：读不到图时 image 的宽高为 0，骨架/密度记 0，并报 image_unreadable。
    """
    network = network if isinstance(network, dict) else {}
    started = time.time()

    # ---------------------------------------------------------- 1. 读图
    image_path = str(image_path or '')
    img = _read_image(image_path) if image_path else None
    # 单独探一次「按路径能不能读到」：只读文件头，成本可忽略，但能暴露
    # 非 ASCII 路径 / 扩展名与实际内容不符这类会让预览图变空白的问题。
    readable_by_path = _readable_by_path(image_path) if image_path else False

    floor_info = network.get('floor_info') or {}
    if img is not None:
        height, width = img.shape[:2]
    else:
        width = int(floor_info.get('width') or 0)
        height = int(floor_info.get('height') or 0)

    real_format = _sniff_format(image_path) if image_path else 'unknown'
    image_facts = {
        'width': int(width),
        'height': int(height),
        'file_size_kb': _file_size_kb(image_path) if image_path else 0,
        'format': real_format,
    }

    # ---------------------------------------------------------- 2. 二值化 / 骨架
    binary_facts: Dict[str, Any] = {'strategy': 'unknown', 'white_ratio': 0.0}
    skeleton_facts: Dict[str, Any] = {'pixel_count': 0, 'coverage': 0.0}
    gray_fill: Dict[str, float] = {}
    topology: Dict[str, float] = {}

    if img is not None:
        try:
            # 在「生成器实际用的那个尺度」上重算二值化与骨架，见 ANALYSIS_MAX_SIDE。
            analysis_side = _analysis_side(floor_info, max_analysis_side)
            gray_for_facts = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if analysis_side and max(gray_for_facts.shape[:2]) > analysis_side:
                gray_for_facts = _downscale(gray_for_facts, analysis_side)

            strategy, binary, white_ratio = _pick_binary(gray_for_facts)
            cleaned = _clean_binary(binary)
            skeleton = _extract_skeleton(cleaned)
            pixel_count = int(cv2.countNonZero(skeleton))
            pixels = float(gray_for_facts.shape[0] * gray_for_facts.shape[1]) or 1.0

            binary_facts = {'strategy': strategy, 'white_ratio': round(white_ratio, 4)}
            skeleton_facts = {
                'pixel_count': pixel_count,
                'coverage': round(pixel_count / pixels, 5),
            }
            gray_fill = _gray_fill_facts(gray_for_facts, cleaned, skeleton)
            endpoints, fragments, per_kpx = _skeleton_topology(skeleton)
            topology = {'endpoints': endpoints, 'fragments': fragments,
                        'endpoints_per_kpx': per_kpx}
        except Exception:                   # noqa: BLE001 - 诊断本身绝不能把主流程搞挂
            logger.warning('图像分析失败，二值化/骨架事实降级为 0', exc_info=True)

    # ---------------------------------------------------------- 3. 路网统计
    network_facts = _network_stats(network, image_facts['width'], image_facts['height'])

    # ---------------------------------------------------------- 4. 规则判定
    facts: Dict[str, Any] = {
        'image': image_facts,
        'binary': binary_facts,
        'skeleton': skeleton_facts,
        'network': network_facts,
        'anomalies': [],
    }
    # 判据要用的中间量挂在带下划线的键上，算完就删：对外只暴露上面五段，
    # 这样返回值形状与约定完全一致（多一段都算改契约）。
    facts['_gray_fill'] = gray_fill
    facts['_topology'] = topology
    facts['_network_raw'] = network
    facts['_image_ok'] = img is not None
    facts['_read_hint'] = {
        'imread_failed': img is not None and not readable_by_path,
        'real_format': real_format,
        'extension': (os.path.splitext(image_path)[1].lower()
                      if image_path else ''),
    }
    facts['anomalies'] = _detect_anomalies(facts, seats)

    for key in [k for k in facts if k.startswith('_')]:
        facts.pop(key)

    logger.debug('路网诊断事实收集完成：%d 个异常，耗时 %.2fs',
                 len(facts['anomalies']), time.time() - started)
    return facts


def _downscale(gray: np.ndarray, max_side: int) -> np.ndarray:
    """等比缩到长边不超过 max_side。"""
    height, width = gray.shape[:2]
    scale = float(max_side) / float(max(height, width))
    return cv2.resize(gray, (max(1, int(width * scale)), max(1, int(height * scale))),
                      interpolation=cv2.INTER_AREA)


def _analysis_side(floor_info: Dict[str, Any],
                   max_analysis_side: Optional[int]) -> Optional[int]:
    """决定用哪个尺度重算二值化/骨架（None = 全尺寸）。

    优先级：
      1. 调用方显式指定 `max_analysis_side` —— 想用速度换精度时自己定。
      2. `floor_info['downsampled']` 为真 —— 生成器把图缩过了，诊断跟着缩，
         这样白色占比/骨架覆盖率才是这次生成真正用的数字。
      3. 其余情况（含老版 mapget 没有这个键）—— 生成器没缩，全尺寸算。
    """
    if max_analysis_side:
        return int(max_analysis_side)
    if (floor_info or {}).get('downsampled'):
        return ANALYSIS_MAX_SIDE
    return None


def _gray_fill_facts(gray: np.ndarray, walkable: np.ndarray,
                     skeleton: np.ndarray) -> Dict[str, float]:
    """量「浅灰填充」：这类像素有多少、多少被判成可行走、骨架压了多少在上面。

    为什么要单独量它：平面图里的家具、讲台、地面色块常画成浅灰（200 上下），
    二值化阈值一旦落在它下面，整块家具就变成通道，路径直接穿家具——这是实测
    最典型的「骨架跑进家具里」。
    """
    band = ((gray >= GRAY_FILL_LOW) & (gray < GRAY_FILL_HIGH))
    area = int(band.sum())
    pixels = float(gray.shape[0] * gray.shape[1]) or 1.0
    if not area:
        return {'area_ratio': 0.0, 'walkable_ratio': 0.0, 'skeleton_on_ratio': 0.0}

    walkable_ratio = float(np.count_nonzero(walkable[band])) / float(area)
    # 骨架是 1 像素宽的线，膨胀一次做 1 像素容差再统计覆盖率
    band_dilated = cv2.dilate(band.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1)
    skeleton_total = int(np.count_nonzero(skeleton)) or 1
    on_ratio = float(np.count_nonzero(skeleton[band_dilated > 0])) / float(skeleton_total)
    return {
        'area_ratio': round(area / pixels, 4),
        'walkable_ratio': round(walkable_ratio, 4),
        'skeleton_on_ratio': round(on_ratio, 4),
    }


# ============================================================== 文案：规则兜底
def _fallback_text(facts: Dict[str, Any]) -> str:
    """无 AI 时的人话诊断（纯规则拼装，必带真实数字）。

    结构：一段总览数字 → 主要问题 → 最多两条次要问题 → 建议。
    与 `ai_service._fallback_admin_report` 的思路一致：宁可说细一点，
    也不要让管理员看到一句「生成异常，请重试」。
    """
    image = facts.get('image') or {}
    binary = facts.get('binary') or {}
    skeleton = facts.get('skeleton') or {}
    network = facts.get('network') or {}
    anomalies = facts.get('anomalies') or []

    iso_ratio = float(network.get('isolated_ratio') or 0.0)
    coverage = float(skeleton.get('coverage') or 0.0)
    white = float(binary.get('white_ratio') or 0.0)

    head = (
        f'本次生成 {network.get("node_count", 0)} 个节点、'
        f'{network.get("edge_count", 0)} 条边，'
        f'孤立节点 {network.get("isolated", 0)} 个（占 {iso_ratio:.1%}），'
        f'平均每个节点 {float(network.get("avg_degree") or 0.0):.2f} 条边，'
        f'骨架占画面 {coverage:.2%}'
        f'（图 {image.get("width", 0)}x{image.get("height", 0)}，'
        f'二值化用 {binary.get("strategy", "unknown")}，'
        f'白色占 {white:.1%}）。'
    )

    if not anomalies:
        return head + (
            '这些指标都在合理区间，本次没发现明显的生成缺陷。'
            '如果看结构仍然不对，多半是纯骨架法的固有局限——它不知道哪里是走廊，'
            '房间中央会画出三角形或星形枝杈，需要在后台手工删掉多余节点。'
        )

    main = anomalies[0]
    text = head + f'发现 {len(anomalies)} 处异常。主要问题：{main["message"]}'
    rest = anomalies[1:]
    if rest:
        # 次要问题最多带两条，再多就把正文淹了（明细在 facts['anomalies'] 里）
        text += '另外，' + ''.join(item['message'] for item in rest[:2])
        if len(rest) > 2:
            text += f'（另有 {len(rest) - 2} 处问题，见下方异常清单。）'
    text += f'建议：{main["suggestion"]}'
    return text


# ============================================================== 文案：大模型
_SYSTEM_PROMPT = (
    '你是室内平面图「自动生成路网」的诊断助手。'
    '用户把一张平面图交给图片处理链（二值化 → 骨架 → 采样成节点 → 按骨架连通性连边）'
    '转成了路网，你要说明这次生成得怎么样、主要问题是什么、该怎么调整。\n'
    '严格要求：\n'
    '1. 只能依据给定的事实数据与异常列表，不要编造没给的数字或结论。\n'
    '2. 用 2~4 句中文说清：生成得怎么样、主要问题、建议怎么改。不要分点、不要罗列 JSON。\n'
    '3. 异常列表里 code 的含义：too_many_nodes/too_few_nodes 是节点数异常，'
    'high_isolation/low_degree 是连边失败，low_skeleton/high_skeleton 是骨架太稀或太密，'
    'binary_ratio_extreme 是二值化白色占比极端，gray_fill_walkable 是家具/填充块被当成通道，'
    'spur_skeleton 是文字标注被细化成短线，imread_fallback 是这张图连普通读图接口都读不到。\n'
    '4. 若异常为空，就说明指标正常，并指出纯骨架法的固有局限（房间中央的星形/三角形枝杈）。\n'
    '5. 不要承诺「重新生成就会好」，给具体动作：裁剪图框、去文字标注、换二值线稿、'
    '手工修正、或改用 DXF 走矢量路网。'
)


def _build_messages(facts: Dict[str, Any]) -> List[Dict[str, str]]:
    """拼提示词：系统约束 + 事实数据（含 anomalies）+ 任务。"""
    payload = json.dumps(facts, ensure_ascii=False, separators=(',', ':'))
    return [
        {'role': 'system', 'content': _SYSTEM_PROMPT},
        {'role': 'user', 'content': (
            f'【事实数据】{payload}\n\n'
            '【任务】用 2~4 句中文说清这张图的生成质量：指标怎么样、主要问题是什么、建议怎么改。'
        )},
    ]


def _ai_text(facts: Dict[str, Any]) -> Optional[str]:
    """让模型写诊断；任何失败都返回 None（由调用方降级）。"""
    try:
        client = get_llm()
        text = client.chat(
            _build_messages(facts),
            max_tokens=400,          # 2~4 句中文远用不到 400，封顶只为控成本
            temperature=0.3,         # 诊断要稳定，不要发挥
        )
    except Exception:                # noqa: BLE001 - 模型层异常一律降级
        logger.warning('路网诊断的模型调用失败，降级为规则文案', exc_info=True)
        return None
    if not text or not str(text).strip():
        return None
    return str(text).strip()


# ============================================================== 对外主接口
def diagnose(image_path: str, network: dict, seats: list = None,
             use_ai: bool = True, max_analysis_side: Optional[int] = None) -> dict:
    """生成诊断报告。

    Args:
        image_path: 平面图路径。
        network: `generate_from_floorplan` 的返回值。
        seats: 可选，预标注的座位位置。
        use_ai: 是否允许调用大模型（False 则只走规则）。
        max_analysis_side: 见 `collect_facts`。

    Returns:
        {
          'facts': {...},        # collect_facts 的结果
          'text': str,           # 人话诊断（AI 写的，或规则拼的）
          'ai_generated': bool,  # True=模型写的，False=规则兜底
          'anomaly_count': int,
        }
    """
    facts = collect_facts(image_path, network, seats,
                          max_analysis_side=max_analysis_side)

    text = _ai_text(facts) if use_ai else None
    ai_generated = bool(text)
    if not text:
        text = _fallback_text(facts)

    return {
        'facts': facts,
        'text': text,
        'ai_generated': ai_generated,
        'anomaly_count': len(facts.get('anomalies') or []),
    }
