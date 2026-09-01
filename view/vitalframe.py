# -*- coding: utf-8 -*-
"""
vitalframe.py —— 步骤1：视频关键帧提取

从视频中按均匀间隔抽取固定数量的关键帧并保存为 jpg。
对外接口：
    vitalframe(video_path, save_path, max_frames=20, target_size=None) -> list[str]

说明：后续可扩展"按大环境变化 big_diff 分组保存"的新需求。
"""

import os
import logging
import uuid

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def vitalframe(video_path, save_path, max_frames=20, target_size=None):
    """
    从视频抽取关键帧并保存为 jpg。

    参数：
        video_path  : str   输入视频路径
        save_path   : str   保存帧图片的目录（不存在会自动创建）
        max_frames  : int   最多抽取的帧数
        target_size : tuple 统一缩放尺寸 (w, h)，None 表示保持原尺寸

    返回：
        list[str] : 保存后的帧图片路径列表；失败返回 None，无帧返回 []
    """
    if save_path:
        os.makedirs(save_path, exist_ok=True)

    video = cv2.VideoCapture(video_path)
    if not video.isOpened():
        logger.error("视频无法打开: %s", video_path)
        return None

    try:
        max_frames = max(1, int(max_frames))
        all_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        # 候选采样：均匀采样最多 3*max_frames 张候选帧，之后按差异/清晰度筛选
        if all_frames > max_frames * 3:
            sample_every = max(1, all_frames // (max_frames * 3))
        else:
            sample_every = 1

        candidates = []
        idx = 0
        while len(candidates) < max_frames * 3:
            ret, frame = video.read()
            if not ret:
                break
            if idx % sample_every == 0 or len(candidates) == 0:
                if target_size is not None:
                    frame = cv2.resize(frame, target_size)
                candidates.append(frame)
            idx += 1

        if not candidates:
            logger.warning("视频未读取到任何帧")
            return []

        # 清晰度（Laplacian 方差）与帧间差异（灰度均值绝对差）
        grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in candidates]
        sharpness = [float(cv2.Laplacian(g, cv2.CV_64F).var()) for g in grays]
        diffs = [0.0]
        for i in range(1, len(grays)):
            diffs.append(float(np.abs(grays[i].astype(np.float32) - grays[i - 1].astype(np.float32)).mean()))

        diff_baseline = float(np.median(diffs)) * 0.6 or 1.0
        sharp_baseline = max(10.0, float(np.median(sharpness)) * 0.3)

        # 第一帧必选；后续按差异+清晰度筛选
        picked = []
        for i in range(len(candidates)):
            if i == 0:
                picked.append(i)
                continue
            if diffs[i] >= diff_baseline and sharpness[i] >= sharp_baseline:
                picked.append(i)
                if len(picked) >= max_frames:
                    break
        # 不足时放宽清晰度门槛补足（仍保证画面差异）
        if len(picked) < max_frames:
            for i in range(len(candidates)):
                if i in picked:
                    continue
                if sharpness[i] >= sharp_baseline * 0.5:
                    picked.append(i)
                    if len(picked) >= max_frames:
                        break

        frames_selected = [candidates[i] for i in sorted(picked)]
        saved_list = []
        for idx2, frame in enumerate(frames_selected):
            path = os.path.join(save_path, "%04d_%s.jpg" % (idx2, uuid.uuid4().hex[:8]))
            if cv2.imwrite(path, frame):
                saved_list.append(path)

        logger.info("候选 %d 帧，按差异/清晰度选定 %d 帧，保存到 %s",
                    len(candidates), len(saved_list), save_path)
        return saved_list
    except Exception as e:
        logger.error("抽帧失败: %s", e)
        return None
    finally:
        video.release()


if __name__ == "__main__":
    print("开始关键帧提取======:")
    save_path = "frames"
    video_path = r"videos\校园青春.mp4"
    ceshi = vitalframe(video_path, save_path)
    if ceshi:
        print("测试成功，提取关键帧数量：%d" % len(ceshi))
        all_exist = all(os.path.isfile(p) for p in ceshi)
        print("提取关键帧图片真实存在" if all_exist else "部分帧文件缺失")
    else:
        print("提取失败")
# 新需求：设置每一大环境变换 big_diff 就保存为一组，