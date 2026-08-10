# Troubleshooting

## No shows found

- Check `media_paths` and that folders contain supported video files ([Media library](media-library.md))  
- For network media, confirm mounts succeeded (startup logs) and [networking](networking.md) is up  
- Try `tv-time-capsule --media-dir /path/to/shows --skip-mounts` to isolate mount issues  

## Mount failed (CIFS/NFS)

- Install packages: `cifs-utils`, `nfs-common`  
- Run `./scripts/ensure-mount-privileges.sh` so `sudo -n mount` works  
- Verify credentials file mode `600` or keyring item: `tv-time-capsule-secrets get <name>`  
- In kiosk, keyring may be locked — use a credentials file ([Secrets](secrets.md))  
- Test manually: `sudo mount -t cifs //nas/share /mnt/test -o credentials=...`  

## Keyring secret missing / locked

- Desktop: unlock the login keyring (or log into the GUI once)  
- Kiosk: switch that mount to a `credentials` file  
- Confirm: `tv-time-capsule-secrets get <name>`  

## Wi‑Fi down in kiosk

```bash
./scripts/ensure-networking.sh --status
nmcli device status
nmcli connection show
```

Ensure the Wi‑Fi profile is a **system** connection (`connection.permissions` empty). See [Networking](networking.md).

## Black screen / fails to open display

- Confirm a display is connected (HDMI/composite)  
- Console kiosk: avoid needing `DISPLAY`; graphical mode needs a desktop session  
- Try `./scripts/set-mode.sh desktop`, start the app from a terminal, then switch back  

## Player won’t stay running

```bash
sudo systemctl status tv-time-capsule
sudo journalctl -u tv-time-capsule -e
```

Check ffmpeg/ffplay are installed and numpy is available in the venv/pipx environment.

## ffmpeg / playback warnings

```bash
./scripts/install-system-deps.sh
```

Or manually: `sudo apt install ffmpeg` / `brew install ffmpeg`.

## Choppy video on Raspberry Pi

- Set `"hw_decode": "auto"` in `playback` (default) — uses V4L2 for H.264 when available  
- `"hw_decode": "off"` forces software decode (slower but works for all codecs)  
- `"hw_decode": "on"` always tries hardware decode (may fail on non-H.264 files)  
- Supported on Pi 3/4/5 with Raspberry Pi OS ffmpeg builds that expose `v4l2m2m`  
- VP9 / HEVC / most MKV codecs may still need software decode or remux to H.264  

Check what ffmpeg offers on the device:

```bash
ffmpeg -hide_banner -hwaccels
journalctl -u tv-time-capsule -e | grep -E 'play |stall|hwaccel'
```

## Playback stalls / black screen during video

The in-app watchdog auto-retries once, then shows **PLAYBACK STALLED** (Enter to retry, Esc to go back). Events are logged to stderr / journal.

```bash
journalctl -u tv-time-capsule -e
```

If the service exits unexpectedly, systemd restarts it (`Restart=on-failure`, 5s delay).

## Desktop shortcut asks “Execute?”

Re-run `./scripts/install-desktop-shortcut.sh` so the `.desktop` file is marked trusted, or right-click → Allow Launching (Pi Desktop).

## Fun tweaks / CRT effects

See [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md). Common issues:

| Symptom | Check |
|---------|--------|
| No static on channel change | Enable `ui.channel_snow` or `--channel-snow`. Snow runs on **numeric commit only**, not arrow keys. |
| Snow silent | Set `ui.channel_snow_audio: true` (defaults on when snow is enabled). If `pygame.mixer` is missing, run `./scripts/ensure-pygame-mixer.sh` (rebuilds pygame with SDL_mixer; ffplay is used as a fallback). |
| Glitches missing during playback / Retro / test patterns | Expected — `analog_artifacts` skips video and easter eggs. |
| Glitches too rare / CLI rate ignored | Use `--analog-artifact-rate N` (auto-enables when `N > 0`); confirm you are not on PLAYING / Retro. Rate is glitches per minute (0–60). |
| Test pattern “not found” | Add your own `colorbars.png`, `grid.png`, `indianhead.png` under `src/tv_time_capsule/assets/` — the app never generates them. |
| Screensaver never starts | `screensaver.enabled: true` or `--screensaver`; timeout is menu idle only (not during playback). |
