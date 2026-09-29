# Installation

*Last updated 2026-06-19.*

Zonik is a server (FastAPI backend + SvelteKit web UI + ARQ worker, backed by
SQLite and Redis) plus native Android clients for phone, Google TV and Pixel
Watch. Any Subsonic-compatible client works too.

## Server: Proxmox LXC (Recommended)

### One-Line Install

Run on your **Proxmox host** — it creates the CT, installs everything, and starts services:

```bash
bash <(curl -sL https://raw.githubusercontent.com/Pr0zak/Zonik/main/create-ct.sh)
```

`create-ct.sh` is interactive. It picks the next free CT ID and asks for:

- hostname, rootfs storage and resources (default 2 cores, 2048 MB RAM, 512 MB swap, 16 GB disk)
- network bridge and DHCP or a static IP
- the host path of your music library (bind-mounted to `/music`)
- optional Intel iGPU passthrough (only offered if `/dev/dri` exists)

It then creates an unprivileged Debian 12 CT (`nesting=1`, start on boot),
installs the system packages and Node.js 22, clones the repo to `/opt/zonik`,
builds the frontend, initialises the database, writes `/etc/zonik/zonik.toml`
with a random `secret_key`, and starts `redis-server`, `zonik-web` and
`zonik-worker`. When it finishes it prints the web UI (`http://<host>:3000`),
the Subsonic endpoint (`http://<host>:3000/rest`) and the default login
`admin` / `admin`.

> **Memory:** the frontend build (`npm run build`) can run out of memory at
> 2 GB. If an install or upgrade dies during the build, give the CT 4 GB.

> **Audio analysis extras:** `create-ct.sh` installs the base Python package
> only. Essentia and CLAP (`[analysis,clap]` extras) are pulled in by
> `install.sh` and by every `upgrade.sh` run, so run `upgrade.sh` once after a
> fresh `create-ct.sh` install if you want BPM/key/mood analysis and the Music
> Map.

Service connections (Soulseek, Lidarr, Last.fm, Spotify, AI assistant) are
configured in the web UI under **Settings** after install. The native Soulseek
client connects directly — no slskd container needed.

### Inside an Existing CT

If you already have a Debian 12 container (run as root):

```bash
curl -sL https://raw.githubusercontent.com/Pr0zak/Zonik/main/install.sh | bash
```

