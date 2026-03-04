#!/bin/bash
# Zonik CT Creator - Run on Proxmox host
# Interactively creates a Debian 12 LXC container and installs Zonik
#
# Usage: bash create-ct.sh

set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

msg()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

ask() {
    local prompt="$1" default="$2" var="$3"
    if [ -n "$default" ]; then
        read -rp "$(echo -e "  ${prompt} ${DIM}[${default}]${NC}: ")" input
        eval "$var='${input:-$default}'"
    else
        read -rp "$(echo -e "  ${prompt}: ")" input
        eval "$var='$input'"
    fi
}

ask_yn() {
    local prompt="$1" default="$2"
    read -rp "$(echo -e "  ${prompt} ${DIM}[${default}]${NC}: ")" input
    input="${input:-$default}"
    [[ "$input" =~ ^[Yy] ]]
}

select_option() {
    local prompt="$1" var="$2"
    shift 2
    local options=("$@")
    local count=${#options[@]}

    echo -e "  ${prompt}:"
    for i in "${!options[@]}"; do
        echo -e "    ${CYAN}$((i+1))${NC}) ${options[$i]}"
    done
    read -rp "$(echo -e "  Select ${DIM}[1]${NC}: ")" choice
    choice="${choice:-1}"
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$count" ]; then
        eval "$var='${options[$((choice-1))]}'"
    else
        eval "$var='${options[0]}'"
    fi
}

# ─── Checks ──────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║      Zonik CT Creator for Proxmox        ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

if ! command -v pct &>/dev/null; then
    err "This script must be run on a Proxmox host (pct not found)"
fi

# ─── Auto-detect next available CTID ─────────────────────────────
CTID=$(pvesh get /cluster/nextid 2>/dev/null || echo "100")
msg "Next available CT ID: ${BOLD}$CTID${NC}"
echo ""

# ─── Hostname ────────────────────────────────────────────────────
ask "Hostname" "zonik" HOSTNAME

# ─── Storage selection ───────────────────────────────────────────
echo ""
echo -e "${BOLD}── Storage ──${NC}"

# Get available storages that support rootdir/images
mapfile -t STORAGE_LIST < <(pvesm status --content rootdir 2>/dev/null | tail -n +2 | awk '{print $1}' || echo "local-lvm")
if [ ${#STORAGE_LIST[@]} -eq 0 ]; then
    # Fallback: try content=images
    mapfile -t STORAGE_LIST < <(pvesm status --content images 2>/dev/null | tail -n +2 | awk '{print $1}' || echo "local-lvm")
fi
if [ ${#STORAGE_LIST[@]} -eq 0 ]; then
    STORAGE_LIST=("local-lvm")
fi

if [ ${#STORAGE_LIST[@]} -eq 1 ]; then
    STORAGE="${STORAGE_LIST[0]}"
    msg "Using storage: ${BOLD}$STORAGE${NC}"
else
    select_option "Select storage for rootfs" STORAGE "${STORAGE_LIST[@]}"
fi

# ─── Resources ───────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── Resources ──${NC}"
echo -e "  ${DIM}Defaults: 2 cores, 2048MB RAM, 512MB swap, 16GB disk${NC}"

if ask_yn "Use default resources?" "Y"; then
    CORES=2
    MEMORY=2048
    SWAP=512
    DISK_SIZE=16
else
    ask "CPU cores" "2" CORES
    ask "Memory (MB)" "2048" MEMORY
    ask "Swap (MB)" "512" SWAP
    ask "Disk size (GB)" "16" DISK_SIZE
fi

# ─── Network ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── Network ──${NC}"

# Detect bridges
mapfile -t BRIDGES < <(ip -br link show type bridge 2>/dev/null | awk '{print $1}' || echo "vmbr0")
if [ ${#BRIDGES[@]} -eq 0 ]; then
    BRIDGES=("vmbr0")
fi

if [ ${#BRIDGES[@]} -eq 1 ]; then
    BRIDGE="${BRIDGES[0]}"
    msg "Using bridge: ${BOLD}$BRIDGE${NC}"
else
    select_option "Select network bridge" BRIDGE "${BRIDGES[@]}"
fi

if ask_yn "Use DHCP?" "Y"; then
    IP="dhcp"
    GATEWAY=""
else
    ask "IP address (e.g. 10.0.0.225/24)" "" IP
    ask "Gateway" "" GATEWAY
fi

# ─── Music library ───────────────────────────────────────────────
echo ""
echo -e "${BOLD}── Music Library ──${NC}"
ask "Host path to music library" "/mnt/data/music" MUSIC_HOST_PATH

if [ -d "$MUSIC_HOST_PATH" ]; then
    MUSIC_COUNT=$(find "$MUSIC_HOST_PATH" -maxdepth 3 \( -name "*.flac" -o -name "*.mp3" -o -name "*.m4a" \) 2>/dev/null | head -200 | wc -l)
    msg "Found music directory ($MUSIC_COUNT+ audio files)"
else
    warn "Path not found. You can mount it later."
fi

# ─── GPU ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── GPU Passthrough ──${NC}"
ENABLE_GPU=false
if [ -d "/dev/dri" ]; then
    if ask_yn "Enable Intel iGPU passthrough for CLAP acceleration?" "n"; then
        ENABLE_GPU=true
    fi
else
    echo -e "  ${DIM}No /dev/dri found, skipping${NC}"
fi

# ─── Confirm ─────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}════════════════════════════════════════${NC}"
echo -e "  CT ID:     ${BOLD}$CTID${NC}  (${HOSTNAME})"
echo -e "  Resources: ${BOLD}${CORES} cores, ${MEMORY}MB RAM, ${DISK_SIZE}GB disk${NC}"
echo -e "  Storage:   ${BOLD}$STORAGE${NC}"
echo -e "  Network:   ${BOLD}$BRIDGE${NC} (${IP})"
echo -e "  Music:     ${BOLD}$MUSIC_HOST_PATH${NC}"
echo -e "  GPU:       ${BOLD}$ENABLE_GPU${NC}"
echo -e "  ${DIM}API keys: configure in web UI after install${NC}"
echo -e "${CYAN}════════════════════════════════════════${NC}"
echo ""

if ! ask_yn "Create CT and install Zonik?" "Y"; then
    echo "Cancelled."
    exit 0
fi

echo ""

# ─── Download template if missing ────────────────────────────────
TEMPLATE_STORAGE="local"
FOUND_TEMPLATE=$(ls /var/lib/vz/template/cache/debian-12-standard_*.tar.zst 2>/dev/null | sort -V | tail -1 || true)

if [ -n "$FOUND_TEMPLATE" ]; then
    TEMPLATE=$(basename "$FOUND_TEMPLATE")
    msg "Using template: $TEMPLATE"
else
    msg "Downloading Debian 12 template..."
    pveam update
    TEMPLATE=$(pveam available --section system 2>/dev/null | grep "debian-12-standard" | awk '{print $2}' | sort -V | tail -1)
    if [ -z "$TEMPLATE" ]; then
        TEMPLATE="debian-12-standard_12.7-1_amd64.tar.zst"
    fi
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

# ─── Create CT ────────────────────────────────────────────────────
msg "Creating CT $CTID..."

CREATE_ARGS=(
    "$CTID"
    "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE"
    --hostname "$HOSTNAME"
    --memory "$MEMORY"
    --swap "$SWAP"
    --cores "$CORES"
    --rootfs "$STORAGE:$DISK_SIZE"
    --ostype debian
    --features nesting=1
    --onboot 1
    --unprivileged 1
    --password "$(openssl rand -base64 12)"
)

if [ "$IP" = "dhcp" ]; then
    CREATE_ARGS+=(--net0 "name=eth0,bridge=$BRIDGE,ip=dhcp")
else
    NET_OPTS="name=eth0,bridge=$BRIDGE,ip=$IP"
    [ -n "$GATEWAY" ] && NET_OPTS+=",gw=$GATEWAY"
    CREATE_ARGS+=(--net0 "$NET_OPTS")
fi

pct create "${CREATE_ARGS[@]}"

# ─── Mount points ────────────────────────────────────────────────
if [ -d "$MUSIC_HOST_PATH" ]; then
    msg "Mounting music library: $MUSIC_HOST_PATH -> /music"
    pct set "$CTID" -mp0 "$MUSIC_HOST_PATH,mp=/music"
fi

# ─── GPU passthrough ─────────────────────────────────────────────
if [ "$ENABLE_GPU" = true ]; then
    msg "Configuring GPU passthrough..."
    cat >> "/etc/pve/lxc/${CTID}.conf" <<'GPUEOF'
lxc.cgroup2.devices.allow: c 226:* rwm
lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir
GPUEOF
fi

# ─── Start CT ────────────────────────────────────────────────────
msg "Starting CT $CTID..."
pct start "$CTID"

msg "Waiting for boot..."
for i in $(seq 1 30); do
    pct exec "$CTID" -- true 2>/dev/null && break
    sleep 1
done

msg "Waiting for network..."
for i in $(seq 1 30); do
    if pct exec "$CTID" -- ping -c1 -W2 github.com &>/dev/null; then
        break
    fi
    sleep 2
done

# ─── Install Zonik inside CT ─────────────────────────────────────
msg "Installing Zonik inside CT (this takes 3-5 minutes)..."
echo ""

pct exec "$CTID" -- bash -c '
set -euo pipefail
DEBIAN_FRONTEND=noninteractive

echo "[1/8] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    ffmpeg libchromaprint-dev \
    redis-server \
    git curl build-essential \
    libffi-dev libssl-dev \
    ca-certificates gnupg \
    > /dev/null 2>&1
echo "       Done."

echo "[2/8] Installing Node.js 22..."
mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg 2>/dev/null
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
apt-get update -qq
apt-get install -y -qq nodejs > /dev/null 2>&1
echo "       Node.js $(node --version)"

echo "[3/8] Cloning Zonik..."
git clone --depth 1 https://github.com/Pr0zak/Zonik.git /opt/zonik 2>&1 | tail -1
cd /opt/zonik

echo "[4/8] Python environment..."
python3 -m venv /opt/zonik/venv
/opt/zonik/venv/bin/pip install --upgrade pip setuptools wheel -q 2>&1
/opt/zonik/venv/bin/pip install -e /opt/zonik -q 2>&1
echo "       Done."

echo "[5/8] Building frontend..."
cd /opt/zonik/frontend
npm install --no-audit --no-fund --loglevel=error 2>&1
npm run build 2>&1 | tail -2
cd /opt/zonik
echo "       Done."

echo "[6/8] Creating directories..."
mkdir -p /opt/zonik/data /opt/zonik/cache/covers /etc/zonik /music/Downloads

echo "[7/8] Initializing database..."
cd /opt/zonik
/opt/zonik/venv/bin/python -c "
import asyncio
from backend.database import init_db
asyncio.run(init_db())
" 2>&1
echo "       Done."

echo "[8/8] Enabling services..."
cp /opt/zonik/deploy/zonik-web.service /etc/systemd/system/
cp /opt/zonik/deploy/zonik-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable redis-server zonik-web zonik-worker > /dev/null 2>&1
systemctl start redis-server
echo "       Done."
echo ""
echo "       Installation complete inside CT."
'

# ─── Write config ────────────────────────────────────────────────
msg "Writing configuration..."
SECRET=$(pct exec "$CTID" -- python3 -c "import secrets; print(secrets.token_urlsafe(32))")

pct exec "$CTID" -- bash -c "cat > /etc/zonik/zonik.toml << 'CFGEOF'
[server]
host = \"0.0.0.0\"
port = 3000
secret_key = \"${SECRET}\"

[library]
music_dir = \"/music\"
cover_cache_dir = \"/opt/zonik/cache/covers\"

[database]
path = \"/opt/zonik/data/zonik.db\"

[redis]
url = \"redis://localhost:6379/0\"

[soulseek]
slskd_url = \"\"
slskd_api_key = \"\"
download_dir = \"/music/Downloads\"
preferred_formats = [\"flac\", \"wav\", \"mp3\"]
min_file_size_mb = 3
max_workers = 4

[lidarr]
url = \"\"
api_key = \"\"
root_folder = \"/music\"

[lastfm]
api_key = \"\"
write_api_key = \"\"
write_api_secret = \"\"

[analysis]
enable_essentia = true
enable_clap = true
use_gpu = ${ENABLE_GPU}
clap_model = \"HTSAT-base\"
max_analysis_workers = 2

[subsonic]
server_name = \"Zonik\"
CFGEOF
ln -sf /etc/zonik/zonik.toml /opt/zonik/zonik.toml"

# ─── GPU drivers ─────────────────────────────────────────────────
if [ "$ENABLE_GPU" = true ]; then
    msg "Installing Intel GPU drivers..."
    pct exec "$CTID" -- bash -c "apt-get install -y -qq intel-opencl-icd > /dev/null 2>&1" || warn "GPU driver install failed (may need manual setup)"
fi

# ─── Start Zonik ─────────────────────────────────────────────────
msg "Starting Zonik..."
pct exec "$CTID" -- systemctl start zonik-web
pct exec "$CTID" -- systemctl start zonik-worker

sleep 3

# ─── Result ──────────────────────────────────────────────────────
CT_IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')
HTTP_STATUS=$(pct exec "$CTID" -- curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000/rest/ping?f=json&u=admin&p=admin" 2>/dev/null || echo "000")

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN} Zonik is running on CT $CTID${NC}"
echo ""
echo -e "  ${CYAN}Web UI:${NC}       http://${CT_IP}:3000"
echo -e "  ${CYAN}Subsonic API:${NC} http://${CT_IP}:3000/rest"
echo -e "  ${CYAN}Credentials:${NC}  admin / admin"

if [ "$HTTP_STATUS" = "200" ]; then
    echo -e "  ${GREEN}Status:       OK${NC}"
else
    echo -e "  ${YELLOW}Status:       Starting up (may need a moment)${NC}"
fi

echo ""
echo -e "  ${BOLD}Quick commands:${NC}"
echo "    pct enter $CTID                                   # Shell"
echo "    pct exec $CTID -- nano /etc/zonik/zonik.toml      # Edit config"
echo "    pct exec $CTID -- systemctl restart zonik-web      # Restart"
echo "    pct exec $CTID -- journalctl -u zonik-web -f       # Logs"
echo "    pct exec $CTID -- bash /opt/zonik/upgrade.sh       # Upgrade"
echo ""
echo -e "  ${BOLD}Symfonium:${NC} http://${CT_IP}:3000  (admin / admin)"
echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
