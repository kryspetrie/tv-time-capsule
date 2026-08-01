#!/usr/bin/env bash
# Build a realistic kids shows + movies demo library under media/ (or --output).
#
# Uses freely licensed clips (SampleLib, test-videos.co.uk Big Buck Bunny / Sintel,
# Blender Foundation posters on Wikimedia Commons) and optional local artwork in
# sample/ (bluey.png, misterrogers.png, thumbnail.png).
#
# Episodes are mostly 20–30 seconds so resume, autoplay countdown, and progress UI
# can be exercised without full-length files.
#
# Usage:
#   ./scripts/fetch-kids-demo-media.sh
#   ./scripts/fetch-kids-demo-media.sh --output ./sample/kids-demo --force
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT="$ROOT/media"
CACHE="$ROOT/sample/.cache/kids-demo"
FORCE=0
UA="Mozilla/5.0 (compatible; tv-time-capsule-kids-demo/1.0)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
            exit 0
            ;;
        --output) OUTPUT="$2"; shift 2 ;;
        --force) FORCE=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Required command not found: $1" >&2
        exit 1
    }
}
need curl
need ffmpeg
need ffprobe

mkdir -p "$CACHE" "$OUTPUT/shows" "$OUTPUT/movies"

download() {
    local url="$1" dest="$2"
    if [[ -f "$dest" && "$FORCE" -eq 0 ]]; then
        return 0
    fi
    echo "  get $(basename "$dest")"
    curl -fsSL -A "$UA" -o "$dest.tmp" "$url"
    mv "$dest.tmp" "$dest"
}

copy_local_art() {
    local src="$1" dest="$2"
    if [[ -f "$src" ]]; then
        cp -f "$src" "$dest"
        return 0
    fi
    return 1
}

validate_video() {
    local path="$1"
    ffprobe -v error -show_entries format=duration -of csv=p=0 "$path" >/dev/null 2>&1 || {
        echo "Not a playable video: $path" >&2
        exit 1
    }
}

make_clip() {
    # make_clip <out> <duration_seconds> <source> [start_seconds]
    local out="$1" dur="$2" src="$3" ss="${4:-0}"
    if [[ -f "$out" && "$FORCE" -eq 0 ]]; then
        return 0
    fi
    echo "  clip $(basename "$out") (${dur}s from $(basename "$src") @ ${ss}s)"
    ffmpeg -y -loglevel error -ss "$ss" -t "$dur" -i "$src" \
        -c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p \
        -an "$out"
    validate_video "$out"
    local got
    got=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")
    if awk -v g="$got" -v want="$dur" 'BEGIN { exit !(g < want - 1.5 || g > want + 1.5) }'; then
        echo "  warn: $(basename "$out") is ${got}s (wanted ${dur}s), re-trimming"
        ffmpeg -y -loglevel error -t "$dur" -i "$out" \
            -c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p -an "$out.tmp"
        mv "$out.tmp" "$out"
    fi
}

make_concat_clip() {
    # Concatenate equal slices from two 10s sources into one re-encoded clip.
    local out="$1" dur="$2" a="$3" b="$4"
    if [[ -f "$out" && "$FORCE" -eq 0 ]]; then
        return 0
    fi
    local half=$((dur / 2))
    local rest=$((dur - half))
    echo "  clip $(basename "$out") (${dur}s concat)"
    ffmpeg -y -loglevel error \
        -t "$half" -i "$a" -t "$rest" -i "$b" \
        -filter_complex "[0:v][1:v]concat=n=2:v=1:a=0[v]" -map "[v]" \
        -c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p \
        -an "$out"
    validate_video "$out"
}

thumb_from() {
    local src="$1" dest="$2"
    if [[ -f "$dest" && "$FORCE" -eq 0 ]]; then
        return 0
    fi
    ffmpeg -y -loglevel error -i "$src" -vf "scale=640:480:force_original_aspect_ratio=decrease,pad=640:480:(ow-iw)/2:(oh-ih)/2" \
        "$dest" 2>/dev/null || cp -f "$src" "$dest"
}

link_or_copy() {
    rm -f "$2"
    ln "$1" "$2" 2>/dev/null || cp -f "$1" "$2"
}

echo "Downloading source clips..."
SAMPLELIB_V="https://samplelib.com/mp4"
SAMPLELIB_I="https://samplelib.com/png"
BBB_V="https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360"
SINTEL_V="https://test-videos.co.uk/vids/sintel/mp4/h264/360"

