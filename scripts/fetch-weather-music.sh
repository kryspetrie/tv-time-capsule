#!/usr/bin/env bash
# Download weather background MP3s into weather assets.
#
# Sources:
#   - https://github.com/netbymatt/ws4kp-music (AI companion tracks)
#   - https://weather.com/retro public RetroCast music assets
#
# Does not fetch classic copyrighted Weather Channel airchecks.
#
# Usage:
#   ./scripts/fetch-weather-music.sh
#   ./scripts/fetch-weather-music.sh --force
#   ./scripts/fetch-weather-music.sh --source twc
#   ./scripts/fetch-weather-music.sh --include-holiday
#   ./scripts/fetch-weather-music.sh --dest /path/to/music
#   ./scripts/fetch-weather-music.sh --python /path/to/venv/bin/python
#
# Called automatically by install.sh / install-pi.sh after the package install.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
            exit 0
            ;;
        --python)
            PYTHON="${2:?--python requires a value}"
            shift 2
            ;;
        --dest|--source|--announcements-dest)
            EXTRA_ARGS+=("$1" "${2:?$1 requires a value}")
            shift 2
            ;;
        --force|--include-holiday)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

pick_python() {
    if [[ -n "$PYTHON" ]]; then
        echo "$PYTHON"
        return
    fi
    if [[ -x "$ROOT/.venv/bin/python" ]]; then
        echo "$ROOT/.venv/bin/python"
        return
    fi
    if command -v poetry >/dev/null 2>&1 && [[ -f "$ROOT/pyproject.toml" ]]; then
        if poetry -C "$ROOT" run python -c "import tv_time_capsule" >/dev/null 2>&1; then
            poetry -C "$ROOT" run which python
            return
        fi
    fi
    command -v python3
}

PY="$(pick_python)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

echo "Using Python: $PY"
exec "$PY" -m tv_time_capsule.weather.fetch_music "${EXTRA_ARGS[@]}"
