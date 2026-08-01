#!/usr/bin/env bash
# Mount and scan test media over local Samba, SFTP (sshfs), and FTP servers.
#
# Requires: docker compose, mount tools (install-system-deps.sh), sudo for CIFS.
#
# Usage:
#   ./scripts/verify-remote-mounts.sh
#   ./scripts/verify-remote-mounts.sh --keep
#   ./scripts/verify-remote-mounts.sh --stop
#   TV_MOUNT_TEST_CONFIG=~/mounts.json ./scripts/verify-remote-mounts.sh --no-docker
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="$ROOT/scripts/mount-test"
COMPOSE="docker compose -f $TEST_DIR/docker-compose.yml"
MOUNT_BASE="${TV_MOUNT_TEST_ROOT:-/tmp/tv-mount-test}"
KEY_DIR="$TEST_DIR/.ssh"
KEY_FILE="$KEY_DIR/id_rsa"

KEEP=0
STOP_ONLY=0
NO_DOCKER=0
TEMP_CONFIG=""

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
        --keep) KEEP=1; shift ;;
        --stop) STOP_ONLY=1; shift ;;
        --no-docker) NO_DOCKER=1; shift ;;
        *)
            echo -e "${RED}Unknown option:${NC} $1" >&2
            exit 1
            ;;
    esac
done

need_cmd() { command -v "$1" >/dev/null 2>&1; }

setup_fixture() {
    local media="$TEST_DIR/media"
    mkdir -p "$media/Mount Test Show/s01"
    if [[ ! -f "$media/Mount Test Show/s01/s01e01.mp4" ]]; then
        : > "$media/Mount Test Show/s01/s01e01.mp4"
    fi
}

setup_ssh_key() {
    mkdir -p "$KEY_DIR"
    chmod 700 "$KEY_DIR"
    if [[ ! -f "$KEY_FILE" ]]; then
        ssh-keygen -t ed25519 -N "" -f "$KEY_FILE" -q
    fi
    chmod 600 "$KEY_FILE"
}

start_docker() {
    if ! need_cmd docker; then
        echo -e "${RED}docker not found — install Docker Desktop (WSL2) or use --no-docker${NC}" >&2
        exit 1
    fi
    if [[ "$(uname -s)" == "Linux" ]]; then
        sudo modprobe cifs 2>/dev/null || true
    fi
    setup_fixture
    setup_ssh_key
    echo -e "${CYAN}Starting local Samba / SFTP / FTP test servers...${NC}"
    $COMPOSE up -d
    wait_for_port() {
        local port="$1" name="$2"
        for _ in $(seq 1 45); do
            if (echo >/dev/tcp/127.0.0.1/"$port") 2>/dev/null; then
                echo -e "  ${GREEN}✓${NC} $name listening on port $port"
                return 0
            fi
            sleep 1
        done
        echo -e "${YELLOW}warning:${NC} $name port $port not open after 45s" >&2
        return 1
    }
    wait_for_port 1445 Samba
    wait_for_port 2222 SFTP
    wait_for_port 2121 FTP
}

stop_docker() {
    if need_cmd docker; then
        $COMPOSE down --remove-orphans 2>/dev/null || true
    fi
}

umount_one() {
    local mp="$1"
    [[ -d "$mp" ]] || return 0
    if ! mountpoint -q "$mp" 2>/dev/null; then
        return 0
    fi
    if fusermount -u "$mp" 2>/dev/null; then
        return 0
    fi
    if umount "$mp" 2>/dev/null; then
        return 0
    fi
    sudo umount "$mp" 2>/dev/null || true
}

umount_all() {
    umount_one "$MOUNT_BASE/cifs"
    umount_one "$MOUNT_BASE/sftp"
    umount_one "$MOUNT_BASE/ftp"
}

if [[ "$STOP_ONLY" -eq 1 ]]; then
    umount_all
    stop_docker
    echo -e "${GREEN}✓${NC} Stopped mount test servers and unmounted test paths"
    exit 0
fi

cleanup() {
    if [[ "$KEEP" -eq 0 ]]; then
        umount_all
        stop_docker
    fi
    [[ -n "$TEMP_CONFIG" && -f "$TEMP_CONFIG" ]] && rm -f "$TEMP_CONFIG"
}
trap cleanup EXIT

