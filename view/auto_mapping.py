# -*- coding: utf-8 -*-
"""
auto_mapping.py —— 手机拍摄自动建图核心处理模块（路径 A）

本模块按照《手机拍摄自动建图技术文档》把"照片/视频 → 全景拼接 → 墙体直线提取"
的整条链路封装成可复用的接口函数，供外部"主函数"调用。

实现说明：本模块**复用**工作区已有的两个实现文件，避免重复代码：
    - vitalframe.py 的 vitalframe()        -> 步骤1 关键帧提取
    - framecut.py  的 similar_frame()      -> 步骤2 特征匹配
    - framecut.py  的 marge_frame()        -> 步骤3 单应性矩阵与变换
    - framecut.py  的 stitch_images()      -> 步骤4 全景拼接
本模块在它们之上补充步骤5-7（直线检测、线段合并、JSON 输出）及高层编排接口。

对外暴露的高层接口（主函数可直接调用）：
    process_video(video_path, output_dir, task_id, ...)
    process_frames(frame_dir, output_dir, task_id, ...)
    process_image_list(image_list, output_dir, task_id, ...)

对外暴露的分步接口（可按需自行组合）：
    extract_keyframes(video_path, save_path, ...)
    match_features(img1, img2)
    homography_and_warp(img2, good, kp1, kp2, img1)
    stitch_keyframes(frame_dir, ...)
    stitch_images(image_list)
    extract_wall_lines_lsd(img, ...)
    extract_wall_lines_hough(img, ...)
    merge_colinear_lines(lines, ...)
    build_plane_json(task_id, stitched, lines, ...)

依赖：opencv-python, numpy
"""

import os
import math
import json
import uuid

import cv2
import numpy as np

# 复用工作区已有的实现（步骤1-4）
from vitalframe import vitalframe as _vitalframe
from framecut import similar_frame as _similar_frame
from framecut import marge_frame as _marge_frame
from framecut import stitch_images as _stitch_images

__all__ = [
    # 高层入口
    "process_video",
    "process_frames",
    "process_image_list",
    # 分步接口
    "extract_keyframes",
    "match_features",
    "homography_and_warp",
    "stitch_keyframes",
    "stitch_images",
    "extract_wall_lines_lsd",
    "extract_wall_lines_hough",
    "merge_colinear_lines",
    "build_plane_json",
]


# ---------------------------------------------------------------------------
# 步骤 1：关键帧提取（复用 vitalframe.vitalframe）
# ---------------------------------------------------------------------------
def extract_keyframes(video_path, save_path, max_frames=20, target_size=(960, 540)):
    """
    从视频中抽取关键帧并保存为 jpg（底层复用 vitalframe.vitalframe）。

    参数：
        video_path : str  输入视频路径
        save_path  : str  保存帧图片的目录
        max_frames : int  最多抽取的帧数（透传给 vitalframe，其余逻辑由其内部处理）
        target_size: tuple 统一缩放尺寸 (w, h)，None 表示保持原尺寸

    返回：
        list[str] : 保存后的帧图片路径列表；失败返回 None
    """
    if save_path:
        os.makedirs(save_path, exist_ok=True)
    return _vitalframe(video_path, save_path, max_frames=max_frames, target_size=target_size)


# ---------------------------------------------------------------------------
# 步骤 2：特征匹配（复用 framecut.similar_frame）
# ---------------------------------------------------------------------------
def match_features(img1, img2, nfeatures=3000, ratio=0.75, min_good=8):
    """
    计算两张图的 ORB 特征点并进行匹配，返回可靠匹配（底层复用 framecut.similar_frame）。

    参数：
        img1, img2 : numpy 数组  待匹配的两张图像
        nfeatures  : int         检测特征点数量上限
        ratio      : float       比率测试阈值（越低越严格）
        min_good   : int         有效匹配点最少数量（RANSAC 至少 8）

    返回：
        (good, kp1, kp2) : 匹配点列表 + 两张图的关键点；失败返回 None
    """
    return _similar_frame(img1, img2, nfeatures=nfeatures, ratio=ratio, min_good=min_good)


