# Fidelity as one container (spec §10: "server: Linux service or containers; the application is unchanged").
# Build:  docker compose build      Run:  docker compose up -d      Open:  http://127.0.0.1:8000

# ---- 1. web interface
FROM node:20-bookworm-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2. application
FROM python:3.11-slim-bookworm
ENV PYTHONUTF8=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    QA_SERVER_HOST=0.0.0.0 QA_SERVER_PORT=8000
# Tesseract (second OCR engine) and the libraries OpenCV/RapidOCR need
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libgl1 libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
COPY adapters/ adapters/
COPY --from=web /app/web/dist web/dist
# Runs as an ordinary user; everything the app writes lives in the two data volumes
RUN useradd --create-home --uid 1000 fidelity \
 && mkdir -p data backend/data \
 && chown -R fidelity:fidelity data backend/data
USER fidelity
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1
# OCR model is fetched once into the data volume (pinned + hash-checked); then the app starts
CMD ["sh", "-c", "python scripts/fetch_ocr_models.py || echo 'OCR model not fetched (offline?) - scans go to review'; exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
