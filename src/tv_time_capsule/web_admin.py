"""Local HTTP admin UI (channel lineup, rescan, logs, watch summary)."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import urlparse

from .log import LOG, log_tail


class AdminContext(Protocol):
    """Callbacks into the running TV Time Capsule app."""

    def admin_status(self) -> dict[str, Any]: ...

    def admin_shows(self) -> list[str]: ...

    def admin_channels(self) -> dict[str, Any]: ...

    def admin_save_channels(self, order: list[str], numbers: dict[str, int]) -> None: ...

    def admin_request_rescan(self) -> tuple[bool, str]: ...

    def admin_watch_summary(self) -> dict[str, Any]: ...

    def admin_keymap(self) -> dict[str, Any]: ...

    def admin_library(self) -> dict[str, Any]: ...

    def admin_config_get(self) -> dict[str, Any]: ...

    def admin_config_save(self, raw: dict) -> tuple[bool, str]: ...

    def admin_config_reload(self) -> tuple[bool, str]: ...

    def admin_settings(self) -> dict[str, Any]: ...

    def admin_update_settings(self, patch: dict) -> tuple[bool, str]: ...

    def admin_verify_path(self, path: str) -> dict[str, Any]: ...

    def admin_verify_mount(self, index: int) -> dict[str, Any]: ...

    def admin_scan_library(
        self, paths: list[str] | None = None, *, apply: bool = False
    ) -> dict[str, Any]: ...

    def admin_update_paths(self, patch: dict) -> tuple[bool, str]: ...


ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TV Time Capsule Admin</title>
<style>
  :root { font-family: system-ui, sans-serif; background: #0a0e1a; color: #e8ecf4; }
  body { max-width: 960px; margin: 0 auto; padding: 1rem; }
  h1 { color: #5096f0; font-size: 1.4rem; }
  h2 { font-size: 1.1rem; margin-top: 1.5rem; color: #60d8dc; }
  h3 { font-size: 0.95rem; color: #8899cc; margin: 0.5rem 0; }
  input, button, select, textarea { font-size: 1rem; padding: 0.4rem 0.6rem; margin: 0.2rem 0; }
  input[type=text], input[type=password], textarea { width: 100%; box-sizing: border-box; }
  textarea { font-family: ui-monospace, monospace; font-size: 0.85rem; min-height: 200px; }
  button { background: #1e3c78; color: #fff; border: 1px solid #5096f0; border-radius: 4px; cursor: pointer; }
  button:hover { background: #2a5098; }
  button.secondary { background: #1a2438; border-color: #445; }
  .card { background: #121a2e; border: 1px solid #253050; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
  .muted { color: #8899aa; font-size: 0.9rem; }
  .row { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
  .toggle { display: flex; align-items: center; gap: 0.5rem; margin: 0.35rem 0; }
  .toggle input { width: auto; }
  .toggle.locked { opacity: 0.55; }
  #log { font-family: monospace; font-size: 0.75rem; white-space: pre-wrap; max-height: 240px; overflow: auto; background: #060810; padding: 0.5rem; }
  ul.channel-list { list-style: none; padding: 0; }
  ul.channel-list li { display: flex; gap: 0.5rem; align-items: center; padding: 0.35rem 0; border-bottom: 1px solid #253050; }
  .err { color: #f66; }
  .ok { color: #5d8; }
  .lib-tree { font-size: 0.85rem; max-height: 420px; overflow: auto; background: #060810; padding: 0.75rem; border-radius: 4px; }
  .lib-tree details { margin: 0.25rem 0 0.25rem 1rem; }
  .lib-tree summary { cursor: pointer; color: #a8c8ff; }
  .lib-tree .ep { color: #8899aa; margin-left: 1.5rem; }
  .path-row { display: flex; gap: 0.4rem; margin: 0.35rem 0; align-items: center; }
  .path-row input { flex: 1; }
  .mount-block { border: 1px solid #253050; border-radius: 6px; padding: 0.5rem; margin: 0.5rem 0; }
  .msg { margin-left: 0.5rem; font-size: 0.9rem; }
</style>
</head>
<body>
<h1>TV Time Capsule Admin</h1>
<p class="muted">On your home network only. No login — anyone who can reach this port can edit settings.</p>

<div class="card">
  <h2>Status</h2>
  <pre id="status">Loading…</pre>
</div>

<div class="card">
  <h2>Player settings</h2>
  <p class="muted">Toggles save to config and apply immediately. Items marked (CLI) are locked by startup flags.</p>
  <div id="settings"></div>
  <button onclick="saveSettings()">Save settings</button>
  <span id="settings-msg" class="msg"></span>
</div>

<div class="card">
  <h2>Media paths</h2>
  <p class="muted">Local folders scanned for shows. Verify checks readability; Scan previews discovery; Apply scan updates the running library.</p>
  <div id="media-paths"></div>
  <div class="row">
    <button class="secondary" onclick="addMediaPath()">Add path</button>
    <button onclick="savePaths()">Save paths</button>
    <button class="secondary" onclick="verifyAllPaths()">Verify all</button>
    <button class="secondary" onclick="scanLibrary(false)">Scan (preview)</button>
    <button onclick="scanLibrary(true)">Scan &amp; apply</button>
  </div>
  <span id="paths-msg" class="msg"></span>
</div>

<div class="card">
  <h2>Network mounts</h2>
  <p class="muted">Configured remote shares (CIFS, NFS, SSHFS, FTP). Verify attempts mount if needed.</p>
  <div id="mounts"></div>
  <button class="secondary" onclick="addMount()">Add mount</button>
  <button onclick="savePaths()">Save mounts</button>
  <span id="mounts-msg" class="msg"></span>
</div>

<div class="card">
  <h2>Cached library</h2>
  <p class="muted" id="lib-summary">Loading…</p>
  <div id="lib-tree" class="lib-tree">Loading…</div>
  <button class="secondary" onclick="loadLibrary()">Refresh tree</button>
  <button onclick="rescan()">Rescan (in-app queue)</button>
  <span id="scan-msg" class="msg"></span>
</div>

<div class="card">
  <h2>Channel lineup</h2>
  <p class="muted">Order shows; set optional fixed channel numbers.</p>
  <ul id="channels" class="channel-list"></ul>
  <button onclick="saveChannels()">Save channels</button>
  <span id="ch-msg" class="msg"></span>
</div>

<div class="card">
  <h2>Config file</h2>
  <p class="muted" id="config-path"></p>
  <textarea id="config-editor" spellcheck="false"></textarea>
  <div class="row">
    <button onclick="saveConfig()">Save config</button>
    <button class="secondary" onclick="reloadConfig()">Reload from disk</button>
  </div>
  <span id="config-msg" class="msg"></span>
</div>

<div class="card">
  <h2>Watch progress</h2>
  <pre id="watch">Loading…</pre>
</div>

<div class="card">
  <h2>Keymap</h2>
  <p class="muted">Current keyboard bindings (read-only). Rebind in-app with Tab.</p>
  <pre id="keymap">Loading…</pre>
</div>

<div class="card">
  <h2>Recent logs</h2>
  <pre id="log"></pre>
  <button onclick="loadLogs()">Refresh logs</button>
</div>

<script>
async function api(path, opts={}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) return r.json();
  return r.text();
}

let channelState = {order: [], numbers: {}, shows: []};
let mediaPaths = [];
let mounts = [];
let settingsState = {};

const SETTING_LABELS = {
  channel_snow: "Channel snow (tune burst)",
  shutdown_collapse: "Shutdown CRT collapse",
  channel_snow_audio: "Channel snow audio",
  scanlines: "CRT scanlines",
  analog_artifacts: "Analog signal glitches (static / tear / roll)",
  analog_artifact_rate: "Analog glitches per minute",
  safe_zone_top: "Safe zone top (%)",
  safe_zone_bottom: "Safe zone bottom (%)",
  safe_zone_left: "Safe zone left (%)",
  safe_zone_right: "Safe zone right (%)",
  safe_zone_offset_x: "Safe zone offset X (px)",
  safe_zone_offset_y: "Safe zone offset Y (px)",
  screensaver: "Screensaver",
  screensaver_timeout_seconds: "Screensaver timeout (seconds)",
};

function renderSettings() {
  const box = document.getElementById("settings");
  box.innerHTML = "";
  const cli = settingsState.cli_overrides || {};
  for (const [key, label] of Object.entries(SETTING_LABELS)) {
    const row = document.createElement("div");
    row.className = "toggle" + (cli[key] || cli[key === "screensaver" ? "screensaver" : key] ? " locked" : "");
    const overrideKey = key === "screensaver_timeout_seconds" ? "screensaver_timeout"
      : (key === "safe_zone_offset_x" || key === "safe_zone_offset_y") ? "safe_zone_offset"
      : key;
    const locked = cli[overrideKey];
    if (key === "screensaver_timeout_seconds" || key === "analog_artifact_rate"
        || (key.startsWith("safe_zone_") && !key.includes("offset"))) {
      row.innerHTML = `<label>${label}${locked ? " (CLI)" : ""}</label>
        <input type="number" min="0" id="set-${key}" value="${settingsState[key] ?? (key === "analog_artifact_rate" ? 12 : 0)}" ${locked ? "disabled" : ""}>`;
    } else if (key === "safe_zone_offset_x" || key === "safe_zone_offset_y") {
      row.innerHTML = `<label>${label}${locked ? " (CLI)" : ""}</label>
        <input type="number" min="-320" max="320" id="set-${key}" value="${settingsState[key] ?? 0}" ${locked ? "disabled" : ""}>`;
    } else {
      row.innerHTML = `<label><input type="checkbox" id="set-${key}" ${settingsState[key] ? "checked" : ""} ${locked ? "disabled" : ""}>
        ${label}${locked ? " (CLI)" : ""}</label>`;
    }
    box.appendChild(row);
  }
}

function renderMediaPaths() {
  const box = document.getElementById("media-paths");
  box.innerHTML = "";
  mediaPaths.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "path-row";
    row.innerHTML = `<input type="text" data-idx="${i}" value="${esc(p)}">
      <button class="secondary" onclick="verifyPath(${i})">Verify</button>
      <button class="secondary" onclick="removeMediaPath(${i})">Remove</button>`;
    box.appendChild(row);
  });
}

function renderMounts() {
  const box = document.getElementById("mounts");
  box.innerHTML = "";
  mounts.forEach((m, i) => {
    const block = document.createElement("div");
    block.className = "mount-block";
    const src = m.source || m.mountpoint || "(mount)";
    block.innerHTML = `<strong>${esc(String(src))}</strong>
      <div class="muted">${esc(m.type || "?")} → ${esc(m.mountpoint || "")}</div>
      <button class="secondary" onclick="verifyMount(${i})">Verify / mount</button>
      <button class="secondary" onclick="editMount(${i})">Edit JSON</button>
      <button class="secondary" onclick="removeMount(${i})">Remove</button>
      <pre id="mount-result-${i}" class="muted"></pre>`;
    box.appendChild(block);
  });
}

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;");
}

function readMediaPathsFromDom() {
  return [...document.querySelectorAll("#media-paths input")].map(i => i.value.trim()).filter(Boolean);
}

function renderLibrary(data) {
  document.getElementById("lib-summary").textContent =
    `${data.shows || 0} show(s), ${data.episodes || 0} episode(s)`;
  const tree = document.getElementById("lib-tree");
  if (!data.tree || !data.tree.length) {
    tree.textContent = "(empty)";
    return;
  }
  tree.innerHTML = data.tree.map(show => {
    const seasons = (show.seasons || []).map(s => {
      const label = s.label ? esc(s.label) : `Season ${s.number}`;
      const eps = (s.episodes || []).map(e =>
        `<div class="ep">E-${String(e.number).padStart(2,"0")} ${esc(e.name || e.file || "")}</div>`
      ).join("");
      return `<details><summary>${label} (${(s.episodes||[]).length} ep)</summary>${eps}</details>`;
    }).join("");
    return `<details open><summary><strong>${esc(show.name)}</strong></summary>${seasons}</details>`;
  }).join("");
}

function renderChannels() {
  const ul = document.getElementById("channels");
  ul.innerHTML = "";
  const ordered = channelState.order.length ? channelState.order.slice() : channelState.shows.slice();
  const seen = new Set(ordered);
  channelState.shows.forEach(s => { if (!seen.has(s)) ordered.push(s); });
  ordered.forEach((name, i) => {
    const li = document.createElement("li");
    const num = channelState.numbers[name] || (i + 1);
    li.innerHTML = `<span style="flex:1">${esc(name)}</span>
      <label>Ch <input type="number" min="1" value="${num}" data-show="${esc(name)}" style="width:4rem"></label>
      <button onclick="moveUp('${name.replace(/'/g, "\\\\'")}')">Up</button>
      <button onclick="moveDown('${name.replace(/'/g, "\\\\'")}')">Down</button>`;
    ul.appendChild(li);
  });
  channelState.order = ordered;
}

function moveUp(name) {
  const o = channelState.order;
  const i = o.indexOf(name);
  if (i > 0) { o.splice(i, 1); o.splice(i - 1, 0, name); renderChannels(); }
}
function moveDown(name) {
  const o = channelState.order;
  const i = o.indexOf(name);
  if (i >= 0 && i < o.length - 1) { o.splice(i, 1); o.splice(i + 1, 0, name); renderChannels(); }
}

async function loadStatus() {
  document.getElementById("status").textContent = JSON.stringify(await api("/api/status"), null, 2);
}
async function loadSettings() {
  settingsState = await api("/api/settings");
  renderSettings();
}
async function saveSettings() {
  const patch = {};
  for (const key of Object.keys(SETTING_LABELS)) {
    const el = document.getElementById("set-" + key);
    if (!el || el.disabled) continue;
    patch[key] = key === "screensaver_timeout_seconds" || key === "analog_artifact_rate"
      || key.startsWith("safe_zone_")
      ? (key === "safe_zone_offset_x" || key === "safe_zone_offset_y"
        ? parseInt(el.value, 10) : parseFloat(el.value))
      : el.checked;
  }
  const r = await api("/api/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(patch)});
  document.getElementById("settings-msg").className = "msg ok";
  document.getElementById("settings-msg").textContent = r.message || "Saved.";
  await loadSettings();
}
async function loadPaths() {
  const data = await api("/api/paths");
  mediaPaths = data.media_paths || [];
  mounts = data.mounts || [];
  renderMediaPaths();
  renderMounts();
}
function addMediaPath() { mediaPaths.push(""); renderMediaPaths(); }
function removeMediaPath(i) { mediaPaths.splice(i, 1); renderMediaPaths(); }
function addMount() {
  mounts.push({type:"cifs", source:"//nas/shows", mountpoint:"/mnt/tv/shows"});
  renderMounts();
}
function removeMount(i) { mounts.splice(i, 1); renderMounts(); }
function editMount(i) {
  const raw = prompt("Mount entry JSON:", JSON.stringify(mounts[i], null, 2));
  if (!raw) return;
  try { mounts[i] = JSON.parse(raw); renderMounts(); }
  catch (e) { alert("Invalid JSON: " + e); }
}
async function savePaths() {
  mediaPaths = readMediaPathsFromDom();
  const r = await api("/api/paths", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({media_paths: mediaPaths, mounts})});
  document.getElementById("paths-msg").className = "msg ok";
  document.getElementById("paths-msg").textContent = r.message || "Saved.";
  await loadPaths(); await loadLibrary();
}
async function verifyPath(i) {
  mediaPaths = readMediaPathsFromDom();
  const path = mediaPaths[i];
  const r = await api("/api/paths/verify", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({path})});
  document.getElementById("paths-msg").className = "msg " + (r.ok ? "ok" : "err");
  document.getElementById("paths-msg").textContent = r.message || r.error || JSON.stringify(r);
}
async function verifyAllPaths() {
  mediaPaths = readMediaPathsFromDom();
  for (let i = 0; i < mediaPaths.length; i++) await verifyPath(i);
}
async function verifyMount(i) {
  const r = await api("/api/mounts/verify", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({index: i})});
  const el = document.getElementById("mount-result-" + i);
  if (el) el.textContent = r.message || r.error || JSON.stringify(r);
}
async function scanLibrary(apply) {
  mediaPaths = readMediaPathsFromDom();
  const r = await api("/api/library/scan", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({paths: mediaPaths, apply})});
  document.getElementById("scan-msg").className = "msg " + (r.ok ? "ok" : "err");
  document.getElementById("scan-msg").textContent = r.message || "Done.";
  if (r.tree) renderLibrary(r);
  if (apply) setTimeout(refreshAll, 500);
}
async function loadLibrary() {
  renderLibrary(await api("/api/library"));
}
async function loadConfig() {
  const data = await api("/api/config");
  document.getElementById("config-path").textContent = data.path || "";
  document.getElementById("config-editor").value = JSON.stringify(data.config, null, 2);
}
async function saveConfig() {
  let raw;
  try { raw = JSON.parse(document.getElementById("config-editor").value); }
  catch (e) { document.getElementById("config-msg").className = "msg err"; document.getElementById("config-msg").textContent = "Invalid JSON: " + e; return; }
  const r = await api("/api/config", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(raw)});
  document.getElementById("config-msg").className = "msg " + (r.ok ? "ok" : "err");
  document.getElementById("config-msg").textContent = r.message || "Saved.";
  if (r.ok) await refreshAll();
}
async function reloadConfig() {
  const r = await api("/api/config/reload", {method:"POST"});
  document.getElementById("config-msg").className = "msg " + (r.ok ? "ok" : "err");
  document.getElementById("config-msg").textContent = r.message || "Reloaded.";
  if (r.ok) await refreshAll();
}
async function loadChannels() {
  channelState = await api("/api/channels");
  renderChannels();
}
async function saveChannels() {
  const numbers = {};
  document.querySelectorAll("#channels input[type=number]").forEach(inp => {
    numbers[inp.dataset.show] = parseInt(inp.value, 10) || 1;
  });
  await api("/api/channels", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({order: channelState.order, numbers})});
  document.getElementById("ch-msg").className = "msg ok";
  document.getElementById("ch-msg").textContent = "Saved.";
}
async function rescan() {
  const r = await api("/api/rescan", {method: "POST"});
  document.getElementById("scan-msg").className = "msg ok";
  document.getElementById("scan-msg").textContent = r.message || "Queued.";
  setTimeout(refreshAll, 2000);
}
async function loadWatch() {
  document.getElementById("watch").textContent = JSON.stringify(await api("/api/watch"), null, 2);
}
async function loadKeymap() {
  const data = await api("/api/keymap");
  const lines = (data.bindings || []).map(row => `${row.label}: ${row.key}`);
  document.getElementById("keymap").textContent = lines.join("\\n") || "(none)";
}
async function loadLogs() {
  document.getElementById("log").textContent = (await api("/api/logs")).lines.join("\\n");
}
async function refreshAll() {
  await loadStatus(); await loadSettings(); await loadPaths(); await loadLibrary();
  await loadConfig(); await loadChannels(); await loadWatch(); await loadKeymap(); await loadLogs();
}
refreshAll();
setInterval(loadLogs, 15000);
</script>
</body>
</html>
"""


