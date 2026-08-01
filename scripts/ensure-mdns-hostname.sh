#!/usr/bin/env bash
# Register a multicast-DNS hostname (e.g. vintage-tv.local) on the LAN.
#
# Uses Avahi on Linux and Bonjour (LocalHostName) on macOS. Each device on the
# network needs a unique short name when running multiple TVs.
#
# Usage:
#   ./scripts/ensure-mdns-hostname.sh
#   ./scripts/ensure-mdns-hostname.sh --hostname vintage-tv-bedroom
#   MDNS_HOSTNAME=vintage-tv-kitchen ./install-pi.sh
#   ./scripts/ensure-mdns-hostname.sh --status
#
set -euo pipefail

ORIGINAL_ARGS=("$@")
HOSTNAME=""
ADMIN_PORT="${ADMIN_PORT:-8765}"
REGISTER_HTTP_SERVICE=1
STATUS_ONLY=0
CONF_DIR="/etc/tv-time-capsule"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
    exit 0
}

normalize_hostname() {
    local raw="${1:-}"
    raw="${raw%.local}"
    raw="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
    raw="$(printf '%s' "$raw" | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//; s/-{2,}/-/g')"
    if [[ -z "$raw" ]]; then
        echo "vintage-tv"
        return
    fi
    printf '%s' "${raw:0:63}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --status) STATUS_ONLY=1; shift ;;
        --hostname)
            HOSTNAME="$(normalize_hostname "${2:?--hostname requires a value}")"
            shift 2
            ;;
        --admin-port)
            ADMIN_PORT="${2:?--admin-port requires a value}"
            shift 2
            ;;
        --no-http-service)
            REGISTER_HTTP_SERVICE=0
            shift
            ;;
        *)
            echo -e "${RED}Unknown option:${NC} $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$HOSTNAME" ]]; then
    if [[ -f "$CONF_DIR/mdns-hostname" ]]; then
        HOSTNAME="$(normalize_hostname "$(tr -d '[:space:]' < "$CONF_DIR/mdns-hostname")")"
    elif [[ -n "${MDNS_HOSTNAME:-}" ]]; then
        HOSTNAME="$(normalize_hostname "$MDNS_HOSTNAME")"
    elif [[ -n "${TV_TIME_CAPSULE_HOSTNAME:-}" ]]; then
        HOSTNAME="$(normalize_hostname "$TV_TIME_CAPSULE_HOSTNAME")"
    else
        HOSTNAME="vintage-tv"
    fi
fi

detect_os() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "macos"
        return
    fi
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        case "${ID:-}${ID_LIKE:-}" in
            *debian*|*ubuntu*|*raspbian*) echo "debian"; return ;;
            *fedora*|*rhel*) echo "fedora"; return ;;
            *arch*) echo "arch"; return ;;
        esac
    fi
    echo "linux"
}

current_short_hostname() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        scutil --get LocalHostName 2>/dev/null || hostname -s 2>/dev/null || hostname
    else
        hostname -s 2>/dev/null || hostname
    fi
}

show_status() {
    local short
    short="$(current_short_hostname)"
    echo -e "${CYAN}mDNS hostname${NC}"
    echo "  short name: $short"
    echo "  browse as:  ${short}.local"
    if command -v avahi-resolve >/dev/null 2>&1; then
        avahi-resolve -n "${short}.local" 2>/dev/null | sed 's/^/  resolves: /' || true
    fi
    if [[ -f "$CONF_DIR/mdns-hostname" ]]; then
        echo "  configured: $(tr -d '[:space:]' < "$CONF_DIR/mdns-hostname")"
    fi
    if [[ -f /etc/avahi/services/tv-time-capsule.service ]]; then
        echo "  http service: /etc/avahi/services/tv-time-capsule.service"
    fi
}

if [[ "$STATUS_ONLY" -eq 1 ]]; then
    show_status
    exit 0
fi

OS="$(detect_os)"
NEED_ROOT=0
if [[ "$OS" != "macos" && "$(id -u)" -ne 0 ]]; then
    NEED_ROOT=1
fi
if [[ "$OS" == "macos" && "$(id -u)" -ne 0 ]]; then
    NEED_ROOT=1
