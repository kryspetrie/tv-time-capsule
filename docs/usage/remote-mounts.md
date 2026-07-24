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

Networking must be up in kiosk mode — see [Networking](networking.md).
