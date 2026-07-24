#!/usr/bin/env bash
# Allow the TV Time Capsule service user to mount remote shares without a password.
#
# CIFS/NFS mounts need root. This installs a narrow sudoers rule so the app can
# run `sudo -n mount ...` / `umount` from kiosk mode.
#
# Usage:
#   ./scripts/ensure-mount-privileges.sh
#   ./scripts/ensure-mount-privileges.sh --user pi
#   ./scripts/ensure-mount-privileges.sh --remove
#
set -euo pipefail

ORIGINAL_ARGS=("$@")
TARGET_USER=""
REMOVE=0
SUDOERS_FILE="/etc/sudoers.d/tv-time-capsule-mounts"

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
        --user)
            TARGET_USER="${2:?--user requires a username}"
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

if [[ "$REMOVE" -eq 1 ]]; then
    rm -f "$SUDOERS_FILE"
    echo -e "${GREEN}✓${NC} Removed $SUDOERS_FILE"
    exit 0
fi

if [[ -z "$TARGET_USER" ]]; then
    TARGET_USER="${SUDO_USER:-}"
fi
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
    echo -e "${RED}Pass --user <username> (not root).${NC}" >&2
    exit 1
fi
if ! id "$TARGET_USER" >/dev/null 2>&1; then
    echo -e "${RED}User not found:${NC} $TARGET_USER" >&2
    exit 1
fi

# Install FUSE allow_other helper note in fuse.conf if present
if [[ -f /etc/fuse.conf ]] && ! grep -q '^user_allow_other' /etc/fuse.conf; then
    echo "user_allow_other" >> /etc/fuse.conf
    echo "  enabled user_allow_other in /etc/fuse.conf (for sshfs)"
fi

tmp="$(mktemp)"
cat > "$tmp" <<EOF
# TV Time Capsule — passwordless mounts for kiosk media shares
# Managed by scripts/ensure-mount-privileges.sh
Defaults:$TARGET_USER !requiretty
$TARGET_USER ALL=(root) NOPASSWD: /bin/mount, /usr/bin/mount, /bin/umount, /usr/bin/umount
$TARGET_USER ALL=(root) NOPASSWD: /sbin/mount.cifs, /usr/sbin/mount.cifs
$TARGET_USER ALL=(root) NOPASSWD: /sbin/mount.nfs, /usr/sbin/mount.nfs, /sbin/mount.nfs4, /usr/sbin/mount.nfs4
$TARGET_USER ALL=(root) NOPASSWD: /usr/bin/sshfs, /bin/fusermount, /usr/bin/fusermount, /bin/fusermount3, /usr/bin/fusermount3
EOF

if command -v visudo >/dev/null 2>&1; then
    if ! visudo -cf "$tmp" >/dev/null; then
        echo -e "${RED}sudoers syntax check failed — not installing.${NC}" >&2
        rm -f "$tmp"
        exit 1
    fi
fi

install -m 440 "$tmp" "$SUDOERS_FILE"
rm -f "$tmp"

echo -e "${CYAN}Installed mount sudoers for $TARGET_USER${NC}"
echo "  $SUDOERS_FILE"
echo -e "${GREEN}✓${NC} Remote CIFS/NFS mounts can run without a password prompt"
