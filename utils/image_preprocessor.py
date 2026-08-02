import cv2
import numpy as np

class ImagePreprocessor:
    """平面图图像预处理器：统一缩放、增强对比度并归一化，供模型使用"""

    def __init__(self, target_size=(512, 512)):
        self.target_size = target_size  # 目标尺寸（宽, 高）

    def preprocessor(self, image_path):
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"无法读取图像, {image_path}")
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)   # 转为 RGB 格式
        original_shape = img_rgb.shape[:2]               # 原始高、宽
        img_enhanced = self._enhance_contrast(img_rgb)
        img_resized = self._resize_with_padding(img_enhanced)
        img_normalized = self._normalize(img_resized)
        return {
            'image': img_normalized,
            'original_shape': original_shape,
            'scale_factors': self._calculate_scale_factors(original_shape)
        }

    def _enhance_contrast(self, img):
        """在 LAB 色彩空间增强亮度通道对比度"""
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)              # L=亮度, A=绿红, B=蓝黄
        contrast_enhancer = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        l_enhanced = contrast_enhancer.apply(l)   # 只对亮度通道做直方图均衡
        lab_enhanced = cv2.merge([l_enhanced, a, b])
        return cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2RGB)

    def _resize_with_padding(self, img):
        """等比缩放并用白色填充到目标尺寸（不拉伸变形）"""
        h, w = img.shape[:2]
        target_h, target_w = self.target_size
        scale = min(target_w / w, target_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(img, (new_w, new_h))
        padded = np.ones((target_h, target_w, 3), dtype=np.uint8) * 255
        y_offset = (target_h - new_h) // 2
        x_offset = (target_w - new_w) // 2
        padded[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
        return padded

    def _normalize(self, img):
        """归一化到 [0,1]，再用 ImageNet 均值/方差标准化，并转为 CHW 格式"""
        img = img.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406])          # ImageNet 均值
        std = np.array([0.229, 0.224, 0.225])           # ImageNet 标准差
        img = (img - mean) / std
        img = img.transpose(2, 0, 1)  # HWC -> CHW
        return img

    def _calculate_scale_factors(self, original_shape):
        """计算缩放系数（等比缩放下 x/y 方向系数相同）"""
        h, w = original_shape
        target_h, target_w = self.target_size
        scale = min(target_w / w, target_h / h)
        return (scale, scale)