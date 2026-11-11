# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS python-deps
WORKDIR /build
COPY requirements-lock.txt ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements-lock.txt

FROM python:3.12-slim-bookworm AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 zamp && useradd --uid 10001 --gid zamp --no-create-home zamp
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    ZAMP_DB_PATH=/data/zamp.sqlite3 ZAMP_DOCUMENT_DIR=/data/documents \
    GEMINI_MODEL=gemini-3.1-flash-lite PORT=8000
WORKDIR /app
COPY --from=python-deps /opt/venv /opt/venv
COPY app/ ./app/
COPY scripts/seed.py scripts/container_start.py ./scripts/
COPY fixtures/synthetic_dataset.json ./fixtures/synthetic_dataset.json
COPY fixtures/*.pdf ./fixtures/
COPY --from=frontend /build/dist ./frontend/dist
# Cloud checkouts can have owner-only source permissions. The server runs as
# UID 10001, with read access to immutable code and write access only under /data.
RUN chmod -R a+rX /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/health',timeout=3).close()"
CMD ["python", "-m", "scripts.container_start"]