download "$SAMPLELIB_V/sample-5s-360p.mp4"  "$CACHE/src-5s.mp4"
download "$SAMPLELIB_V/sample-10s-360p.mp4" "$CACHE/src-10s.mp4"
download "$SAMPLELIB_V/sample-15s-360p.mp4" "$CACHE/src-15s.mp4"
download "$SAMPLELIB_V/sample-20s-360p.mp4" "$CACHE/src-20s.mp4"
download "$SAMPLELIB_V/sample-30s-360p.mp4" "$CACHE/src-30s.mp4"
download "$BBB_V/Big_Buck_Bunny_360_10s_1MB.mp4" "$CACHE/src-bbb-10s.mp4"
download "$SINTEL_V/Sintel_360_10s_1MB.mp4"     "$CACHE/src-sintel-10s.mp4"
download "$BBB_V/Big_Buck_Bunny_360_10s_2MB.mp4" "$CACHE/src-bbb-10s-hq.mp4"

for f in "$CACHE"/src-*.mp4; do validate_video "$f"; done

echo "Building 20–30s episode clips..."
make_clip "$CACHE/clip-20s-a.mp4" 20 "$CACHE/src-20s.mp4" 0
make_clip "$CACHE/clip-22s-a.mp4" 22 "$CACHE/src-30s.mp4" 0
make_clip "$CACHE/clip-25s-a.mp4" 25 "$CACHE/src-30s.mp4" 2
make_clip "$CACHE/clip-28s-a.mp4" 28 "$CACHE/src-30s.mp4" 1
make_clip "$CACHE/clip-24s-a.mp4" 24 "$CACHE/src-30s.mp4" 4
make_concat_clip "$CACHE/clip-20s-bbb-sintel.mp4" 20 "$CACHE/src-bbb-10s.mp4" "$CACHE/src-sintel-10s.mp4"
make_clip "$CACHE/clip-30s-mix.mp4" 30 "$CACHE/src-30s.mp4" 0
make_clip "$CACHE/clip-26s-mix.mp4" 26 "$CACHE/src-30s.mp4" 3
make_clip "$CACHE/clip-23s-mix.mp4" 23 "$CACHE/src-30s.mp4" 5
make_clip "$CACHE/clip-21s-mix.mp4" 21 "$CACHE/src-20s.mp4" 0
make_clip "$CACHE/clip-27s-mix.mp4" 27 "$CACHE/src-30s.mp4" 2
make_clip "$CACHE/clip-29s-mix.mp4" 29 "$CACHE/src-30s.mp4" 1

echo "Downloading CC-licensed posters / artwork..."
download "https://upload.wikimedia.org/wikipedia/commons/c/c5/Big_buck_bunny_poster_big.jpg" "$CACHE/poster-bbb.jpg"
download "https://upload.wikimedia.org/wikipedia/commons/8/8f/Sintel_poster.jpg"             "$CACHE/poster-sintel.jpg"
download "https://upload.wikimedia.org/wikipedia/commons/3/36/Fred_Rogers%2C_late_1960s.jpg" "$CACHE/poster-rogers.jpg"
download "https://upload.wikimedia.org/wikipedia/commons/4/41/Children_reading.jpg"           "$CACHE/poster-reading.jpg"
download "$SAMPLELIB_I/sample-boat-400x300.png"       "$CACHE/img-boat.png"
download "$SAMPLELIB_I/sample-hut-400x300.png"        "$CACHE/img-hut.png"
download "$SAMPLELIB_I/sample-bumblebee-400x300.png" "$CACHE/img-bee.png"
download "$SAMPLELIB_I/sample-clouds2-400x300.png"   "$CACHE/img-clouds.png"
download "$SAMPLELIB_I/sample-red-400x300.png"        "$CACHE/img-red.png"
download "$SAMPLELIB_I/sample-green-400x300.png"      "$CACHE/img-green.png"

# Optional local title cards (if you added sample/*.png yourself)
copy_local_art "$ROOT/sample/bluey.png"        "$CACHE/poster-bluey.png"   || true
copy_local_art "$ROOT/sample/misterrogers.png"  "$CACHE/poster-misterrogers.png" || cp -f "$CACHE/poster-rogers.jpg" "$CACHE/poster-misterrogers.png"
copy_local_art "$ROOT/sample/thumbnail.png"    "$CACHE/poster-sesame.png"  || cp -f "$CACHE/poster-reading.jpg" "$CACHE/poster-sesame.png"

[[ -f "$CACHE/poster-bluey.png" ]] || cp -f "$CACHE/img-bee.png" "$CACHE/poster-bluey.png"
[[ -f "$CACHE/poster-sesame.png" ]] || cp -f "$CACHE/poster-reading.jpg" "$CACHE/poster-sesame.png"

echo "Building split kids library at $OUTPUT ..."
rm -rf "$OUTPUT/shows" "$OUTPUT/movies"
mkdir -p "$OUTPUT/shows" "$OUTPUT/movies"

