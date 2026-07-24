#!/usr/bin/env bash
# Switch between kiosk (player) mode and full desktop mode on Raspberry Pi OS.
#
# Kiosk:  console (or graphical) auto-login + TV Time Capsule autostart
# Desktop: boot to desktop GUI, stop/disable the player so you can configure
#          networking, Samba mounts, etc.
#
# Usage:
#   ./scripts/set-mode.sh kiosk
#   ./scripts/set-mode.sh desktop
#   ./scripts/set-mode.sh desktop --reboot
#   ./scripts/set-mode.sh kiosk --graphical --media-dir /media/usb
#   ./scripts/set-mode.sh status
#
# Modes:
#   kiosk     Auto-login + enable player on boot (default: console / Lite-style)
#   desktop   Boot to desktop, stop & disable player autostart
#   status    Show current boot target, autologin, and player service state
#
# Options (kiosk):
#   --graphical     Use desktop session + --graphical player autostart
#   --media-dir DIR Forwarded to enable-autostart (repeatable)
#   --force-43      Forwarded to enable-autostart
#   --scanlines     Forwarded to enable-autostart
#   --reboot        Reboot when done
#   --start         Start the player immediately (kiosk only)
#
# Options (desktop):
#   --keep-service  Leave the systemd unit enabled (only stop it for now)
#   --reboot        Reboot when done
#
set -euo pipefail

ORIGINAL_ARGS=("$@")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE=""
GRAPHICAL=0
DO_REBOOT=0
START_NOW=0
KEEP_SERVICE=0
FORCE_43=0
SCANLINES=0
MEDIA_DIRS=()

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
    exit 0
}

if [[ $# -lt 1 ]]; then
    usage
fi

case "$1" in
    -h|--help) usage ;;
    kiosk|desktop|status) MODE="$1"; shift ;;
    *)
        echo -e "${RED}Unknown mode:${NC} $1 (use kiosk, desktop, or status)" >&2
        exit 1
        ;;
esac

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --graphical) GRAPHICAL=1; shift ;;
        --reboot) DO_REBOOT=1; shift ;;
        --start) START_NOW=1; shift ;;
        --keep-service) KEEP_SERVICE=1; shift ;;
        --force-43) FORCE_43=1; shift ;;
        --scanlines) SCANLINES=1; shift ;;
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

if [[ "$MODE" != "status" && "$(id -u)" -ne 0 ]]; then
    echo -e "${YELLOW}Re-running with sudo...${NC}"
    exec sudo \
        TV_TIME_CAPSULE_BIN="${TV_TIME_CAPSULE_BIN:-}" \
        MEDIA_DIR="${MEDIA_DIR:-}" \
        "$0" "${ORIGINAL_ARGS[@]}"
fi

show_status() {
    echo -e "${CYAN}Boot / session${NC}"
    if command -v systemctl >/dev/null 2>&1; then
        echo "  default target: $(systemctl get-default 2>/dev/null || echo unknown)"
    fi
    if [[ -f /etc/systemd/system/getty@tty1.service.d/autologin.conf ]]; then
        local user
        user="$(grep -oE -- '--autologin [^[:space:]]+' /etc/systemd/system/getty@tty1.service.d/autologin.conf 2>/dev/null | awk '{print $2}' || true)"
        echo "  console autologin: yes${user:+ ($user)}"
    else
        echo "  console autologin: no"
    fi
    if [[ -f /etc/lightdm/lightdm.conf ]] && grep -q '^autologin-user=' /etc/lightdm/lightdm.conf 2>/dev/null; then
        echo "  desktop autologin: yes ($(grep '^autologin-user=' /etc/lightdm/lightdm.conf | cut -d= -f2))"
    else
        echo "  desktop autologin: no/unknown"
    fi

    echo ""
    echo -e "${CYAN}TV Time Capsule service${NC}"
    if systemctl cat tv-time-capsule.service >/dev/null 2>&1; then
        echo "  unit: installed"
        systemctl is-enabled tv-time-capsule.service 2>/dev/null | awk '{print "  enabled: "$0}'
        systemctl is-active tv-time-capsule.service 2>/dev/null | awk '{print "  active: "$0}'
    else
        echo "  unit: not installed"
    fi
}

set_kiosk() {
    echo -e "${CYAN}Switching to kiosk mode...${NC}"

    local auto_args=()
    local start_args=()

    if [[ "$GRAPHICAL" -eq 1 ]]; then
        auto_args+=(--desktop)
        start_args+=(--graphical)
        echo "  boot: desktop auto-login + graphical player"
    else
        auto_args+=(--console)
        echo "  boot: console auto-login + player service"
    fi

    # Networking must work without a desktop Wi‑Fi applet
    "$SCRIPT_DIR/ensure-networking.sh" || true

    "$SCRIPT_DIR/enable-autologin.sh" "${auto_args[@]}"

    for dir in "${MEDIA_DIRS[@]+"${MEDIA_DIRS[@]}"}"; do
        start_args+=(--media-dir "$dir")
    done
    [[ "$FORCE_43" -eq 1 ]] && start_args+=(--force-43)
    [[ "$SCANLINES" -eq 1 ]] && start_args+=(--scanlines)
    [[ "$START_NOW" -eq 1 ]] && start_args+=(--start)

    TV_TIME_CAPSULE_BIN="${TV_TIME_CAPSULE_BIN:-}" \
        MEDIA_DIR="${MEDIA_DIR:-}" \
        "$SCRIPT_DIR/enable-autostart.sh" "${start_args[@]+"${start_args[@]}"}"

    echo -e "${GREEN}✓${NC} Kiosk mode configured"
    echo "  After reboot the player should start on its own."
    echo "  To reach the desktop later:  ./scripts/set-mode.sh desktop --reboot"
}

set_desktop() {
    echo -e "${CYAN}Switching to desktop mode...${NC}"
    echo "  boot: desktop auto-login; player stopped for configuration"

    "$SCRIPT_DIR/enable-autologin.sh" --desktop

    if systemctl cat tv-time-capsule.service >/dev/null 2>&1; then
        systemctl stop tv-time-capsule.service 2>/dev/null || true
        if [[ "$KEEP_SERVICE" -eq 1 ]]; then
            echo "  player service: stopped (still enabled for next kiosk boot)"
        else
            "$SCRIPT_DIR/disable-autostart.sh" --no-stop || true
            # already stopped above; disable without removing unit
            echo "  player service: stopped and disabled"
        fi
    else
        echo "  player service: not installed (nothing to stop)"
    fi

    echo -e "${GREEN}✓${NC} Desktop mode configured"
    echo "  Use the desktop for Wi‑Fi, Samba, file managers, etc."
    echo "  Return to kiosk:  ./scripts/set-mode.sh kiosk --reboot"
    if [[ "$GRAPHICAL" -eq 0 ]]; then
        echo "  (Add --graphical to kiosk if you prefer the player inside the desktop session.)"
    fi
}

case "$MODE" in
    status) show_status ;;
    kiosk) set_kiosk ;;
    desktop) set_desktop ;;
esac

if [[ "$MODE" != "status" && "$DO_REBOOT" -eq 1 ]]; then
    echo -e "${CYAN}Rebooting...${NC}"
    systemctl reboot
elif [[ "$MODE" != "status" ]]; then
    echo ""
    echo "Reboot to fully apply boot-target changes:"
    echo "  sudo reboot"
    echo "  # or: ./scripts/set-mode.sh $MODE --reboot"
fi
