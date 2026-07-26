import cv2
import numpy as np
class ImagePreprocessor:
  '''图像预处理：图片标准化，增强，为语义分割ai做准备'''
  def __init__(self,target_size=(512,512)):
    self.target_size=target_size
    
  def preprocessor(self,image_path):
    """
    输入：原始图片路径
    输出：预处理后的图像数组,适配模型输入
    """
    #1.读取图像
    img=cv2.imread(image_path)
    if img is None:
      raise ValueError(f"无法读取图像,{image_path}")
    #2.BGR转RGB,RGB是ai使用格式统一颜色空间
    img_rgb=cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
    #3.记录原始尺寸（后续需要映射回原始坐标）
    original_shape=img_rgb.shape[:2]
    #4.自适应直方图均衡化(增强对比度，让墙体、通道更清晰)
    img_enhanced=self._enhance_contrast(img_rgb)
    #5.缩放模型输入尺寸(保持宽高比，填充)
    img_resized=self._resize_with_padding(img_enhanced)
    #6.归一化(模型需要的标准输入)
    img_normalized=self._normalize(img_resized)
    return {
      'image':img_normalized,#模型输入（3，512，512）
      'original_shape':original_shape,#原始尺寸，用于坐标映射
      'scale_factors':self._calculate_scale_factors(original_shape)
    }
  def _enhance_contrast(self,img):
    """CLAHE自适应直方图均衡化"""
    #转到LAB颜色空间(L通道控制亮度)
    lab=cv2.cvtColor(img,cv2.COLOR_RGB2LAB)
    l,a,b=cv2.split(lab)
    #对L亮度通道做CLAHE
    # clipLimit=2.0对比度限制阈值。数值越大，明暗增强力度越强
    # tileGridSize=(8,8)把整张图片切成 8×8 个小方格，每个方格单独做直方图均衡（自适应的核心）。
    clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8))
    l_enhanced=clahe.apply(l)
    #合并回去
    lab_enhanced=cv2.merge([l_enhanced,a,b])
    img_enhanced=cv2.cvtColor(lab_enhanced,cv2.COLOR_LAB2RGB)
    
    return img_enhanced
  
  def _resize_with_padding(self,img):
    """缩放并填充到目标尺寸，保持宽高比"""
    h,w=img.shape[0:2]
    target_h,target_w=self.target_size
    #计算缩放比例
    scale=min(target_w/w,target_h/h)
    new_w,new_h=int(w*scale),int(h*scale)
    #缩放
    resized=cv2.resize(img,(new_w,new_h))
    
    #创建白色背景
    padded=np.ones((target_h,target_w,3),dtype=np.uint8)*255
    #居中放置
    y_offset = (target_h - new_h) // 2
    x_offset = (target_w - new_w) // 2
    padded[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
    
    return padded