#!/usr/bin/env bash
# Install a Desktop + applications-menu shortcut for TV Time Capsule.
#
# On Raspberry Pi OS Desktop this puts a double-clickable icon on the desktop
# so you can restart the player if it was closed.
#
# Usage:
#   ./scripts/install-desktop-shortcut.sh
#   ./scripts/install-desktop-shortcut.sh --user pi
#   TV_TIME_CAPSULE_BIN=/opt/tv-time-capsule/.venv/bin/tv-time-capsule \
#     ./scripts/install-desktop-shortcut.sh --media-dir /media/usb
#
# Options:
#   --user NAME      Target user (default: SUDO_USER / current user)
#   --media-dir DIR  Pass through to the app (repeatable)
#   --force-43       Pass --force-43 to the app
#   --scanlines      Pass --scanlines to the app
#   --remove         Remove installed shortcuts
#
set -euo pipefail

ORIGINAL_ARGS=("$@")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/desktop/tv-time-capsule.desktop.in"
DESKTOP_ID="tv-time-capsule.desktop"

REMOVE=0
FORCE_43=0
SCANLINES=0
MEDIA_DIRS=()
TARGET_USER=""

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
        --remove) REMOVE=1; shift ;;
        --force-43) FORCE_43=1; shift ;;
        --scanlines) SCANLINES=1; shift ;;
        --user)
            TARGET_USER="${2:?--user requires a username}"
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
    # Installing into another user's Desktop usually needs root
    if [[ -n "$TARGET_USER" && "$TARGET_USER" != "$(id -un)" ]]; then
        echo -e "${YELLOW}Re-running with sudo...${NC}"
        exec sudo \
            TV_TIME_CAPSULE_BIN="${TV_TIME_CAPSULE_BIN:-}" \
            MEDIA_DIR="${MEDIA_DIR:-}" \
            "$0" "${ORIGINAL_ARGS[@]}"
    fi
fi

if [[ -z "$TARGET_USER" ]]; then
    if [[ "$(id -u)" -eq 0 ]]; then
        TARGET_USER="${SUDO_USER:-}"
    else
        TARGET_USER="$(id -un)"
    fi
fi
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
    echo -e "${RED}Refusing to install a desktop shortcut for root.${NC}" >&2
    echo "Pass --user <username>." >&2
    exit 1
fi
if ! id "$TARGET_USER" >/dev/null 2>&1; then
    echo -e "${RED}User not found:${NC} $TARGET_USER" >&2
    exit 1
fi

TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_GID="$(id -g "$TARGET_USER")"
DESKTOP_DIR="$TARGET_HOME/Desktop"
APPS_DIR="$TARGET_HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/$DESKTOP_ID"
APPS_FILE="$APPS_DIR/$DESKTOP_ID"

is_raspberry_pi_os() {
    [[ -f /etc/rpi-issue ]] && return 0
    [[ -f /proc/device-tree/model ]] && grep -qi raspberry /proc/device-tree/model 2>/dev/null && return 0
    grep -qiE 'raspbian|raspberry' /etc/os-release 2>/dev/null && return 0
    return 1
}

has_desktop_session() {
    [[ -d "$DESKTOP_DIR" ]] && return 0
    [[ -f /etc/lightdm/lightdm.conf ]] && return 0
    [[ -d /usr/share/xsessions ]] && return 0
    [[ -d /usr/share/wayland-sessions ]] && return 0
    command -v startlxde-pi >/dev/null 2>&1 && return 0
    command -v labwc >/dev/null 2>&1 && return 0
    return 1
}

remove_shortcuts() {
    local removed=0
    for f in "$DESKTOP_FILE" "$APPS_FILE"; do
        if [[ -e "$f" ]]; then
            rm -f "$f"
            echo "  removed $f"
            removed=1
        fi
    done
    if [[ "$removed" -eq 0 ]]; then
        echo -e "${YELLOW}No shortcuts found for $TARGET_USER.${NC}"
    else
        echo -e "${GREEN}✓${NC} Desktop shortcut removed"
    fi
}

if [[ "$REMOVE" -eq 1 ]]; then
    remove_shortcuts
    exit 0
fi

