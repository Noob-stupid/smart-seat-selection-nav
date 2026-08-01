FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（OpenCV 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
  libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
  && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 创建必要目录
RUN mkdir -p uploads data/networks data/qrcodes data/overlays instance

EXPOSE 5800

CMD ["sh", "-c", "python setup_db.py && exec gunicorn --bind 0.0.0.0:5800 --workers 1 --timeout 120 app:app"]
