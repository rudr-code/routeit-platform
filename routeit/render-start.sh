#!/usr/bin/env bash
# Render Start Script for Route.it
set -o errexit

export PYTHONPATH=engine:reference:roads:traffic:backend
export ROUTEIT_ENV=production
export ROUTEIT_FRONTEND_DIST="$(pwd)/frontend/dist"
export ROUTEIT_SQLITE_PATH="${ROUTEIT_SQLITE_PATH:-./data/routeit.db}"

echo "==> Starting Route.it on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
