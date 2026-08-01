# Remote mount testing

Verify that **Samba (CIFS), SFTP (sshfs), and FTP** mounts work on your machine before pointing at a multi-terabyte NAS. The app does **not** mount SCP; use **SFTP via sshfs** for SSH servers.

## Quick test (Docker on localhost)

**Requirements:** Docker (`docker compose`), mount tools from `./scripts/install-system-deps.sh`, and passwordless `sudo` for CIFS (`./scripts/ensure-mount-privileges.sh --user "$USER"`).

```bash
./scripts/verify-remote-mounts.sh
```

The script:

1. Starts three containers on `127.0.0.1` (Samba, SFTP, vsftpd) with a tiny fake show library.
2. Mounts each share under `/tmp/tv-mount-test/{cifs,sftp,ftp}`.
3. Runs `discover_shows()` on all three mountpoints.
4. Prints pass/fail and tears down (unless you pass `--keep`).

Options:

| Option | Meaning |
|--------|---------|
| `--keep` | Leave containers running after the test (for manual debugging) |
| `--stop` | Stop containers and unmount only |
| `--no-docker` | Skip Docker; test mounts from `$TV_MOUNT_TEST_CONFIG` (see below) |

### Expected output (success)

```
✓ cifs  mounted //127.0.0.1/media -> /tmp/tv-mount-test/cifs
✓ sshfs mounted media@127.0.0.1:/media -> /tmp/tv-mount-test/sftp
✓ ftp   mounted ftp://127.0.0.1/ -> /tmp/tv-mount-test/ftp
✓ discovery: 1 show(s), 1 episode(s) across 3 mount(s)
```

## Test against your real NAS

After localhost tests pass, use the same mount types in `config.json` with your server hostname/IP.

### 1. Mount + scan (no UI)

```bash
poetry run tv-time-capsule --rescan-only
```

Startup logs list each mount (`mounted …` or `failed to mount …`). The rescan summary lists show/episode counts.

### 2. One mount at a time

Temporarily keep a single entry in `mounts` while debugging credentials or `vers=` / NFS options.

### 3. Skip mounts to isolate

```bash
poetry run tv-time-capsule --rescan-only --skip-mounts --media-dir /mnt/tv/nas-shows
```

Use this when the share is **already mounted** (e.g. by `/etc/fstab` or you ran `mount` manually).

### 4. Web admin

With admin enabled, the UI can verify paths and trigger library scans ([Web admin](../usage/web-admin.md)).

## Protocol notes

| You asked about | Supported? | How |
|-----------------|------------|-----|
| **Samba / SMB** | Yes | `"type": "cifs"` |
| **FTP** | Yes | `"type": "ftp"` (curlftpfs) |
| **SFTP** | Yes | `"type": "sshfs"` or `"sftp"` |
| **SCP** | No | Not a filesystem mount; use sshfs or Samba/NFS |
| **NFS** | Yes | `"type": "nfs"` — not in the Docker harness yet; test against a real NFS export |

### SFTP vs SCP

- **SFTP (sshfs):** kernel/FUSE view of `user@host:/path/shows` — what the player needs.
- **SCP:** copies files; no directory mount. If your NAS exposes SFTP (most SSH servers do), use sshfs.

### Large libraries

`discover_shows()` only **lists directories and filenames** with video extensions. It does not open or hash video files. Terabyte libraries are limited by **mount stability and scan time**, not by copying data.

For very large trees:

- Prefer **NFS or Samba** on LAN over FTP/FUSE if you see stalls.
- Use `"library": { "rescan_interval_seconds": 0 }` during dev to avoid background rescans.
- Run `--rescan-only` once after mount changes before launching the full UI.

## Manual debugging

With `./scripts/verify-remote-mounts.sh --keep`:

```bash
# Samba (credentials: media / secret)
sudo mount -t cifs //127.0.0.1/media /tmp/tv-mount-test/cifs \
  -o username=media,password=secret,vers=3.0,uid=$(id -u),gid=$(id -g)
ls /tmp/tv-mount-test/cifs

# SFTP (key generated under scripts/mount-test/.ssh/)
sshfs -o port=2222,IdentityFile=scripts/mount-test/.ssh/id_rsa,StrictHostKeyChecking=no \
  media@127.0.0.1:/media /tmp/tv-mount-test/sftp

# FTP
curlftpfs -o user=media:secret ftp://127.0.0.1 /tmp/tv-mount-test/ftp
```

Unmount:

```bash
sudo umount /tmp/tv-mount-test/cifs   # or: fusermount -u … for FUSE mounts
```

## Custom config (`--no-docker`)

Export a JSON file with a top-level `mounts` array (same shape as `config.json`) and run:

```bash
TV_MOUNT_TEST_CONFIG=~/my-mounts.json ./scripts/verify-remote-mounts.sh --no-docker
```

This runs `ensure_mounts()` + discovery against your entries without starting Docker.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `skip mount: mount.cifs not installed` | `./scripts/install-system-deps.sh` |
| `a password is required` / sudo mount fails | `./scripts/ensure-mount-privileges.sh --user "$USER"` |
| CIFS `Host is down` | Check Docker is running; wait and retry; try `vers=3.0` |
| sshfs `Connection refused` | Port 2222 — ensure SFTP container is up (`--keep`) |
| FTP hangs | Passive ports 21100–21110 must be published (compose file handles this) |
| Discovery finds 0 shows | Mount succeeded but path wrong — need `Show Name/s01/s01e01.mp4` layout ([Media library](../usage/media-library.md)) |
| Works in WSL, fails on Pi | Check uid/gid in CIFS `options`, credentials, and [Networking](../usage/networking.md) in kiosk |

## Related

- [WSL2 development](wsl2.md)
- [Remote mounts](../usage/remote-mounts.md)
- [Troubleshooting](../usage/troubleshooting.md)
