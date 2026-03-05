#!/bin/bash
# Zonik Upgrade Script
set -euo pipefail

ZONIK_DIR="/opt/zonik"

echo "╔══════════════════════════════════════╗"
echo "║         Zonik Upgrade                ║"
echo "╚══════════════════════════════════════╝"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root"
    exit 1
fi

if [ ! -d "$ZONIK_DIR/.git" ]; then
    echo "Error: Zonik not found at $ZONIK_DIR"
    exit 1
fi

cd "$ZONIK_DIR"

# Get current and new versions
OLD_VERSION=$("$ZONIK_DIR/venv/bin/python" -c "import importlib.metadata; print(importlib.metadata.version('zonik'))" 2>/dev/null || echo "unknown")

echo "[1/5] Pulling latest code..."
git fetch origin
git pull --ff-only origin main

NEW_VERSION=$("$ZONIK_DIR/venv/bin/python" -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])
")

echo "  $OLD_VERSION → $NEW_VERSION"

echo "[2/5] Updating Python dependencies..."
"$ZONIK_DIR/venv/bin/pip" install -e "$ZONIK_DIR[analysis,clap]" -q

echo "[3/5] Rebuilding frontend..."
cd "$ZONIK_DIR/frontend"
npm install --silent 2>/dev/null
npm run build
cd "$ZONIK_DIR"

echo "[4/5] Running database migrations..."
"$ZONIK_DIR/venv/bin/python" -c "
import asyncio
from backend.database import init_db
asyncio.run(init_db())
print('  Database up to date.')
"

if [ "${SKIP_RESTART:-0}" = "1" ]; then
    echo "Skipping service restart (managed by web UI)."
else
    echo "[5/5] Restarting services..."
    systemctl restart zonik-web zonik-worker
    echo ""
    echo "Zonik upgraded to v$NEW_VERSION"
    echo "Services restarted."
fi