fi
if [[ "$NEED_ROOT" -eq 1 ]]; then
    echo -e "${YELLOW}Re-running with sudo for mDNS hostname setup...${NC}"
    exec sudo "$0" "${ORIGINAL_ARGS[@]}"
fi

persist_config() {
    mkdir -p "$CONF_DIR"
    printf '%s\n' "$HOSTNAME" > "$CONF_DIR/mdns-hostname"
    chmod 644 "$CONF_DIR/mdns-hostname"
}

update_hosts_line() {
    local hosts_file="/etc/hosts"
    [[ -f "$hosts_file" ]] || return 0
    if grep -q '^127\.0\.1\.1[[:space:]]' "$hosts_file"; then
        sed -i.bak -E "s/^127\.0\.1\.1[[:space:]].*/127.0.1.1\t${HOSTNAME}/" "$hosts_file"
        rm -f "${hosts_file}.bak"
    else
        printf '127.0.1.1\t%s\n' "$HOSTNAME" >> "$hosts_file"
    fi
}

install_linux() {
    case "$OS" in
        debian)
            if command -v apt-get >/dev/null 2>&1; then
                apt-get install -y -qq avahi-daemon avahi-utils >/dev/null 2>&1 \
                    || apt-get install -y -qq avahi-daemon >/dev/null 2>&1 \
                    || true
            fi
            ;;
        fedora)
            if command -v dnf >/dev/null 2>&1; then
                dnf install -y avahi avahi-tools >/dev/null 2>&1 || true
            fi
            ;;
        arch)
            if command -v pacman >/dev/null 2>&1; then
                pacman -Sy --noconfirm --needed avahi nss-mdns >/dev/null 2>&1 || true
            fi
            ;;
    esac

    local current
    current="$(current_short_hostname)"
    if [[ "$current" != "$HOSTNAME" ]]; then
        echo -e "${CYAN}Setting system hostname:${NC} $current → $HOSTNAME"
        if command -v hostnamectl >/dev/null 2>&1; then
            hostnamectl set-hostname "$HOSTNAME"
        else
            printf '%s\n' "$HOSTNAME" > /etc/hostname
            hostname "$HOSTNAME"
        fi
        update_hosts_line
    else
        echo -e "${CYAN}Hostname already set:${NC} $HOSTNAME"
    fi

    if systemctl cat avahi-daemon.service >/dev/null 2>&1; then
        systemctl enable avahi-daemon.service >/dev/null 2>&1 || true
        systemctl restart avahi-daemon.service >/dev/null 2>&1 || true
    fi

    if [[ "$REGISTER_HTTP_SERVICE" -eq 1 ]]; then
        mkdir -p /etc/avahi/services
        cat > /etc/avahi/services/tv-time-capsule.service <<EOF
<?xml version="1.0" standalone="no"?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">TV Time Capsule on %h</name>
  <service>
    <type>_http._tcp</type>
    <port>${ADMIN_PORT}</port>
    <txt-record>path=/</txt-record>
  </service>
</service-group>
EOF
        chmod 644 /etc/avahi/services/tv-time-capsule.service
        if systemctl is-active avahi-daemon >/dev/null 2>&1; then
            systemctl reload-or-restart avahi-daemon >/dev/null 2>&1 || true
        fi
    fi
}

install_macos() {
    local current
    current="$(current_short_hostname)"
    if [[ "$current" != "$HOSTNAME" ]]; then
        echo -e "${CYAN}Setting Bonjour hostname:${NC} $current → $HOSTNAME"
        scutil --set HostName "$HOSTNAME"
        scutil --set LocalHostName "$HOSTNAME"
        scutil --set ComputerName "Vintage TV"
    else
        echo -e "${CYAN}Bonjour hostname already set:${NC} $HOSTNAME"
    fi
}

echo -e "${CYAN}Registering mDNS hostname:${NC} ${HOSTNAME}.local"
case "$OS" in
    macos) install_macos ;;
    *) install_linux ;;
esac

persist_config
echo -e "${GREEN}✓${NC} Reach this device at ${GREEN}http://${HOSTNAME}.local:${ADMIN_PORT}/${NC} (when admin is enabled)"
show_status
