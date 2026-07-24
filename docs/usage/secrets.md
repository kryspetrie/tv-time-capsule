# Secrets & keychain

Prefer **not** storing passwords in `config.json`. Use a credentials file or the OS keychain.

## Credentials files

Mode `600`, owned by the service user:

```bash
chmod 600 ~/.config/tv-time-capsule/*.cred
```

### CIFS (`nas.cred`)

```
username=media
password=secret
domain=WORKGROUP
```

### FTP (`ftp.cred`)

```
username=media
password=secret
```

Point mounts at the file with `"credentials": "/home/pi/.config/tv-time-capsule/nas.cred"`.

## OS keychain / keyring

Mount passwords can live in:

- macOS Keychain  
- Windows Credential Locker  
- Linux Secret Service (GNOME Keyring / KWallet) when the session keyring is unlocked  

### CLI

```bash
tv-time-capsule-secrets set nas-kids    # prompts (stays out of shell history)
tv-time-capsule-secrets get nas-kids    # confirms presence; does not print the secret
tv-time-capsule-secrets delete nas-kids
```

Secrets are stored under service name `tv-time-capsule` and the item name you choose.

### Config

```json
{
  "type": "cifs",
  "source": "//nas.local/KidsShows",
  "mountpoint": "/mnt/tv/nas-kids",
  "username": "media",
  "keyring": "nas-kids"
}
```

Optional: `"username_keyring": "nas-kids-user"` if the username should also come from the keychain. `"password_keyring"` is an alias of `"keyring"`.

CIFS passwords from the keyring are written to a temporary `0600` credentials file for `mount.cifs`, then removed, so the password does not appear in process arguments.

## Kiosk caveat (important)

A **user** keyring is often **locked** without a desktop login session. Console kiosk may not be able to read keychain secrets.

| Scenario | Recommendation |
|----------|----------------|
| Desktop / development | Keychain is convenient |
| Console kiosk | Use `credentials` files (`chmod 600`) |
| Desktop auto-login kiosk | Keyring may unlock with the session — test on device |

## Wi‑Fi passwords

The app **does not** read Wi‑Fi PSKs from the keychain. Networking is owned by NetworkManager. See [Networking](networking.md) for system connections that work in kiosk mode.
