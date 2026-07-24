# Raspberry Pi setup

## Recommended image

Use **Raspberry Pi OS Desktop**, and run day-to-day in **kiosk mode** (console auto-login + player service).

You keep a real desktop for Wi‑Fi UI, Samba browsing, and file management, without paying desktop RAM/CPU cost during normal TV use. Versus Lite: more disk and packages to update; kiosk runtime is similar to Lite.

Details and switching: [Kiosk ↔ desktop](kiosk-desktop.md).

## Full install

From a git checkout on the Pi:

```bash
chmod +x install-pi.sh && ./install-pi.sh
```

This typically:

- Installs all system prerequisites via `scripts/install-system-deps.sh`
  (ffmpeg/ffprobe/ffplay, SDL runtime, keyring, cifs/nfs/sshfs/curlftpfs, NetworkManager, exFAT, mpv/omxplayer)  
- Ensures networking + mount sudoers privileges  
- Copies the project to `/opt/tv-time-capsule` and installs into a venv  
- Creates a sample media tree under `/media/usb`  
- Enables systemd autostart  
- Installs a desktop shortcut when a Desktop environment is present  
- Tweaks audio / older-Pi settings as needed  

To (re)install system packages later:

```bash
./scripts/install-system-deps.sh
```

Environment overrides:

| Variable | Default | Meaning |
|----------|---------|---------|
| `MEDIA_ROOT` | `/media/usb` | Sample media + optional `--media-dir` for autostart |
| `INSTALL_DIR` | `/opt/tv-time-capsule` | Install location |
| `AUTOSTART` | `yes` | Set to `no` to skip systemd enable |

## After install

1. Add shows under your media root(s) or configure [remote mounts](remote-mounts.md)  
2. Edit `~/.config/tv-time-capsule/config.json` as the service user  
3. Reboot (or `sudo systemctl start tv-time-capsule`)  

## Display notes

- You need a **display** (HDMI or composite), not necessarily a full desktop session  
- Default kiosk uses SDL/pygame on the console framebuffer / KMS when possible  
- `--graphical` autostart waits for a desktop session and sets `DISPLAY=:0`  

See [Autostart & login](autostart.md) and [Networking](networking.md).