# ---------------------------------------------------------------------------
# 步骤 3：单应性矩阵与图像变换（复用 framecut.marge_frame）
# ---------------------------------------------------------------------------
def homography_and_warp(img2, good, kp1, kp2, img1):
    """
    由匹配点计算单应性矩阵 H，把 img2 变换到 img1 坐标系并合并成新画布
    （底层复用 framecut.marge_frame）。

    参数：
        img2 : numpy 数组  待变换的帧
        good : 匹配点列表（match_features 返回值）
        kp1, kp2 : 对应关键点列表
        img1 : numpy 数组  当前底图

    返回：
        numpy 数组 : 合并后的新图像；失败返回 None
    """
    return _marge_frame(img1, img2, good, kp1, kp2)


# ---------------------------------------------------------------------------
# 步骤 4：全景拼接（复用 framecut.stitch_images）
# ---------------------------------------------------------------------------
def stitch_images(image_list, max_canvas_side=None):
    """
    将有序图像列表逐帧拼接为一张大平面图，可自动跳过失败帧（复用 framecut.stitch_images）。

    参数：
        image_list       : list[numpy 数组]  有序图像列表
        max_canvas_side  : int  拼接画布最长边上限，超过则等比缩小以防内存爆炸；
                               默认 None 表示不限制

    返回：
        numpy 数组 : 最终全景图；失败返回 None
    """
    return _stitch_images(image_list, max_canvas_side=max_canvas_side)


def stitch_keyframes(frame_dir, target_size=(960, 540), max_canvas_side=None):
    """
    读取关键帧目录，按文件名顺序拼接为一张大图。

    参数：
        frame_dir       : str  存放关键帧 jpg 的目录
        target_size     : tuple 统一缩放尺寸；None 表示保持原尺寸
        max_canvas_side : int  拼接画布最长边上限，超过则等比缩小以防内存爆炸

    返回：
        numpy 数组 : 拼接后的全景图；失败返回 None
    """
    if not os.path.isdir(frame_dir):
        return None
    frame_files = sorted([f for f in os.listdir(frame_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))])
    if len(frame_files) < 2:
        return None

    image_list = []
    for fn in frame_files:
        img = cv2.imread(os.path.join(frame_dir, fn))
        if img is None:
            continue
        if target_size is not None:
            img = cv2.resize(img, target_size)
        image_list.append(img)
    return _stitch_images(image_list, max_canvas_side=max_canvas_side)


# ---------------------------------------------------------------------------
# 步骤 5：直线检测（LSD 主方案 + Hough 备选）
# ---------------------------------------------------------------------------
def _is_wall_orientation(angle, angle_tol):
    """判断角度是否近似水平(0°/180°)或垂直(90°)。"""
    a = angle % 180
    return a < angle_tol or abs(a - 90) < angle_tol


def extract_wall_lines_lsd(img, min_length=60, angle_tol=15):
    """
    使用 LSD（直线段检测器）从拼接图提取代表墙体的水平/垂直线段。

    参数：
        img        : numpy 数组  输入图像
        min_length : int  过滤短噪声的最小线段长度
        angle_tol  : float  角度容差（度），只保留近似水平/垂直

    返回：
        list[[x1, y1, x2, y2, length, angle], ...]
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_ADV)
    lines, _, _, _ = lsd.detect(gray)

    result = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            angle = min(angle, 180 - angle)  # 归一化到 0-90
            if length < min_length:
                continue
            if not _is_wall_orientation(angle, angle_tol):
                continue
            result.append([float(x1), float(y1), float(x2), float(y2), float(length), float(angle)])
    return result


def extract_wall_lines_hough(img, threshold=80, min_line_length=60, max_line_gap=10):
    """
    备选方案：Canny + HoughLinesP 提取线段。

    参数：
        img             : numpy 数组  输入图像
        threshold       : int  Hough 阈值
        min_line_length : int  最短线段
        max_line_gap    : int  线段最大断裂间隙

    返回：
        list[[x1, y1, x2, y2], ...]
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=threshold,
                            minLineLength=min_line_length, maxLineGap=max_line_gap)
    result = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            result.append([float(x1), float(y1), float(x2), float(y2)])
    return result


# ---------------------------------------------------------------------------
# 步骤 6：线段过滤与合并（墙体轮廓）
# ---------------------------------------------------------------------------
def _angle_of(x1, y1, x2, y2):
    """计算线段角度（0-180，mod 180）。"""
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180


