# Native weather & cached playback (defaults)

TV Time Capsule **defaults to offline-friendly, local-first modes**:

| Feature | Default | Live opt-in |
|---------|---------|-------------|
| Weather (`weather.provider`) | **`native`** — custom pygame Retro Weather | `twc` or `ws4kp` (Chrome screencast) |
| YouTube (`youtube.playback_mode`) | **`prefer_cache`** — play yt-dlp file when present | `live` (always Chrome); miss still falls back to live under `prefer_cache` |
| YouTube offline tree (`youtube.cache.enabled`) | **`true`** — idle yt-dlp fills | Set `false` to stop downloads (playback still works) |
| Decades / Retro TV (`retro_tv.playback_mode`) | **`cached`** — playlist oracle + temp clips + ffmpeg | `live` (full Chrome CDP screencast) |
| Remote-mount episode copy (`cache.enabled`) | **`true`** (unchanged) | Set `false` if you never want local copies |

**Live features are fully supported** — they are just not the out-of-box path. Flip the knobs below (or use the in-app Weather provider menu) when you want Chromium-driven experiences.

Also see [Configuration](configuration.md), [Raspberry Pi profiles](raspberry-pi.md#device-profiles-features--youtube-cache), and the developer [ports & adapters](../development/architecture.md#ports--adapters) notes.

---

## Why these defaults?

- **Pi-friendly:** Native weather and cached YouTube/Decades avoid continuous high-FPS Chrome screencasts on weak ARM boards.
- **SD-sized caches:** YouTube/Decades yt-dlp defaults prefer **≤480p** (best match for the 640×480 canvas) so fills stay small without looking soft on a CRT/SD pipeline. Override `youtube.cache.format` if you want HD.
- **Same UX on desktop:** File backends share crop/zoom with live; Weather still looks like a 90s local channel.
- **Explicit live:** Choosing `live` / `twc` / `ws4kp` is a deliberate enable of Chromium-backed modes.

---

## Weather

### Default: `native` (custom channel)

```json
{
  "weather": {
    "provider": "native",
    "zip": "02108",
    "native": { "page_seconds": 12, "alert_style": "marquee" },
    "maps": { "enabled": true }
  }
}
```

- Drawn entirely in pygame (NWS / Open-Meteo data, music, announcements, RIDGE radar loop).
- **No Chromium** required.
- Forecast re-fetches about every **3 minutes** and again when the page carousel wraps. Live chain: **NWS → Open-Meteo → MET Norway**; successes are written to a disk last-good cache (cold start / total outage). Mid-session failures keep the in-memory snapshot (Current shows `(cached)`). Elapsed hourly slots are dropped immediately.
- Alerts re-poll about every **90 seconds** (NWS active alerts).
- Radar re-fetches on Current, every **~5 minutes**, and on carousel wrap; stale loops show `cached` in the lower-thirds bar.

### Live opt-in

| `weather.provider` | Backend | Needs Chromium? |
|--------------------|---------|-----------------|
| `native` (default) | Custom pygame Retro Weather | No |
| `auto` | Resolves to **native** (kept for older configs / picker) | No |
| `twc` | weather.com/retro CDP screencast | **Yes** |
| `ws4kp` | WeatherStar 4000+ CDP screencast | **Yes** |

While watching dial **`004`**, press **Enter / Space** to open the provider picker; the choice is saved to `config.json` and the channel restarts.

Screencast knobs (`weather.screencast.*`) apply **only** to live providers (`twc` / `ws4kp`).

Disable the channel entirely with `features.weather: false`.

---

## YouTube virtual shows

### Default: prefer file cache, keep live as fallback

```json
{
  "youtube": {
    "playback_mode": "prefer_cache",
    "cache": {
      "enabled": true,
      "directory": null,
      "download_when_idle": true
    }
  }
}
```

| Mode | Cache hit | Cache miss |
|------|-----------|------------|
| `prefer_cache` (**default**) | ffmpeg file | **live Chrome** |
| `live` | live Chrome | live Chrome |
| `cached_only` | ffmpeg file | blocked (queue / snackbar; typical Pi 1 / Zero) |

- **`youtube.cache.enabled: true` (default)** starts idle yt-dlp fills for configured `youtube_channels`.
- Set `cache.enabled: false` if you do not want background downloads; with `prefer_cache`, uncached episodes still play **live**.
- Set `playback_mode: live` to force Chrome for every episode even when a file exists.
- Fill on a desktop/NAS: `tv-time-capsule --youtube-cache-sync`, then point Pis at the same `youtube.cache.directory`.

Press **Y** in browse to priority-cache the selected show/season/episode.

---

## MyRetroTVs Decades (`1950`–`2009`)

### Default: `cached`

```json
{
  "retro_tv": {
    "playback_mode": "cached",
    "cache_directory": null
  }
}
```

- Chrome (when available) only drives the site as a **playlist oracle** (power on, filters, channel down).
- yt-dlp downloads a **rolling pair** of temp clips; ffmpeg plays them.
- Temp files are wiped when you leave Decades (not the forever YouTube offline tree).

### Live opt-in

```json
{ "retro_tv": { "playback_mode": "live" } }
```

Full Chrome CDP screencast of the MyRetroTVs page (heavier on CPU/GPU).

Disable Decades with `features.retro_tv: false`.

---

## Ports & adapters (architecture)

Product code talks to **ports** (Python `Protocol`s); concrete backends live in **adapters**:

| Concern | Port | Default adapter | Live adapter |
|---------|------|-----------------|--------------|
| Weather UI | `weather.ports.WeatherPresenter` | `presenter_native` | `presenter_twc`, `presenter_ws4kp` |
| Forecast | `weather.ports.ForecastClient` | `forecast_resilient.build_forecast_client` (NWS → Open-Meteo → MET Norway + disk) | — |
| Alerts | `weather.ports.AlertClient` | `forecast_nws.NwsAlertClient` | keep last alerts if poll fails |
| Forecast store | `weather.ports.ForecastSnapshotStore` | `forecast_cache.DiskForecastStore` | — |
| Radar loop | `weather.ports.RadarLoopSource` | `radar_image.RidgeRadarLoopSource` | — |
| YouTube offline tree | `playback.ports.EpisodeOfflineCache` | `YoutubeOfflineCache` | Chrome via `youtube_player` when backend is `live` |
| Decades temp clips | `playback.ports.RollingClipCache` | `RetroTvTempCache` | Chrome screencast when `retro_tv.playback_mode: live` |

Factories:

- `weather.service.WeatherSession.from_config(...)` — picks a presenter adapter from `weather.provider`
- `weather.adapters.forecast_resilient.build_forecast_client()` — resilient forecast + disk cache
- `playback.create_episode_offline_cache(config)` — forever YouTube tree
- `playback.create_retro_clip_cache(config, decade=...)` — Decades 2-slot cache

See [Architecture → Ports & adapters](../development/architecture.md#ports--adapters) and [Module map](../development/modules.md).

---

## Migrating an existing `config.json`

Omitting keys picks up the new defaults on next parse. To **keep old live behavior**:

```json
{
  "weather": { "provider": "twc" },
  "youtube": {
    "playback_mode": "live",
    "cache": { "enabled": false }
  },
  "retro_tv": { "playback_mode": "live" }
}
```

To match the new product defaults explicitly (recommended):

```json
{
  "weather": { "provider": "native" },
  "youtube": {
    "playback_mode": "prefer_cache",
    "cache": { "enabled": true }
  },
  "retro_tv": { "playback_mode": "cached" }
}
```
