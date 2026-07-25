# Module map

Package root: `src/tv_time_capsule/`.

| Module | Role |
|--------|------|
| `__init__.py` | Package version |
| `__main__.py` | `python -m tv_time_capsule` |
| `cli.py` | Argparse entry: config, mounts, discovery, launch app |
| `app.py` | `TVTimeCapsule` — pygame UI, navigation, overlays, event loop |
| `player.py` | `EmbeddedPlayer` — ffmpeg raw RGB + ffplay audio; Pi hwaccel; stall watchdog |
| `metadata.py` | NFO parsing, poster.jpg / folder.jpg discovery |
| `web_admin.py` | Local HTTP admin (channels, rescan, logs) |
| `log.py` | stderr / journal logging + ring buffer for admin |
| `media.py` | Show/season/episode discovery, filename parsing, folder season labels |
| `mounts.py` | Mount/unmount helpers for remote stores |
| `secrets.py` | Keyring get/set + resolve helpers |
| `secrets_cli.py` | `tv-time-capsule-secrets` console script |
| `config.py` | Paths, colors (`C`), timing constants, config search/load/save |
| `state.py` | Resume position persistence |
| `keymap.py` | Default keymap, display names, load from config |
| `gamepad.py` | USB controller → logical navigation actions |
| `channels.py` | Custom show order and display channel numbers |
| `channel_fx.py` | Optional CRT snow burst on channel changes (pre-cached frames); shutdown collapse |
| `analog_artifacts.py` | Optional random static / tear / roll on the show browser |
| `test_patterns.py` | Easter egg dial codes `0` / `00` / `000` → user-supplied test pattern PNGs |
| `screensaver.py` | Bouncing VHS logo idle screensaver (2× pixelated scale, multiply tint) |
| `fonts.py` | VCR OSD Mono + pygame.font / freetype compatibility |
| `assets/` | Bundled `vcr_osd_mono.ttf`, `vhs.bmp` (packaged as package data) |

## Console scripts

Defined in `pyproject.toml`:

| Command | Target |
|---------|--------|
| `tv-time-capsule` | `tv_time_capsule.cli:main` |
| `tv-time-capsule-secrets` | `tv_time_capsule.secrets_cli:main` |

## External tools

| Tool | Used for |
|------|----------|
| ffmpeg / ffprobe | Video decode, duration/fps |
| ffplay | Audio during embedded playback |
| omxplayer | Legacy Pi GPU path |
| mount / mount.cifs / mount.nfs | Privileged mounts |
| sshfs / curlftpfs | FUSE remotes |
| nmcli / rfkill | Networking ensure script |
| raspi-config | Auto-login nonint API |
