# Stage 1: build the React UI to frontend/dist
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: FastAPI app, which also serves the built UI
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    CONFIG_PATH=/app/config.yaml \
    FRONTEND_DIST=/app/frontend/dist \
    DB_PATH=/data/app.db \
    UPLOAD_DIR=/data/uploads \
    PORT=8000

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/tools ./tools
COPY config.yaml /app/config.yaml
COPY data /app/data
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY deploy/entrypoint.sh /entrypoint.sh

# A Windows checkout can give the script CRLF endings, which sh cannot run. No VOLUME line: the
# platform attaches the volume at /data, and the folder below works without one too.
RUN sed -i 's/\r$//' /entrypoint.sh \
    && chmod +x /entrypoint.sh \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/uploads \
    && chown -R app:app /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import json, os, sys, urllib.request as u; r = u.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4); sys.exit(0 if json.load(r)['ok'] else 1)"]

# Starts as root only to fix /data ownership, then drops to the app user. One worker on purpose:
# SSE subscribers and the run lock live in process memory.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
