# ============================================================
# Atom Media — 轻量级影片管理器
# 适配 linux/arm/v7（树莓派 2/3/4 32 位、玩客云等）
# 基础镜像 python:3.12-alpine ≈ 50MB，依赖均为纯 Python wheel，
# 最终镜像约 65-75MB（远低于 200MB 目标）。
#
# 构建（在树莓派上本机构建；设备 DNS 不佳导致 pip 拉取失败时加 --network=host）:
#   docker build --network=host -t atom-media:latest .
#
# 交叉构建（在 x86 电脑上）:
#   docker run --privileged --rm tonistiigi/binfmt --install armv7
#   docker buildx build --network=host --platform linux/arm/v7 -t atom-media:latest --load .
# ============================================================

FROM python:3.12-alpine

LABEL org.opencontainers.image.title="Atom Media" \
      org.opencontainers.image.description="轻量级影片信息刮削与分类管理器 (ARMv7)" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.architecture="arm32v7"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    MEDIA_DIR=/media \
    PORT=8080

# PyPI 镜像源（默认清华源；海外构建可覆盖：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.org/simple .）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

# 先装依赖再拷代码，充分利用构建缓存
# 升级 pip 提升依赖解析效率；PIP_INDEX_URL 环境变量让所有 pip 命令都走清华源
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web

# 说明：为兼容树莓派 USB 盘 / Samba 等常见 root 属主的 bind mount，
# 默认以 root 运行（媒体容器通行做法）。如需降权，可自行添加
#   user: "1000:1000"  并确保宿主机 /data、/media 目录对该 UID 可写。
RUN mkdir -p /data /media

VOLUME ["/data", "/media"]
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)" || exit 1

CMD ["python", "-m", "app.main"]