class _AdminHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, addr, handler, ctx: AdminContext):
        self.ctx = ctx
        super().__init__(addr, handler)


class _DualStackAdminHTTPServer(_AdminHTTPServer):
    """Listen on IPv6 :: with IPv4-mapped addresses (fixes macOS localhost → ::1)."""

    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def create_admin_httpd(bind: str, port: int, ctx: AdminContext) -> _AdminHTTPServer:
    """Create a listening HTTP server, preferring dual-stack when binding all interfaces."""
    if bind in ("0.0.0.0", "", "::"):
        try:
            return _DualStackAdminHTTPServer(("::", port), AdminHandler, ctx)
        except OSError as exc:
            LOG.warning("dual-stack bind failed (%s); falling back to IPv4", exc)
            bind = "0.0.0.0"
    return _AdminHTTPServer((bind, port), AdminHandler, ctx)


def verify_admin_reachable(port: int, timeout: float = 1.5) -> tuple[bool, str | None]:
    """Return (ok, working_host) after the server thread has started."""
    for host in ("127.0.0.1", "::1", "localhost"):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True, host
        except OSError:
            continue
    return False, None


def resolve_admin_bind(admin_cfg: dict[str, Any], *, local_only: bool = False) -> str:
    """Pick listen address; windowed dev runs default to loopback-only."""
    bind = str(admin_cfg.get("bind", "0.0.0.0")).strip() or "0.0.0.0"
    if local_only and bind in ("0.0.0.0", "", "::"):
        return "127.0.0.1"
    return bind


