# Kiosk ↔ desktop

## Why Desktop OS + kiosk?

| Approach | Pros | Cons |
|----------|------|------|
| **Desktop image, kiosk by default** (recommended) | Easy Samba/Wi‑Fi when needed; normal TV use stays lean | More disk; more packages to update |
| Lite only | Smallest image | No GUI; configure via SSH only |
| Always boot desktop + player | Simple mental model | Desktop RAM/CPU always on; player can cover the UI |

**Recommended:** install Desktop, run `set-mode.sh kiosk` for daily use, switch to `desktop` when you need to tinker.

## Switching modes

```bash
# Day-to-day appliance (console auto-login + player + networking kept alive)
./scripts/set-mode.sh kiosk --reboot

# Occasional full desktop (Wi‑Fi UI, file manager, Samba)
./scripts/set-mode.sh desktop --reboot

# Back to TV
./scripts/set-mode.sh kiosk --reboot

./scripts/set-mode.sh status
```

### What each mode does

**`kiosk`**

- Console auto-login (or `--graphical` for desktop session + player)  
- Enables player systemd unit  
- Runs networking ensure (Wi‑Fi stack stays available without a desktop applet)  

**`desktop`**

- Desktop auto-login  
- Stops and disables player autostart so the UI is usable  
- Use `--keep-service` to only stop the player for this boot while leaving the unit enabled  

### Light alternative

Stay on desktop and only pause the player:

```bash
sudo systemctl stop tv-time-capsule
# …configure shares / Wi‑Fi…
sudo systemctl start tv-time-capsule
```

## Graphical kiosk

If you prefer the player inside a desktop session:

```bash
./scripts/set-mode.sh kiosk --graphical --reboot
```

That uses desktop auto-login and `enable-autostart.sh --graphical` (`DISPLAY=:0`).
