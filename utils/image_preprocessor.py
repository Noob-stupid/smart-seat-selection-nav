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
        tu_xiang_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)   # 转为 RGB 格式
        yuan_shi_chi_cun = tu_xiang_rgb.shape[:2]             # 原始高、宽
        zeng_qiang_tu = self._zeng_qiang_dui_bi_du(tu_xiang_rgb)
        suo_fang_tu = self._suo_fang_bing_tian_chong(zeng_qiang_tu)
        gui_yi_tu = self._gui_yi_hua(suo_fang_tu)
        return {
            'image': gui_yi_tu,
            'original_shape': yuan_shi_chi_cun,
            'scale_factors': self._ji_suan_suo_fang_xi_shu(yuan_shi_chi_cun)
        }

    def _zeng_qiang_dui_bi_du(self, img):
        """在 LAB 色彩空间增强亮度通道对比度"""
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)              # L=亮度, A=绿红, B=蓝黄
        dui_bi_zeng_qiang = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        l_zeng_qiang = dui_bi_zeng_qiang.apply(l)   # 只对亮度通道做直方图均衡
        lab_zeng_qiang = cv2.merge([l_zeng_qiang, a, b])
        return cv2.cvtColor(lab_zeng_qiang, cv2.COLOR_LAB2RGB)

    def _suo_fang_bing_tian_chong(self, img):
        """等比缩放并用白色填充到目标尺寸（不拉伸变形）"""
        h, w = img.shape[:2]
        target_h, target_w = self.target_size
        suo_fang_bi = min(target_w / w, target_h / h)
        new_w, new_h = int(w * suo_fang_bi), int(h * suo_fang_bi)
        suo_fang_tu = cv2.resize(img, (new_w, new_h))
        tian_chong_tu = np.ones((target_h, target_w, 3), dtype=np.uint8) * 255
        y_pian_yi = (target_h - new_h) // 2
        x_pian_yi = (target_w - new_w) // 2
        tian_chong_tu[y_pian_yi:y_pian_yi+new_h, x_pian_yi:x_pian_yi+new_w] = suo_fang_tu
        return tian_chong_tu

    def _gui_yi_hua(self, img):
        """归一化到 [0,1]，再用 ImageNet 均值/方差标准化，并转为 CHW 格式"""
        img = img.astype(np.float32) / 255.0
        jun_zhi = np.array([0.485, 0.456, 0.406])          # ImageNet 均值
        biao_zhun_cha = np.array([0.229, 0.224, 0.225])    # ImageNet 标准差
        img = (img - jun_zhi) / biao_zhun_cha
        img = img.transpose(2, 0, 1)  # HWC -> CHW
        return img

    def _ji_suan_suo_fang_xi_shu(self, yuan_shi_chi_cun):
        """计算缩放系数（等比缩放下 x/y 方向系数相同）"""
        h, w = yuan_shi_chi_cun
        target_h, target_w = self.target_size
        suo_fang_bi = min(target_w / w, target_h / h)
        return (suo_fang_bi, suo_fang_bi)