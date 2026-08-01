#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# TV Time Capsule — Raspberry Pi Setup Script
# Works on: Pi Model B (2011), Pi 2, Pi 3, Pi 4, Pi 5
# ─────────────────────────────────────────────────────────────────────────────
#
# Run on a fresh Raspberry Pi OS Lite installation:
#   chmod +x install-pi.sh && ./install-pi.sh
#   ./install-pi.sh --hostname vintage-tv-bedroom
#
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKIP_HOSTNAME=0
HOSTNAME_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
            exit 0
            ;;
        --hostname)
            HOSTNAME_ARG="${2:?--hostname requires a value}"
            shift 2
            ;;
        --skip-hostname)
            SKIP_HOSTNAME=1
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--hostname NAME] [--skip-hostname]" >&2
            exit 1
            ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           TV Time Capsule — Pi Setup                     ║"
echo "║                                                          ║"
echo "║  Big buttons. Big text. Sequential episodes.            ║"
echo "║  Auto-resume where you left off.                        ║"
echo "║  Works on any Raspberry Pi with composite out.           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ─── Detect Pi Model ────────────────────────────────────────────────────────

PI_MODEL="unknown"
if [ -f /proc/device-tree/model ]; then
    PI_MODEL=$(tr -d '\0' < /proc/device-tree/model)
    echo -e "${GREEN}Detected:${NC} $PI_MODEL"
else
    echo -e "${YELLOW}Warning:${NC} Not running on a Raspberry Pi. Some features may not work."
fi

# Determine video player
USE_OMXPLAYER=false
USE_MPV=false
if echo "$PI_MODEL" | grep -qi "model b\|pi 2\|pi 3"; then
    USE_OMXPLAYER=true
    echo -e "${GREEN}Video player:${NC} omxplayer (GPU-accelerated for this Pi)"
elif echo "$PI_MODEL" | grep -qi "pi 4\|pi 5"; then
    USE_MPV=true
    echo -e "${GREEN}Video player:${NC} mpv (hardware decode for this Pi)"
else
    USE_OMXPLAYER=true
    echo -e "${YELLOW}Video player:${NC} Will try omxplayer, fall back to mpv"
fi

# ─── Configuration ──────────────────────────────────────────────────────────

MEDIA_ROOT="${MEDIA_ROOT:-/media/usb}"
INSTALL_DIR="${INSTALL_DIR:-/opt/tv-time-capsule}"
AUTOSTART="${AUTOSTART:-yes}"
MDNS_HOSTNAME="${HOSTNAME_ARG:-${MDNS_HOSTNAME:-${TV_TIME_CAPSULE_HOSTNAME:-vintage-tv}}}"
USER_NAME="${SUDO_USER:-$(whoami)}"

echo ""
echo -e "${CYAN}Configuration:${NC}"
echo "  Media root: $MEDIA_ROOT"
echo "  Install dir: $INSTALL_DIR"
echo "  Autostart: $AUTOSTART"
echo "  mDNS name: ${MDNS_HOSTNAME}.local"
echo "  User: $USER_NAME"
echo ""

# ─── Install Dependencies ────────────────────────────────────────────────────

echo -e "${CYAN}Installing system prerequisites...${NC}"
"$SCRIPT_DIR/scripts/install-system-deps.sh"

# Legacy Pi video player fallbacks
if [ "$USE_OMXPLAYER" = true ]; then
    sudo apt-get install -y -qq omxplayer 2>/dev/null || true
    if ! command -v omxplayer &>/dev/null && ! command -v omxplayer.bin &>/dev/null; then
        echo -e "${YELLOW}omxplayer not available, using mpv instead...${NC}"
        sudo apt-get install -y -qq mpv 2>/dev/null || true
        USE_OMXPLAYER=false
        USE_MPV=true
    fi
fi

if [ "$USE_MPV" = true ]; then
    sudo apt-get install -y -qq mpv 2>/dev/null || true
fi

echo -e "${GREEN}✓${NC} System packages installed"

# Networking + LAN hostname + passwordless mounts
"$SCRIPT_DIR/scripts/ensure-networking.sh" || true
if [[ "$SKIP_HOSTNAME" -eq 0 ]]; then
    "$SCRIPT_DIR/scripts/install-hostname.sh" \
        --hostname "$MDNS_HOSTNAME" \
        --user "$USER_NAME"
else
    echo -e "${YELLOW}Skipping mDNS hostname setup (--skip-hostname)${NC}"
fi
"$SCRIPT_DIR/scripts/ensure-mount-privileges.sh" --user "$USER_NAME" || true

# ─── Create venv and install package ─────────────────────────────────────────

echo -e "${CYAN}Setting up Python virtual environment...${NC}"

sudo mkdir -p "$INSTALL_DIR"
sudo chown -R "$USER_NAME:$USER_NAME" "$INSTALL_DIR"

# Copy project files into the install dir
mkdir -p "$INSTALL_DIR"
if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
        --exclude '.git' \
        --exclude '.venv' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude 'media' \
        --exclude 'sample' \
        --exclude 'dist' \
        "$SCRIPT_DIR/" "$INSTALL_DIR/"
else
    tar -C "$SCRIPT_DIR" \
        --exclude='.git' \
        --exclude='.venv' \
        --exclude='__pycache__' \
        --exclude='media' \
        --exclude='sample' \
        --exclude='dist' \
        -cf - . | tar -C "$INSTALL_DIR" -xf -
fi

# Create venv and install package (pip reads Poetry's pyproject.toml)
python3 -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"
pip install --upgrade pip --quiet
pip install "$INSTALL_DIR"
TV_TIME_CAPSULE_VENV="$INSTALL_DIR/.venv" \
    "$SCRIPT_DIR/scripts/ensure-pygame-mixer.sh" || true