if ! is_raspberry_pi_os; then
    echo -e "${YELLOW}Not Raspberry Pi OS — skipping desktop shortcut.${NC}"
    exit 0
fi

if ! has_desktop_session; then
    echo -e "${YELLOW}No desktop environment detected — skipping shortcut (Lite?).${NC}"
    echo "  On Desktop Pi OS, re-run: ./scripts/install-desktop-shortcut.sh"
    exit 0
fi

resolve_bin() {
    if [[ -n "${TV_TIME_CAPSULE_BIN:-}" ]]; then
        echo "$TV_TIME_CAPSULE_BIN"
        return
    fi
    local from_user
    from_user="$(sudo -u "$TARGET_USER" -H bash -lc 'command -v tv-time-capsule' 2>/dev/null || true)"
    if [[ -n "$from_user" ]]; then
        echo "$from_user"
        return
    fi
    if command -v tv-time-capsule >/dev/null 2>&1; then
        command -v tv-time-capsule
        return
    fi
    local candidate
    for candidate in \
        "$TARGET_HOME/.local/bin/tv-time-capsule" \
        /opt/tv-time-capsule/.venv/bin/tv-time-capsule \
        "$TARGET_HOME/.local/pipx/venvs/tv-time-capsule/bin/tv-time-capsule"
    do
        if [[ -x "$candidate" ]]; then
            echo "$candidate"
            return
        fi
    done
    return 1
}

if ! BIN="$(resolve_bin)"; then
    echo -e "${RED}Could not find tv-time-capsule — install the app first.${NC}" >&2
    exit 1
fi

if [[ ${#MEDIA_DIRS[@]} -eq 0 && -n "${MEDIA_DIR:-}" ]]; then
    MEDIA_DIRS+=("$MEDIA_DIR")
fi

# Desktop Exec= lines: quote only when needed; keep it simple/readable
EXEC="$BIN"
for dir in "${MEDIA_DIRS[@]+"${MEDIA_DIRS[@]}"}"; do
    EXEC+=" --media-dir ${dir}"
done
[[ "$FORCE_43" -eq 1 ]] && EXEC+=" --force-43"
[[ "$SCANLINES" -eq 1 ]] && EXEC+=" --scanlines"

if [[ ! -f "$TEMPLATE" ]]; then
    echo -e "${RED}Missing template:${NC} $TEMPLATE" >&2
    exit 1
fi

mkdir -p "$DESKTOP_DIR" "$APPS_DIR"
chown "$TARGET_UID:$TARGET_GID" "$DESKTOP_DIR" "$APPS_DIR" 2>/dev/null || true
# ensure parents for .local/share exist with correct ownership
mkdir -p "$TARGET_HOME/.local/share"
chown -R "$TARGET_UID:$TARGET_GID" "$TARGET_HOME/.local" 2>/dev/null || true

tmp="$(mktemp)"
sed -e "s|__EXEC__|$EXEC|g" "$TEMPLATE" > "$tmp"
install -o "$TARGET_UID" -g "$TARGET_GID" -m 755 "$tmp" "$DESKTOP_FILE"
install -o "$TARGET_UID" -g "$TARGET_GID" -m 644 "$tmp" "$APPS_FILE"
rm -f "$tmp"

# Mark desktop icon as trusted (PCManFM / Pi Desktop otherwise shows "Execute?" prompt)
mark_trusted() {
    local file="$1"
    if command -v gio >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" -H \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$TARGET_UID/bus" \
            gio set "$file" metadata::trusted true 2>/dev/null || true
    fi
    # Fallback used on some Pi images
    if command -v gvfs-set-attribute >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" -H \
            gvfs-set-attribute "$file" metadata::trusted true 2>/dev/null || true
    fi
}
mark_trusted "$DESKTOP_FILE"

# Refresh application menu if possible
if command -v update-desktop-database >/dev/null 2>&1; then
    sudo -u "$TARGET_USER" update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

echo -e "${CYAN}Installed desktop shortcut for $TARGET_USER${NC}"
echo "  Desktop:  $DESKTOP_FILE"
echo "  Menu:     $APPS_FILE"
echo "  Launch:   $EXEC"
echo -e "${GREEN}✓${NC} Double-click “TV Time Capsule” on the desktop to restart the app"