def _lan_ip() -> str | None:
    """Best-effort primary LAN address for admin URL hints."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def announce_admin_urls(bind: str, port: int, *, reachable: bool) -> None:
    """Print admin URLs to stderr (always visible, even when stdout is buffered)."""
    import sys

    if reachable:
        print(f"Admin UI: http://127.0.0.1:{port}/", file=sys.stderr, flush=True)
        if bind not in ("127.0.0.1", "::1"):
            lan = _lan_ip()
            if lan:
                print(f"         http://{lan}:{port}/  (LAN)", file=sys.stderr, flush=True)
    else:
        print(
            f"WARNING: Admin UI not reachable on port {port} — "
            f"try http://127.0.0.1:{port}/",
            file=sys.stderr,
            flush=True,
        )


class DeferredAdminBridge:
    """AdminContext that forwards to the app once the UI has finished starting."""

    def __init__(self) -> None:
        self._app: AdminContext | None = None

    def attach(self, app: AdminContext) -> None:
        self._app = app

    def admin_status(self) -> dict[str, Any]:
        if self._app is None:
            return {
                "shows": 0,
                "view": "starting",
                "playing": False,
                "current_show": None,
            }
        return self._app.admin_status()

    def admin_shows(self) -> list[str]:
        if self._app is None:
            return []
        return self._app.admin_shows()

    def admin_channels(self) -> dict[str, Any]:
        if self._app is None:
            return {"order": [], "numbers": {}, "shows": []}
        return self._app.admin_channels()

    def admin_save_channels(self, order: list[str], numbers: dict[str, int]) -> None:
        if self._app is not None:
            self._app.admin_save_channels(order, numbers)

    def admin_request_rescan(self) -> tuple[bool, str]:
        if self._app is None:
            return False, "app still starting"
        return self._app.admin_request_rescan()

    def admin_watch_summary(self) -> dict[str, Any]:
        if self._app is None:
            return {}
        return self._app.admin_watch_summary()

    def admin_keymap(self) -> dict[str, Any]:
        if self._app is None:
            return {"bindings": []}
        return self._app.admin_keymap()

    def admin_library(self) -> dict[str, Any]:
        if self._app is None:
            return {"shows": 0, "episodes": 0, "tree": [], "media_paths": []}
        return self._app.admin_library()

    def admin_config_get(self) -> dict[str, Any]:
        if self._app is None:
            return {"path": "", "config": {}}
        return self._app.admin_config_get()

    def admin_config_save(self, raw: dict) -> tuple[bool, str]:
        if self._app is None:
            return False, "app still starting"
        return self._app.admin_config_save(raw)

    def admin_config_reload(self) -> tuple[bool, str]:
        if self._app is None:
            return False, "app still starting"
        return self._app.admin_config_reload()

    def admin_settings(self) -> dict[str, Any]:
        if self._app is None:
            return {}
        return self._app.admin_settings()

    def admin_update_settings(self, patch: dict) -> tuple[bool, str]:
        if self._app is None:
            return False, "app still starting"
        return self._app.admin_update_settings(patch)

    def admin_verify_path(self, path: str) -> dict[str, Any]:
        if self._app is None:
            return {"ok": False, "error": "app still starting"}
        return self._app.admin_verify_path(path)

    def admin_verify_mount(self, index: int) -> dict[str, Any]:
        if self._app is None:
            return {"ok": False, "error": "app still starting"}
        return self._app.admin_verify_mount(index)

    def admin_scan_library(
        self, paths: list[str] | None = None, *, apply: bool = False
    ) -> dict[str, Any]:
        if self._app is None:
            return {"ok": False, "message": "app still starting"}
        return self._app.admin_scan_library(paths, apply=apply)

    def admin_update_paths(self, patch: dict) -> tuple[bool, str]:
        if self._app is None:
            return False, "app still starting"
        return self._app.admin_update_paths(patch)


def start_admin_if_enabled(
    ctx: AdminContext,
    admin_cfg: dict[str, Any],
    *,
    port_override: int | None = None,
    local_only: bool = False,
) -> AdminServer | None:
    """Start the admin HTTP server when enabled in config or via CLI."""
    cfg = dict(admin_cfg or {})
    if not cfg.get("enabled"):
        return None
    port = int(port_override if port_override is not None else cfg.get("port", 8765))
    bind = resolve_admin_bind(cfg, local_only=local_only)
    try:
        server = AdminServer(ctx, bind, port)
        server.start()
    except OSError as exc:
        LOG.error("admin UI failed to bind %s:%s — %s", bind, port, exc)
        import sys

        print(
            f"WARNING: Admin UI could not start on port {port} ({exc})",
            file=sys.stderr,
            flush=True,
        )
        return None
    ok, _host = verify_admin_reachable(port)
    announce_admin_urls(bind, port, reachable=ok)
    return server


class AdminHandler(BaseHTTPRequestHandler):
    server: _AdminHTTPServer  # type: ignore[assignment]

    def log_message(self, fmt: str, *args) -> None:
        LOG.debug("admin %s", fmt % args)

    def _send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_html(ADMIN_HTML)
            return
        ctx = self.server.ctx
        if path == "/api/status":
            self._send_json(200, ctx.admin_status())
        elif path == "/api/channels":
            self._send_json(200, ctx.admin_channels())
        elif path == "/api/watch":
            self._send_json(200, ctx.admin_watch_summary())
        elif path == "/api/keymap":
            self._send_json(200, ctx.admin_keymap())
        elif path == "/api/logs":
            self._send_json(200, {"lines": log_tail(150)})
        elif path == "/api/library":
            self._send_json(200, ctx.admin_library())
        elif path == "/api/config":
            self._send_json(200, ctx.admin_config_get())
        elif path == "/api/settings":
            self._send_json(200, ctx.admin_settings())
        elif path == "/api/paths":
            cfg = ctx.admin_config_get().get("config") or {}
            self._send_json(
                200,
                {
                    "media_paths": list(cfg.get("media_paths") or []),
                    "mounts": list(cfg.get("mounts") or []),
                },
            )
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        ctx = self.server.ctx
        if path == "/api/channels":
            data = self._read_json()
            order = data.get("order") or []
            numbers = data.get("numbers") or {}
            if not isinstance(order, list):
                order = []
            if not isinstance(numbers, dict):
                numbers = {}
            clean_numbers = {}
            for k, v in numbers.items():
                try:
                    clean_numbers[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
            ctx.admin_save_channels([str(x) for x in order], clean_numbers)
            self._send_json(200, {"ok": True})
        elif path == "/api/rescan":
            ok, message = ctx.admin_request_rescan()
            code = 200 if ok else 409
            self._send_json(code, {"ok": ok, "message": message})
        elif path == "/api/config":
            data = self._read_json()
            ok, message = ctx.admin_config_save(data)
            code = 200 if ok else 400
            self._send_json(code, {"ok": ok, "message": message})
        elif path == "/api/config/reload":
            ok, message = ctx.admin_config_reload()
            code = 200 if ok else 500
            self._send_json(code, {"ok": ok, "message": message})
        elif path == "/api/settings":
            data = self._read_json()
            ok, message = ctx.admin_update_settings(data)
            code = 200 if ok else 400
            self._send_json(code, {"ok": ok, "message": message})
        elif path == "/api/paths":
            data = self._read_json()
            ok, message = ctx.admin_update_paths(data)
            code = 200 if ok else 400
            self._send_json(code, {"ok": ok, "message": message})
        elif path == "/api/paths/verify":
            data = self._read_json()
            path_str = str(data.get("path") or "")
            self._send_json(200, ctx.admin_verify_path(path_str))
        elif path == "/api/mounts/verify":
            data = self._read_json()
            try:
                index = int(data.get("index", -1))
            except (TypeError, ValueError):
                index = -1
            self._send_json(200, ctx.admin_verify_mount(index))
        elif path == "/api/library/scan":
            data = self._read_json()
            paths = data.get("paths")
            if paths is not None and not isinstance(paths, list):
                paths = None
            apply = bool(data.get("apply"))
            result = ctx.admin_scan_library(paths, apply=apply)
            self._send_json(200, result)
        else:
            self._send_json(404, {"error": "not found"})


class AdminServer:
    """Background thread serving the admin UI."""

    def __init__(self, ctx: AdminContext, bind: str, port: int):
        self._ctx = ctx
        self._bind = bind
        self._port = port
        self._httpd: _AdminHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._httpd = create_admin_httpd(self._bind, self._port, self._ctx)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="tv-admin", daemon=True
        )
        self._thread.start()
        time.sleep(0.05)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self._thread = None
