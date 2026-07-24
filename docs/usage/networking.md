# Networking

Kiosk/console mode has **no desktop Wi‑Fi applet**. The stack must stay enabled under systemd.

## What the project does

`scripts/ensure-networking.sh` (also run from autostart / `set-mode.sh kiosk` / `install-pi.sh`):

- Enables **NetworkManager** when present (else dhcpcd / systemd-networkd)  
- Enables `NetworkManager-wait-online` (or networkd wait-online)  
- Turns networking + Wi‑Fi radio on (`nmcli`)  
- Unblocks Wi‑Fi via `rfkill`  

The player systemd unit starts **after** `network-online.target` so remote mounts can succeed.

```bash
./scripts/ensure-networking.sh
./scripts/ensure-networking.sh --status
```

## Wi‑Fi passwords & keychain

The app does **not** configure Wi‑Fi from the OS keychain. Use NetworkManager:

| Mode | Approach |
|------|----------|
| Desktop | Connect in the UI; NM may store the PSK in the session keyring |
| Kiosk | Use a **system** connection (no unlocked user keyring required) |

```bash
# After connecting on the desktop, make the profile system-wide:
sudo nmcli connection modify "MyHomeWiFi" connection.permissions ""

# Or create a system Wi‑Fi connection directly:
sudo nmcli device wifi connect "MyHomeWiFi" password "secret"
sudo nmcli connection modify "MyHomeWiFi" connection.permissions ""
```

System connections live under `/etc/NetworkManager/system-connections/` (root-readable only).

## Remote media

Once the network is up, [remote mounts](remote-mounts.md) can attach Samba/NFS/SSHFS/FTP shares before the library scan.
