"""Remote media mounts (CIFS/SMB, NFS, SSHFS, FTP) from config."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

from .config import CONFIG_DIR
from .secrets import resolve_password, resolve_username

SUPPORTED_TYPES = {"cifs", "smb", "nfs", "sshfs", "sftp", "ftp", "ftps"}

# Tool name → short install hint (optional features; never abort the player)
_TOOL_HINTS = {
    "mount.cifs": "cifs-utils",
    "mount.nfs": "nfs-common",
    "sshfs": "sshfs",
    "curlftpfs": "curlftpfs",
}

_MISSING_PREFIX = "skip mount:"


def _expand(path: str | None) -> str | None:
    if path is None:
        return None
    return os.path.expanduser(os.path.expandvars(path))


def _find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for prefix in ("/sbin", "/usr/sbin", "/usr/bin", "/bin"):
        candidate = f"{prefix}/{name}"
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _missing_tool_message(tool: str) -> str:
    hint = _TOOL_HINTS.get(tool, tool)
    return f"{_MISSING_PREFIX} {tool} not installed (optional; apt/brew: {hint})"


def is_mounted(mountpoint: str) -> bool:
    """Return True if mountpoint is an active mount."""
    mountpoint = os.path.abspath(_expand(mountpoint) or mountpoint)
    if os.path.ismount(mountpoint):
        return True
    if _find_tool("findmnt"):
        result = subprocess.run(
            ["findmnt", "-n", mountpoint],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    return False


def _run(cmd: list[str], *, use_sudo: bool = False) -> subprocess.CompletedProcess:
    full = list(cmd)
    if use_sudo:
        full = ["sudo", "-n", "--"] + full
    return subprocess.run(full, capture_output=True, text=True, check=False)


def _normalize_type(raw: str) -> str:
    t = (raw or "").strip().lower()
    if t == "smb":
        return "cifs"
    if t == "sftp":
        return "sshfs"
    if t == "ftps":
        return "ftp"
    return t


def _required_tool_for(mount_type: str) -> str | None:
    if mount_type == "cifs":
        return "mount.cifs"
    if mount_type == "nfs":
        return "mount.nfs"
    if mount_type == "sshfs":
        return "sshfs"
    if mount_type == "ftp":
        return "curlftpfs"
    return None


def _options_list(entry: dict[str, Any]) -> list[str]:
    opts = entry.get("options") or []
    if isinstance(opts, str):
        return [p for p in opts.split(",") if p]
    return [str(o) for o in opts]


def _ensure_mountpoint(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _write_cifs_credfile(
    username: str,
    password: str,
    domain: str | None = None,
) -> str:
    """Write a 0600 credentials file for mount.cifs (avoids password in ps)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="cifs-", suffix=".cred", dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"username={username}\n")
            f.write(f"password={password}\n")
            if domain:
                f.write(f"domain={domain}\n")
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def _load_credentials_file(path: str) -> dict[str, str]:
    kv: dict[str, str] = {}
    plain: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        lines = [
            ln.strip()
            for ln in f
            if ln.strip() and not ln.strip().startswith("#")
        ]
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            kv[k.strip().lower()] = v.strip()
        else:
            plain.append(ln)
    if "username" not in kv and "user" not in kv and plain:
        kv["username"] = plain[0]
    if "password" not in kv and len(plain) > 1:
        kv["password"] = plain[1]
    if "user" in kv and "username" not in kv:
        kv["username"] = kv["user"]
    return kv


