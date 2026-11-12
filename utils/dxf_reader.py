"""DXF 图纸 -> 路网 + 座位候选

为什么要另开一条链路
--------------------
图片链路（``utils/mapget.py`` 的 ``RoadNetworkGenerator``）要先二值化、再细化
骨架去「猜」哪块能走。真实 CAD 图上它丢掉了图层语义：实测同一张图书馆平面图，
图片链路出 4243 个节点、孤立 31%，因为墙、家具、标注的线在灰度图里一模一样。

DXF 是结构化数据：墙在 ``A-WALL``、椅子在 ``A-FURN``、房间名在 ``A-TEXT``，
读出来就是答案，不用猜。

本模块只做三件事
----------------
1. 认图层：先按名字关键词模糊匹配，匹配不上再按几何特征兜底；
2. 建路网：墙栅格化成黑白图 -> 反色得可行走区 -> **复用** ``RoadNetworkGenerator``
   的 ``_extract_skeleton`` / ``_skeleton_to_graph``（不重写骨架算法）；
3. 出候选：家具图层里抠小方块当座位，文字图层里配对房间，给座位编号。

不做的事：不碰数据库、不改任何既有模块；除可选的 ``render_preview()`` 外不写文件。
"""
import logging
import math
import os
import re

import cv2
import numpy as np

from utils.mapget import RoadNetworkGenerator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 角色 -> 图层名关键词（全部按小写匹配）。**元组顺序即优先级**：
# 填充/窗/门/楼梯/柱在前，家具、文字居中，墙垫底 —— 否则 "A-WALL-FILL" 会被
# "wall" 先抢走，把墙体填充层当成墙线层，后面按「墙」统计长度就全错。
_ROLE_KEYWORDS = (
    ('wall_fill', ('fill', '填充', 'hatch', '剖面', '斜线')),
    ('window', ('wind', 'window', '窗')),
    ('door', ('door', '门')),
    ('stair', ('stair', '楼梯', '阶梯', '梯段', 'step')),
    ('column', ('column', 'col', '柱')),
    ('furniture', ('furn', 'chair', 'seat', '家具', '桌椅', '椅')),
    ('text', ('text', 'txt', '文字', '标注', '注记', 'room')),
    ('wall', ('wall', '墙')),
)

# 契约要求的五个角色（返回的 roles / guess 里一定有这五个键）
ROLES = ('wall', 'furniture', 'text', 'door', 'stair')
# 额外识别的三个角色：它们在建路网时同样是障碍物，只是契约里没点名。
# 单独列出来是为了让调用方能看见「窗洞被封住了」这件事，而不是藏在实现里。
EXTRA_ROLES = ('wall_fill', 'window', 'column')

# 座位候选：长宽都在 300~900mm、长宽比不超过 2 的闭合方块。
# 样本图里椅子是 450x450mm，书架/桌台是 1200x450 以上的长条，靠这个尺寸区间能分开。
SEAT_SIDE_MIN_MM = 300.0
SEAT_SIDE_MAX_MM = 900.0
SEAT_ASPECT_MAX = 2.0
SEAT_DEDUP_MM = 200.0
# 尺寸区间放宽 1mm：CAD 坐标是浮点数，900x900 的方块算出来可能是 900.0000001
# （实测被 0.9m-0.8m 的偏移量顶出去过），卡死不放过会把正好 900mm 的椅子漏掉。
SEAT_SIDE_EPS_MM = 1.0

# 房间名与「编号 + 面积」的配对阈值（毫米）。第一轮严格，第二轮放宽。
ROOM_PAIR_DY_MM = 1000.0
ROOM_PAIR_DX_MM = 500.0
ROOM_PAIR_FAR_MM = 3000.0
# 座位归属房间的最大距离：房间名写在房间中心，321.6 ㎡ 的大厅最远角落约 12.6 m，
# 取 25 m 足够覆盖，同时能挡住「整层只有一个房间名」时把全楼座位都算进去。
SEAT_ROOM_MAX_MM = 25000.0

# 骨架采样步长（像素）。mapget 默认 20，实测 20 步长孤点 15.6%，16 步长 6.2%、
# 节点从 635 涨到 817（仍是几百量级），所以这里取 16。
NODE_STEP_PX = 16
# 孤点补连的搜索半径 = 步长 * 该系数
LINK_SEARCH_FACTOR = 3

# 可行走连通域的最小面积（像素）。小于它的多是墙缝、图框角落的碎块。
MIN_WALK_AREA_PX = 1500
# 画布上限：超过就降采样，避免一张 1:1 的超大图把骨架算法拖到分钟级。
MAX_CANVAS_PX = 4000

# 单位换算：$INSUNITS -> 一单位等于多少毫米。0/缺省按坐标量级猜。
_UNIT_TO_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}
# 平面图跨度小于这个值，说明不是毫米制（一栋楼不可能只有 3 米）。
MIN_PLAN_SPAN_MM = 3000.0

_ROOM_CODE_RE = re.compile(r'^\s*([A-Za-z]{1,3}[-\s_]?\d{1,4}|\d{3,4})(?![0-9])')
_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_AREA_RE = re.compile(r'(㎡|m2|m²|M2|平米|平方米)')


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _iter_entities(container, depth=0):
    """遍历容器里的图元，把块参照（INSERT）就地展开。

    真实学校的 CAD 图里，椅子、门窗基本都做成块再插入。不展开的话，一层楼
    40 把椅子在模型空间里只是 1 个 INSERT，家具图层看上去空空如也，座位一个
    也认不出来。展开出来的图元若落在 0 层，按块参照自己的图层算 —— 这是 CAD
    的「随层」约定。
    """
    for e in container:
        try:
            etype = e.dxftype()
        except Exception:
            continue
        if etype == 'INSERT' and depth < 2:
            try:
                ins_layer = e.dxf.layer
                children = list(e.virtual_entities())
            except Exception:
                # 块定义损坏或引用了不存在的块，当作普通图元处理，不中断整张图
                yield e.dxf.layer, e
                continue
            for lay, ve in _iter_entities(children, depth + 1):
                if lay in ('0', '', None):
                    lay = ins_layer
                yield lay, ve
            continue
        yield getattr(e.dxf, 'layer', '0'), e


