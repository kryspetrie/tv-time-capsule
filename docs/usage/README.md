# Usage documentation

How to install, configure, and run TV Time Capsule on a desktop or Raspberry Pi.

## Guides

1. [Getting started](getting-started.md) — install with pipx, first run, CLI flags  
2. [Controls](controls.md) — remote / keyboard map  
3. [Media library layout](media-library.md) — folder structures and thumbnails  
4. [Configuration](configuration.md) — `config.json`, paths, options  
5. [Remote mounts](remote-mounts.md) — Samba/CIFS, NFS, SSHFS, FTP  
6. [Secrets & keychain](secrets.md) — credential files and OS keyring  
7. [Raspberry Pi setup](raspberry-pi.md) — `install-pi.sh`, packages, shortcut  
8. [Kiosk ↔ desktop](kiosk-desktop.md) — recommended appliance workflow  
9. [Networking](networking.md) — Wi‑Fi in kiosk, NetworkManager  
10. [Autostart & login](autostart.md) — systemd, auto-login, desktop icon  
11. [Troubleshooting](troubleshooting.md) — common failures  
12. [Web admin](web-admin.md) — configure from phone/browser on LAN  
13. [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md) — CRT snow, glitches, screensaver, secret test patterns  

## Configure from your phone

Enable the [web admin](web-admin.md) (`admin.enabled: true`), then open `http://<pi-ip>:8765/` to reorder channels, rescan after USB copies, and view watch progress — no keyboard on the TV required.

## License

TV Time Capsule is licensed under [CC BY-NC 4.0](../../LICENSE). See the root README for a short summary.
