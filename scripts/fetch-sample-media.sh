#!/usr/bin/env bash
# Download short sample videos/images and build a test media hierarchy.
#
# Sources (free demo/test assets):
#   5-second video + images: https://samplelib.com/
#   10-second video: https://test-videos.co.uk/bigbuckbunny/mp4-h264
#   30-second video: https://getsamplefiles.com/sample-video-files/mp4
#
# Usage:
#   ./scripts/fetch-sample-media.sh
#   ./scripts/fetch-sample-media.sh --force   # re-download even if present
#
# Output: sample/media-a and sample/media-b under the repo root.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SAMPLE_ROOT="$ROOT/sample"
CACHE="$SAMPLE_ROOT/.cache"
FORCE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
            exit 0
            ;;
        --force) FORCE=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

UA="Mozilla/5.0 (compatible; tv-time-capsule-sample-fetch/1.0)"
SAMPLELIB_V="https://samplelib.com/mp4"
SAMPLELIB_I="https://samplelib.com/png"
BBB_V="https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360"
GETSAMPLE_V="https://getsamplefiles.com/download/mp4"

mkdir -p "$CACHE"

download() {
    local url="$1" dest="$2"
    if [[ -f "$dest" && "$FORCE" -eq 0 ]]; then
        return 0
    fi
    echo "  get $(basename "$dest")"
    curl -fsSL -A "$UA" -o "$dest.tmp" "$url"
    mv "$dest.tmp" "$dest"
}

validate_video() {
    local path="$1"
    if ! ffprobe -v error -show_entries format=duration "$path" >/dev/null 2>&1; then
        echo "Downloaded file is not a playable video: $path" >&2
        rm -f "$path"
        exit 1
    fi
}

echo "Downloading short sample videos..."
download "$SAMPLELIB_V/sample-5s-360p.mp4" "$CACHE/clip-5s.mp4"
download "$BBB_V/Big_Buck_Bunny_360_10s_1MB.mp4" "$CACHE/clip-10s.mp4"
download "$GETSAMPLE_V/sample-5.mp4" "$CACHE/clip-30s.mp4"
validate_video "$CACHE/clip-5s.mp4"
validate_video "$CACHE/clip-10s.mp4"
validate_video "$CACHE/clip-30s.mp4"
rm -f "$CACHE/clip-15s.mp4"  # removed from an older version of this fixture

echo "Downloading sample thumbnails..."
download "$SAMPLELIB_I/sample-boat-400x300.png"      "$CACHE/img-boat.png"
download "$SAMPLELIB_I/sample-hut-400x300.png"       "$CACHE/img-hut.png"
download "$SAMPLELIB_I/sample-bumblebee-400x300.png" "$CACHE/img-bee.png"
download "$SAMPLELIB_I/sample-clouds2-400x300.png"   "$CACHE/img-clouds.png"
download "$SAMPLELIB_I/sample-red-400x300.png"       "$CACHE/img-red.png"
download "$SAMPLELIB_I/sample-green-400x300.png"     "$CACHE/img-green.png"

cp_vid() {
    # Episodes reuse three source clips. Hard links keep the fixture small while
    # presenting each episode as a normal file; copy only if linking is unavailable.
    rm -f "$2"
    ln "$1" "$2" 2>/dev/null || cp -f "$1" "$2"
}
cp_img() { cp -f "$1" "$2"; }

echo "Building sample media hierarchy..."
rm -rf "$SAMPLE_ROOT/media-a" "$SAMPLE_ROOT/media-b"
mkdir -p "$SAMPLE_ROOT/media-a" "$SAMPLE_ROOT/media-b"

# ── 1. Flat numbered episodes, no thumbnails ─────────────────────────────────
d="$SAMPLE_ROOT/media-a/Flat Numbers"
mkdir -p "$d"
cp_vid "$CACHE/clip-5s.mp4"  "$d/01.mp4"
cp_vid "$CACHE/clip-10s.mp4" "$d/02.mp4"
cp_vid "$CACHE/clip-30s.mp4" "$d/03.mp4"

# ── 2. Named flat (sXXeYY - Title), show + some episode thumbs ───────────────
d="$SAMPLE_ROOT/media-a/Named Flat"
mkdir -p "$d"
cp_img "$CACHE/img-boat.png" "$d/thumbnail.png"
cp_vid "$CACHE/clip-5s.mp4"  "$d/s01e01 - Opening.mp4"
cp_img "$CACHE/img-bee.png"  "$d/s01e01.png"          # episode thumb (stem)
cp_vid "$CACHE/clip-10s.mp4" "$d/s01e02 - Middle.mp4"  # no episode thumb
cp_vid "$CACHE/clip-30s.mp4" "$d/s01e03 - Finale.mp4"
cp_img "$CACHE/img-hut.png"  "$d/s01e03.png"           # matched via s01e03 stem

# ── 3. Season folders + bare numbers; show + season thumbs ───────────────────
d="$SAMPLE_ROOT/media-a/Season Folders"
mkdir -p "$d/s01" "$d/Season 2"
cp_img "$CACHE/img-clouds.png" "$d/show.png"
cp_img "$CACHE/img-red.png"    "$d/s01.png"            # season thumb
cp_vid "$CACHE/clip-5s.mp4"    "$d/s01/01.mp4"
cp_img "$CACHE/img-green.png"  "$d/s01/01.png"         # episode thumb by stem
cp_vid "$CACHE/clip-10s.mp4"   "$d/s01/02.mp4"         # no episode thumb
cp_vid "$CACHE/clip-30s.mp4"   "$d/Season 2/01.mp4"    # "Season 2" folder naming
cp_vid "$CACHE/clip-5s.mp4"    "$d/Season 2/02.mp4"    # no season-2 thumb

