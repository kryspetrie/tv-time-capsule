#!/usr/bin/env bash
# Disable / remove TV Time Capsule on-boot startup.
#
# Usage:
#   ./scripts/disable-autostart.sh
#   ./scripts/disable-autostart.sh --remove
#
# Options:
#   --remove   Also delete the systemd unit file
#   --stop     Stop the service if it is running (default)
#   --no-stop  Leave a running instance alone
#
set -euo pipefail

ORIGINAL_ARGS=("$@")
SERVICE_NAME="tv-time-capsule.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
REMOVE=0
STOP=1

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --remove) REMOVE=1; shift ;;
        --stop) STOP=1; shift ;;
        --no-stop) STOP=0; shift ;;
        *)
            echo -e "${RED}Unknown option:${NC} $1" >&2
            exit 1
            ;;
    esac
done

if [[ "$(id -u)" -ne 0 ]]; then
    echo -e "${YELLOW}Re-running with sudo...${NC}"
    exec sudo "$0" "${ORIGINAL_ARGS[@]}"
fi

if [[ ! -f "$SERVICE_PATH" ]] && ! systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
    echo -e "${YELLOW}No $SERVICE_NAME unit found — nothing to disable.${NC}"
    exit 0
fi

echo -e "${CYAN}Disabling autostart...${NC}"

if [[ "$STOP" -eq 1 ]]; then
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
fi

systemctl disable "$SERVICE_NAME" 2>/dev/null || true

if [[ "$REMOVE" -eq 1 ]]; then
    rm -f "$SERVICE_PATH"
    systemctl daemon-reload
    systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Disabled and removed $SERVICE_NAME"
else
    systemctl daemon-reload
    echo -e "${GREEN}✓${NC} Disabled $SERVICE_NAME (unit file kept at $SERVICE_PATH)"
    echo "  Pass --remove to delete the unit file."
fi
