#!/usr/bin/env bash
# Ensure networking (and Wi‑Fi) stay available in kiosk / console mode.
#
# Raspberry Pi OS can leave NetworkManager or wpa_supplicant disabled after
# some imaging/config paths; kiosk mode has no desktop applet to turn Wi‑Fi on.
#
# Usage:
#   ./scripts/ensure-networking.sh
#   ./scripts/ensure-networking.sh --status
#
set -euo pipefail

ORIGINAL_ARGS=("$@")
STATUS_ONLY=0

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
        --status) STATUS_ONLY=1; shift ;;
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

have_unit() {
    systemctl list-unit-files "$1" 2>/dev/null | grep -q "$1"
}

enable_now() {
    local unit="$1"
    if have_unit "$unit" || systemctl cat "$unit" >/dev/null 2>&1; then
        systemctl enable --now "$unit" 2>/dev/null || systemctl start "$unit" 2>/dev/null || true
        echo "  $unit: $(systemctl is-active "$unit" 2>/dev/null || echo unknown)"
        return 0
    fi
    return 1
}

show_status() {
    echo -e "${CYAN}Networking${NC}"
    for unit in NetworkManager.service dhcpcd.service systemd-networkd.service \
                wpa_supplicant.service NetworkManager-wait-online.service \
                systemd-networkd-wait-online.service; do
        if systemctl cat "$unit" >/dev/null 2>&1; then
            echo "  $unit: enabled=$(systemctl is-enabled "$unit" 2>/dev/null || echo n/a) active=$(systemctl is-active "$unit" 2>/dev/null || echo n/a)"
        fi
    done
    if command -v nmcli >/dev/null 2>&1; then
        echo "  nmcli networking: $(nmcli networking 2>/dev/null || echo n/a)"
        echo "  nmcli wifi: $(nmcli radio wifi 2>/dev/null || echo n/a)"
    fi
    if command -v rfkill >/dev/null 2>&1; then
        rfkill list wifi 2>/dev/null | sed 's/^/  /' || true
    fi
}

if [[ "$STATUS_ONLY" -eq 1 ]]; then
    show_status
    exit 0
fi

echo -e "${CYAN}Ensuring networking stack for kiosk mode...${NC}"

# Unblock Wi‑Fi / Bluetooth soft blocks (common after imaging)
if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock wifi 2>/dev/null || true
    rfkill unblock wlan 2>/dev/null || true
fi

# Prefer NetworkManager on modern Raspberry Pi OS; fall back to dhcpcd / networkd
if enable_now NetworkManager.service; then
    enable_now NetworkManager-wait-online.service || true
    if command -v nmcli >/dev/null 2>&1; then
        nmcli networking on 2>/dev/null || true
        nmcli radio wifi on 2>/dev/null || true
    fi
elif enable_now dhcpcd.service; then
    :
elif enable_now systemd-networkd.service; then
    enable_now systemd-networkd-wait-online.service || true
else
    echo -e "${YELLOW}No known network manager found to enable.${NC}"
fi

# wpa_supplicant is pulled in by NM on Bookworm; enable if present standalone
enable_now wpa_supplicant.service || true

# Make sure general network-online target can be satisfied
systemctl daemon-reload 2>/dev/null || true

echo -e "${GREEN}✓${NC} Networking services checked/enabled"
show_status
