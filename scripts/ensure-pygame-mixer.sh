#!/usr/bin/env bash
# Ensure pygame was built with SDL_mixer (pygame.mixer available).
#
# Prebuilt pygame wheels omit mixer on some Python versions (e.g. 3.14 on macOS
# before official wheels exist). This script installs SDL2_mixer system libs if
# needed, then rebuilds pygame from source when mixer is missing.
#
# Usage:
#   ./scripts/ensure-pygame-mixer.sh           # fix active Poetry / .venv / pipx env
#   ./scripts/ensure-pygame-mixer.sh --check # exit 0 when mixer OK, 1 when not
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${TV_TIME_CAPSULE_VENV:-$ROOT/.venv}"
CHECK_ONLY=0

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
        --check) CHECK_ONLY=1; shift ;;
        *)
            echo -e "${RED}Unknown option:${NC} $1" >&2
            exit 1
            ;;
    esac
done

run_python() {
    if [[ -x "$VENV_DIR/bin/python" ]]; then
        "$VENV_DIR/bin/python" "$@"
    elif command -v poetry >/dev/null 2>&1 && [[ -f "$ROOT/pyproject.toml" ]]; then
        poetry -C "$ROOT" run python "$@"
    elif command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q 'tv-time-capsule'; then
        pipx run --spec "$ROOT" python "$@"
    else
        python3 "$@"
    fi
}

run_pip() {
    if [[ -x "$VENV_DIR/bin/pip" ]]; then
        "$VENV_DIR/bin/pip" "$@"
    elif command -v poetry >/dev/null 2>&1 && [[ -f "$ROOT/pyproject.toml" ]]; then
        poetry -C "$ROOT" run pip "$@"
    elif command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q 'tv-time-capsule'; then
        pipx runpip tv-time-capsule "$@"
    else
        python3 -m pip "$@"
    fi
}

mixer_available() {
    run_python - <<'PY' >/dev/null 2>&1
import pygame
raise SystemExit(0 if pygame.mixer else 1)
PY
}

setup_pkg_config() {
    if [[ "$(uname -s)" != "Darwin" ]] || ! command -v brew >/dev/null 2>&1; then
        return 0
    fi
    local paths=()
    local lib prefix
    for lib in sdl2 sdl2_mixer sdl2_image sdl2_ttf; do
        prefix="$(brew --prefix "$lib" 2>/dev/null)" || continue
        if [[ -d "$prefix/lib/pkgconfig" ]]; then
            paths+=("$prefix/lib/pkgconfig")
        fi
    done
    if [[ ${#paths[@]} -eq 0 ]]; then
        return 1
    fi
    local joined
    joined="$(IFS=:; echo "${paths[*]}")"
    if [[ -n "${PKG_CONFIG_PATH:-}" ]]; then
        export PKG_CONFIG_PATH="${joined}:${PKG_CONFIG_PATH}"
    else
        export PKG_CONFIG_PATH="${joined}"
    fi
}

ensure_sdl_mixer_libs() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        if ! command -v brew >/dev/null 2>&1; then
            echo -e "${RED}Homebrew is required on macOS to build pygame with mixer.${NC}" >&2
            return 1
        fi
        echo -e "${CYAN}Installing SDL2 libraries (Homebrew)...${NC}"
        for pkg in sdl2 sdl2_mixer sdl2_image sdl2_ttf; do
            brew list "$pkg" >/dev/null 2>&1 || brew install "$pkg"
        done
        return 0
    fi

    if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists SDL2_mixer 2>/dev/null; then
        return 0
    fi

    echo -e "${CYAN}SDL2_mixer not found — installing system packages...${NC}"
    "$ROOT/scripts/install-system-deps.sh"
}

rebuild_pygame() {
    setup_pkg_config || true
    if [[ "$(uname -s)" == "Darwin" ]] && ! pkg-config --exists SDL2_mixer 2>/dev/null; then
        echo -e "${RED}SDL2_mixer pkg-config entry not found after install.${NC}" >&2
        echo "Try: brew install sdl2_mixer" >&2
        return 1
    fi

    echo -e "${CYAN}Rebuilding pygame from source with SDL_mixer...${NC}"
    run_pip install --force-reinstall --no-cache-dir --no-binary pygame "pygame>=2.5.0"
}

if mixer_available; then
    if [[ "$CHECK_ONLY" -eq 1 ]]; then
        exit 0
    fi
    echo -e "${GREEN}✓${NC} pygame.mixer is available"
    exit 0
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
    exit 1
fi

echo -e "${YELLOW}pygame.mixer is missing — installing SDL_mixer and rebuilding pygame...${NC}"
ensure_sdl_mixer_libs
rebuild_pygame

if mixer_available; then
    echo -e "${GREEN}✓${NC} pygame.mixer is now available"
    exit 0
fi

echo -e "${RED}pygame.mixer is still unavailable after rebuild.${NC}" >&2
echo "Channel snow audio will fall back to ffplay when triggered." >&2
exit 1