# ── Shows ────────────────────────────────────────────────────────────────────

# Bluey — flat named episodes (no season folders)
d="$OUTPUT/shows/Bluey"
mkdir -p "$d"
cp -f "$CACHE/poster-bluey.png" "$d/thumbnail.png"
link_or_copy "$CACHE/clip-22s-a.mp4" "$d/s01e01 - The Pool.mp4"
cp -f "$CACHE/img-boat.png" "$d/s01e01.png"
link_or_copy "$CACHE/clip-25s-a.mp4" "$d/s01e02 - Magic Xylophone.mp4"
cp -f "$CACHE/img-hut.png" "$d/s01e02.png"
link_or_copy "$CACHE/clip-20s-bbb-sintel.mp4" "$d/s01e03 - Keepy Uppy.mp4"
link_or_copy "$CACHE/clip-28s-a.mp4" "$d/s01e04 - Sleepytime.mp4"
cp -f "$CACHE/img-clouds.png" "$d/s01e04.png"
link_or_copy "$CACHE/clip-24s-a.mp4" "$d/s01e05 - BBQ.mp4"

# Sesame Street — flat s01eNN naming
d="$OUTPUT/shows/Sesame Street"
mkdir -p "$d"
cp -f "$CACHE/poster-sesame.png" "$d/thumbnail.png"
link_or_copy "$CACHE/clip-20s-a.mp4"  "$d/s01e01 - Big Bird Visits.mp4"
cp -f "$CACHE/img-red.png" "$d/s01e01.png"
link_or_copy "$CACHE/clip-26s-mix.mp4" "$d/s01e02 - Counting Song.mp4"
link_or_copy "$CACHE/clip-23s-mix.mp4" "$d/s01e03 - Sunny Day.mp4"
cp -f "$CACHE/img-green.png" "$d/s01e03.png"
link_or_copy "$CACHE/clip-30s-mix.mp4" "$d/s02e01 - Letter of the Day.mp4"
link_or_copy "$CACHE/clip-21s-mix.mp4" "$d/s02e02 - Snack Time.mp4"

# Mister Rogers — season folders + episode names
d="$OUTPUT/shows/Mister Rogers' Neighborhood"
mkdir -p "$d/s01" "$d/s02"
cp -f "$CACHE/poster-misterrogers.png" "$d/thumbnail.png"
ffmpeg -y -loglevel error -i "$CACHE/poster-misterrogers.png" -vf scale=640:480 "$d/s01.png" 2>/dev/null || cp -f "$CACHE/poster-misterrogers.png" "$d/s01.png"
cp -f "$CACHE/img-hut.png" "$d/s02.png"
link_or_copy "$CACHE/clip-25s-a.mp4" "$d/s01/s01e01 - Welcome to the Neighborhood.mp4"
cp -f "$CACHE/img-boat.png" "$d/s01/s01e01.png"
link_or_copy "$CACHE/clip-22s-a.mp4" "$d/s01/s01e02 - Making Friends.mp4"
link_or_copy "$CACHE/clip-20s-a.mp4"  "$d/s01/s01e03 - Feelings.mp4"
cp -f "$CACHE/img-bee.png" "$d/s01/s01e03.png"
link_or_copy "$CACHE/clip-28s-a.mp4" "$d/s01/s01e04 - Music Shop.mp4"
link_or_copy "$CACHE/clip-24s-a.mp4" "$d/s01/s01e05 - Trolley Ride.mp4"
link_or_copy "$CACHE/clip-30s-mix.mp4" "$d/s02/s02e01 - Garden Visit.mp4"
link_or_copy "$CACHE/clip-26s-mix.mp4" "$d/s02/s02e02 - Picture Picture.mp4"
link_or_copy "$CACHE/clip-23s-mix.mp4" "$d/s02/s02e03 - Quiet Time.mp4"

# Reading Rainbow — season folders, bare episode numbers
d="$OUTPUT/shows/Reading Rainbow"
mkdir -p "$d/s01" "$d/s02"
cp -f "$CACHE/poster-reading.jpg" "$d/thumbnail.png"
cp -f "$CACHE/poster-reading.jpg" "$d/s01.png"
cp -f "$CACHE/img-clouds.png" "$d/s02.png"
link_or_copy "$CACHE/clip-20s-a.mp4"  "$d/s01/01.mp4"
cp -f "$CACHE/img-green.png" "$d/s01/01.png"
link_or_copy "$CACHE/clip-25s-a.mp4" "$d/s01/02.mp4"
link_or_copy "$CACHE/clip-22s-a.mp4" "$d/s01/03.mp4"
cp -f "$CACHE/img-red.png" "$d/s01/03.png"
link_or_copy "$CACHE/clip-28s-a.mp4" "$d/s01/04.mp4"
link_or_copy "$CACHE/clip-24s-a.mp4" "$d/s02/01.mp4"
link_or_copy "$CACHE/clip-30s-mix.mp4" "$d/s02/02.mp4"
cp -f "$CACHE/img-boat.png" "$d/s02/02.png"

