FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMRIP_CONFIG_PATH=/config/streamrip/config.toml \
    DOWNLOAD_TARGET_DIR=/downloads \
    JOBS_FILE=/data/jobs.json \
    PORT=8686

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY *.py ./

RUN mkdir -p /config/streamrip /downloads /data

EXPOSE 8686

VOLUME ["/config", "/downloads", "/data"]

CMD ["python", "main.py"]
