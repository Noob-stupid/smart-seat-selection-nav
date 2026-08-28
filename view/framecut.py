# -*- coding: utf-8 -*-
"""
framecut.py —— 步骤2-4：特征匹配 / 单应性变换 / 全景拼接

对外接口：
    similar_frame(img1, img2, nfeatures=3000, ratio=0.75, min_good=8)
        -> (good, kp1, kp2) | None                    步骤2 特征匹配（ORB）
    marge_frame(img1, img2, matches, kp1, kp2)
        -> numpy 数组 | None                           步骤3 单应性矩阵与变换
    stitch_images(image_list, max_canvas_side=None)
        -> numpy 数组 | None                           步骤4 全景拼接
"""

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def similar_frame(img1, img2, nfeatures=3000, ratio=0.75, min_good=8):
    """
    用 ORB 计算两张图的特征点并进行匹配，返回可靠匹配点与关键点。

    参数：
        img1, img2 : numpy 数组  待匹配的两张图像
        nfeatures  : int         检测特征点数量上限
        ratio      : float       比率测试阈值（越低越严格）
        min_good   : int         有效匹配点最少数量（RANSAC 至少 8）

    返回：
        (good, kp1, kp2) : 匹配点列表 + 两张图的关键点；失败返回 None
    """
    if img1 is None or img2 is None:
        logger.warning("输入图像为空，匹配失败")
        return None

    orb = cv2.ORB_create(nfeatures=nfeatures)
    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
        logger.debug("特征点太少，跳过匹配")
        return None

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = bf.knnMatch(des1, des2, k=2)

    good = []
    for m, n in matches:
        if m.distance < ratio * n.distance:
            good.append(m)

    if len(good) < min_good:
        logger.debug("有效匹配点太少：%d，跳过", len(good))
        return None

    return good, kp1, kp2


def marge_frame(img1, img2, matches, kp1, kp2):
    """
    将 img2 变换到 img1 的坐标系，并合并为一张大图。

    参数：
        img1    : numpy 数组  当前全景图（底图）
        img2    : numpy 数组  新的一帧
        matches : similar_frame 返回的 good matches
        kp1, kp2: 对应的关键点列表

    返回：
        合并后的新图像（numpy 数组），失败返回 None
    """
    if (not matches) or kp1 is None or kp2 is None or img1 is None or img2 is None:
        logger.error("拼接参数不完整，无法合并")
        return None

    # 过滤无效匹配（索引为 -1 表示未匹配成功）
    valid = [(m.queryIdx, m.trainIdx) for m in matches
             if m.queryIdx >= 0 and m.trainIdx >= 0]
    if len(valid) < 4:
        logger.error("有效匹配点不足，无法计算单应性")
        return None

    # 提取匹配点坐标（img2 上的点 -> src，img1 上的点 -> dst）
    src_pts = np.float32([kp2[t].pt for _, t in valid]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp1[q].pt for q, _ in valid]).reshape(-1, 1, 2)

    # 计算单应性矩阵 H（从 img2 到 img1 的透视变换）
    H, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if H is None:
        logger.error("单应性矩阵计算失败")
        return None

    # 计算新画布大小（容纳两张图所有像素）
    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]

    corners1 = np.float32([[0, 0], [0, h1], [w1, h1], [w1, 0]]).reshape(-1, 1, 2)
    corners2 = np.float32([[0, 0], [0, h2], [w2, h2], [w2, 0]]).reshape(-1, 1, 2)
    corners2_t = cv2.perspectiveTransform(corners2, H)

    # 所有角点合并，求最小/最大 x, y
    all_corners = np.concatenate((corners1, corners2_t), axis=0)
    x_min, y_min = np.int32(all_corners.min(axis=0).ravel() - 0.5)
    x_max, y_max = np.int32(all_corners.max(axis=0).ravel() + 0.5)

    new_w = int(x_max - x_min)
    new_h = int(y_max - y_min)

    # 构造平移矩阵，使所有坐标为正
    translation = np.float32([[1, 0, -x_min], [0, 1, -y_min], [0, 0, 1]])
    H_final = translation @ H

    # 执行透视变换（将 img2 投射到新画布）
    result = cv2.warpPerspective(img2, H_final, (new_w, new_h))

    # 将 img1 覆盖到结果图像的相应位置（左上角偏移）
    result[-y_min:-y_min + h1, -x_min:-x_min + w1] = img1

    return result


def _resize_if_needed(img, max_side):
    """若图像最长边超过 max_side，则等比缩小。"""
    if max_side is None or img is None:
        return img
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > max_side:
        scale = max_side / float(longest)
        return cv2.resize(img, (int(w * scale), int(h * scale)))
    return img


def stitch_images(image_list, max_canvas_side=None):
    """
    将有序的图像列表逐帧拼接成全景图，匹配/合并失败的帧会自动跳过。

    参数：
        image_list       : list[numpy 数组]  有序图像列表（建议已统一尺寸）
        max_canvas_side  : int  拼接画布最长边上限，超过则等比缩小以防内存爆炸；
                               默认 None 表示不限制

    返回：
        最终全景图（numpy 数组），失败返回 None
    """
    if len(image_list) < 2:
        logger.warning("图像列表少于2张，无法拼接")
        return None

    # 取第一张作为初始底图（复制，避免修改原数据）
    result = image_list[0].copy()

    for i in range(1, len(image_list)):
        img = image_list[i]

        # 特征匹配
        matched = similar_frame(result, img)
        if matched is None:
            logger.warning("第 %d 张匹配失败，跳过", i + 1)
            continue

        good, kp1, kp2 = matched
        new_result = marge_frame(result, img, good, kp1, kp2)
        if new_result is None:
            logger.warning("第 %d 张合并失败，跳过", i + 1)
            continue

        result = new_result
        result = _resize_if_needed(result, max_canvas_side)
        logger.info("第 %d 张拼接成功，当前全景尺寸：%dx%d", i + 1, result.shape[1], result.shape[0])

    return result