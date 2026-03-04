# Installation

## Proxmox LXC (Recommended)

### One-Line Install

Run on your **Proxmox host** — it creates the CT, installs everything, and starts services:

```bash
bash <(curl -sL https://raw.githubusercontent.com/Pr0zak/Zonik/main/create-ct.sh)
```

The interactive installer will prompt for CT resources, network, music path, GPU passthrough, and API keys.

### Inside an Existing CT

If you already have a Debian 12 container:

```bash
curl -sL https://raw.githubusercontent.com/Pr0zak/Zonik/main/install.sh | bash
```

### Manual Install

```bash
# System dependencies
apt update && apt install -y \
    python3 python3-venv python3-pip python3-dev \
    ffmpeg libchromaprint-dev \
    redis-server nodejs npm git curl build-essential

# Clone
git clone https://github.com/Pr0zak/Zonik.git /opt/zonik
cd /opt/zonik

# Python
python3 -m venv /opt/zonik/venv
/opt/zonik/venv/bin/pip install -e .

# Frontend
cd frontend && npm install && npm run build && cd ..

# Config
mkdir -p /etc/zonik
cp zonik.toml.example /etc/zonik/zonik.toml
ln -sf /etc/zonik/zonik.toml /opt/zonik/zonik.toml
# Edit /etc/zonik/zonik.toml with your settings

# Database
mkdir -p /opt/zonik/data /opt/zonik/cache/covers
/opt/zonik/venv/bin/python -c "import asyncio; from backend.database import init_db; asyncio.run(init_db())"

# Services
cp deploy/zonik-web.service /etc/systemd/system/
cp deploy/zonik-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now redis-server zonik-web zonik-worker
```

### Mount Points

Mount your music library into the container:

```bash
# In Proxmox host, add to CT config:
# mp0: /path/to/music,mp=/music
```

Or use a bind mount in the LXC config file (`/etc/pve/lxc/<CTID>.conf`):

```
mp0: /mnt/data/music,mp=/music
```

### GPU Passthrough (Optional)

For accelerated CLAP embedding generation on Intel N100:

```bash
# On Proxmox host, add to CT config:
# lxc.cgroup2.devices.allow: c 226:* rwm
# lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir

# Inside CT:
apt install -y intel-opencl-icd
```

Set `use_gpu = true` in `zonik.toml` under `[analysis]`.

## Development Setup

```bash
git clone https://github.com/Pr0zak/Zonik.git
cd Zonik

# Python backend (requires uv or pip)
uv venv && uv pip install -e .
cp zonik.toml.example zonik.toml
# Edit zonik.toml: set music_dir, database path, API keys

# Start backend
uv run uvicorn backend.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev  # http://localhost:5173 (proxies API to :8000)

# Worker (separate terminal, requires Redis)
redis-server &
uv run arq backend.workers.WorkerSettings
```

## Upgrading

```bash
cd /opt/zonik
bash upgrade.sh
```

Or manually:

```bash
cd /opt/zonik
git pull
/opt/zonik/venv/bin/pip install -e .
cd frontend && npm install && npm run build && cd ..
systemctl restart zonik-web zonik-worker
```

## Connecting Symfonium

1. Open Symfonium on Android
2. Add Server > Subsonic
3. URL: `http://<zonik-ip>:3000`
4. Username: `admin`
5. Password: `admin`
6. Test connection

The default credentials are created on first startup. Change them in the database or via a future user management UI.
