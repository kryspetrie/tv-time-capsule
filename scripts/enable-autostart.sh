#!/usr/bin/env bash
# Enable TV Time Capsule to start on boot (Raspberry Pi OS / Raspbian).
#
# Usage:
#   ./scripts/enable-autostart.sh
#   ./scripts/enable-autostart.sh --graphical
#   MEDIA_DIR=/media/usb ./scripts/enable-autostart.sh
#   TV_TIME_CAPSULE_BIN=/opt/tv-time-capsule/.venv/bin/tv-time-capsule \
#     ./scripts/enable-autostart.sh --media-dir /media/usb --media-dir /home/pi/shows
#
# Options:
#   --graphical     Start after the desktop (graphical.target); sets DISPLAY=:0
#   --media-dir DIR Pass through to the app (repeatable). If omitted, the app
#                   uses ~/.config/tv-time-capsule/config.json
#   --user NAME     Systemd service user (default: SUDO_USER or current user)
#   --force-43      Pass --force-43 to the app
#   --start         Start the service immediately after enabling
#
set -euo pipefail

ORIGINAL_ARGS=("$@")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/systemd/tv-time-capsule.service.in"
SERVICE_NAME="tv-time-capsule.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

GRAPHICAL=0
START_NOW=0
FORCE_43=0
MEDIA_DIRS=()
SERVICE_USER=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --graphical) GRAPHICAL=1; shift ;;
        --start) START_NOW=1; shift ;;
        --force-43) FORCE_43=1; shift ;;
        --user)
            SERVICE_USER="${2:?--user requires a username}"
            shift 2
            ;;
        --media-dir)
            MEDIA_DIRS+=("${2:?--media-dir requires a path}")
            shift 2
            ;;
        *)
            echo -e "${RED}Unknown option:${NC} $1" >&2
            exit 1
            ;;
    esac
done

if [[ "$(id -u)" -ne 0 ]]; then
    echo -e "${YELLOW}Re-running with sudo...${NC}"
    exec sudo \
        TV_TIME_CAPSULE_BIN="${TV_TIME_CAPSULE_BIN:-}" \
        MEDIA_DIR="${MEDIA_DIR:-}" \
        "$0" "${ORIGINAL_ARGS[@]}"
fi

# Resolve service user (not root)
if [[ -z "$SERVICE_USER" ]]; then
    SERVICE_USER="${SUDO_USER:-}"
fi
if [[ -z "$SERVICE_USER" || "$SERVICE_USER" == "root" ]]; then
    echo -e "${RED}Refusing to run the service as root.${NC}" >&2
    echo "Pass --user <pi-username> or run via sudo from a normal account." >&2
    exit 1
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo -e "${RED}User not found:${NC} $SERVICE_USER" >&2
    exit 1
fi

SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
SERVICE_UID="$(id -u "$SERVICE_USER")"
SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"

resolve_bin() {
    if [[ -n "${TV_TIME_CAPSULE_BIN:-}" ]]; then
        echo "$TV_TIME_CAPSULE_BIN"
        return
    fi
    # Prefer the invoking user's PATH (pipx / poetry / local installs)
    if [[ -n "${SUDO_USER:-}" ]]; then
        local from_user
        from_user="$(sudo -u "$SUDO_USER" -H bash -lc 'command -v tv-time-capsule' 2>/dev/null || true)"
        if [[ -n "$from_user" ]]; then
            echo "$from_user"
            return
        fi
    fi
    if command -v tv-time-capsule >/dev/null 2>&1; then
        command -v tv-time-capsule
        return
    fi
    local candidate
    for candidate in \
        "$SERVICE_HOME/.local/bin/tv-time-capsule" \
        /opt/tv-time-capsule/.venv/bin/tv-time-capsule \
        "$SERVICE_HOME/.local/pipx/venvs/tv-time-capsule/bin/tv-time-capsule"
    do
        if [[ -x "$candidate" ]]; then
            echo "$candidate"
            return
        fi
    done
    return 1
}

if ! BIN="$(resolve_bin)"; then
    echo -e "${RED}Could not find tv-time-capsule on PATH.${NC}" >&2
    echo "Install first (pipx / poetry / install-pi.sh), or set TV_TIME_CAPSULE_BIN." >&2
    exit 1
