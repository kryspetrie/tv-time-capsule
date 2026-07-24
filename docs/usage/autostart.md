# Autostart & login

## Player autostart (systemd)

```bash
./scripts/enable-autostart.sh
./scripts/enable-autostart.sh --graphical
./scripts/enable-autostart.sh --start --media-dir /media/usb
./scripts/enable-autostart.sh --media-dir /a --media-dir /b --force-43

./scripts/disable-autostart.sh
./scripts/disable-autostart.sh --remove
```

Omit `--media-dir` to use `~/.config/tv-time-capsule/config.json` for the service user (including `mounts`).

Useful operations:

```bash
sudo systemctl start tv-time-capsule
sudo systemctl stop tv-time-capsule
sudo systemctl status tv-time-capsule
sudo journalctl -u tv-time-capsule -f
```

The unit template lives at `scripts/systemd/tv-time-capsule.service.in`. It:

- Runs as your normal user (not root)  
- Wants `network-online.target`  
- Restarts the app if it exits  

Autostart also invokes [networking](networking.md) and mount-privilege helpers.

## Auto-login (no password at boot)

```bash
./scripts/enable-autologin.sh              # console (Lite / kiosk)
./scripts/enable-autologin.sh --desktop    # GUI
./scripts/enable-autologin.sh --reboot
./scripts/enable-autologin.sh --disable
```

This wraps `raspi-config nonint do_boot_behaviour` (B2/B4) with a manual getty/LightDM fallback.

Note: systemd can start the player **without** interactive login. Auto-login mainly improves console UX and is required for `--graphical` desktop sessions.

## Combined workflow

Prefer [Kiosk ↔ desktop](kiosk-desktop.md) via `./scripts/set-mode.sh`, which wires auto-login + autostart + networking together.

## Desktop shortcut

On Raspberry Pi OS Desktop, a launcher is installed on the Desktop and in the app menu so you can restart the player if it was closed:

```bash
./scripts/install-desktop-shortcut.sh
./scripts/install-desktop-shortcut.sh --media-dir /media/usb
./scripts/install-desktop-shortcut.sh --remove
```

Skipped automatically on Lite or non-Pi systems.