# ── Movies ───────────────────────────────────────────────────────────────────

link_or_copy "$CACHE/clip-27s-mix.mp4" "$OUTPUT/movies/Big Buck Bunny.mp4"
cp -f "$CACHE/poster-bbb.jpg" "$OUTPUT/movies/Big Buck Bunny.png"

link_or_copy "$CACHE/clip-29s-mix.mp4" "$OUTPUT/movies/Sintel.mp4"
cp -f "$CACHE/poster-sintel.jpg" "$OUTPUT/movies/Sintel.png"

link_or_copy "$CACHE/clip-26s-mix.mp4" "$OUTPUT/movies/Alpha Adventure.mp4"
cp -f "$CACHE/img-bee.png" "$OUTPUT/movies/Alpha Adventure.png"

link_or_copy "$CACHE/clip-25s-a.mp4" "$OUTPUT/movies/Zulu Zone.mp4"
cp -f "$CACHE/img-clouds.png" "$OUTPUT/movies/Zulu Zone.png"

link_or_copy "$CACHE/clip-20s-bbb-sintel.mp4" "$OUTPUT/movies/Big Buck Clip.mp4"
cp -f "$CACHE/poster-bbb.jpg" "$OUTPUT/movies/Big Buck Clip.png"

mkdir -p "$OUTPUT/movies/Shorts"
link_or_copy "$CACHE/clip-22s-a.mp4" "$OUTPUT/movies/Shorts/Coral Reef.mp4"
cp -f "$CACHE/img-boat.png" "$OUTPUT/movies/Shorts/Coral Reef.png"
link_or_copy "$CACHE/clip-21s-mix.mp4" "$OUTPUT/movies/Shorts/Space Walk.mp4"
cp -f "$CACHE/img-clouds.png" "$OUTPUT/movies/Shorts/Space Walk.png"

cat > "$OUTPUT/SOURCES.md" <<'EOF'
# Kids demo media library

Generated by `./scripts/fetch-kids-demo-media.sh`.

## Video clips (20–30 seconds)

| Source | License / notes |
|--------|-----------------|
| [SampleLib](https://samplelib.com/sample-mp4.html) 5s–30s 360p clips | Free sample files |
| [Test Videos](https://test-videos.co.uk/) Big Buck Bunny & Sintel 360p H.264 10s clips | © Blender Foundation, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |

Clips are trimmed or concatenated with ffmpeg to land between ~20–30 seconds so resume, autoplay, and progress overlays can be tested.

## Posters & thumbnails

| File | Source |
|------|--------|
| `Big Buck Bunny.png`, `Big Buck Clip.png` | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Big_buck_bunny_poster_big.jpg) — Blender Foundation, CC BY 3.0 |
| `Sintel.png` | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Sintel_poster.jpg) — Blender Foundation, CC BY 3.0 |
| `Mister Rogers' Neighborhood/thumbnail.png` | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Fred_Rogers,_late_1960s.jpg) or `sample/misterrogers.png` if present locally |
| `Reading Rainbow/thumbnail.png` | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Children_reading.jpg) |
| `Bluey/thumbnail.png`, `Sesame Street/thumbnail.png` | `sample/bluey.png` / `sample/thumbnail.png` when present, else SampleLib PNG placeholders |
| Episode / movie art (other `.png`) | [SampleLib](https://samplelib.com/sample-png.html) demo images |

**Note:** Folder names (`Bluey`, `Sesame Street`, etc.) are familiar labels for layout testing only. Only the listed CC-licensed or SampleLib assets are downloaded automatically; add your own rips under `media/` for real playback.

## Regenerate

```bash
./scripts/fetch-kids-demo-media.sh --force
```

Point the app at this tree (default in `config.json`):

```bash
tv-time-capsule --windowed --media-dir ./media
```
EOF

echo ""
echo "Kids demo library ready under: $OUTPUT"
echo "Shows:"
find "$OUTPUT/shows" -name '*.mp4' | wc -l | xargs echo "  episodes:"
echo "Movies:"
find "$OUTPUT/movies" -name '*.mp4' | wc -l | xargs echo "  titles:"
echo ""
echo "Durations (seconds):"
while IFS= read -r f; do
    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
    printf "  %5.1fs  %s\n" "$dur" "${f#$OUTPUT/}"
done < <(find "$OUTPUT" -name '*.mp4' | sort)
echo ""
echo "See: $OUTPUT/SOURCES.md"
