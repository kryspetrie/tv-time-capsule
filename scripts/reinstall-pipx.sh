#!/usr/bin/env bash
# Reinstall TV Time Capsule into pipx so the bare `tv-time-capsule` command
# on your PATH picks up this checkout.
#
# Uses --editable: Python edits under src/ apply without reinstalling again.
# Re-run this script when pyproject.toml / entry points / packaged assets change.
#
# Usage:
#   ./scripts/reinstall-pipx.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx not found on PATH." >&2
    echo "Install it first, e.g.: sudo apt install pipx && pipx ensurepath" >&2
    exit 1
fi

echo "Reinstalling (editable) from: $ROOT"
pipx install --force --editable "$ROOT"

echo ""
echo "Installed:"
command -v tv-time-capsule
tv-time-capsule --help | head -n 3
echo ""
echo "Ready. Example:"
echo "  tv-time-capsule --windowed --media-dir sample/media-a"
