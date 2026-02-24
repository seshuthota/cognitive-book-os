#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR"
echo "[check] Running backend tests..."
uv run --extra dev pytest -q

echo "[check] Building frontend..."
cd "$ROOT_DIR/frontend"
npm run build

echo "[check] All checks passed."
