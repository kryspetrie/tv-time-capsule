#!/usr/bin/env bash
# One-shot installer for desktop/laptop use (macOS, Debian/Ubuntu, Fedora, Arch).
#
# Installs system prerequisites (ffmpeg, etc.) and then the app itself via pipx
# (preferred) or a local virtualenv.
#
# Usage:
#   ./install.sh
#   ./install.sh --hostname vintage-tv
#   ./install.sh --from-git
#   ./install.sh --venv
#   ./install.sh --skip-hostname
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_URL="git+https://github.com/kryspetrie/tv-time-capsule.git"

FROM_GIT=0
USE_VENV=0
SKIP_HOSTNAME=0
HOSTNAME_ARG=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --from-git) FROM_GIT=1; shift ;;
        --venv) USE_VENV=1; shift ;;
        --hostname)
            HOSTNAME_ARG="${2:?--hostname requires a value}"
            shift 2
            ;;
        --skip-hostname)
            SKIP_HOSTNAME=1
            shift
            ;;
        *)
            echo -e "${RED}Unknown option:${NC} $1" >&2
            exit 1
            ;;
    esac
done

MDNS_HOSTNAME="${HOSTNAME_ARG:-${MDNS_HOSTNAME:-${TV_TIME_CAPSULE_HOSTNAME:-vintage-tv}}}"

echo -e "${CYAN}TV Time Capsule installer${NC}"
echo "  mDNS name: ${MDNS_HOSTNAME}.local"

"$SCRIPT_DIR/scripts/install-system-deps.sh"

if [[ "$SKIP_HOSTNAME" -eq 0 ]]; then
    "$SCRIPT_DIR/scripts/install-hostname.sh" --hostname "$MDNS_HOSTNAME"
else
    echo -e "${YELLOW}Skipping mDNS hostname setup (--skip-hostname)${NC}"
fi

install_with_pipx() {
    if ! command -v pipx >/dev/null 2>&1; then
        echo -e "${YELLOW}pipx not found — attempting to install...${NC}"
        if command -v brew >/dev/null 2>&1; then
            brew install pipx && pipx ensurepath || return 1
        elif command -v apt-get >/dev/null 2>&1; then
            sudo apt-get install -y -qq pipx >/dev/null 2>&1 || \
                python3 -m pip install --user pipx || return 1
            python3 -m pipx ensurepath >/dev/null 2>&1 || true
        else
            python3 -m pip install --user pipx || return 1
            python3 -m pipx ensurepath >/dev/null 2>&1 || true
        fi
    fi
    command -v pipx >/dev/null 2>&1 || return 1

    if [[ "$FROM_GIT" -eq 1 ]]; then
        echo -e "${CYAN}pipx install $REPO_URL${NC}"
        pipx install --force "$REPO_URL"
    else
        echo -e "${CYAN}pipx install $SCRIPT_DIR${NC}"
        pipx install --force "$SCRIPT_DIR"
    fi
}

install_with_venv() {
    echo -e "${CYAN}Creating .venv and installing locally...${NC}"
    python3 -m venv "$SCRIPT_DIR/.venv"
    "$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip --quiet
    "$SCRIPT_DIR/.venv/bin/pip" install "$SCRIPT_DIR"
    echo -e "${GREEN}✓${NC} Installed to $SCRIPT_DIR/.venv"
    echo "  Run: $SCRIPT_DIR/.venv/bin/tv-time-capsule"
}

if [[ "$USE_VENV" -eq 1 ]]; then
    install_with_venv
elif install_with_pipx; then
    echo -e "${GREEN}✓${NC} Installed with pipx"
else
    echo -e "${YELLOW}pipx unavailable — falling back to a local virtualenv${NC}"
    install_with_venv
fi

echo ""
echo -e "${CYAN}Ensuring pygame includes SDL_mixer (channel snow audio)...${NC}"
"$SCRIPT_DIR/scripts/ensure-pygame-mixer.sh" || true

echo ""
echo -e "${CYAN}Downloading weather music assets (ws4kp-music)...${NC}"
FETCH_PY=""
if [[ "$USE_VENV" -eq 1 && -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    FETCH_PY="$SCRIPT_DIR/.venv/bin/python"
elif command -v pipx >/dev/null 2>&1; then
    PIPX_VENV="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || true)"
    if [[ -n "$PIPX_VENV" && -x "$PIPX_VENV/tv-time-capsule/bin/python" ]]; then
        FETCH_PY="$PIPX_VENV/tv-time-capsule/bin/python"
    fi
fi
if [[ -n "$FETCH_PY" ]]; then
    "$SCRIPT_DIR/scripts/fetch-weather-music.sh" --python "$FETCH_PY" || \
        echo -e "${YELLOW}Weather music download failed (native weather will be silent until fixed)${NC}"
else
    "$SCRIPT_DIR/scripts/fetch-weather-music.sh" || \
        echo -e "${YELLOW}Weather music download failed (native weather will be silent until fixed)${NC}"
fi

echo ""
echo -e "${CYAN}Next steps${NC}"
echo "  tv-time-capsule --media-dir /path/to/media"
echo "  Web admin:  http://${MDNS_HOSTNAME}.local:8765/ (when admin enabled)"
echo "  Config: ~/.config/tv-time-capsule/config.json"
echo "  Docs:   docs/usage/getting-started.md"
