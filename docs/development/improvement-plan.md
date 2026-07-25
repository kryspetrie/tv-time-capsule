# Phased improvement plan

Living roadmap for high-value features and hardening work. Each phase ends with a **retro** whose outputs explicitly adjust the next phase (scope, priority, or acceptance criteria).

**Out of scope for this plan** (by design): parental PIN / allowlists, sleep timer, startup default channel, subtitle & audio track selection, multi-child profiles.

---

## Overview

| Phase | Theme | Primary outcomes |
|-------|--------|------------------|
| [1](#phase-1-playback--input) | Playback & input | Autoplay, gamepad/remote, CRT channel-change polish |
| [2](#phase-2-library--channel-lineup) | Library & channel lineup | Custom channel order/numbers, hot rescan |
| [3](#phase-3-pi-performance--reliability) | Pi performance & reliability | Hardware decode, watchdog, core tests |
| [4](#phase-4-metadata--operations) | Metadata & operations | NFO/metadata, web admin, expanded tests |

Phases are sequential in intent but overlap is fine (e.g. start test scaffolding in Phase 3, expand in Phase 4).

---

## Phase 1: Playback & input

**Goal:** Make daily viewing feel like a real TV — hands on a remote, episodes flow naturally, channel changes have character.

### Deliverables

1. **Configurable autoplay**
   - Config block, e.g. `playback.autoplay` (`off` | `next_episode` | `next_in_season_only`).
   - Optional interstitial: “Up next” splash with countdown (configurable seconds; `0` = instant).
   - On natural end: advance `playing_index`, update resume state, start next file (reuse existing `playing_episodes` list).
   - Esc / back still stops immediately; no autoplay loop across seasons unless configured.
   - Document behavior in [Controls](../usage/controls.md) and [Configuration](../usage/configuration.md).

2. **Gamepad & TV remote input**
   - New input layer in front of `keymap.py`: map pygame joystick / hat / button events → logical actions (`up`, `down`, `select`, …).
   - Sensible defaults for common USB gamepads (D-pad + face buttons).
   - Optional: HDMI-CEC via `cec-client` or libCEC when present (best-effort; degrade gracefully).
   - In-app note on Help screen when a controller is detected.
   - No change to persisted keymap schema for keyboard; controller bindings in separate config section if needed.

3. **CRT channel-change feel**
   - Brief static/noise overlay (~200–400 ms) when jumping channels or entering a show from the show browser.
   - Optional short audio sting (bundled asset, muted when volume is 0).
   - Config: `ui.channel_change_effects` (`off` | `visual` | `visual+audio`).

### Success criteria

- A full season can be watched with one “Play” press and only Esc to stop.
- USB gamepad navigates show → season → episode → playback without a keyboard.
- Channel jumps feel distinct from ordinary menu redraws (visible static flash).

### Dependencies & notes

- Mostly touches `app.py`, `player.py`, `config.py`, `keymap.py`; small assets in `assets/`.
- Autoplay must respect existing resume/bookmark rules in `state.py` (near-end completion, mid-episode bookmark on manual stop).

### Phase 1 retro → informs Phase 2

Run after Phase 1 ships (or after a time-boxed slice is in production on a Pi).

| Question | Why it matters for Phase 2 |
|----------|----------------------------|
| Did autoplay cause surprise navigation (wrong next episode, season boundary confusion)? | Informs hot-rescan behavior — must not reset playback mid-autoplay chain. |
| Which input device won in practice (keyboard vs gamepad vs CEC)? | Prioritize rescan trigger binding on the dominant device. |
| Did users want per-show autoplay rules? | May add show-level overrides when implementing custom channel lineup. |
| Any ffmpeg stalls during back-to-back episodes? | Escalate watchdog / hardware-decode priority in Phase 3. |
| Is alphabetical channel order still the main pain point? | Validates Phase 2 custom lineup as the right next focus. |

**Retro outputs (record in this doc or a dated `docs/development/retros/` note):**

- [ ] Autoplay config defaults confirmed (`next_episode` vs conservative `off`).
- [ ] Controller mapping gaps list (devices that need explicit profiles).
- [ ] Decision: per-show autoplay override — yes/no/defer.
- [ ] Phase 2 scope adjustment (if any).

---

## Phase 2: Library & channel lineup

**Goal:** Parents curate what “TV” looks like; the library stays fresh without rebooting the kiosk.

### Deliverables

1. **Custom channel lineup**
   - Config schema, e.g.:
     ```json
     "channels": {
       "order": ["Bluey", "Mister Rogers", "Movies"],
       "numbers": { "Bluey": 1, "Movies": 9 }
     }
     ```
   - Unlisted shows: append after ordered shows (stable secondary sort) or hide via empty order + explicit list — document one clear rule.
   - Channel overlay and `#ch` input use **display channel** (assigned or fallback index).
   - Merge behavior unchanged when the same show name appears on multiple roots.

2. **Hot library rescan**
   - Trigger: configurable key combo (default: long-press `R` or dedicated key if added to keymap), plus CLI flag `--rescan` for systemd hook scripts.
   - Optional: periodic rescan interval in config (e.g. every 30 min while idle on show list only).
   - UX: non-blocking scan where possible; “Updating channels…” banner; preserve cursor by show name when still present.
   - Safe during playback: rescan disabled while `PLAYING` unless explicitly forced.

3. **Docs & operator workflow**
   - Update [Media library](../usage/media-library.md) and [Configuration](../usage/configuration.md) with channel config examples.
   - Note in [Raspberry Pi](../usage/raspberry-pi.md): USB insert → rescan keystroke.

### Success criteria

- Favorite shows occupy channels 1–N in config order; typing `3` jumps to the configured show.
- Adding a file to NAS/USB and rescanning surfaces new episodes without full service restart.
- Rescan never corrupts or clears `state.json`.

### Dependencies & notes

- `media.discover_shows()` already isolated — extend CLI/app to call it incrementally.
- Channel numbering interacts with autoplay and show browser; add tests for ordering helpers (even lightweight unit tests before Phase 3’s full suite).

### Phase 2 retro → informs Phase 3

| Question | Why it matters for Phase 3 |
|----------|----------------------------|
| How long does rescan take on the largest real library (file count, mount type)? | Sets watchdog timeouts and whether rescan must be incremental/async. |
| Did remount/NFS glitches appear after rescan? | May need mount health checks before Phase 3 watchdog. |
| Any stutter when autoplay chains after rescan discovered new files? | Hardware decode priority vs scan-time ffprobe caching. |
| Did custom channel numbers confuse kids (gaps in 1–9)? | UI polish only; no Phase 3 impact unless we add “tuning” delay per channel. |

**Retro outputs:**

- [ ] Typical rescan duration on reference Pi (document hardware + library size).
- [ ] Decision: incremental scan vs full walk — keep or redesign.
- [ ] ffprobe/duration cache invalidation rules written down.
- [ ] Phase 3 priority: hardware decode vs watchdog first.

---

## Phase 3: Pi performance & reliability

**Goal:** Smooth playback on target hardware; the kiosk recovers from stuck ffmpeg without power-cycling.

### Deliverables

1. **Hardware-accelerated decode on Raspberry Pi**
   - Prefer V4L2 / `h264_v4l2m2m` (or platform-appropriate) in ffmpeg pipeline when `is_pi()` and probe succeeds.
   - Fallback to current software path unchanged on desktop and when hw probe fails.
   - Config override: `playback.hw_decode`: `auto` | `on` | `off`.
   - Document supported Pi models and codecs in [Troubleshooting](../usage/troubleshooting.md).

2. **Watchdog & self-healing**
   - In-app: detect ffmpeg/ffplay stall (no frames / time not advancing for N seconds); kill and offer “Retry” or auto-retry once.
   - systemd: ensure `Restart=on-failure` and sensible `RestartSec` in `tv-time-capsule.service`.
   - Structured logging (stderr/journal): play start/stop, seek, recovery events — no secrets in logs.

3. **Core automated tests**
   - `media.py`: parsing, season labels, merge across roots, channel order helper (from Phase 2).
   - `state.py`: resume, completion, reset, autoplay-adjacent edge cases.
   - `player.py` (limited): mock subprocess — stall detection hook, clean teardown.
   - CI: run on push (GitHub Actions or equivalent); no Pi hardware required for unit tests.

### Success criteria

- 720p H.264 sample plays without sustained frame drops on reference Pi (define model in retro).
- Killing ffmpeg mid-play results in recoverable UI state, not a black-screen hang.
- Test suite covers regressions for Phases 1–2 behavior (autoplay index, channel order).

### Dependencies & notes

- Phase 1 retro may have already flagged decode pain during autoplay chains — use that to pick hw decode vs watchdog ordering within the phase.
- Keep `EmbeddedPlayer` interface stable so `app.py` changes stay minimal.

### Phase 3 retro → informs Phase 4

| Question | Why it matters for Phase 4 |
|----------|----------------------------|
| Is remaining slowness scan/metadata bound rather than decode bound? | Prioritize metadata cache vs web admin features. |
| Did watchdog false-positive (recover during slow network mount)? | Tune before adding web-triggered rescan in Phase 4. |
| What test gaps hurt most during Phase 3 work? | Drives Phase 4 test expansion targets. |
| Are thumbnails still the main setup friction? | Validates metadata/NFO priority. |

**Retro outputs:**

- [ ] Reference Pi model + resolution + measured CPU during playback.
- [ ] hw_decode default (`auto` vs `off`) for shipping config.
- [ ] Watchdog timeout values documented with rationale.
- [ ] Test coverage gaps list for Phase 4.

---

## Phase 4: Metadata & operations

**Goal:** Less manual artwork/naming work; easier configuration without editing JSON on the Pi.

### Deliverables

1. **Metadata without manual thumbnails**
   - Sidecar **NFO** parsing (title, plot optional; poster path or embedded art).
   - Optional: read local `poster.jpg` / `folder.jpg` conventions compatible with common media servers.
   - Fallback order unchanged: explicit thumbnail filenames → NFO art → first usable frame (optional, lazy) → text title.
   - Cache art paths and dimensions under `~/.local/share/tv-time-capsule/` to avoid repeated ffmpeg on scan.

2. **Lightweight web admin**
   - Local HTTP server (bind localhost + LAN interface, config port default e.g. `8765`).
   - Auth: simple token in config file (generated on first run); HTTPS optional/deferred.
   - Minimum pages: channel order editor (drag or ordered list), trigger rescan, view logs tail, read-only watch summary from `state.json`.
   - No cloud dependency; document firewall/LAN exposure in usage docs.

3. **Expanded tests & docs**
   - NFO parser fixtures; web API smoke tests (TestClient).
   - Operator guide: “Configure from your phone” section in usage README.

### Success criteria

- New show folder with NFO + poster needs no hand-placed `thumbnail.png` to look good in the browser.
- Channel order can be changed from a phone browser and persists to config without hand-editing JSON on the Pi.
- Web-triggered rescan respects Phase 2 safety rules (not during playback unless forced).

### Dependencies & notes

- Phase 2 rescan API and Phase 3 logging/watchdog are prerequisites for a safe admin UI.
- Keep web admin read-only for playback controls initially (no remote play/pause) to limit scope.

### Phase 4 retro → future work

| Question | Follow-up outside this plan |
|----------|----------------------------|
| Do operators want push notifications (library updated)? | Out of scope; note for backlog. |
| Is token auth enough on shared LANs? | May revisit if product direction changes. |
| Did NFO cover >80% of library without manual assets? | If not, consider Jellyfin/Plex export import as a separate initiative. |

**Retro outputs:**

- [ ] Metadata source breakdown (% NFO vs manual thumb vs fallback).
- [ ] Web admin usage: which screens mattered vs unused.
- [ ] Backlog candidates for a future Phase 5 (import formats, mDNS discovery, etc.).

---

## Cross-cutting principles

- **Config-first:** New behavior defaults to sensible off/auto; document every key in `config.example.json`.
- **Kiosk-safe:** No feature should require a keyboard or desktop session on the Pi.
- **State integrity:** `state.json` migrations must be backward compatible; never wipe on rescan or config edit.
- **Retro discipline:** Do not start Phase N+1 until Phase N retro outputs are checked off or explicitly deferred with a one-line reason.

---

## Tracking

| Phase | Status | Target retro date | Notes |
|-------|--------|-------------------|-------|
| 1 — Playback & input | Complete | | Autoplay, gamepad, channel FX |
| 2 — Library & channel lineup | Complete | | Custom channels, hot rescan, tests |
| 3 — Pi performance & reliability | Complete | | Hw decode, watchdog, tests, CI |
| 4 — Metadata & operations | Complete | | NFO/posters, web admin, tests |

Update this table as phases complete. Link retro notes from `docs/development/retros/YYYY-MM-DD-phase-N.md` when created.
