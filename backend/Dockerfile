ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG DEBIAN_MIRROR=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PPNLP_HOME=/opt/paddlenlp \
    UIE_MODEL=uie-micro

RUN if [ -n "$DEBIAN_MIRROR" ]; then \
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
RUN python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --upgrade pip==26.2.1 \
    && python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt
COPY . .
RUN python /app/prefetch_uie.py \
    && chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
