FROM node:22-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
COPY frontend/.npmrc ./
RUN npm install --include=optional --no-fund --no-audit
COPY frontend/ ./

RUN npm run build


FROM python:3.13-slim AS backend-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl krb5-user \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
COPY deploy/docker/entrypoint.sh /app/deploy/docker/entrypoint.sh

RUN chmod +x /app/deploy/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/deploy/docker/entrypoint.sh"]