fi

# Optional single MEDIA_DIR env for convenience with install-pi.sh
if [[ ${#MEDIA_DIRS[@]} -eq 0 && -n "${MEDIA_DIR:-}" ]]; then
    MEDIA_DIRS+=("$MEDIA_DIR")
fi

EXEC_START="$BIN"
for dir in "${MEDIA_DIRS[@]+"${MEDIA_DIRS[@]}"}"; do
    EXEC_START+=" --media-dir $(printf '%q' "$dir")"
done
if [[ "$FORCE_43" -eq 1 ]]; then
    EXEC_START+=" --force-43"
fi

if [[ "$GRAPHICAL" -eq 1 ]]; then
    AFTER="graphical.target"
    WANTED_BY="graphical.target"
    EXTRA_ENVIRONMENT=$(cat <<EOF
Environment=DISPLAY=:0
Environment=XAUTHORITY=$SERVICE_HOME/.Xauthority
EOF
)
else
    AFTER="multi-user.target"
    WANTED_BY="multi-user.target"
    EXTRA_ENVIRONMENT=""
fi

if [[ ! -f "$TEMPLATE" ]]; then
    echo -e "${RED}Missing service template:${NC} $TEMPLATE" >&2
    exit 1
fi

echo -e "${CYAN}Installing systemd unit...${NC}"
echo "  User:    $SERVICE_USER"
echo "  Binary:  $BIN"
echo "  Target:  $WANTED_BY"
if [[ ${#MEDIA_DIRS[@]} -gt 0 ]]; then
    echo "  Media:   ${MEDIA_DIRS[*]}"
else
    echo "  Media:   (from config file for $SERVICE_USER)"
fi

tmp="$(mktemp)"
sed \
    -e "s|__AFTER__|$AFTER|g" \
    -e "s|__WANTED_BY__|$WANTED_BY|g" \
    -e "s|__USER__|$SERVICE_USER|g" \
    -e "s|__GROUP__|$SERVICE_GROUP|g" \
    -e "s|__HOME__|$SERVICE_HOME|g" \
    -e "s|__UID__|$SERVICE_UID|g" \
    -e "s|__EXEC_START__|$EXEC_START|g" \
    "$TEMPLATE" > "$tmp"

if [[ -n "$EXTRA_ENVIRONMENT" ]]; then
    awk -v env="$EXTRA_ENVIRONMENT" '
        /__EXTRA_ENVIRONMENT__/ { print env; next }
        { print }
    ' "$tmp" > "${tmp}.out"
    mv "${tmp}.out" "$tmp"
else
    # portable delete of placeholder line (no GNU sed -i assumed on all Pi images)
    grep -v '__EXTRA_ENVIRONMENT__' "$tmp" > "${tmp}.out"
    mv "${tmp}.out" "$tmp"
fi

install -m 644 "$tmp" "$SERVICE_PATH"
rm -f "$tmp"

# Keep Wi‑Fi / Ethernet up without a desktop session; allow passwordless mounts
if [[ -x "$SCRIPT_DIR/ensure-networking.sh" ]]; then
    "$SCRIPT_DIR/ensure-networking.sh" || true
fi
if [[ -x "$SCRIPT_DIR/ensure-mount-privileges.sh" ]]; then
    "$SCRIPT_DIR/ensure-mount-privileges.sh" --user "$SERVICE_USER" || true
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

if [[ "$START_NOW" -eq 1 ]]; then
    systemctl restart "$SERVICE_NAME"
    echo -e "${GREEN}✓${NC} Enabled and started $SERVICE_NAME"
else
    echo -e "${GREEN}✓${NC} Enabled $SERVICE_NAME (starts on next boot)"
fi

echo ""
echo -e "${CYAN}Useful commands:${NC}"
echo "  sudo systemctl start tv-time-capsule"
echo "  sudo systemctl stop tv-time-capsule"
echo "  sudo systemctl status tv-time-capsule"
echo "  sudo journalctl -u tv-time-capsule -f"
echo "  ./scripts/disable-autostart.sh"
echo "  ./scripts/ensure-networking.sh --status"
