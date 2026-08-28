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
        # 总帧数足够多时按间隔抽样，否则逐帧
        jiange_frames = all_frames // max_frames if all_frames > max_frames else 1
        jiange_frames = max(1, jiange_frames)

        frames = []
        getframe = 0
        frame_count = 0
        while getframe < max_frames:
            ret, frame = video.read()
            if not ret:
                break
            if frame_count % jiange_frames == 0 or getframe == 0:
                frames.append(frame)
                getframe += 1
            frame_count += 1

        if not frames:
            logger.warning("视频未读取到任何帧")
            return []

        saved_list = []
        for idx, frame in enumerate(frames):
            if target_size is not None:
                frame = cv2.resize(frame, target_size)
            path = os.path.join(save_path, "%04d_%s.jpg" % (idx, uuid.uuid4().hex[:8]))
            if cv2.imwrite(path, frame):
                saved_list.append(path)

        logger.info("共抽取 %d 帧关键帧，保存到 %s", len(saved_list), save_path)
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