def merge_colinear_lines(lines, angle_thr=5, gap_thr=25):
    """
    将碎片化线段按角度分组、组内共线合并为连续墙体轮廓。

    参数：
        lines     : list  线段列表，[(x1, y1, x2, y2, ...), ...]
        angle_thr : float 角度分组容差
        gap_thr   : float 位置合并容差（垂直距离）

    返回：
        list[[x1, y1, x2, y2], ...]  合并后的线段
    """
    if not lines:
        return []

    groups = []
    for ln in lines:
        x1, y1, x2, y2 = ln[0], ln[1], ln[2], ln[3]
        a = _angle_of(x1, y1, x2, y2)
        placed = False
        for g in groups:
            if abs(g["angle"] - a) < angle_thr or abs(g["angle"] - a) > 180 - angle_thr:
                g["lines"].append(ln)
                placed = True
                break
        if not placed:
            groups.append({"angle": a, "lines": [ln]})

    merged = []
    for g in groups:
        segs = g["lines"]
        xs = []
        ys = []
        for s in segs:
            xs += [s[0], s[2]]
            ys += [s[1], s[3]]
        # 近似水平线（y 方向跨度小）按 x 取两端；否则按 y 取两端
        if max(ys) - min(ys) < max(xs) - min(xs):
            merged.append([min(xs), sum(ys) / len(ys), max(xs), sum(ys) / len(ys)])
        else:
            merged.append([sum(xs) / len(xs), min(ys), sum(xs) / len(xs), max(ys)])
    return merged


# ---------------------------------------------------------------------------
# 步骤 7：输出矢量平面图 JSON
# ---------------------------------------------------------------------------
def build_plane_json(task_id, stitched, lines, name="自动建模房间", mode="phone_capture"):
    """
    将线段数据序列化为前端可用的矢量平面图 JSON。

    参数：
        task_id  : str  任务/房间 id
        stitched : numpy 数组  拼接图
        lines    : list  线段列表
        name     : str  房间名
        mode     : str  来源模式 phone_capture / upload

    返回：
        dict : 平面图 JSON 协议
    """
    return {
        "room": {"id": task_id, "name": name, "mode": mode},
        "image": {
            "width": int(stitched.shape[1]),
            "height": int(stitched.shape[0]),
            "url": "/outputs/%s/stitched.jpg" % task_id,
        },
        "lines": [
            {
                "x1": int(l[0]),
                "y1": int(l[1]),
                "x2": int(l[2]),
                "y2": int(l[3]),
                "angle": round(float(l[5]), 1) if len(l) > 5 else 0,
                "length": round(float(l[4]), 1) if len(l) > 4 else 0,
                "type": "wall",
            }
            for l in lines
        ],
        "unit": "pixel",
    }


# ---------------------------------------------------------------------------
# 高层入口：串起整条链路
# ---------------------------------------------------------------------------
def _save_outputs(output_dir, task_id, stitched, plane_json):
    """把拼接图和平面图 JSON 保存到输出目录（供主函数后续使用）。"""
    task_out = os.path.join(output_dir, task_id)
    os.makedirs(task_out, exist_ok=True)
    stitched_path = os.path.join(task_out, "stitched.jpg")
    cv2.imwrite(stitched_path, stitched)
    plane_json["image"]["url"] = "/outputs/%s/stitched.jpg" % task_id
    with open(os.path.join(task_out, "plane.json"), "w", encoding="utf-8") as f:
        json.dump(plane_json, f, ensure_ascii=False, indent=2)
    return task_out