# ── 4. Season folders + named episodes; show-name thumb + mixed ──────────────
d="$SAMPLE_ROOT/media-a/Season Named"
mkdir -p "$d/s01" "$d/s02"
cp_img "$CACHE/img-boat.png" "$d/Season Named.png"     # <Show Name>.png
cp_img "$CACHE/img-hut.png"  "$d/s02.png"              # season thumb for s02 only
cp_vid "$CACHE/clip-5s.mp4"  "$d/s01/s01e01 - Dance.mp4"
cp_img "$CACHE/img-bee.png"  "$d/s01/s01e01.png"
cp_vid "$CACHE/clip-10s.mp4" "$d/s01/s01e02 - Swim.mp4" # no ep thumb
cp_vid "$CACHE/clip-30s.mp4" "$d/s02/s02e01 - Jump.mp4"
cp_vid "$CACHE/clip-5s.mp4"  "$d/s02/s02.e02 - Run.mp4" # sXX.eYY variant
cp_img "$CACHE/img-clouds.png" "$d/s02/s02e02.png"     # matched via s02e02 lookup

# ── 5. Flat mix of naming styles, partial thumbs ─────────────────────────────
d="$SAMPLE_ROOT/media-a/Mixed Naming"
mkdir -p "$d"
cp_img "$CACHE/img-red.png"  "$d/thumbnail.png"        # show thumb; episodes partial
cp_vid "$CACHE/clip-5s.mp4"  "$d/s01e01 - First Has Thumb.mp4"
cp_img "$CACHE/img-green.png" "$d/s01e01.png"
cp_vid "$CACHE/clip-10s.mp4" "$d/s02e01 - Second Season Flat.mp4"
cp_vid "$CACHE/clip-30s.mp4" "$d/03 - Bare Number Name.mp4"

# ── 6. Season folders, zero thumbnails ───────────────────────────────────────
d="$SAMPLE_ROOT/media-a/No Thumbnails"
mkdir -p "$d/s01"
cp_vid "$CACHE/clip-5s.mp4"  "$d/s01/s01e01 - Ghost.mp4"
cp_vid "$CACHE/clip-10s.mp4" "$d/s01/s01e02 - Shadow.mp4"

# ── Second root: same show name → merge episodes across media dirs ───────────
d="$SAMPLE_ROOT/media-b/Named Flat"
mkdir -p "$d"
cp_vid "$CACHE/clip-30s.mp4" "$d/s01e04 - Bonus From Root B.mp4"
cp_img "$CACHE/img-bee.png"  "$d/s01e04.png"

# Attribution / how to use
cat > "$SAMPLE_ROOT/SOURCES.md" <<'EOF'
# Sample media sources

Downloaded for local testing:

- 5-second 360p MP4 and PNG thumbnails:
  [SampleLib](https://samplelib.com/sample-mp4.html)
- 10-second 360p H.264 Big Buck Bunny MP4:
  [Test Videos](https://test-videos.co.uk/bigbuckbunny/mp4-h264)
  (Big Buck Bunny is © Blender Foundation, CC BY 3.0)
- 30-second 320p MP4:
  [Get Sample Files](https://getsamplefiles.com/sample-video-files/mp4)

Other sources considered but intentionally not downloaded:

- [Blender BBB archive](https://download.blender.org/demo/movies/BBB/):
  full-film archives are 275–822 MB, too large for this small fixture.
- [Dolby AC-4 kit](https://ott.dolby.com/OnDelKits/AC-4/Dolby_AC-4_Online_Delivery_Kit_1.5/help_files/topics/kit_wrapper_MP4_multiplexed_streams.html):
  specialized codec-compatibility fixtures rather than ordinary player samples.
- [File Examples](https://file-examples.com/index.php/sample-video-files/sample-mp4-files/):
  direct downloads may return an anti-bot HTML page.

Regenerate with:

```bash
./scripts/fetch-sample-media.sh
```

## Layout under test

| Show | Structure | Thumbnails |
|------|-----------|------------|
| `Flat Numbers` | Flat `01.mp4`… | none |
| `Named Flat` | Flat `s01e01 - Title.mp4` | show + some episodes |
| `Season Folders` | `s01/` + `Season 2/` with bare numbers | show + s01 season + one episode |
| `Season Named` | `s01/` / `s02/` with `sXXeYY - Title` (incl. `s02.e02`) | show name file + s02 season + some episodes |
| `Mixed Naming` | Flat mix of `sXXeYY`, bare numbers | show `.png` + one episode |
| `No Thumbnails` | Season folders | none |
| `Named Flat` in `media-b/` | Extra `s01e04` | merges with `media-a` show of same name |

## Run

```bash
tv-time-capsule --media-dir sample/media-a --media-dir sample/media-b
```
EOF

# Tree summary
echo ""
echo "Sample library ready:"
if command -v find >/dev/null; then
    find "$SAMPLE_ROOT/media-a" "$SAMPLE_ROOT/media-b" -type f | sort | sed "s|$SAMPLE_ROOT/||"
fi
echo ""
echo "Run: tv-time-capsule --media-dir sample/media-a --media-dir sample/media-b"
echo "See: sample/SOURCES.md"
