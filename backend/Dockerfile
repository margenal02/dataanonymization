ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG DEBIAN_MIRROR=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PPNLP_HOME=/opt/paddlenlp \
    UIE_MODEL=uie-micro

RUN echo "[后端构建 1/4] 配置 Debian 镜像并安装系统依赖" \
    && if [ -n "$DEBIAN_MIRROR" ]; then \
        sed -i \
          -e "s|https://deb.debian.org/debian-security|${DEBIAN_MIRROR}-security|g" \
          -e "s|http://deb.debian.org/debian-security|${DEBIAN_MIRROR}-security|g" \
          -e "s|https://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
          -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
          /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN echo "[后端构建 2/4] 更新 pip" \
    && python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --upgrade pip==26.2.1 \
    && echo "[后端构建 3/4] 从选定镜像安装 Django、PaddlePaddle 与 PaddleNLP" \
    && python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --progress-bar on -r requirements.txt
COPY . .
RUN echo "[后端构建 4/4] 下载、转换并自检 UIE-micro 模型" \
    && python /app/prefetch_uie.py \
    && chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
