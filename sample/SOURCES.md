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
