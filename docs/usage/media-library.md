# Media library layout

Organize shows under one or more media roots (local disks, USB, or mounted network shares).

## Example

```
media/
  Bluey/
    thumbnail.png
    s01/
      s01e01 - Dancing.mp4
      s01e02 - Swimming.mp4
      s01e01.png          ← episode thumbnail
    s01.png               ← season thumbnail
  Sesame Street/
    thumbnail.png
    s01e01 - Big Bird.mp4
    s01e02 - Big Bird.mp4
```

## Supported structures

1. **Flat**: `Show/01.mp4`, `Show/02.mp4`, …  
2. **Named flat**: `Show/s01e01 - Name.mp4`, …  
3. **Season folders**: `Show/s01/01.mp4`, … — or named folders such as `Movies/Action/`  
4. **Season folders + names**: `Show/s01/s01e01 - Name.mp4`, …

When season folders use **genre-style names** (e.g. `Movies/Action/`, `Movies/Adventure/`), the season menu shows the **folder name** instead of “Season 1”. Conventional names (`s01`, `Season 2`, etc.) still show as “Season N”.

## Movies alongside TV shows

Use a normal show folder (e.g. `Movies/`) in the same media root as series like `Bluey/`:

**Flat list** — one file per title, no subfolders (skips the season screen):

```
media/
  Movies/
    thumbnail.png
    Big Hero.mp4
    The Red Balloon.mkv
```

**Genre “seasons”** — subfolders become seasons; folder names appear in the season menu:

```
media/
  Movies/
    thumbnail.png
    Action/
      Big Hero.mp4
    Adventure/
      Journey.mp4
```

Each video file is one “episode”. The UI still uses show/season/episode language, but playback works the same.

**Note:** Video files loose in the media root (not inside a show folder) are ignored. Every title needs a folder under the media root, or live inside a folder such as `Movies/`.

## Thumbnails

| Level | Typical filenames |
|-------|-------------------|
| Show | `thumbnail.png`, `show.png`, or `<Show Name>.png` |
| Season | `s01.png` or `<folder name>.png` next to the season folder (e.g. `Action.png`) |
| Episode | same stem as the video, e.g. `s01e01.png` |

Supported image extensions: `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`.

## Video extensions

`.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.webm`, `.wmv`, `.flv`, `.f4v`, `.mpg`, `.mpeg`, `.vob`

## Multiple roots

Shows with the **same folder name** across roots are merged (episodes combined, sorted by number). Configure multiple roots in [configuration](configuration.md) or pass multiple `--media-dir` flags.

## Sample library (for testing)

Download short clips from [SampleLib](https://samplelib.com/sample-mp4.html) and build a tree covering every naming/thumbnail combination:

```bash
./scripts/fetch-sample-media.sh
tv-time-capsule --media-dir sample/media-a --media-dir sample/media-b
```

Details: `sample/SOURCES.md`.
