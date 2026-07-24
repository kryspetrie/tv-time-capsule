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

## Desktop shortcut asks “Execute?”

Re-run `./scripts/install-desktop-shortcut.sh` so the `.desktop` file is marked trusted, or right-click → Allow Launching (Pi Desktop).