def _resolve_auth(entry: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return (username, password, domain) from file / keyring / literals."""
    username = resolve_username(entry)
    password = resolve_password(entry)
    domain = entry.get("domain")

    creds = _expand(entry.get("credentials"))
    if creds and os.path.isfile(creds):
        kv = _load_credentials_file(creds)
        username = username or kv.get("username")
        if password is None:
            password = kv.get("password")
        domain = domain or kv.get("domain")

    return username, password, domain


def _mount_cifs(entry: dict[str, Any], mountpoint: str) -> subprocess.CompletedProcess:
    source = entry["source"]
    opts = _options_list(entry)
    username, password, domain = _resolve_auth(entry)
    temp_cred: str | None = None

    creds = _expand(entry.get("credentials"))
    if creds and os.path.isfile(creds) and password is None:
        opts = [o for o in opts if not o.startswith("credentials=")]
        opts.append(f"credentials={creds}")
    elif username and password is not None:
        temp_cred = _write_cifs_credfile(username, password, domain)
        opts = [
            o
            for o in opts
            if not o.startswith("credentials=")
            and not o.startswith("username=")
            and not o.startswith("password=")
        ]
        opts.append(f"credentials={temp_cred}")
    elif username:
        opts.append(f"username={username}")
        if domain:
            opts.append(f"domain={domain}")

    for default in ("file_mode=0644", "dir_mode=0755"):
        key = default.split("=", 1)[0]
        if not any(o.startswith(key + "=") for o in opts):
            opts.append(default)

    cmd = ["mount", "-t", "cifs", source, mountpoint]
    if opts:
        cmd.extend(["-o", ",".join(opts)])
    try:
        return _run(cmd, use_sudo=True)
    finally:
        if temp_cred:
            try:
                os.unlink(temp_cred)
            except OSError:
                pass


def _mount_nfs(entry: dict[str, Any], mountpoint: str) -> subprocess.CompletedProcess:
    source = entry["source"]
    opts = _options_list(entry)
    if not any(o.startswith("soft") or o == "soft" for o in opts):
        opts.append("soft")
    if not any(o.startswith("timeo=") for o in opts):
        opts.append("timeo=30")
    cmd = ["mount", "-t", "nfs", source, mountpoint]
    if opts:
        cmd.extend(["-o", ",".join(opts)])
    return _run(cmd, use_sudo=True)


def _mount_sshfs(entry: dict[str, Any], mountpoint: str) -> subprocess.CompletedProcess:
    source = entry["source"]
    opts = _options_list(entry)
    for default in (
        "reconnect",
        "ServerAliveInterval=15",
        "ServerAliveCountMax=3",
        "allow_other",
    ):
        key = default.split("=", 1)[0]
        if not any(o == default or o.startswith(key + "=") for o in opts):
            opts.append(default)
    identity = _expand(entry.get("identity_file") or entry.get("IdentityFile"))
    if identity:
        opts = [o for o in opts if not o.startswith("IdentityFile=")]
        opts.append(f"IdentityFile={identity}")
    cmd = ["sshfs", source, mountpoint]
    if opts:
        cmd.extend(["-o", ",".join(opts)])
    result = _run(cmd, use_sudo=False)
    if result.returncode != 0 and "allow_other" in opts:
        result = _run(cmd, use_sudo=True)
    return result


def _mount_ftp(entry: dict[str, Any], mountpoint: str) -> subprocess.CompletedProcess:
    source = entry["source"]
    if "://" not in source:
        source = "ftp://" + source
    opts = _options_list(entry)
    user, password, _domain = _resolve_auth(entry)
    if user:
        opts = [o for o in opts if not o.startswith("user=")]
        if password is not None:
            opts.append(f"user={user}:{password}")
        else:
            opts.append(f"user={user}")
    cmd = ["curlftpfs", source, mountpoint]
    if opts:
        cmd.extend(["-o", ",".join(opts)])
    return _run(cmd, use_sudo=False)


def mount_one(entry: dict[str, Any]) -> tuple[bool, str]:
    """Attempt to mount a single config entry. Returns (ok, message).

    Missing optional tools are reported as skip messages (not hard failures).
    """
    mount_type = _normalize_type(entry.get("type", ""))
    source = entry.get("source")
    mountpoint = _expand(entry.get("mountpoint"))

    if mount_type not in SUPPORTED_TYPES and mount_type not in {
        "cifs",
        "nfs",
        "sshfs",
        "ftp",
    }:
        return False, f"unsupported mount type: {entry.get('type')!r}"
    if not source or not mountpoint:
        return False, "mount entry requires source and mountpoint"

    if is_mounted(mountpoint):
        return True, f"already mounted: {mountpoint}"

    tool = _required_tool_for(mount_type)
    if tool and not _find_tool(tool):
        return False, f"{_missing_tool_message(tool)} — {source}"

    try:
        _ensure_mountpoint(mountpoint)
    except OSError as exc:
        return False, f"cannot create mountpoint {mountpoint}: {exc}"

    if mount_type == "cifs":
        result = _mount_cifs(entry, mountpoint)
    elif mount_type == "nfs":
        result = _mount_nfs(entry, mountpoint)
    elif mount_type == "sshfs":
        result = _mount_sshfs(entry, mountpoint)
    elif mount_type == "ftp":
        result = _mount_ftp(entry, mountpoint)
    else:
        return False, f"unsupported mount type: {mount_type}"

    if result.returncode == 0 and is_mounted(mountpoint):
        return True, f"mounted {source} -> {mountpoint}"

    err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
    if "password is required" in err.lower() or "a password is required" in err.lower():
        err += " (install mount sudoers via scripts/ensure-mount-privileges.sh)"
    if entry.get("keyring") or entry.get("password_keyring"):
        err += " (check: tv-time-capsule-secrets get <name>)"
    return False, f"failed to mount {source} -> {mountpoint}: {err}"


def _is_permanent_failure(msg: str) -> bool:
    return msg.startswith(_MISSING_PREFIX) or msg.startswith("unsupported mount type")


def ensure_mounts(
    mounts: list[dict[str, Any]] | None,
    *,
    retries: int = 6,
    delay_s: float = 5.0,
) -> tuple[list[str], list[str]]:
    """Ensure all configured mounts are active.

    Returns ``(all_messages, failure_messages)``. Missing tools and other
    permanent failures are logged once and skipped; transient network failures
    are retried. Never aborts the player.
    """
    if not mounts:
        return [], []

    messages: list[str] = []
    failures: list[str] = []
    pending = [dict(m) for m in mounts if isinstance(m, dict)]

    for attempt in range(1, retries + 1):
        still = []
        for entry in pending:
            ok, msg = mount_one(entry)
            label = entry.get("mountpoint") or entry.get("source") or "?"
            if ok:
                if attempt == 1 or "already mounted" not in msg:
                    messages.append(msg)
            elif _is_permanent_failure(msg):
                messages.append(msg)
                failures.append(msg)
            else:
                still.append(entry)
                if attempt == retries:
                    messages.append(msg)
                    failures.append(msg)
                else:
                    print(
                        f"mount retry {attempt}/{retries} for {label}: {msg}",
                        flush=True,
                    )
        pending = still
        if not pending:
            break
        time.sleep(delay_s)

    return messages, failures


def mountpoints_from_config(mounts: list[dict[str, Any]] | None) -> list[str]:
    """Return expanded mountpoint paths from mount entries."""
    out = []
    for entry in mounts or []:
        if not isinstance(entry, dict):
            continue
        mp = _expand(entry.get("mountpoint"))
        if mp:
            out.append(mp)
    return out
