#!/usr/bin/env bash
# Install OS-level prerequisites for TV Time Capsule.
#
# Required: ffmpeg (ffprobe + ffplay). Everything else is best-effort —
# remote mounts, keyring backends, NetworkManager, etc. The app runs
# without them and logs a message if a configured feature needs a missing tool.
#
# Usage:
#   ./scripts/install-system-deps.sh
#
set -euo pipefail

ORIGINAL_ARGS=("$@")

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
        *)
            echo -e "${RED}Unknown option:${NC} $1" >&2
            echo "Usage: $0" >&2
            exit 1
            ;;
    esac
done

need_cmd() { command -v "$1" >/dev/null 2>&1; }

is_pi() {
    [[ -f /proc/device-tree/model ]] && grep -qi raspberry /proc/device-tree/model 2>/dev/null
}

detect_os() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "macos"
        return
    fi
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        case "${ID:-}" in
            debian|ubuntu|raspbian|linuxmint|pop) echo "debian"; return ;;
            fedora|rhel|centos|rocky|almalinux) echo "fedora"; return ;;
            arch|manjaro|endeavouros) echo "arch"; return ;;
        esac
        case "${ID_LIKE:-}" in
            *debian*|*ubuntu*) echo "debian"; return ;;
            *fedora*|*rhel*) echo "fedora"; return ;;
            *arch*) echo "arch"; return ;;
        esac
    fi
    echo "unknown"
}

have_tool() {
    local name="$1"
    need_cmd "$name" || [[ -x "/sbin/$name" || -x "/usr/sbin/$name" ]]
}

check_required() {
    local ok=1
    echo -e "${CYAN}Required (media player)${NC}"
    for cmd in ffmpeg ffprobe ffplay; do
        if need_cmd "$cmd"; then
            echo -e "  ${GREEN}✓${NC} $cmd ($(command -v "$cmd"))"
        else
            echo -e "  ${RED}✗${NC} $cmd missing"
            ok=0
        fi
    done
    [[ "$ok" -eq 1 ]]
}

report_optional() {
    echo -e "${CYAN}Optional (logged at runtime if missing)${NC}"
    local cmd
    for cmd in mount.cifs mount.nfs sshfs curlftpfs nmcli; do
        if have_tool "$cmd"; then
            echo -e "  ${GREEN}✓${NC} $cmd"
        else
            echo -e "  ${YELLOW}·${NC} $cmd not installed"
        fi
    done
}

apt_try() {
    local p
    for p in "$@"; do
        if ! apt-get install -y -qq "$p" >/dev/null 2>&1; then
            echo -e "  ${YELLOW}skip${NC} $p (unavailable)"
        fi
    done
}

install_debian() {
    echo -e "${CYAN}Installing packages with apt...${NC}"
    apt-get update -qq || true

    # Required for playback
    apt_try ffmpeg python3 python3-venv python3-pip
    apt_try libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libsdl2-ttf-2.0-0

    # Optional — app degrades gracefully without these
    apt_try gnome-keyring libsecret-1-0
    apt_try cifs-utils nfs-common sshfs curlftpfs
    apt_try util-linux network-manager exfat-fuse
    apt-get install -y -qq exfatprogs >/dev/null 2>&1 \
        || apt-get install -y -qq exfat-utils >/dev/null 2>&1 \
        || true

    if is_pi; then
        apt_try mpv
        apt-get install -y -qq omxplayer >/dev/null 2>&1 || true
    fi
}

install_fedora() {
    echo -e "${CYAN}Installing packages with dnf...${NC}"
    dnf install -y ffmpeg python3 python3-pip \
        SDL2 SDL2_image SDL2_mixer SDL2_ttf \
        libsecret gnome-keyring \
        cifs-utils nfs-utils fuse-sshfs curlftpfs \
        exfatprogs NetworkManager || true
}

install_arch() {
    echo -e "${CYAN}Installing packages with pacman...${NC}"
    pacman -Sy --noconfirm --needed \
        ffmpeg python python-pip \
        sdl2 sdl2_image sdl2_mixer sdl2_ttf \
        libsecret gnome-keyring \
        cifs-utils nfs-utils sshfs curlftpfs \
        exfatprogs networkmanager || true
}

install_macos() {
    if ! need_cmd brew; then
        echo -e "${RED}Homebrew is required on macOS.${NC}" >&2
        echo "Install from https://brew.sh then re-run this script." >&2
        exit 1
    fi
    echo -e "${CYAN}Installing packages with Homebrew...${NC}"
    brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
}

OS="$(detect_os)"
echo -e "${CYAN}Detected OS family:${NC} $OS"
if is_pi; then
    echo -e "${CYAN}Raspberry Pi:${NC} $(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo yes)"
fi

if [[ "$OS" != "macos" && "$(id -u)" -ne 0 ]]; then
    echo -e "${YELLOW}Re-running with sudo for package install...${NC}"
    exec sudo "$0" "${ORIGINAL_ARGS[@]}"
fi

case "$OS" in
    debian) install_debian ;;
    fedora) install_fedora ;;
    arch)   install_arch ;;
    macos)  install_macos ;;
    *)
        echo -e "${RED}Unsupported OS for automatic dependency install ($OS).${NC}" >&2
        echo "Install manually: ffmpeg (providing ffprobe and ffplay)." >&2
        exit 1
        ;;
esac

echo ""
if check_required; then
    report_optional
    echo -e "${GREEN}✓${NC} Essential prerequisites ready"
else
    echo -e "${RED}ffmpeg/ffprobe/ffplay are required for playback and are still missing.${NC}" >&2
    exit 1
fi
