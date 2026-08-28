# -*- coding: utf-8 -*-
"""
main_example.py —— 调用示例（主函数可参考此写法）

这是"主函数如何调用 auto_mapping"的示例。
你只需要关注如何调用 process_video / process_frames 等高层接口即可。
"""

import os
from auto_mapping import process_video, process_frames, process_image_list


def main():
    # ---------------- 方式 1：从视频生成平面图 ----------------
    video_path = r"videos\校园青春.mp4"
    output_dir = "outputs"
    if os.path.exists(video_path):
        result = process_video(
            video_path,
            output_dir=output_dir,
            task_id="room_video_demo",
            max_frames=20,
            target_size=(960, 540),
            name="演示房间",
            line_method="lsd",   # 可改为 "hough"
        )
        if result is not None:
            print("视频建图成功！")
            print("拼接图尺寸：%dx%d" % (result["image"]["width"], result["image"]["height"]))
            print("检测到墙体线段数：%d" % len(result["lines"]))
        else:
            print("视频建图失败")

    # ---------------- 方式 2：直接从关键帧目录生成 ----------------
    frame_dir = "frames"
    if os.path.isdir(frame_dir):
        result2 = process_frames(
            frame_dir,
            output_dir=output_dir,
            task_id="room_frames_demo",
            name="演示房间",
            line_method="lsd",
        )
        if result2 is not None:
            print("帧目录建图成功！线段数：%d" % len(result2["lines"]))

    # ---------------- 方式 3：从内存图像列表生成 ----------------
    # import cv2
    # image_list = [cv2.imread(os.path.join(frame_dir, f)) for f in sorted(os.listdir(frame_dir)) if f.endswith('.jpg')]
    # image_list = [im for im in image_list if im is not None]
    # result3 = process_image_list(image_list, output_dir=output_dir, task_id="room_mem_demo")


if __name__ == "__main__":
    main()
