#!/bin/bash
# Zonik Installer for Proxmox LXC (Debian 12)
# Usage: curl -sL https://raw.githubusercontent.com/Pr0zak/Zonik/main/install.sh | bash
set -euo pipefail

ZONIK_DIR="/opt/zonik"
CONFIG_DIR="/etc/zonik"
DATA_DIR="/opt/zonik/data"
CACHE_DIR="/opt/zonik/cache"
MUSIC_DIR="/music"
DOWNLOAD_DIR="/downloads"

echo "╔══════════════════════════════════════╗"
echo "║         Zonik Installer v0.1         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root"
    exit 1
fi

# Check Debian 12
if ! grep -q 'bookworm' /etc/os-release 2>/dev/null; then
    echo "Warning: This installer is designed for Debian 12 (Bookworm)"
    echo "Continuing anyway..."
fi

echo "[1/8] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    ffmpeg libchromaprint-dev \
    redis-server \
    nodejs npm \
    git curl build-essential \
    libffi-dev libssl-dev \
    > /dev/null

echo "[2/8] Cloning Zonik..."
if [ -d "$ZONIK_DIR/.git" ]; then
    echo "  Existing installation found, pulling latest..."
    cd "$ZONIK_DIR"
    git pull --ff-only
else
    git clone https://github.com/Pr0zak/Zonik.git "$ZONIK_DIR"
    cd "$ZONIK_DIR"
fi

echo "[3/8] Setting up Python environment..."
python3 -m venv "$ZONIK_DIR/venv"
"$ZONIK_DIR/venv/bin/pip" install --upgrade pip setuptools wheel -q
"$ZONIK_DIR/venv/bin/pip" install -e "$ZONIK_DIR" -q

echo "[4/8] Building frontend..."
cd "$ZONIK_DIR/frontend"
npm install --silent 2>/dev/null
npm run build
cd "$ZONIK_DIR"

echo "[5/8] Creating directories..."
mkdir -p "$DATA_DIR" "$CACHE_DIR/covers" "$CONFIG_DIR" "$MUSIC_DIR" "$DOWNLOAD_DIR"

echo "[6/8] Setting up configuration..."
if [ ! -f "$CONFIG_DIR/zonik.toml" ]; then
    cp "$ZONIK_DIR/zonik.toml.example" "$CONFIG_DIR/zonik.toml"
    # Generate random secret key
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s/change-me-to-a-random-string/$SECRET/" "$CONFIG_DIR/zonik.toml"
    echo "  Config created at $CONFIG_DIR/zonik.toml"
    echo "  Please edit it with your API keys and settings."
else
    echo "  Config already exists, skipping."
fi

# Symlink config so backend finds it
ln -sf "$CONFIG_DIR/zonik.toml" "$ZONIK_DIR/zonik.toml"

echo "[7/8] Initializing database..."
cd "$ZONIK_DIR"
"$ZONIK_DIR/venv/bin/python" -c "
import asyncio
from backend.database import init_db
asyncio.run(init_db())
print('  Database initialized.')
"

echo "[8/8] Installing systemd services..."
cp "$ZONIK_DIR/deploy/zonik-web.service" /etc/systemd/system/
cp "$ZONIK_DIR/deploy/zonik-worker.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable redis-server zonik-web zonik-worker
systemctl start redis-server
systemctl start zonik-web
systemctl start zonik-worker

echo ""
echo "══════════════════════════════════════"
echo " Zonik installed successfully!"
echo ""
echo " Web UI:  http://$(hostname -I | awk '{print $1}'):3000"
echo " Config:  $CONFIG_DIR/zonik.toml"
echo " Music:   $MUSIC_DIR"
echo " Data:    $DATA_DIR"
echo ""
echo " Default Subsonic credentials: admin / admin"
echo ""
echo " Next steps:"
echo "   1. Edit $CONFIG_DIR/zonik.toml with your API keys"
echo "   2. Mount your music library to $MUSIC_DIR"
echo "   3. Run a library scan from the web UI"
echo "   4. Point Symfonium at http://<IP>:3000/rest"
echo "══════════════════════════════════════"