def _match_role(layer_name):
    """图层名 -> 角色。匹配不到返回 None。"""
    name = (layer_name or '').strip().lower()
    if not name:
        return None
    for role, words in _ROLE_KEYWORDS:
        for w in words:
            if w in name:
                return role
    return None


def _entity_points(e):
    """取图元的平面坐标点（毫米），用于求包围盒。取不到返回 []。"""
    try:
        t = e.dxftype()
        if t == 'LINE':
            return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        if t == 'LWPOLYLINE':
            return [(x, y) for x, y in e.get_points('xy')]
        if t == 'POLYLINE':
            return [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        if t in ('CIRCLE', 'ARC'):
            c, r = e.dxf.center, abs(e.dxf.radius)
            return [(c.x - r, c.y - r), (c.x + r, c.y + r)]
        if t == 'ELLIPSE':
            c = e.dxf.center
            r = max(abs(e.dxf.major_axis.x), abs(e.dxf.major_axis.y), e.dxf.ratio)
            return [(c.x - r, c.y - r), (c.x + r, c.y + r)]
        if t == 'HATCH':
            pts = []
            for path in e.paths:
                for v in getattr(path, 'vertices', []):
                    pts.append((v[0], v[1]))
            return pts
        if t in ('SOLID', 'TRACE', '3DFACE'):
            out = []
            for key in ('vtx0', 'vtx1', 'vtx2', 'vtx3'):
                try:
                    p = getattr(e.dxf, key)
                    out.append((p.x, p.y))
                except Exception:
                    continue
            return out
    except Exception:
        return []
    return []


def _bbox_of(points):
    """(x0, y0, x1, y1) 或 None"""
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _is_closed_polyline(e, pts):
    """判断多段线是否闭合。

    ``e.closed`` 只认 DXF 的 closed 标志位；但不少导出程序把首尾点写成同一个点、
    标志位却留 0（天正、部分 SVG->DXF 转换器都这样），光看标志位会漏掉一半椅子。
    """
    try:
        if getattr(e, 'closed', False) or getattr(e, 'is_closed', False):
            return True
    except Exception:
        pass
    if len(pts) >= 4:
        x0, y0 = pts[0]
        x1, y1 = pts[-1]
        if math.hypot(x1 - x0, y1 - y0) <= 1.0:      # 1mm 容差
            return True
    return False


class _Layout:
    """一次解析后的图纸布局：单位、画布范围、毫米->像素映射。

    DXF 的 y 轴向上，图像的 y 轴向下。翻转只在 :meth:`px` 里做一次，
    别处一律用毫米，否则某个函数忘了翻就会整层位移。
    """

    def __init__(self, canvas_mm, scale):
        self.x0, self.y0, self.x1, self.y1 = canvas_mm
        self.scale = float(scale)
        self.width = max(1, int(round((self.x1 - self.x0) * self.scale)))
        self.height = max(1, int(round((self.y1 - self.y0) * self.scale)))

    def px_raw(self, x_mm, y_mm):
        """毫米坐标 -> 像素坐标（不钳制）。

        画图元时必须用这个：钳制会把画在图外的图元（雨棚边线、图框）压到画布
        边缘上，凭空多出一圈墙。OpenCV 自己会裁掉画布外的部分。
        """
        x = int(round((x_mm - self.x0) * self.scale))
        y = int(round((self.y1 - y_mm) * self.scale))
        # 极端坐标（十万米级别）会让 OpenCV 的填充退化成诡异形状，兜一下
        lim = max(self.width, self.height) * 10
        return max(-lim, min(lim, x)), max(-lim, min(lim, y))

    def px(self, x_mm, y_mm):
        """毫米坐标 -> 像素坐标（int，已翻转 y 轴、已钳制在图内）"""
        x, y = self.px_raw(x_mm, y_mm)
        return (max(0, min(self.width - 1, x)),
                max(0, min(self.height - 1, y)))

    def size(self):
        return (self.width, self.height)


class _Context:
    """``load()`` / ``build()`` 共用的一次解析结果"""

    def __init__(self):
        self.path = ''
        self.entities = []           # [(图层名, 图元)]
        self.layers = {}             # {图层名: 图元数}
        self.guess = {}              # 关键词匹配到的图层
        self.roles = {}              # 最终采用的角色 -> 图层列表
        self.unit = 1.0              # 图纸单位 -> 毫米
        self.layout = None           # _Layout
        self.warnings = []
        self.doc = None

    # -- 便捷访问 ---------------------------------------------------------
    def layer_set(self, *roles):
        out = set()
        for r in roles:
            out.update(self.roles.get(r) or [])
        return out

    def barrier_layers(self):
        """障碍图层：墙、墙体填充、窗、柱。

        窗必须算障碍。外墙的窗洞在 DXF 里是墙线断开、只留几条窗线；不封住它，
        室内可行走区和楼外就连成一片（实测可行走域多出 13000 像素的一圈外环），
        A* 会规划出「从窗户出去、绕楼一圈、再从另一个窗户进来」这种路径。
        """
        return self.layer_set('wall', 'wall_fill', 'window', 'column')


class DxfRoadNetworkBuilder:
    """从 DXF 直接构建路网与座位候选。"""

    def __init__(self, scale: float = 1 / 50.0):
        """scale: 毫米 -> 像素 的缩放比。默认 1/50 即 1 像素 = 50mm。"""
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            scale = 1 / 50.0
        if not math.isfinite(scale) or scale <= 0:
            scale = 1 / 50.0
        self.scale = scale
        self._generator = RoadNetworkGenerator()

    # ==================================================================
    # 公共接口
    # ==================================================================
    def load(self, dxf_path: str) -> dict:
        """解析 DXF，返回图层清单与识别结果（不建路网、不写任何东西）。"""
        out = {
            'ok': False,
            'layers': {},
            'roles': {r: [] for r in ROLES + EXTRA_ROLES},
            'guess': {r: [] for r in ROLES + EXTRA_ROLES},
            'bbox_mm': (0, 0, 0, 0),
            'size_px': (0, 0),
            'warnings': [],
            'error': None,
        }
        ctx, err = self._parse(dxf_path)
        if err:
            out['error'] = err
            return out

        lay = ctx.layout
        out.update({
            'ok': True,
            'layers': dict(ctx.layers),
            'roles': {k: list(v) for k, v in ctx.roles.items()},
            'guess': {k: list(v) for k, v in ctx.guess.items()},
            'bbox_mm': (int(round(lay.x0)), int(round(lay.y0)),
                        int(round(lay.x1)), int(round(lay.y1))),
            'size_px': lay.size(),
            'warnings': list(ctx.warnings),
        })
        return out

    def build(self, dxf_path: str) -> dict:
        """生成路网与座位候选。任何失败都返回 error 字段，不抛异常。"""
        out = {
            'ok': False,
            'network': {'nodes': {}, 'edges': [],
                        'floor_info': {'width': 0, 'height': 0}},
            'seats': [],
            'rooms': [],
            'stats': {'node_count': 0, 'edge_count': 0,
                      'seat_count': 0, 'room_count': 0},
            'warnings': [],
            'error': None,
        }
        ctx, err = self._parse(dxf_path)
        if err:
            out['error'] = err
            return out
        warnings = out['warnings']
        warnings.extend(ctx.warnings)
        lay = ctx.layout

        # --- 1. 可行走区 -> 骨架 -> 图 -----------------------------------
        walk = self._walkable_mask(ctx, warnings)
        if walk is None:
            out['error'] = '墙体把整张图都填满了，没有可行走区域'
            return out

        skeleton = self._generator._extract_skeleton(walk)
        if cv2.countNonZero(skeleton) == 0:
            out['error'] = '骨架提取结果为空，无法生成路网（检查墙图层是否选对）'
            return out

        nodes, edges = self._generator._skeleton_to_graph(
            skeleton, min_node_dist=NODE_STEP_PX)
        if not nodes:
            out['error'] = '骨架里没有采到任何节点，无法生成路网'
            return out

        nodes, edges, dropped = self._link_isolated(nodes, edges, walk)
        if dropped:
            warnings.append('删除了 %d 个补连后仍然孤立的骨架点' % dropped)

        # --- 2. 座位候选 -------------------------------------------------
        seats_mm, seat_warn = self._collect_seats(ctx)
        warnings.extend(seat_warn)

        # --- 3. 房间 -----------------------------------------------------
        rooms_mm, room_warn = self._collect_rooms(ctx)
        warnings.extend(room_warn)

        # --- 4. 编号 -----------------------------------------------------
        seats = self._label_seats(seats_mm, rooms_mm, lay, warnings)

        rooms = []
        for r in sorted(rooms_mm, key=lambda m: (m['y'], m['x'])):
            rx, ry = lay.px(r['x'], r['y'])
            rooms.append({'name': r['name'], 'code': r['code'],
                          'x': rx, 'y': ry})

        out.update({
            'ok': True,
            'network': {
                'nodes': nodes,
                'edges': edges,
                'floor_info': {'width': lay.width, 'height': lay.height,
                               'image_path': ctx.path},
            },
            'seats': seats,
            'rooms': rooms,
            'stats': {
                'node_count': int(len(nodes)),
                'edge_count': int(len(edges)),
                'seat_count': int(len(seats)),
                'room_count': int(len(rooms)),
            },
        })
        logger.info('DXF 路网生成完成 %s: 节点 %d / 边 %d / 座位 %d / 房间 %d',
                    os.path.basename(str(dxf_path)), len(nodes), len(edges),
                    len(seats), len(rooms))
        return out

    def render_preview(self, dxf_path: str, out_path: str) -> dict:
        """把栅格化后的「墙 + 可行走区」导出成 PNG，给后台当平面图底图用。

        DXF 本身没法直接塞进 <img>，后台要拖拽座位就得有一张同尺寸的位图。
        可选接口：不调用它，build() 一样能跑。
        """
        ctx, err = self._parse(dxf_path)
        if err:
            return {'ok': False, 'error': err, 'path': None}
        try:
            walk = self._walkable_mask(ctx, [])
            if walk is None:
                return {'ok': False, 'error': '没有可行走区域', 'path': None}
            img = np.full((walk.shape[0], walk.shape[1], 3), 255, np.uint8)
            img[walk == 0] = (170, 170, 170)          # 墙 = 浅灰
            img[walk > 0] = (255, 255, 255)
            ok, buf = cv2.imencode('.png', img)
            if not ok:
                return {'ok': False, 'error': 'PNG 编码失败', 'path': None}
            # cv2.imwrite 在中文路径上会静默失败（Windows 下 imwrite 不支持非 ASCII
            # 路径，返回 False 而不是抛错），这里统一走 imencode + tofile。
            buf.tofile(out_path)
            return {'ok': True, 'error': None, 'path': out_path}
        except Exception as e:
            logger.exception('DXF 预览图导出失败: %s', e)
            return {'ok': False, 'error': '预览图导出失败：%s' % e, 'path': None}

    # ==================================================================
    # 解析：图层统计 -> 角色判定 -> 画布范围
    # ==================================================================
    def _parse(self, dxf_path):
        """返回 (ctx, 错误说明)。成功时错误说明为 None。"""
        if not dxf_path:
            return None, '没有指定 DXF 文件路径'
        try:
            path = os.fspath(dxf_path)
        except TypeError:
            return None, 'DXF 路径不合法：%r' % (dxf_path,)
        if not os.path.exists(path):
            return None, '找不到 DXF 文件：%s' % path
        if os.path.isdir(path):
            return None, '给的是目录不是文件：%s' % path

        try:
            import ezdxf
        except ImportError:
            return None, '缺少 ezdxf 依赖，请执行 pip install ezdxf'

        try:
            doc = ezdxf.readfile(path)
        except Exception as e:
            # 文件被改了扩展名、被 Excel/记事本存成 ANSI、或者根本不是 DXF，
            # ezdxf 抛的异常类型五花八门（IOError / DXFStructureError / UnicodeDecodeError），
            # 一律兜住换成中文原因，不能让 500 页面糊到前端。
            return None, 'DXF 读取失败（文件可能已损坏或不是有效的 DXF）：%s' % e

        try:
            entities = list(_iter_entities(doc.modelspace()))
        except Exception as e:
            return None, 'DXF 模型空间遍历失败：%s' % e
        if not entities:
            return None, 'DXF 里没有任何图元（模型空间是空的）'

        ctx = _Context()
        ctx.path = path
        ctx.doc = doc
        ctx.entities = entities

        # 图层计数（保留首次出现的顺序，报错时人能对上图纸的图层管理器）
        for layer_name, _e in entities:
            ctx.layers[layer_name] = ctx.layers.get(layer_name, 0) + 1

        # 单位换算 + 角色判定
        ctx.unit = self._unit_factor(doc, entities, ctx.warnings)
        ctx.guess, ctx.roles = self._resolve_roles(ctx)

        barrier = ctx.barrier_layers()
        if not barrier:
            return None, ('没有识别到墙图层：既没有名字像墙（wall/墙）的图层，'
                          '也没有图元几何像墙（长直线/闭合墙段）的图层。'
                          '请在 CAD 里把墙体单独放到一个图层上再导出 DXF')

        # 画布：墙主体结构的包围盒（顺带把图框、雨棚边线这类零散图元排除掉）
        #
        # 先按「整幅墙图跨度」决定工作缩放：一张 1:1 的 500m 总图按 1/50 缩放是
        # 10000 像素宽，光是找连通域就要几十兆内存，必须先在临时画布上降采样，
        # 否则算到一半机器就顶不住了。
        full_span = self._wall_span(ctx, barrier)
        work_scale = self.scale
        if full_span and full_span * work_scale > MAX_CANVAS_PX:
            work_scale = MAX_CANVAS_PX / full_span
            ctx.warnings.append(
                '图纸跨度 %.0fmm，按 1/%.0f 缩放会超过 %d 像素，已自动降到 1/%.0f'
                % (full_span, 1 / self.scale, MAX_CANVAS_PX, 1 / work_scale))

        canvas = self._canvas_from_walls(ctx, barrier, work_scale)
        if canvas is None:
            return None, '墙图元没有有效的坐标范围，无法确定图纸尺寸'
        ctx.layout = _Layout(canvas, work_scale)
        return ctx, None

    def _unit_factor(self, doc, entities, warnings):
        """图纸单位 -> 毫米 的换算系数。

        建筑 DXF 的模型空间通常是毫米（$INSUNITS=4），但有人按米画（$INSUNITS=6）。
        按毫米解释一张米制图，整栋楼会缩成 1 像素里的一个点，骨架直接是空的；
        反过来按米解释毫米图，画布会大到算不动。所以先看单位头，头里没有就按跨度猜。
        """
        try:
            insunits = int(doc.header.get('$INSUNITS', 0) or 0)
        except Exception:
            insunits = 0
        factor = _UNIT_TO_MM.get(insunits)
        if factor:
            return float(factor)

        pts = []
        for _lay, e in entities:
            pts.extend(_entity_points(e))
            if len(pts) > 4000:                      # 抽样够判断量级就行
                break
        box = _bbox_of(pts)
        if not box:
            return 1.0
        span = max(box[2] - box[0], box[3] - box[1])
        if span <= 0:
            return 1.0
        if span < MIN_PLAN_SPAN_MM:
            # 一栋楼不可能只有几米，说明单位不是毫米：几十的量级是米，上千的是厘米
            factor = 1000.0 if span < 100 else 10.0
            warnings.append('图纸没有标注单位，按跨度 %.1f 判断为%s制，已换算成毫米'
                            % (span, '米' if factor == 1000.0 else '厘米'))
            return factor
        return 1.0

    def _resolve_roles(self, ctx):
        """先按图层名模糊匹配，匹配不到的角色再按几何特征兜底。"""
        guess = {r: [] for r in ROLES + EXTRA_ROLES}
        for layer_name in ctx.layers:
            role = _match_role(layer_name)
            if role:
                guess[role].append(layer_name)
        roles = {r: list(v) for r, v in guess.items()}

        fallback = []
        # 墙：名字认不出来时，找「长直线总长度最大」的图层
        if not roles['wall'] and not roles['wall_fill']:
            pick = self._guess_wall_layer(ctx)
            if pick:
                roles['wall'] = [pick]
                fallback.append('wall->%s' % pick)
        # 座位：找「小闭合方块最多」的图层
        if not roles['furniture']:
            pick = self._guess_furniture_layer(ctx, roles)
            if pick:
                roles['furniture'] = [pick]
                fallback.append('furniture->%s' % pick)
        # 文字：找「TEXT 最多」的图层
        if not roles['text']:
            pick = self._guess_text_layer(ctx)
            if pick:
                roles['text'] = [pick]
                fallback.append('text->%s' % pick)
        # 门、楼梯认不出来不致命（只是少两个统计），不兜底

        if fallback:
            msg = '图层名匹配不上，已按几何特征兜底：' + '、'.join(fallback)
            ctx.warnings.append(msg)
            logger.info(msg)
        return guess, roles

    def _layer_stats(self, ctx):
        """逐图层统计几何特征，供兜底判定用。"""
        stats = {}
        for layer_name, e in ctx.entities:
            st = stats.setdefault(layer_name, {
                'line_len': 0.0, 'long_lines': 0, 'squares': 0,
                'texts': 0, 'count': 0,
            })
            st['count'] += 1
            t = e.dxftype()
            if t in ('TEXT', 'MTEXT'):
                st['texts'] += 1
            pts = _entity_points(e)
            box = _bbox_of(pts)
            if not box:
                continue
            w = (box[2] - box[0]) * ctx.unit
            h = (box[3] - box[1]) * ctx.unit
            if t in ('LINE', 'LWPOLYLINE', 'POLYLINE'):
                length = 0.0
                if t == 'LINE':
                    length = math.hypot(box[2] - box[0], box[3] - box[1]) * ctx.unit
                else:
                    for i in range(1, len(pts)):
                        length += math.hypot(pts[i][0] - pts[i - 1][0],
                                             pts[i][1] - pts[i - 1][1]) * ctx.unit
                st['line_len'] += length
                if length >= 1000.0:                 # 1 米以上算「长直线」
                    st['long_lines'] += 1
            if self._is_seat_shape(t, e, w, h):
                st['squares'] += 1
        return stats

    def _guess_wall_layer(self, ctx):
        """几何兜底猜墙：长直线总长度最大的图层。

        图框、轴网也画长直线，所以按「长直线总长」排序而不是图元数 —— 墙是
        一层楼里线最多也最长的东西，图框只有 4 条边。
        """
        try:
            stats = self._layer_stats(ctx)
        except Exception:
            return None
        best, best_score = None, 0.0
        for layer_name, st in stats.items():
            if st['texts'] and st['texts'] >= st['long_lines']:
                continue                             # 文字层不可能是墙
            score = st['line_len'] * (1.0 + min(st['long_lines'], 50) / 50.0)
            if score > best_score:
                best, best_score = layer_name, score
        return best if best_score > 0 else None

    def _guess_furniture_layer(self, ctx, roles):
        """几何兜底猜家具：小闭合方块最多的图层。"""
        try:
            stats = self._layer_stats(ctx)
        except Exception:
            return None
        skip = set(roles.get('wall') or []) | set(roles.get('wall_fill') or [])
        best, best_n = None, 0
        for layer_name, st in stats.items():
            if layer_name in skip:
                continue
            if st['squares'] > best_n:
                best, best_n = layer_name, st['squares']
        return best if best_n >= 3 else None

    def _guess_text_layer(self, ctx):
        """几何兜底猜文字：TEXT/MTEXT 最多的图层。"""
        cnt = {}
        for layer_name, e in ctx.entities:
            try:
                if e.dxftype() in ('TEXT', 'MTEXT'):
                    cnt[layer_name] = cnt.get(layer_name, 0) + 1
            except Exception:
                continue
        if not cnt:
            return None
        return max(cnt.items(), key=lambda kv: kv[1])[0]

    # ==================================================================
    # 画布与栅格化
    # ==================================================================
    def _wall_points(self, ctx, barrier_layers):
        """墙体图元的坐标点（已换算成毫米）。

        这里必须乘 ctx.unit：``_entity_points`` 给的是图纸原始坐标，
        一张按米画的图（$INSUNITS=6）原始坐标只有 6 和 4，直接用会让画布
        变成 1x1 像素、整张图挤成一个点（实测就是 1x1）。
        """
        pts = []
        for layer_name, e in ctx.entities:
            if layer_name in barrier_layers:
                pts.extend([(x * ctx.unit, y * ctx.unit) for x, y in _entity_points(e)])
        return pts

    def _wall_span(self, ctx, barrier_layers):
        """整幅墙图的较大跨度（毫米），用来决定要不要降采样。"""
        box = _bbox_of(self._wall_points(ctx, barrier_layers))
        if not box:
            return 0.0
        return max(box[2] - box[0], box[3] - box[1])

    def _canvas_from_walls(self, ctx, barrier_layers, work_scale):
        """画布 = 墙主体结构的包围盒（毫米）。

        直接用「所有墙图元的 bbox」会把零散图元算进来：样本图底部有一根
        400mm 长的雨棚边线在 y=-8800，于是画布多出 170 像素高的空带 —— 那里没有
        任何房间，骨架却在里面长出一簇谁也走不到的点。改成只在墙的连通域里找
        主体（面积占最大块 10% 以上的都算），零散线自然被排除。
        """
        full = _bbox_of(self._wall_points(ctx, barrier_layers))
        if full is None:
            return None
        if full[2] - full[0] <= 0 or full[3] - full[1] <= 0:
            return None

        tmp = _Layout(full, work_scale)               # 先按整幅墙图铺一张临时画布
        mask = self._rasterize(ctx, barrier_layers, tmp)
        n, lbl, stats, _ = cv2.connectedComponentsWithStats(
            (mask > 0).astype(np.uint8), connectivity=8)
        if n <= 1:
            return full
        areas = [(int(stats[i, cv2.CC_STAT_AREA]), i) for i in range(1, n)]
        areas.sort(reverse=True)
        biggest = areas[0][0]
        keep = [i for a, i in areas if biggest and a >= biggest * 0.10]
        ys, xs = np.where(np.isin(lbl, keep))
        if xs.size == 0:
            return full

        x0 = full[0] + xs.min() / tmp.scale
        x1 = full[0] + (xs.max() + 1) / tmp.scale
        y1 = full[3] - ys.min() / tmp.scale
        y0 = full[3] - (ys.max() + 1) / tmp.scale

        # 退化保护：主体范围不到整幅的一半，说明墙被门洞切得太碎，
        # 这时候只留主体反而会把半栋楼裁掉，宁可退回去用整幅 bbox。
        if ((x1 - x0) * (y1 - y0)) < 0.5 * ((full[2] - full[0]) * (full[3] - full[1])):
            ctx.warnings.append('墙体连通块太碎，已退回按整幅墙图范围出图')
            return full
        return (round(x0), round(y0), round(x1), round(y1))

    def _rasterize(self, ctx, layers, layout, thick_px=None):
        """把指定图层的图元画成黑白图（255 = 障碍）。"""
        if thick_px is None:
            # 线宽按 100mm 折算，最少 2 像素：1 像素的墙在膨胀一次后就没了，
            # 可行走区会从墙缝里漏过去。
            thick_px = max(2, int(round(100 * layout.scale)))
        mask = np.zeros((layout.height, layout.width), np.uint8)

        for layer_name, e in ctx.entities:
            if layer_name not in layers:
                continue
            try:
                self._draw_entity(mask, e, layout, thick_px, ctx.unit)
            except Exception:
                # 单个图元坐标异常（块里塞了 3D 点、半径是负数等）不该让整张图失败
                continue
        return mask

    def _draw_entity(self, mask, e, layout, thick_px, unit):
        t = e.dxftype()
        scale_u = unit

        def to_px(x, y):
            return layout.px_raw(x * scale_u, y * scale_u)

        if t == 'LINE':
            cv2.line(mask, to_px(e.dxf.start.x, e.dxf.start.y),
                     to_px(e.dxf.end.x, e.dxf.end.y), 255, thick_px)
        elif t in ('LWPOLYLINE', 'POLYLINE'):
            if t == 'LWPOLYLINE':
                pts = [(x, y) for x, y in e.get_points('xy')]
            else:
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            if len(pts) < 2:
                return
            arr = np.array([to_px(x, y) for x, y in pts], np.int32)
            if _is_closed_polyline(e, pts) and len(pts) >= 3:
                cv2.fillPoly(mask, [arr], 255)
            else:
                cv2.polylines(mask, [arr], False, 255, thick_px)
        elif t == 'CIRCLE':
            cv2.circle(mask, to_px(e.dxf.center.x, e.dxf.center.y),
                       max(1, int(round(abs(e.dxf.radius) * unit * layout.scale))),
                       255, thick_px)
        elif t in ('ARC', 'ELLIPSE'):
            # 弧线不直接用 cv2.ellipse：DXF 的起止角是逆时针、图像 y 轴朝下，
            # 角度会镜像，采样成折线就不用管这些了。
            arr = np.array([to_px(x, y) for x, y in self._arc_points(e)], np.int32)
            if len(arr) >= 2:
                cv2.polylines(mask, [arr], False, 255, thick_px)
        elif t == 'HATCH':
            for path in e.paths:
                vs = getattr(path, 'vertices', None)
                if not vs or len(vs) < 3:
                    continue
                arr = np.array([to_px(v[0], v[1]) for v in vs], np.int32)
                cv2.fillPoly(mask, [arr], 255)
        elif t in ('SOLID', 'TRACE', '3DFACE'):
            pts = []
            for key in ('vtx0', 'vtx1', 'vtx2', 'vtx3'):
                try:
                    p = getattr(e.dxf, key)
                    pts.append(to_px(p.x, p.y))
                except Exception:
                    continue
            if len(pts) >= 3:
                cv2.fillPoly(mask, [np.array(pts, np.int32)], 255)

    def _arc_points(self, e, samples=16):
        """把 ARC / ELLIPSE 采样成折线点（毫米）。"""
        c = e.dxf.center
        if e.dxftype() == 'ARC':
            r = abs(e.dxf.radius)
            a0 = math.radians(e.dxf.start_angle)
            a1 = math.radians(e.dxf.end_angle)
            if a1 < a0:
                a1 += 2 * math.pi
            n = max(2, samples)
            return [(c.x + r * math.cos(a0 + (a1 - a0) * i / n),
                     c.y + r * math.sin(a0 + (a1 - a0) * i / n))
                    for i in range(n + 1)]
        ax = e.dxf.major_axis
        major = math.hypot(ax.x, ax.y)
        minor = major * abs(e.dxf.ratio)
        rot = math.atan2(ax.y, ax.x)
        a0 = e.dxf.start_param
        a1 = e.dxf.end_param
        if a1 < a0:
            a1 += 2 * math.pi
        n = max(2, samples)
        out = []
        for i in range(n + 1):
            t = a0 + (a1 - a0) * i / n
            x = major * math.cos(t)
            y = minor * math.sin(t)
            out.append((c.x + x * math.cos(rot) - y * math.sin(rot),
                        c.y + x * math.sin(rot) + y * math.cos(rot)))
        return out

    # ==================================================================
    # 可行走区与路网
    # ==================================================================
    def _walkable_mask(self, ctx, warnings):
        """可行走区 = 墙的反色，裁掉零散碎块。返回 uint8 掩膜或 None。"""
        lay = ctx.layout
        wall = self._rasterize(ctx, ctx.barrier_layers(), lay)
        walk = 255 - cv2.dilate(wall, np.ones((3, 3), np.uint8), iterations=1)
        if cv2.countNonZero(walk) == 0:
            return None

        n, lbl, stats, _ = cv2.connectedComponentsWithStats(
            (walk > 0).astype(np.uint8), connectivity=8)
        if n <= 1:
            return walk
        keep = np.zeros_like(walk)
        kept, dropped = 0, 0
        for i in range(1, n):
            if int(stats[i, cv2.CC_STAT_AREA]) >= MIN_WALK_AREA_PX:
                keep[lbl == i] = 255
                kept += 1
            else:
                dropped += 1
        if cv2.countNonZero(keep) == 0:
            return walk
        # 这里刻意「保留所有够大的连通域」而不是「只保留最大连通域」：
        # 房间之间是靠门洞连通的，一旦某个房间门被家具堵上，它自成一块，
        # 只留最大块等于把那个房间整个丢掉。实测只留最大块时，样本图
        # 6451 像素的阅览室和 1768 像素的设备间会连人带座位一起消失。
        if dropped:
            logger.debug('可行走区丢弃 %d 个小于 %d 像素的碎块',
                         dropped, MIN_WALK_AREA_PX)
        return keep

    def _link_isolated(self, nodes, edges, walk):
        """给孤立节点补一条边，补不上就删掉。

        ``_skeleton_to_graph`` 只连「距离 < 1.5 步长 且连线全程压在骨架上」的点，
        骨架是 1 像素宽的细线，斜向的骨架枝梢经常连不上：实测 817 个节点里
        51 个（6.2%）没有边。这些点落在可行走区里，离邻居并不远，只是连线偏出
        骨架一两像素。
        这里换成「连线全程落在可行走区（已膨胀 1 像素）」的判据 —— 语义照样是
        「两点之间能直着走过去」，但不再要求精确踩在骨架上。
        """
        degree = set()
        for e in edges:
            degree.add(e['from'])
            degree.add(e['to'])
        isolated = [nid for nid in nodes if nid not in degree]
        if not isolated:
            return nodes, edges, 0

        check = cv2.dilate(walk, np.ones((3, 3), np.uint8), iterations=1)
        max_d = NODE_STEP_PX * LINK_SEARCH_FACTOR
        for nid in isolated:
            a = nodes[nid]
            best, best_d = None, float('inf')
            for other, b in nodes.items():
                if other == nid or other not in degree:
                    continue                      # 只往已经连上的节点上挂
                d = (a['x'] - b['x']) ** 2 + (a['y'] - b['y']) ** 2
                if d < best_d and d <= max_d * max_d:
                    if self._line_walkable(check, a['x'], a['y'], b['x'], b['y']):
                        best, best_d = other, d
            if best:
                edges.append({'from': nid, 'to': best})
                degree.add(nid)
                degree.add(best)

        still = [nid for nid in nodes if nid not in degree]
        for nid in still:
            nodes.pop(nid, None)
        return nodes, edges, len(still)

    @staticmethod
    def _line_walkable(mask, x1, y1, x2, y2, samples=24):
        """两点连线是否全程落在掩膜内（每 ~3 像素采一个点，跨不过 2 像素的墙）"""
        for i in range(samples + 1):
            t = i / samples
            x = int(round(x1 + (x2 - x1) * t))
            y = int(round(y1 + (y2 - y1) * t))
            if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]):
                return False
            if mask[y, x] == 0:
                return False
        return True

    # ==================================================================
    # 座位候选
    # ==================================================================
    @staticmethod
    def _is_seat_shape(etype, e, w_mm, h_mm):
        """是不是一个「小方块」：300~900mm、长宽比 <= 2 的闭合方块/圆。"""
        if w_mm <= 0 or h_mm <= 0:
            return False
        lo = SEAT_SIDE_MIN_MM - SEAT_SIDE_EPS_MM
        hi = SEAT_SIDE_MAX_MM + SEAT_SIDE_EPS_MM
        if not (lo <= w_mm <= hi):
            return False
        if not (lo <= h_mm <= hi):
            return False
        if max(w_mm, h_mm) / min(w_mm, h_mm) > SEAT_ASPECT_MAX:
            return False
        if etype == 'CIRCLE':
            return True
        if etype in ('LWPOLYLINE', 'POLYLINE'):
            if etype == 'LWPOLYLINE':
                pts = [(x, y) for x, y in e.get_points('xy')]
            else:
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            return len(pts) >= 4 and _is_closed_polyline(e, pts)
        return False

    def _collect_seats(self, ctx):
        """从家具图层抠座位候选。返回 (毫米坐标列表, 警告列表)。"""
        warnings = []
        layers = set(ctx.roles.get('furniture') or [])
        if not layers:
            warnings.append('没有家具图层，座位候选为空（需要人工补座位或指定图层）')
            return [], warnings

        raw = []
        for layer_name, e in ctx.entities:
            if layer_name not in layers:
                continue
            try:
                etype = e.dxftype()
                if etype not in ('LWPOLYLINE', 'POLYLINE', 'CIRCLE'):
                    continue
                box = _bbox_of(_entity_points(e))
                if not box:
                    continue
                w = (box[2] - box[0]) * ctx.unit
                h = (box[3] - box[1]) * ctx.unit
                if not self._is_seat_shape(etype, e, w, h):
                    continue
                raw.append(((box[0] + box[2]) / 2 * ctx.unit,
                            (box[1] + box[3]) / 2 * ctx.unit))
            except Exception:
                continue

        # 去重：中心点相距不到 200mm 的当成同一把椅子（一块椅子既画了外框又插了块，
        # 或者 CAD 里复制重叠时会出两个中心几乎重合的方块）
        seats, merged = [], 0
        for cx, cy in raw:
            for sx, sy in seats:
                if math.hypot(cx - sx, cy - sy) < SEAT_DEDUP_MM:
                    merged += 1
                    break
            else:
                seats.append((cx, cy))
        if merged:
            warnings.append('座位去重：%d 个重叠方块合并成了已识别的座位' % merged)
        if not seats:
            warnings.append('家具图层里没找到 300~900mm 的小方块，座位候选为空')
        return seats, warnings

    # ==================================================================
    # 房间
    # ==================================================================
    def _collect_rooms(self, ctx):
        """从文字图层配对房间：房间名 + 紧跟其后的「编号 面积」。"""
        warnings = []
        layers = set(ctx.roles.get('text') or [])
        if not layers:
            warnings.append('没有文字图层，房间信息为空，座位将用 A-1 递增编号')
            return [], warnings

        lay = ctx.layout
        texts = []
        for layer_name, e in ctx.entities:
            if layer_name not in layers:
                continue
            try:
                etype = e.dxftype()
                if etype == 'TEXT':
                    raw = e.dxf.text or ''
                    pos = e.dxf.insert
                elif etype == 'MTEXT':
                    raw = e.plain_text() if hasattr(e, 'plain_text') else (e.text or '')
                    pos = e.dxf.insert
                else:
                    continue
                content = ' '.join(str(raw).replace('\\P', ' ').split())
                if not content:
                    continue
                x = pos.x * ctx.unit
                y = pos.y * ctx.unit
                # 只认画布范围内的文字：图框标题栏、门窗表都在楼外，
                # 那些「R101 少儿阅览室 144.0」是房间明细表，配进来会凭空多出房间。
                if not (lay.x0 - 2000 <= x <= lay.x1 + 2000
                        and lay.y0 - 2000 <= y <= lay.y1 + 2000):
                    continue
                texts.append({'text': content, 'x': x, 'y': y})
            except Exception:
                continue

        codes = []
        names = []
        for t in texts:
            m = _ROOM_CODE_RE.match(t['text'])
            if m:
                codes.append({
                    'code': m.group(1).replace(' ', '').replace('_', ''),
                    'x': t['x'], 'y': t['y'], 'text': t['text'],
                })
            elif (_CJK_RE.search(t['text']) and not _AREA_RE.search(t['text'])
                  and 2 <= len(t['text']) <= 24):
                names.append(t)

        if not codes:
            # 没有编号的图纸：文字本身就是房间名
            rooms = [{'name': t['text'], 'code': '', 'x': t['x'], 'y': t['y']}
                     for t in names]
            if not rooms:
                warnings.append('文字图层里没有识别出房间名，座位将用 A-1 递增编号')
            return rooms, warnings

        rooms = []
        used = set()

        # 第一轮：严格邻近（同列上下排，Y 差 <= 1000mm、X 差 <= 500mm）
        for c in codes:
            idx = self._nearest_name(names, used, c, ROOM_PAIR_DX_MM, ROOM_PAIR_DY_MM)
            if idx is not None:
                used.add(idx)
                n = names[idx]
                rooms.append({'name': n['text'], 'code': c['code'],
                              'x': n['x'], 'y': n['y']})
                c['paired'] = True

        # 第二轮：房间太小的时候 CAD 会把名字和编号左右并排，甚至跨过 600mm
        # （样本图「强电井 / R312」横向就差 630mm），严格阈值会漏掉这一间。
        unmatched = []
        for c in codes:
            if c.get('paired'):
                continue
            idx = self._nearest_name(names, used, c, ROOM_PAIR_FAR_MM, ROOM_PAIR_FAR_MM)
            if idx is not None:
                used.add(idx)
                n = names[idx]
                rooms.append({'name': n['text'], 'code': c['code'],
                              'x': n['x'], 'y': n['y']})
            else:
                # 编号存在但没配上名字的，仍然当作一个房间：有编号就够给座位起名了
                rooms.append({'name': '', 'code': c['code'],
                              'x': c['x'], 'y': c['y']})
                unmatched.append(c['code'])

        left = [names[i]['text'] for i in range(len(names)) if i not in used]
        if left:
            preview = '、'.join(left[:3])
            if len(left) > 3:
                preview += ' 等'
            warnings.append('%d 条文字没配上房间编号，已忽略（%s）'
                            % (len(left), preview))
        if unmatched:
            warnings.append('%d 个编号找不到对应房间名，只按编号建房间（%s）'
                            % (len(unmatched), '、'.join(unmatched[:3])))
        return rooms, warnings

    @staticmethod
    def _nearest_name(names, used, code, dx_lim, dy_lim):
        """在没用过的房间名里找离编号最近的一个（横竖分别卡阈值），返回下标或 None。"""
        best, best_d = None, float('inf')
        for i, n in enumerate(names):
            if i in used:
                continue
            dx = abs(n['x'] - code['x'])
            dy = abs(n['y'] - code['y'])
            if dx > dx_lim or dy > dy_lim:
                continue
            if dx * dx + dy * dy < best_d:
                best, best_d = i, dx * dx + dy * dy
        return best

    # ==================================================================
    # 座位编号
    # ==================================================================
    def _label_seats(self, seats_mm, rooms_mm, lay, warnings):
        """给每个座位起名：有房号用「R101-01」，只有房名用「首字-序号」，全无房间用「A-1」。"""
        ordered = sorted(seats_mm, key=lambda p: (p[1], p[0]))   # 按读数方向排，编号不乱跳
        used_labels = set()
        room_seq = {}
        free_seq = 0
        far = 0
        out = []

        for x_mm, y_mm in ordered:
            room, dist = self._nearest_room(rooms_mm, x_mm, y_mm)
            assigned = room is not None and dist <= SEAT_ROOM_MAX_MM
            if room is not None and not assigned:
                far += 1
            while True:
                if assigned:
                    key = room['code'] or room['name']
                    room_seq[key] = room_seq.get(key, 0) + 1
                    seq = room_seq[key]
                    if room['code']:
                        label = '%s-%02d' % (room['code'], seq)
                    else:
                        label = '%s-%d' % ((room['name'] or 'A')[:1], seq)
                else:
                    free_seq += 1
                    label = 'A-%d' % free_seq
                if label not in used_labels:
                    break
            used_labels.add(label)

            px, py = lay.px(x_mm, y_mm)
            out.append({'seat_label': label, 'x': int(px), 'y': int(py)})

        if far:
            warnings.append('%d 个座位离所有房间都超过 %.0fmm，已用 A-1 递增编号'
                            % (far, SEAT_ROOM_MAX_MM))
        if not rooms_mm and out:
            warnings.append('图纸里没有房间信息，%d 个座位已用 A-1 递增编号' % len(out))
        return out

    @staticmethod
    def _nearest_room(rooms_mm, x_mm, y_mm):
        """最近的房间（用房间名的位置当锚点）及其距离（毫米）。"""
        room, best = None, float('inf')
        for r in rooms_mm:
            d = math.hypot(x_mm - r['x'], y_mm - r['y'])
            if d < best:
                room, best = r, d
        return room, best
