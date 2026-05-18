FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 源码打入镜像
COPY configs/ configs/
COPY src/ src/
COPY api/ api/
COPY pipeline.py .
COPY run_api.py .

# 数据通过 Volume 外部挂载 (铁律七)
VOLUME ["/app/data", "/app/models", "/app/logs"]

# 默认入口：执行全流水线
CMD ["python", "pipeline.py"]