`install.sh` installs the system packages (using Debian's `nodejs`/`npm`),
clones or fast-forwards `/opt/zonik`, installs Python deps **with** the
`[analysis,clap]` extras, builds the frontend, copies `zonik.toml.example` to
`/etc/zonik/zonik.toml` (with a random secret) if it doesn't exist, initialises
the database and enables the systemd services. Mount your music at `/music`.

### Mount Points

Music is read from `/music`; downloads (Soulseek/Lidarr) land in `/downloads`.
In an unprivileged CT, mount the shares (NFS, CIFS, local disk) on the
Proxmox host and bind them in:

```bash
# On the Proxmox host
pct set <CTID> -mp0 /path/to/music,mp=/music
pct set <CTID> -mp1 /path/to/downloads,mp=/downloads
```

This is equivalent to adding `mp0:` / `mp1:` lines to `/etc/pve/lxc/<CTID>.conf`.
`create-ct.sh` sets up `mp0` for you; add `mp1` yourself if you use downloads.

### GPU Passthrough (Optional)

For accelerated CLAP embedding generation on Intel iGPUs (e.g. N100).
`create-ct.sh` does this for you if you answer yes; to do it by hand:

```bash
# On the Proxmox host, append to /etc/pve/lxc/<CTID>.conf:
# lxc.cgroup2.devices.allow: c 226:* rwm
# lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir

# Inside the CT:
apt install -y intel-opencl-icd
```

Set `use_gpu = true` in `zonik.toml` under `[analysis]`.

## Server: Manual / Bare-Metal Install

Debian 12 (or similar), Python 3.11+, Node.js 18+ (the CT script uses 22 from
NodeSource), Redis, ffmpeg and Chromaprint:

```bash
# System dependencies
apt update && apt install -y \
    python3 python3-venv python3-pip python3-dev \
    ffmpeg libchromaprint-dev \
    redis-server nodejs npm git curl build-essential \
    libffi-dev libssl-dev

# Clone
git clone https://github.com/Pr0zak/Zonik.git /opt/zonik
cd /opt/zonik

# Python — drop [analysis,clap] to skip Essentia/CLAP (analysis then no-ops)
python3 -m venv /opt/zonik/venv
/opt/zonik/venv/bin/pip install --upgrade pip setuptools wheel
/opt/zonik/venv/bin/pip install -e ".[analysis,clap]"

# Frontend
cd frontend && npm install && npm run build && cd ..

# Config — set secret_key; paths default to /music, /downloads, /opt/zonik/...
mkdir -p /etc/zonik
cp zonik.toml.example /etc/zonik/zonik.toml
ln -sf /etc/zonik/zonik.toml /opt/zonik/zonik.toml

# Directories + database
mkdir -p /opt/zonik/data /opt/zonik/cache/covers /music /downloads
/opt/zonik/venv/bin/python -c "import asyncio; from backend.database import init_db; asyncio.run(init_db())"

# Services (zonik-web = uvicorn on :3000, zonik-worker = arq)
cp deploy/zonik-web.service /etc/systemd/system/
cp deploy/zonik-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now redis-server zonik-web zonik-worker
```

The service files assume `/opt/zonik` and its venv. The `admin` / `admin`
user is created on first startup.

## Development Setup

```bash
git clone https://github.com/Pr0zak/Zonik.git
cd Zonik

# Python backend (requires uv or pip)
uv venv && uv pip install -e .          # add ".[analysis,clap]" for Essentia/CLAP
cp zonik.toml.example zonik.toml
# Edit zonik.toml: set music_dir, database path
# API keys can be configured via the web UI at Settings

# Start backend
uv run uvicorn backend.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev  # http://localhost:5173 (proxies /api and /rest to :8000)

# Worker (separate terminal, requires Redis)
redis-server &
uv run arq backend.workers.WorkerSettings
```

## Upgrading

```bash
cd /opt/zonik
bash upgrade.sh
```

Or from the web UI: **Settings → About & updates**. `upgrade.sh` must run as
root. It:

1. `git pull --ff-only origin main`
2. reinstalls Python deps with `[analysis,clap]`
3. rebuilds the frontend
4. runs `init_db()` — creates any **new tables**, but does **not** run Alembic
5. restarts `zonik-web` and `zonik-worker` (skipped with `SKIP_RESTART=1`,
   which the web UI trigger uses)

Because Alembic is not run, releases that add columns to existing tables need
the migrations applied by hand:

```bash
cd /opt/zonik
/opt/zonik/venv/bin/alembic upgrade head   # migrations live in backend/migrations
systemctl restart zonik-web zonik-worker
```

## Clients

All mobile builds are attached to GitHub releases tagged **`app-vX.Y.Z`** at
<https://github.com/Pr0zak/Zonik/releases> (server releases are tagged
`server-vX.Y.Z` and carry no APKs). Android 8.0+ is required. See
[mobile/README.md](../mobile/README.md) for more.

The apps log in with a **username and API key**, not a password. Generate a
key in the web UI under **Settings → Users & access**. The default `admin` /
`admin` account is created on first startup — change the password there too.

### Android phone

1. Download `zonik-vX.Y.Z-debug.apk` from the latest `app-v*` release and sideload it.
2. Open Zonik and enter the server URL (`http://<host>:3000`), username and API key —
   or tap **Pair with code** and enter the 6-digit code at `http://<host>:3000/pair`.

The app self-updates from GitHub releases. For **Android Auto**, enable
Developer Mode in Android Auto settings (tap the version 10×), then enable
"Unknown sources".

### Google TV

1. Install the **Downloader** app from the Play Store.
2. In Downloader, enter `<host>:3000/app` — the server redirects to the newest
   phone/TV APK from the latest `app-v*` release. Install it.
3. Open Zonik → enter the server URL → tap **Pair with code**.
4. On a phone or computer, open `http://<host>:3000/pair`, enter the 6-digit
   code plus the server URL, username and API key. Codes expire after 5 minutes.

### Pixel Watch

The watch app is a standalone player (streams directly from the server).

1. Install and sign in to the phone app first.
2. Download `zonik-wear-vX.Y.Z-debug.apk` from the same release.
3. On the watch, enable Developer options (**Settings → System → About → tap
   Build number 7×**), then **ADB debugging** and **Wireless debugging**.
4. From a computer on the same network:
   ```bash
   adb pair <watch-ip>:<pair-port>        # enter the 6-digit code
   adb connect <watch-ip>:<connect-port>
   adb -s <watch-ip>:<connect-port> install zonik-wear-vX.Y.Z-debug.apk
   ```
5. Open Zonik on the watch, then on the phone go to **Settings → Wear OS →
   Send**. The watch receives the server config and opens Now Playing.
   (Fallback: the watch's "enter URL manually" link uses the `/pair` code flow.)

Updates install over the top with `adb install -r`. APKs built locally are
signed with a different key from the release APKs — uninstall before switching.

### Other Subsonic clients

Any Subsonic/OpenSubsonic client (Symfonium, DSub, etc.) can connect to
`http://<host>:3000/rest` (some clients want just `http://<host>:3000`) with
your Zonik username and password.
