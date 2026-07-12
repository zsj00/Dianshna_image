# ============================================================
# MeituEcomAgent - 美图电商智能生图代理服务
# ============================================================
# 一键启动: 双击项目根目录下的 start.bat
# 手动构建: docker build -t meitu-ecom-agent .
# 手动运行: docker run -p 8000:8000 --env-file .env meitu-ecom-agent
# ============================================================

# ---- 构建阶段 ----
FROM docker.m.daocloud.io/library/python:3.11-slim AS builder

# ---- 替换 apt 源（阿里云 → 清华 → 中科大 多级回退） ----
RUN echo "deb http://deb.debian.org/debian bookworm main contrib non-free" > /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian bookworm-updates main contrib non-free" >> /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian-security bookworm-security main contrib non-free" >> /etc/apt/sources.list \
    && ( sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list \
      || sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list \
      || sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list \
      || true )

# ---- 安装系统依赖和编译工具（带重试） ----
RUN for i in 1 2 3; do \
        apt-get update && apt-get install -y --no-install-recommends \
            libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
            libgomp1 libjpeg62-turbo libpng16-16 libwebp7 gcc g++ \
        && break || sleep 3 ; \
    done \
    && rm -rf /var/lib/apt/lists/*

# ---- 安装 Python 依赖（清华镜像） ----
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -r requirements.txt

# ============================================================
# 运行阶段
# ============================================================
FROM docker.m.daocloud.io/library/python:3.11-slim AS runtime

LABEL maintainer="MeituEcomAgent"
LABEL description="美图电商智能生图代理服务 — 多平台商品图片自动生成与合规审核"

WORKDIR /app

# ---- 替换 apt 源（多级回退） ----
RUN echo "deb http://deb.debian.org/debian bookworm main contrib non-free" > /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian bookworm-updates main contrib non-free" >> /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian-security bookworm-security main contrib non-free" >> /etc/apt/sources.list \
    && sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list

# ---- 安装运行时依赖（带重试） ----
RUN for i in 1 2 3; do \
        apt-get update && apt-get install -y --no-install-recommends \
            libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libgomp1 \
            libjpeg62-turbo libpng16-16 libwebp7 curl \
        && break || sleep 3 ; \
    done \
    && rm -rf /var/lib/apt/lists/*

# ---- 从 builder 复制编译好的 Python 包 ----
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# ---- 创建非 root 用户 ----
RUN groupadd -r appuser && useradd -r -g appuser -m appuser

# ---- 创建必要目录并设权限 ----
RUN mkdir -p knowledge_base knowledge_base_index workflows output && \
    chown -R appuser:appuser /app

# ---- 复制项目代码 ----
COPY --chown=appuser:appuser . .

# ---- 切换到非 root 用户 ----
USER appuser

# ---- rembg 模型目录（首次运行自动下载 ~4MB，有30s超时兜底） ----
ENV U2NET_HOME=/app/.u2net

# ---- 暴露端口 ----
EXPOSE 8000

# ---- 健康检查 ----
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# ---- 启动 ----
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
