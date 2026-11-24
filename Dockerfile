# ==============================================================================
# Route.it Multi-Stage Production Dockerfile for Render Deployment
# Stage 1: Build the React + TypeScript + Vite Dispatcher UI
# Stage 2: Fast Python 3.11 Runtime serving both /v1 REST API and UI SPA
# ==============================================================================

# --- Stage 1: Frontend Build ---
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY routeit/frontend/package.json routeit/frontend/tsconfig.json routeit/frontend/vite.config.ts routeit/frontend/index.html ./
COPY routeit/frontend/src ./src

RUN npm install && npm run build

# --- Stage 2: Python Backend Runtime ---
FROM python:3.11-slim AS production

# Install curl for container health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python modules and package definitions
COPY routeit/pyproject.toml routeit/README.md ./
COPY routeit/engine ./engine
COPY routeit/reference ./reference
COPY routeit/roads ./roads
COPY routeit/traffic ./traffic
COPY routeit/backend ./backend

# Install python dependencies
RUN pip install --no-cache-dir .

# Copy built frontend SPA from Stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Set runtime environment
ENV PYTHONPATH=/app/engine:/app/reference:/app/roads:/app/traffic:/app/backend
ENV ROUTEIT_ENV=production
ENV ROUTEIT_SQLITE_PATH=/app/data/routeit.db
ENV ROUTEIT_FRONTEND_DIST=/app/frontend/dist
ENV ROUTEIT_API_HOST=0.0.0.0
ENV PORT=8000

# Create persistent/working data directory for SQLite
RUN mkdir -p /app/data

EXPOSE 8000

# Render assigns dynamic $PORT at runtime (e.g. 10000)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
