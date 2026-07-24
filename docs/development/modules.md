# Module map

Package root: `src/tv_time_capsule/`.

| Module | Role |
|--------|------|
| `__init__.py` | Package version |
| `__main__.py` | `python -m tv_time_capsule` |
| `cli.py` | Argparse entry: config, mounts, discovery, launch app |
| `app.py` | `TVTimeCapsule` — pygame UI, navigation, overlays, event loop |
| `player.py` | `EmbeddedPlayer` — ffmpeg raw RGB + ffplay audio; omxplayer fallback |
| `media.py` | Show/season/episode discovery and filename parsing |
| `mounts.py` | Mount/unmount helpers for remote stores |
| `secrets.py` | Keyring get/set + resolve helpers |
| `secrets_cli.py` | `tv-time-capsule-secrets` console script |
| `config.py` | Paths, colors (`C`), timing constants, load/save config |
| `state.py` | Resume position persistence |
| `keymap.py` | Default keymap and display names |
| `fonts.py` | VCR OSD Mono + pygame.font / freetype compatibility |
| `assets/` | Bundled `vcr_osd_mono.ttf` (packaged as package data) |

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
