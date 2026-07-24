#!/usr/bin/env bash
# Enable Raspberry Pi OS auto-login (no password prompt at boot).
#
# Prefers the official raspi-config noninteractive API; falls back to the same
# getty / LightDM changes raspi-config makes.
#
# Usage:
#   ./scripts/enable-autologin.sh              # console auto-login (Lite / CLI)
#   ./scripts/enable-autologin.sh --desktop    # desktop auto-login (GUI)
#   ./scripts/enable-autologin.sh --user pi
#   ./scripts/enable-autologin.sh --reboot
#
# Options:
#   --console   Boot to text console, auto-login (default; raspi-config B2)
#   --desktop   Boot to desktop GUI, auto-login (raspi-config B4)
#   --user NAME Account to auto-login (default: SUDO_USER / invoking user)
#   --reboot    Reboot immediately after configuring
#   --disable   Turn auto-login off (console→B1, desktop→B3 based on mode)
#
set -euo pipefail

ORIGINAL_ARGS=("$@")

MODE="console"
DISABLE=0
DO_REBOOT=0
LOGIN_USER=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    awk '
        NR == 1 { next }
        /^#/ { sub(/^# ?/, ""); print; next }
        { exit }
    ' "$0"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --console) MODE="console"; shift ;;
        --desktop) MODE="desktop"; shift ;;
        --disable) DISABLE=1; shift ;;
        --reboot) DO_REBOOT=1; shift ;;
        --user)
            LOGIN_USER="${2:?--user requires a username}"
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
    exec sudo "$0" "${ORIGINAL_ARGS[@]}"
fi

if [[ -z "$LOGIN_USER" ]]; then
    LOGIN_USER="${SUDO_USER:-}"
fi
if [[ -z "$LOGIN_USER" || "$LOGIN_USER" == "root" ]]; then
    echo -e "${RED}Refusing to auto-login as root.${NC}" >&2
    echo "Pass --user <username> or run via sudo from a normal account." >&2
    exit 1
fi
if ! id "$LOGIN_USER" >/dev/null 2>&1; then
    echo -e "${RED}User not found:${NC} $LOGIN_USER" >&2
    exit 1
fi

if [[ "$DISABLE" -eq 1 ]]; then
    if [[ "$MODE" == "desktop" ]]; then
        BOOTOPT="B3"
        LABEL="desktop (login required)"
    else
        BOOTOPT="B1"
        LABEL="console (login required)"
    fi
else
    if [[ "$MODE" == "desktop" ]]; then
        BOOTOPT="B4"
        LABEL="desktop auto-login"
    else
        BOOTOPT="B2"
        LABEL="console auto-login"
    fi
fi

echo -e "${CYAN}Configuring boot behaviour:${NC} $LABEL as '$LOGIN_USER'"

via_raspi_config() {
    command -v raspi-config >/dev/null 2>&1 || return 1
    # raspi-config uses $USER / $SUDO_USER for the autologin account
    SUDO_USER="$LOGIN_USER" USER="$LOGIN_USER" raspi-config nonint do_boot_behaviour "$BOOTOPT"
}

via_manual() {
    local dropin_dir="/etc/systemd/system/getty@tty1.service.d"
    local dropin="$dropin_dir/autologin.conf"

    case "$BOOTOPT" in
        B1)
            systemctl --quiet set-default multi-user.target
            rm -f "$dropin"
            ;;
        B2)
            systemctl --quiet set-default multi-user.target
            mkdir -p "$dropin_dir"
            cat > "$dropin" <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $LOGIN_USER --noclear %I \$TERM
EOF
            ;;
        B3)
            if [[ ! -e /etc/init.d/lightdm && ! -f /etc/lightdm/lightdm.conf ]]; then
                echo -e "${RED}LightDM not found — install a desktop or use --console.${NC}" >&2
                return 1
            fi
            systemctl --quiet set-default graphical.target
            rm -f "$dropin"
            if [[ -f /etc/lightdm/lightdm.conf ]]; then
                sed /etc/lightdm/lightdm.conf -i -e "s/^autologin-user=.*/#autologin-user=/"
            fi
            ;;
        B4)
            if [[ ! -f /etc/lightdm/lightdm.conf ]]; then
                echo -e "${RED}LightDM not found — install a desktop or use --console.${NC}" >&2
                return 1
            fi
            systemctl --quiet set-default graphical.target
            mkdir -p "$dropin_dir"
            cat > "$dropin" <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $LOGIN_USER --noclear %I \$TERM
EOF
            sed /etc/lightdm/lightdm.conf -i -e "s/^\(#\|\)autologin-user=.*/autologin-user=$LOGIN_USER/"
            ;;
        *)
            echo -e "${RED}Internal error: unknown boot option $BOOTOPT${NC}" >&2
            return 1
            ;;
    esac
    systemctl daemon-reload
}

if via_raspi_config; then
    echo -e "${GREEN}✓${NC} Applied via raspi-config ($BOOTOPT)"
elif via_manual; then
    echo -e "${YELLOW}raspi-config unavailable — applied manual $BOOTOPT config${NC}"
    echo -e "${GREEN}✓${NC} Auto-login configured for '$LOGIN_USER'"
else
    echo -e "${RED}Failed to configure auto-login.${NC}" >&2
    exit 1
fi

echo ""
echo "Takes effect after reboot."
echo "  Pair with app autostart:  ./scripts/enable-autostart.sh"
if [[ "$MODE" == "desktop" && "$DISABLE" -eq 0 ]]; then
    echo "  For GUI player:         ./scripts/enable-autostart.sh --graphical"
fi

if [[ "$DO_REBOOT" -eq 1 ]]; then
    echo -e "${CYAN}Rebooting...${NC}"
    systemctl reboot
fi
