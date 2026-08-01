#!/usr/bin/env bash
# Install-step helper: register mDNS hostname and save to config.json.
#
# Called by install.sh and install-pi.sh (not usually run directly).
#
# Usage:
#   ./scripts/install-hostname.sh --hostname vintage-tv
#   ./scripts/install-hostname.sh --hostname vintage-tv-bedroom --user pi
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOSTNAME=""
ADMIN_PORT="${ADMIN_PORT:-8765}"
CONFIG_USER=""
CONFIG_PATH=""

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --hostname)
            HOSTNAME="${2:?--hostname requires a value}"
            shift 2
            ;;
        --admin-port)
            ADMIN_PORT="${2:?--admin-port requires a value}"
            shift 2
            ;;
        --user)
            CONFIG_USER="${2:?--user requires a value}"
            shift 2
            ;;
        --config)
            CONFIG_PATH="${2:?--config requires a value}"
            shift 2
            ;;
        *)
            echo -e "${RED}Unknown option:${NC} $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$HOSTNAME" ]]; then
    HOSTNAME="${MDNS_HOSTNAME:-${TV_TIME_CAPSULE_HOSTNAME:-vintage-tv}}"
fi

if [[ -z "$CONFIG_PATH" ]]; then
    if [[ -n "$CONFIG_USER" ]]; then
        USER_HOME="$(getent passwd "$CONFIG_USER" 2>/dev/null | cut -d: -f6 || true)"
        if [[ -z "$USER_HOME" ]]; then
            USER_HOME="$(eval echo "~${CONFIG_USER}")"
        fi
    else
        USER_HOME="${HOME}"
    fi
    CONFIG_PATH="${USER_HOME}/.config/tv-time-capsule/config.json"
fi

echo -e "${CYAN}Configuring LAN hostname (mDNS)...${NC}"
ADMIN_PORT="$ADMIN_PORT" "$SCRIPT_DIR/ensure-mdns-hostname.sh" \
    --hostname "$HOSTNAME" --admin-port "$ADMIN_PORT"

if [[ -f /etc/tv-time-capsule/mdns-hostname ]]; then
    HOSTNAME="$(tr -d '[:space:]' < /etc/tv-time-capsule/mdns-hostname)"
fi

mkdir -p "$(dirname "$CONFIG_PATH")"
python3 <<PY
import json
import os

path = ${CONFIG_PATH@Q}
hostname = ${HOSTNAME@Q}
port = int(${ADMIN_PORT@Q})

data = {}
if os.path.isfile(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
if not isinstance(data, dict):
    data = {}

network = data.get("network")
if not isinstance(network, dict):
    network = {}
network["mdns_hostname"] = hostname
network["admin_port"] = port
data["network"] = network

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY

if [[ -n "$CONFIG_USER" && "$(id -un)" == "root" ]]; then
    chown "$(id -u "$CONFIG_USER")":"$(id -g "$CONFIG_USER")" "$CONFIG_PATH" 2>/dev/null || true
fi

echo -e "${GREEN}✓${NC} Hostname ${HOSTNAME}.local saved to ${CONFIG_PATH}"
