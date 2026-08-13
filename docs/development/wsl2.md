# Development on Windows (WSL2)

The supported way to develop on a Windows PC is **WSL2** (Ubuntu or Debian). You get the same Linux toolchain as macOS/Pi — bash installers, remote mounts, ffmpeg, and pygame — without maintaining a separate Windows code path.

Native Windows is possible for quick UI checks (`--windowed`, local `--media-dir`), but WSL2 is recommended whenever you work with **Samba, NFS, SFTP/SSHFS, or FTP** libraries.

## Setup

### 1. Install WSL2

In PowerShell (Admin):

```powershell
wsl --install -d Ubuntu
```

Reboot if prompted. Update the distro:

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Put the repo on the Linux filesystem

Clone inside WSL, not under `/mnt/c/`:

```bash
mkdir -p ~/dev
cd ~/dev
git clone git@github.com:kryspetrie/tv-time-capsule.git
cd tv-time-capsule
```

Files on `/mnt/c/...` work but are **much slower** for git, Python imports, and scanning large media trees.

### 3. Install prerequisites

```bash
./install.sh --venv
# or: poetry install && ./scripts/ensure-pygame-mixer.sh
```

This installs ffmpeg and SDL/pygame build deps, then the app into `.venv`.

### 4. Config and sample media

```bash
cp config.example.json config.json
./scripts/fetch-sample-media.sh   # optional small test library
```

Edit `config.json` for your paths. In dev, `./config.json` in the repo root is picked up automatically ([Configuration](../usage/configuration.md#where-the-app-looks-for-configjson)).

### 5. Run windowed

```bash
poetry run tv-time-capsule --windowed --media-dir ./media
# or:
.venv/bin/tv-time-capsule --windowed --media-dir ./sample/media-a
```

**Display:** Windows 11 + WSLg shows the pygame window automatically. On Windows 10, install an X server (VcXsrv, GWSL) and set `DISPLAY` if the window does not appear.

Useful dev flags:

| Flag | Why |
|------|-----|
| `--windowed` | Fixed 800×600 window; safe zone defaults to 0% |
| `--scale N` | Integer 640×480 scale (`2`–`6`); implies `--windowed` |
| `--no-admin` | Skip web admin / port 8765 |
| `--skip-mounts` | Local media only — no network mounts at startup |
| `--rescan-only` | Scan library and print summary, then exit (no UI) |

## Remote media (terabytes on a NAS)

Production and serious dev both use the same mount layer ([Remote mounts](../usage/remote-mounts.md)):

| Config `type` | Protocol | Mount tool |
|---------------|----------|------------|
| `cifs` / `smb` | Samba / Windows shares | `mount.cifs` |
| `nfs` | NFS | `mount.nfs` |
| `sshfs` / `sftp` | SSH filesystem | `sshfs` |
| `ftp` | FTP | `curlftpfs` |

**SCP is not a mount type.** SCP copies files one-by-one; the player expects a **directory tree** via CIFS, NFS, SFTP (sshfs), or FTP. Use SFTP/sshfs for SSH servers.

### Privileges in WSL

CIFS and NFS need root:

```bash
./scripts/ensure-mount-privileges.sh --user "$USER"
./scripts/install-system-deps.sh   # cifs-utils, nfs-common, sshfs, curlftpfs
```

SSHFS and FTP usually mount as your user; CIFS/NFS use `sudo -n mount` after the sudoers step.

### Point at your real library

Example `config.json` snippet:

```json
{
  "media_paths": ["/mnt/tv/nas-shows"],
  "mounts": [
    {
      "type": "cifs",
      "source": "//192.168.1.50/KidsTV",
      "mountpoint": "/mnt/tv/nas-shows",
      "credentials": "~/.config/tv-time-capsule/nas.cred",
      "options": ["uid=1000", "gid=1000", "vers=3.0"]
    }
  ]
}
```

Validate **without opening the UI**:

```bash
poetry run tv-time-capsule --rescan-only
```

Discovery only walks directory names and file extensions — it does not read video data, so multi-terabyte libraries are fine as long as the mount is stable.

### Access Windows drives from WSL

- ` /mnt/c/Users/...` — local files, no mount config needed; add path to `media_paths`.
- A share mounted in Windows (e.g. `\\nas\KidsTV`) is **not** automatically visible in WSL. Prefer mounting inside WSL via `mounts` in config, or mount in WSL with `sudo mount -t drvfs '\\server\share' /mnt/nas`.

## Local mount verification (before your NAS)

Use Docker test servers on localhost to prove Samba, SFTP, and FTP mounts work on your machine:

```bash
./scripts/verify-remote-mounts.sh
```

See [Remote mount testing](remote-mount-testing.md) for details, troubleshooting, and how this maps to a production NAS.

## Docker in WSL2

Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with **WSL2 integration** enabled for your Ubuntu distro. The mount verification script and any future containerized tests expect `docker compose` on PATH inside WSL.

## Day-to-day workflow

```bash
cd ~/dev/vintage-tv
git pull
poetry install
./scripts/ensure-pygame-mixer.sh    # if pygame.mixer missing after upgrade
poetry run pytest -q
poetry run tv-time-capsule --windowed --media-dir ./media --no-admin
```

After changing mount config:

```bash
poetry run tv-time-capsule --rescan-only
```

## What WSL2 does not cover

- Raspberry Pi V4L2 hardware decode (Linux Pi only; WSL uses software ffmpeg — fine for UI/dev).
- **systemd kiosk** / autostart — test on a Pi or Linux VM; see [Raspberry Pi setup](../usage/raspberry-pi.md).
- **Native Windows** pygame/kiosk — not a supported target; use WSL2 instead.

## Related docs

- [Development setup](setup.md)
- [Remote mounts](../usage/remote-mounts.md)
- [Remote mount testing](remote-mount-testing.md)
- [Secrets](../usage/secrets.md) — keyring / credentials files for shares
