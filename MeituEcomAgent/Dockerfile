# ============================================================
# MeituEcomAgent
# ============================================================
FROM python:3.11-slim AS builder

RUN echo "deb http://deb.debian.org/debian bookworm main" > /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian bookworm-updates main" >> /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian-security bookworm-security main" >> /etc/apt/sources.list

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
        libgomp1 libjpeg62-turbo libpng16-16 libwebp7 gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --retries 5 -r requirements.txt

# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN echo "deb http://deb.debian.org/debian bookworm main" > /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian bookworm-updates main" >> /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian-security bookworm-security main" >> /etc/apt/sources.list

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libgomp1 \
        libjpeg62-turbo libpng16-16 libwebp7 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

RUN groupadd -r appuser && useradd -r -g appuser -m appuser
RUN mkdir -p knowledge_base knowledge_base_index workflows output \
    && chown -R appuser:appuser /app

COPY --chown=appuser:appuser . .

USER appuser
ENV U2NET_HOME=/app/.u2net
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
