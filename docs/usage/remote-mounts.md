# Remote mounts

TV Time Capsule can mount network media before scanning the library. Configure entries under `mounts` in `config.json` ([Configuration](configuration.md)).

## Supported types

| `type` | Protocol | Typical package |
|--------|----------|-----------------|
| `cifs` / `smb` | Samba / Windows shares | `cifs-utils` |
| `nfs` | NFS | `nfs-common` |
| `sshfs` / `sftp` | SSH filesystem | `sshfs` |
| `ftp` / `ftps` | FTP via curlftpfs | `curlftpfs` |

These are installed automatically by `install.sh` / `install-pi.sh`. To add them later:

```bash
./scripts/install-system-deps.sh
./scripts/ensure-mount-privileges.sh   # passwordless sudo for mount/umount
```

If a mount tool is missing at runtime, the player logs a skip line and continues with local media.

**Local verification:** Before wiring a NAS, run `./scripts/verify-remote-mounts.sh` (Docker on localhost). See [Remote mount testing](../development/remote-mount-testing.md).

CIFS and NFS need root; the privilege script installs a narrow sudoers rule so the kiosk user can run `sudo -n mount` without a password prompt.

## Common fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | One of the types above |
| `source` | yes | Share URL / path (`//host/share`, `host:/export`, `user@host:/path`, `ftp://host/path`) |
| `mountpoint` | yes | Local directory (created if needed) |
| `options` | no | Extra mount options (array or comma-separated string) |
| `credentials` | no | Path to a credentials file |
| `username` | no | Share username |
| `password` | no | Literal password (discouraged) |
| `keyring` / `password_keyring` | no | OS keychain item name for the password |
| `username_keyring` | no | OS keychain item name for the username |
| `domain` | no | CIFS domain / workgroup |
| `identity_file` | no | SSH private key for `sshfs` |

## Examples

### Samba / CIFS

```json
{
  "type": "cifs",
  "source": "//nas.local/KidsShows",
  "mountpoint": "/mnt/tv/nas-kids",
  "credentials": "/home/pi/.config/tv-time-capsule/nas.cred",
  "options": ["uid=1000", "gid=1000", "vers=3.0"]
}
```

Or with keychain (see [Secrets](secrets.md)):

```json
{
  "type": "cifs",
  "source": "//nas.local/KidsShows",
  "mountpoint": "/mnt/tv/nas-kids",
  "username": "media",
  "keyring": "nas-kids",
  "options": ["uid=1000", "gid=1000", "vers=3.0"]
}
```

### NFS

```json
{
  "type": "nfs",
  "source": "nas.local:/export/media",
  "mountpoint": "/mnt/tv/nfs-media"
}
```

### SSHFS

```json
{
  "type": "sshfs",
  "source": "pi@fileserver:/home/shared/media",
  "mountpoint": "/mnt/tv/ssh-media",
  "identity_file": "/home/pi/.ssh/id_rsa"
}
```

Prefer SSH keys. Password-based sshfs is not the primary path.

### FTP

```json
{
  "type": "ftp",
  "source": "ftp://nas.local/media",
  "mountpoint": "/mnt/tv/ftp-media",
  "credentials": "/home/pi/.config/tv-time-capsule/ftp.cred"
}
```

## Behaviour

- Mounts run at startup (with retries while the network comes up)  
- Already-mounted paths are left alone  
- Use `--skip-mounts` to skip this step  
- Failed mounts are logged; discovery continues with whatever paths are available  

## Playback cache

When an episode is read from a remote mount (NFS, SMB, SSHFS, etc.), the player can copy it to local disk in the background so playback stays smooth if the network hiccups.

Configure under `cache` in `config.json`:

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Turn background caching on or off |
| `directory` | `~/.local/share/tv-time-capsule/playback-cache` | Where cached files are stored |
| `max_bytes` | `2147483648` (2 GiB) | LRU size cap; oldest entries are removed when full |
| `prefetch_next` | `true` | Cache the next autoplay episode during the up-next countdown |
| `cache_before_playing` | `false` | Wait on the title screen with a progress bar until caching finishes before playback starts |

While you watch, a background thread copies the file. If the copy finishes before the episode ends, playback switches to the local copy at the current position. Retries after a stall also prefer the cache when it is ready.

Set `cache_before_playing` to `true` to skip that mid-playback switch: the now-playing title screen stays up with a green progress bar until the full file is local, then playback starts from the cache. **Enter** starts playback immediately from the remote stream (caching continues in the background). **Esc** cancels and returns to the browse menu.

While streaming with a background cache in progress, pause to see the cache progress bar. Press **C** to stop caching if it is affecting playback.

Local USB paths and other non-mount media are never cached.

Networking must be up in kiosk mode — see [Networking](networking.md).