deactivate

echo -e "${GREEN}✓${NC} Virtual environment created with tv-time-capsule"

# ─── Desktop shortcut (Raspberry Pi OS Desktop) ──────────────────────────────

echo -e "${CYAN}Installing desktop shortcut (if Desktop is available)...${NC}"
TV_TIME_CAPSULE_BIN="$INSTALL_DIR/.venv/bin/tv-time-capsule" \
    MEDIA_DIR="$MEDIA_ROOT" \
    "$SCRIPT_DIR/scripts/install-desktop-shortcut.sh" \
        --user "$USER_NAME" \
        --media-dir "$MEDIA_ROOT" || true

# ─── Create Media Directory ──────────────────────────────────────────────────

echo -e "${CYAN}Setting up media directory at $MEDIA_ROOT...${NC}"
sudo mkdir -p "$MEDIA_ROOT"
sudo mkdir -p "$MEDIA_ROOT/Mister Rogers' Neighborhood/s01"
sudo mkdir -p "$MEDIA_ROOT/Mister Rogers' Neighborhood/s02"
echo -e "${GREEN}✓${NC} Created media directories"
echo ""
echo -e "${YELLOW}Put your episodes in:${NC}"
echo "  $MEDIA_ROOT/Mister Rogers' Neighborhood/s01/s01e01.mp4"
echo "  ..."

# ─── Configure Autostart ─────────────────────────────────────────────────────

if [ "$AUTOSTART" = "yes" ]; then
    echo -e "${CYAN}Setting up autostart...${NC}"
    TV_TIME_CAPSULE_BIN="$INSTALL_DIR/.venv/bin/tv-time-capsule" \
        MEDIA_DIR="$MEDIA_ROOT" \
        "$SCRIPT_DIR/scripts/enable-autostart.sh" \
            --user "$USER_NAME" \
            --media-dir "$MEDIA_ROOT"
else
    echo -e "${YELLOW}Autostart not configured. Enable later with:${NC}"
    echo "  TV_TIME_CAPSULE_BIN=$INSTALL_DIR/.venv/bin/tv-time-capsule \\"
    echo "    $SCRIPT_DIR/scripts/enable-autostart.sh --media-dir=$MEDIA_ROOT"
    echo ""
    echo -e "${YELLOW}Or run manually:${NC}"
    echo "  $INSTALL_DIR/.venv/bin/tv-time-capsule --media-dir=$MEDIA_ROOT"
fi

# ─── Configure Audio ─────────────────────────────────────────────────────────

echo -e "${CYAN}Configuring audio for 3.5mm (analog) output...${NC}"
sudo amixer cset numid=3 1 2>/dev/null || true
sudo amixer sset PCM 100% 2>/dev/null || true
sudo alsactl store 2>/dev/null || true
echo -e "${GREEN}✓${NC} Audio configured for 3.5mm analog out"

# ─── Pi Model B optimizations ────────────────────────────────────────────────

if echo "$PI_MODEL" | grep -qi "model b"; then
    echo ""
    echo -e "${CYAN}Detected original Pi Model B — applying optimizations...${NC}"

    # GPU memory for omxplayer at 480i
    if ! grep -q "gpu_mem" /boot/config.txt 2>/dev/null; then
        echo "gpu_mem=192" | sudo tee -a /boot/config.txt > /dev/null
    fi

    # Composite output
    if ! grep -q "enable_tvout" /boot/config.txt 2>/dev/null; then
        sudo bash -c 'cat >> /boot/config.txt << "EOF"

# ── TV Time Capsule: CRT composite output ──
enable_tvout=1
sdtv_mode=0
sdtv_aspect=1
EOF'
    fi

    # Free RAM
    sudo systemctl disable triggerhappy 2>/dev/null || true
    sudo systemctl disable bluetooth 2>/dev/null || true

    echo -e "${GREEN}✓${NC} Pi Model B optimizations applied"
fi

# ─── Done ────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗"
echo -e "║           TV Time Capsule is installed!                  ║"
echo -e "╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Next steps:${NC}"
echo ""
echo "  1. Add episodes to your media directory:"
echo "     $MEDIA_ROOT/Show Name/s01/s01e01.mp4"
echo ""
echo "  2. Optional: add a poster image for each show:"
echo "     $MEDIA_ROOT/Show Name/thumbnail.png"
echo ""
if [ "$AUTOSTART" = "yes" ]; then
    echo "  3. Reboot to start TV Time Capsule:"
    echo "     sudo reboot"
else
    echo "  3. Run TV Time Capsule:"
    echo "     $INSTALL_DIR/.venv/bin/tv-time-capsule --media-dir=$MEDIA_ROOT"
fi
echo ""
echo -e "${CYAN}Controls:${NC}"
echo "  Arrow keys: Navigate"
echo "  Enter/→:    Select/Play"
echo "  Esc/←:      Back"
echo "  0-9:        Type channel number"
echo "  Tab:        Kids / parent mode (F2: key setup)"
echo ""
echo -e "${YELLOW}Web admin (when enabled in config):${NC}"
echo "  http://${MDNS_HOSTNAME}.local:8765/"
echo ""
echo -e "${YELLOW}To copy files from your computer:${NC}"
echo "  scp -r '/path/to/Show Name/*' pi@${MDNS_HOSTNAME}.local:$MEDIA_ROOT/"
echo ""
echo -e "${YELLOW}Multiple TVs on one network?${NC} Use a unique hostname per install:"
echo "  ./install-pi.sh --hostname vintage-tv-bedroom"
echo ""