def process_frames(frame_dir, output_dir="outputs", task_id=None, name="自动建模房间",
                   line_method="lsd", min_length=60, angle_tol=15, max_canvas_side=None):
    """
    从关键帧目录生成平面图（对应"上传帧"模式）。

    参数：
        frame_dir        : str  关键帧图片目录
        output_dir       : str  输出根目录
        task_id          : str  任务 id，None 则自动生成
        name             : str  房间名
        line_method      : str  直线检测方式 "lsd" 或 "hough"
        min_length, angle_tol : 直线过滤参数
        max_canvas_side  : int  拼接画布最长边上限，超过则等比缩小以防内存爆炸

    返回：
        dict : 平面图 JSON；失败返回 None
    """
    if task_id is None:
        task_id = "room_" + uuid.uuid4().hex[:8]

    stitched = stitch_keyframes(frame_dir, max_canvas_side=max_canvas_side)
    if stitched is None:
        return None

    if line_method == "hough":
        raw_lines = extract_wall_lines_hough(stitched)
        # Hough 输出只有 4 个坐标，统一补上 length/angle 以便后续合并
        raw_lines = [
            [x1, y1, x2, y2,
             float(np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)),
             float(_angle_of(x1, y1, x2, y2))]
            for x1, y1, x2, y2 in raw_lines
        ]
    else:
        raw_lines = extract_wall_lines_lsd(stitched, min_length=min_length, angle_tol=angle_tol)

    lines = merge_colinear_lines(raw_lines)
    plane_json = build_plane_json(task_id, stitched, lines, name=name)
    _save_outputs(output_dir, task_id, stitched, plane_json)
    return plane_json


def process_video(video_path, output_dir="outputs", task_id=None, max_frames=20,
                  target_size=(960, 540), frame_save_dir=None, name="自动建模房间",
                  line_method="lsd", min_length=60, angle_tol=15, max_canvas_side=None):
    """
    从视频生成平面图（对应"上传视频"模式），串起步骤 1-7。

    参数：
        video_path       : str  输入视频路径
        output_dir       : str  输出根目录
        task_id          : str  任务 id，None 则自动生成
        max_frames       : int  抽取关键帧数量
        target_size      : tuple 帧统一缩放尺寸
        frame_save_dir   : str 关键帧临时目录，None 自动创建
        name             : str  房间名
        line_method      : str  直线检测方式 "lsd" / "hough"
        min_length, angle_tol : 直线过滤参数
        max_canvas_side  : int  拼接画布最长边上限，超过则等比缩小以防内存爆炸

    返回：
        dict : 平面图 JSON；失败返回 None
    """
    if task_id is None:
        task_id = "room_" + uuid.uuid4().hex[:8]
    if frame_save_dir is None:
        frame_save_dir = os.path.join(output_dir, task_id, "frames")

    os.makedirs(frame_save_dir, exist_ok=True)
    saved = extract_keyframes(video_path, frame_save_dir, max_frames=max_frames, target_size=target_size)
    if saved is None or len(saved) < 2:
        return None

    return process_frames(frame_save_dir, output_dir=output_dir, task_id=task_id,
                          name=name, line_method=line_method,
                          min_length=min_length, angle_tol=angle_tol,
                          max_canvas_side=max_canvas_side)


def process_image_list(image_list, output_dir="outputs", task_id=None, name="自动建模房间",
                       line_method="lsd", min_length=60, angle_tol=15, max_canvas_side=None):
    """
    从内存中的有序图像列表生成平面图。

    参数：
        image_list       : list[numpy 数组]  有序图像列表
        output_dir       : str  输出根目录
        task_id          : str  任务 id，None 则自动生成
        name             : str  房间名
        line_method      : str  直线检测方式 "lsd" / "hough"
        min_length, angle_tol : 直线过滤参数
        max_canvas_side  : int  拼接画布最长边上限，超过则等比缩小以防内存爆炸

    返回：
        dict : 平面图 JSON；失败返回 None
    """
    if task_id is None:
        task_id = "room_" + uuid.uuid4().hex[:8]

    stitched = stitch_images(image_list, max_canvas_side=max_canvas_side)
    if stitched is None:
        return None

    if line_method == "hough":
        raw_lines = extract_wall_lines_hough(stitched)
        raw_lines = [
            [x1, y1, x2, y2,
             float(np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)),
             float(_angle_of(x1, y1, x2, y2))]
            for x1, y1, x2, y2 in raw_lines
        ]
    else:
        raw_lines = extract_wall_lines_lsd(stitched, min_length=min_length, angle_tol=angle_tol)

    lines = merge_colinear_lines(raw_lines)
    plane_json = build_plane_json(task_id, stitched, lines, name=name)
    _save_outputs(output_dir, task_id, stitched, plane_json)
    return plane_json
