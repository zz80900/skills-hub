#!/bin/sh
set -eu

cd /app/backend

exec uvicorn app.main:app --host 0.0.0.0 --port 8000