if [[ "$NO_DOCKER" -eq 0 ]]; then
    start_docker
    TEMP_CONFIG="$(mktemp)"
    cat > "$TEMP_CONFIG" <<EOF
{
  "mounts": [
    {
      "type": "cifs",
      "source": "//127.0.0.1/media",
      "mountpoint": "$MOUNT_BASE/cifs",
      "username": "media",
      "password": "secret",
      "options": ["vers=3.0", "port=1445", "uid=$(id -u)", "gid=$(id -g)"]
    },
    {
      "type": "sshfs",
      "source": "media@127.0.0.1:/media",
      "mountpoint": "$MOUNT_BASE/sftp",
      "identity_file": "$KEY_FILE",
      "options": ["port=2222", "StrictHostKeyChecking=no", "UserKnownHostsFile=/dev/null"]
    },
    {
      "type": "ftp",
      "source": "ftp://127.0.0.1:2121",
      "mountpoint": "$MOUNT_BASE/ftp",
      "username": "media",
      "password": "secret"
    }
  ]
}
EOF
    MOUNT_CONFIG="$TEMP_CONFIG"
else
    if [[ -z "${TV_MOUNT_TEST_CONFIG:-}" || ! -f "$TV_MOUNT_TEST_CONFIG" ]]; then
        echo -e "${RED}Set TV_MOUNT_TEST_CONFIG to a JSON file with a mounts array${NC}" >&2
        exit 1
    fi
    MOUNT_CONFIG="$TV_MOUNT_TEST_CONFIG"
fi

mkdir -p "$MOUNT_BASE/cifs" "$MOUNT_BASE/sftp" "$MOUNT_BASE/ftp"

run_python() {
    if [[ -x "$ROOT/.venv/bin/python" ]]; then
        "$ROOT/.venv/bin/python" "$@"
    elif command -v poetry >/dev/null 2>&1 && [[ -f "$ROOT/pyproject.toml" ]]; then
        poetry -C "$ROOT" run python "$@"
    else
        python3 "$@"
    fi
}

echo -e "${CYAN}Running mount + library discovery test...${NC}"
set +e
RESULT="$(run_python - "$MOUNT_CONFIG" <<'PY'
import json
import sys

from tv_time_capsule.media import discover_shows
from tv_time_capsule.mounts import ensure_mounts

with open(sys.argv[1], encoding="utf-8") as f:
    cfg = json.load(f)
mounts = cfg.get("mounts") or []

lines = ensure_mounts(mounts, retries=3, delay_s=2.0)
fail = 0
for line in lines:
    print(line)
    if line.startswith("failed ") or line.startswith("skip mount"):
        fail += 1

mountpoints = [m["mountpoint"] for m in mounts if m.get("mountpoint")]
shows = discover_shows(mountpoints)
eps = sum(
    len(s["episodes"])
    for show in shows.values()
    for s in show.get("seasons", {}).values()
)
print(f"DISCOVERY:{len(shows)}:{eps}:{len(mountpoints)}")
sys.exit(1 if fail or not shows else 0)
PY
)"
STATUS=$?
set -e

while IFS= read -r line; do
    case "$line" in
        mounted*|already\ mounted*)
            echo -e "  ${GREEN}✓${NC} $line" ;;
        failed*|skip\ mount*)
            echo -e "  ${RED}✗${NC} $line" ;;
        DISCOVERY:*)
            disc="${line#DISCOVERY:}"
            nshows="${disc%%:*}"
            rest="${disc#*:}"
            neps="${rest%%:*}"
            nmnts="${rest##*:}"
            echo ""
            echo -e "${GREEN}✓${NC} discovery: ${nshows} show(s), ${neps} episode(s) across ${nmnts} mount(s)" ;;
        *)
            [[ -n "$line" ]] && echo "  $line" ;;
    esac
done <<< "$RESULT"

if [[ "$STATUS" -ne 0 ]]; then
    echo ""
    echo -e "${RED}Mount verification failed.${NC}" >&2
    echo "See docs/development/remote-mount-testing.md" >&2
    if [[ "$NO_DOCKER" -eq 0 && "$KEEP" -eq 0 ]]; then
        echo -e "${YELLOW}Leaving containers up for debugging — run:${NC} $0 --stop" >&2
        KEEP=1
    fi
    exit 1
fi

echo ""
if [[ "$KEEP" -eq 1 ]]; then
    echo -e "${YELLOW}Containers still running (--keep). Stop with:${NC} $0 --stop"
else
    echo -e "${GREEN}✓${NC} All mount protocols verified"
fi
