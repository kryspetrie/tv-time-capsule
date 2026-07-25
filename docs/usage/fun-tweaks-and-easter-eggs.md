# Fun tweaks & easter eggs

Optional polish that makes the CRT feel more alive. Everything here is **off by default** unless noted. None of it affects library layout, playback quality, or watch progress.

For config keys and CLI flags, see [Configuration](configuration.md). Toggle most **fun tweaks** live from the [Web admin → Player settings](web-admin.md#features).

---

## Fun tweaks

Cosmetic effects you can turn on deliberately. Good for demos, nostalgia, or a kid-friendly “real TV” vibe.

### Channel snow

**Label:** fun tweak

A brief burst of fine black-and-white TV static whenever you **commit a channel number** (after the ~1.5s dial timeout).

| Where it runs | Behavior |
|---------------|----------|
| Show list | Jump to the show on that cable channel |
| Season list | Jump to season 1–N |
| Episode list | Jump to episode 1–N and play |

- **Not** triggered by arrow keys or Enter — numeric dial only.
- ~320ms animation; frames are **pre-generated and cached** when snow is enabled (smooth, consistent length everywhere).
- Optional quiet white-noise audio (defaults **on** when snow is enabled; mute with `channel_snow_audio: false`).

```json
{
  "ui": {
    "channel_snow": true,
    "channel_snow_audio": true
  }
}
```

CLI one-run override: `--channel-snow`

### Shutdown collapse

**Label:** fun tweak

Classic CRT **vertical collapse** when you quit the app (after the “Quit?” confirmation). The last frame squashes to a bright line, then black.

```json
{
  "ui": {
    "shutdown_collapse": true
  }
}
```

CLI: `--shutdown-collapse`

Independent of channel snow — you can enable either or both.

### Scanlines

**Label:** fun tweak

Semi-transparent horizontal CRT scanlines over the whole UI (menus and playback).

```json
{
  "ui": {
    "scanlines": true
  }
}
```

CLI: `--scanlines`

### Analog signal glitches

**Label:** fun tweak

Random brief **static flash**, **horizontal line tear**, and **vertical roll** on the **show browser only** (not seasons, episodes, or video). Rate is configurable glitches per minute.

```json
{
  "ui": {
    "analog_artifacts": true,
    "analog_artifact_rate": 12
  }
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `analog_artifacts` | `false` | Master switch |
| `analog_artifact_rate` | `12` | Glitches per minute; `0` disables timing |

CLI: `--analog-artifacts` and `--analog-artifact-rate N`

### Screensaver

**Label:** fun tweak

Greyscale **VHS logo** bounces on black (DVD-style) after menu idle time. Random multiply tint on each wall bounce. Any key dismisses. Menus only — not during playback.

See [Configuration → screensaver](configuration.md#screensaver). CLI: `--screensaver`, `--screensaver-timeout SEC`.

### Autoplay

**Label:** quality-of-life (not hidden)

When an episode finishes naturally, advance to the next one with an “Up next” countdown. **Esc** cancels during the countdown.

See [Configuration → playback](configuration.md#playback) and [Controls → During playback](controls.md#during-playback).

### Gamepad / USB controller

**Label:** input convenience (enabled by default when a pad is connected)

Same actions as the keyboard. See [Controls → Gamepad](controls.md#gamepad).

---

## Easter eggs

Hidden or discoverable extras — no config switch; they are always available when assets and context match.

### Secret test patterns (show browser)

**Label:** easter egg

On the **show list only**, dial these channel codes (same numeric entry as normal channels — wait for auto-commit):

| Dial | Pattern | Asset file |
|------|---------|------------|
| `0` | Color bars | `src/tv_time_capsule/assets/colorbars.png` |
| `00` | Grid | `src/tv_time_capsule/assets/grid.png` |
| `000` | Indian head | `src/tv_time_capsule/assets/indianhead.png` |

- Full-screen display (no header, footer, or channel chrome).
- **Escape** exits the pattern (does not open the quit dialog).
- Typing more digits stays on the pattern until commit or Esc.
- The app **never generates or overwrites** these PNGs — supply your own (classic broadcast test art works well).
- If a file is missing, you get a “not found” error like any invalid channel.
- Channel snow still plays when a pattern loads (if snow is enabled).

**Install note:** Packaged installs include the `assets/` folder; drop your PNGs next to `vcr_osd_mono.ttf` and `vhs.bmp` in the installed package data directory, or rebuild after adding files under `src/tv_time_capsule/assets/` in a checkout.

---

## Quick reference

| Item | Type | Config / CLI | Default |
|------|------|--------------|---------|
| Channel snow | Fun tweak | `ui.channel_snow`, `--channel-snow` | off |
| Channel snow audio | Fun tweak | `ui.channel_snow_audio` | off (follows snow when enabled) |
| Shutdown collapse | Fun tweak | `ui.shutdown_collapse`, `--shutdown-collapse` | off |
| Scanlines | Fun tweak | `ui.scanlines`, `--scanlines` | off |
| Analog glitches | Fun tweak | `ui.analog_artifacts`, `--analog-artifacts` | off |
| Screensaver | Fun tweak | `screensaver.enabled`, `--screensaver` | off |
| Autoplay | QoL | `playback.autoplay` | `next_in_season_only` |
| Gamepad | Input | `gamepad.enabled` | on |
| Test patterns `0` / `00` / `000` | Easter egg | *(none)* | always if PNGs exist |

Legacy config `ui.channel_change_effects` (`off` \| `visual` \| `visual+audio`) is still read once and mapped to `channel_snow` / `channel_snow_audio` when the new keys are absent.

---

## Suggested combos

**Kid TV night:** `channel_snow: true`, `screensaver` with a long timeout, `autoplay: next_in_season_only`.

**Demo / showroom:** `channel_snow`, `scanlines`, `analog_artifacts`, `shutdown_collapse` — enable via `--channel-snow --scanlines --analog-artifacts --shutdown-collapse` for one run.

**Purist / low CPU:** leave all fun tweaks off; easter egg patterns still work if you dial them intentionally.

See also [Controls](controls.md) (channel numbers, quit flow) and [Web admin](web-admin.md) (live toggles).
