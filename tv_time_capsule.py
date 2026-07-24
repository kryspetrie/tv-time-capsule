#!/usr/bin/env python3
"""
TV Time Capsule — A child-friendly CRT media player for Raspberry Pi.
Works on the original Pi Model B (2011) through Pi 5.

Cable-TV style interface: channel numbers, single-show focus, stack navigation.
Uses pygame for the menu and embedded FFmpeg video rendering.
Audio plays via ffplay; video is paced to the wall clock to stay in sync.

Usage:
    python3 tv_time_capsule.py [--media-dir DIR] [--force-43] [--test]

Media folder structures supported:
    1) Show folder + unstructured files (skip straight to episodes):
       /Show Name/01.mp4, /Show Name/02.mp4, ...

    2) Show folder + structured filenames (seasons inferred):
       /Show Name/s01e01 - Pilot.mp4, /Show Name/s02e01 - Return.mp4, ...

    3) Show folder + season folders + unstructured files:
       /Show Name/s01/01.mp4, /Show Name/s02/01.mp4, ...

    4) Show folder + season folders + structured filenames:
       /Show Name/s01/s01e01 - Hello.mp4, /Show Name/s01/s01e01.png, ...

Thumbnails:
    Shows:   /Show Name/thumbnail.png  or  /Show Name/show.png
    Seasons: /Show Name/s01.png  (alongside the season folder)
    Episodes: /Show Name/s01/s01e01.png  (same name as video, .png extension)
"""

import pygame
import os
import json
import subprocess
import sys
import re
import shutil
import time
import threading
import warnings
from pathlib import Path
from datetime import datetime
from select import select as _select

# ─── Font Compatibility Layer ─────────────────────────────────────────────────
# pygame.font broken on Python 3.14+ (circular import). Use _freetype fallback.

_USE_FREETYPE = False

# Font file — VCR OSD Mono for that vintage CRT look
FONT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vcr_osd_mono.ttf")


def _make_font(size):
    """Return a font object with a unified .render() -> Surface API.
    Uses VCR OSD Mono if available, falls back to pygame default."""
    font_path = FONT_FILE if os.path.isfile(FONT_FILE) else None
    if _USE_FREETYPE:
        return _FTFontWrapper(font_path, size, pygame._freetype)
    else:
        return pygame.font.Font(font_path, size)


class _FTFontWrapper:
    """Wraps pygame._freetype.Font to match pygame.font.Font's render() API."""

    def __init__(self, name, size, freetype_mod):
        self._font = freetype_mod.Font(name, size)
        self._size = size

    def render(self, text, antialias, color):
        surf, _rect = self._font.render(text, color)
        return surf

    def size(self, text):
        r = self._font.get_rect(text)
        # get_sized_height() gives the full line height (ascent+descent),
        # not just the tight glyph bounding box that get_rect returns.
        line_h = self._font.get_sized_height()
        return (r.width, max(r.height, line_h))

    def get_linesize(self):
        return self._font.get_sized_height()


# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_MEDIA_ROOT = "/media/usb"
STATE_DIR = os.path.expanduser("~/.local/share/tv-time-capsule")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
CONFIG_DIR = os.path.expanduser("~/.config/tv-time-capsule")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

SCREEN_W = 720
SCREEN_H = 480

VIDEO_EXTENSIONS = {
    '.mp4', '.mkv', '.avi', '.mov', '.m4v',
    '.webm', '.wmv', '.flv', '.f4v', '.mpg', '.mpeg', '.vob'
}

# Channel number: type digits, after timeout -> jump to channel
CHANNEL_TIMEOUT_MS = 1500
CHANNEL_FLASH_MS = 800
CHANNEL_ERROR_MS = 1500
CHANNEL_PENDING_MS = 500

# How many items visible in the season/episode stack
STACK_VISIBLE = 4

# Overlay display durations
OVERLAY_SHOW_MS = 3000
PROGRESS_SEEK_S = 10

# ─── Colors — Vintage TV palette (white/blue primary, green overlays) ────────

class C:
    # Background
    BG            = (8, 14, 28)
    BG_CARD       = (18, 28, 52)
    BG_CARD_SEL   = (30, 60, 120)
    BG_FOOTER     = (6, 10, 22)
    BG_HEADER     = (12, 20, 38)

    # Text
    WHITE         = (230, 235, 245)
    BRIGHT        = (255, 255, 255)
    BLUE          = (80, 150, 240)
    CYAN          = (60, 200, 220)
    DIM           = (90, 110, 140)
    DARK_DIM      = (45, 55, 75)

    # Overlays (green — like CRT on-screen displays)
    GREEN         = (50, 220, 100)
    GREEN_DIM     = (25, 80, 45)
    GREEN_BG      = (0, 15, 8, 200)
    OVERLAY_BG    = (0, 0, 0, 180)

    # Misc
    BLACK         = (0, 0, 0)
    SCANLINE      = (0, 0, 0, 28)
    NOW_PLAYING   = (255, 210, 80)
    WATCHED       = (60, 80, 100)
    NEXT_UP       = (40, 100, 60)


# ─── Numpy (optional, for embedded video) ────────────────────────────────────
try:
    import numpy as _numpy_mod
    _np_frombuffer = _numpy_mod.frombuffer
    _np_uint8 = _numpy_mod.uint8
except ImportError:
    _np_frombuffer = None
    _np_uint8 = None

# ─── Video Player (Embedded FFmpeg) ──────────────────────────────────────────

def detect_ffmpeg():
    """Check for ffmpeg + ffprobe (required for embedded playback)."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg
    return None


def detect_ffplay():
    """Check for ffplay (for audio during embedded playback)."""
    return shutil.which("ffplay")


def detect_omxplayer():
    """Check for omxplayer (Pi fallback)."""
    for cmd in ["omxplayer.bin", "omxplayer"]:
        path = shutil.which(cmd)
        if path:
            return path
    return None


def is_pi():
    return os.path.exists("/proc/device-tree/model")


def get_video_info(filepath):
    """Get video duration and FPS using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", filepath],
            capture_output=True, text=True, timeout=5
        )
        info = json.loads(result.stdout)
        fps = 24.0
        duration = 0.0
        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                fps_str = s.get("r_frame_rate", "24/1")
                if "/" in fps_str:
                    num, den = fps_str.split("/")
                    fps = float(num) / float(den) if float(den) > 0 else 24.0
                else:
                    fps = float(fps_str)
                break
        fmt = info.get("format", {})
        dur_str = fmt.get("duration", "0")
        try:
            duration = float(dur_str)
        except (ValueError, TypeError):
            duration = 0.0
        return fps, duration
    except Exception:
        return 24.0, 0.0


class EmbeddedPlayer:
    """Embedded video player using FFmpeg for frame decoding and pygame for rendering.
    
    Video frames are piped from ffmpeg via subprocess as raw RGB24 data,
    converted to pygame Surfaces via numpy, and blitted directly to the canvas.
    Audio is played via a separate ffplay process for perfect sync.
    
    Key design:
    - The frame-reading thread throttles to video FPS so it doesn't
      exhaust the stream faster than real-time.
    - "Finished" is detected when ffplay (audio) exits, signaling the
      video's natural end — not when FFmpeg's stream ends.
    - Pause suspends frame reading (via threading Event) and kills audio;
      unpause resumes reading from where we left off and restarts audio.
    """

    def __init__(self, canvas_w, canvas_h):
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h
        self.ffmpeg_path = detect_ffmpeg()
        self.ffplay_path = detect_ffplay()
        self.use_omx = False  # Set externally if needed

        # Playback state
        self.proc = None           # FFmpeg video process
        self.audio_proc = None     # ffplay audio process
        self.thread = None         # Frame-reading thread
        self.running = False       # Is playback active?
        self.finished = False      # Did the video reach the end naturally?
        self.paused = False
        self.volume = 100
        self.time_pos = 0.0
        self.duration = 0.0
        self.fps = 24.0
        self.frame_time = 1.0 / 24.0
        self.start_time = 0.0     # monotonic time when playback started
        self.pause_offset = 0.0   # accumulated pause time in seconds
        self.pause_start = 0.0    # when current pause began (monotonic)
        self.current_frame = None  # pygame.Surface of latest frame
        self.frame_lock = threading.Lock()
        self.filepath = None
        self._pause_event = threading.Event()  # Frame thread blocks on this when paused
        self._pause_event.set()  # Start un-blocked

        # Omxplayer fallback state
        self.omx_proc = None
        self.omx_cmd = None

    def start(self, filepath, resume_pos=None):
        """Start playing a video file. Returns True if successful."""
        self.stop()
        self.filepath = filepath
        self.finished = False
        self.paused = False
        self.time_pos = 0.0
        self.pause_offset = 0.0
        self._pause_event.set()  # Un-block frame thread

        # Get video info for duration and fps
        self.fps, self.duration = get_video_info(filepath)
        self.frame_time = 1.0 / max(self.fps, 1.0)

        # Omxplayer fallback for Pi without X11
        if self.use_omx:
            return self._start_omx(filepath, resume_pos)

        # Embedded FFmpeg playback
        W, H = self.canvas_w, self.canvas_h
        frame_size = W * H * 3

        # Build FFmpeg command for raw RGB24 output
        cmd = [
            self.ffmpeg_path, "-i", filepath,
        ]
        if resume_pos and resume_pos > 0:
            cmd.extend(["-ss", str(resume_pos)])
        cmd.extend([
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                   f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-an",  # No audio from FFmpeg — we play audio separately
            "-loglevel", "quiet", "-"
        ])

        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=frame_size
            )
        except Exception as e:
            print(f"Failed to start ffmpeg: {e}")
            self.proc = None
            return False

        # Start audio via ffplay (silent, no window)
        if self.ffplay_path:
            audio_cmd = [
                self.ffplay_path, "-nodisp", "-autoexit",
                "-loglevel", "quiet", "-volume", str(int(self.volume)),
            ]
            if resume_pos and resume_pos > 0:
                audio_cmd.extend(["-ss", str(resume_pos)])
            audio_cmd.append(filepath)
            try:
                self.audio_proc = subprocess.Popen(
                    audio_cmd,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                self.audio_proc = None

        self.running = True
        self.start_time = time.monotonic()

        # Start frame-reading thread
        self.thread = threading.Thread(target=self._read_frames, daemon=True)
        self.thread.start()

        return True

    def _start_omx(self, filepath, resume_pos=None):
        """Start playback via omxplayer (Pi fallback)."""
        cmd = [self.omx_cmd, "-o", "both", "--no-osd", "--blank"]
        if resume_pos:
            cmd.extend(["--pos", str(int(resume_pos))])
        cmd.append(filepath)
        try:
            self.omx_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self.running = True
            return True
        except Exception:
            self.omx_proc = None
            return False

    def _read_frames(self):
        """Thread: read raw RGB frames from FFmpeg at real-time pace.
        
        Throttles to the video's FPS using time.sleep so we don't
        exhaust the stream faster than display rate. Pauses when
        the _pause_event is cleared. Detects video end when the
        ffmpeg stream closes OR ffplay exits.
        """
        W, H = self.canvas_w, self.canvas_h
        frame_size = W * H * 3
        frame_time = self.frame_time

        # Pace frames against the wall clock so video tracks the audio
        # instead of drifting slower than real time.
        seg_start = time.monotonic()
        paused_accum = 0.0
        frame_index = 0

        while self.running:
            # Block here if paused (and remember how long we were paused)
            if not self._pause_event.is_set():
                p0 = time.monotonic()
                self._pause_event.wait(timeout=0.1)
                paused_accum += time.monotonic() - p0
                if not self.running:
                    break
                continue
            if not self.running:
                break

            try:
                raw = self.proc.stdout.read(frame_size)
                if len(raw) != frame_size:
                    # FFmpeg stream ended — video reached the end
                    break

                arr = _np_frombuffer(raw, dtype=_np_uint8).reshape((H, W, 3))
                surf = pygame.surfarray.make_surface(arr.swapaxes(0, 1))

                with self.frame_lock:
                    self.current_frame = surf

                # Sleep only until this frame's scheduled time — no fixed
                # per-frame delay, so decode time doesn't accumulate as drift.
                frame_index += 1
                target = seg_start + paused_accum + frame_index * frame_time
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)

            except Exception:
                break

        # FFmpeg stream ended — the video is done. Wait for audio to
        # finish too (ffplay exits with -autoexit when it's done).
        # Mark finished once audio process ends.
        if self.running and not self.use_omx:
            self._wait_audio_and_finish()

    def _wait_audio_and_finish(self):
        """Wait for the audio process (ffplay) to finish, then mark done."""
        if self.audio_proc:
            try:
                self.audio_proc.wait(timeout=max(self.duration, 30) if self.duration > 0 else 30)
            except subprocess.TimeoutExpired:
                pass
        self.finished = True
        self.running = False

    def get_frame(self):
        """Get the latest decoded frame as a pygame Surface, or None."""
        with self.frame_lock:
            return self.current_frame

    def is_playing(self):
        """Is the video still playing?"""
        if self.use_omx:
            return self.omx_proc is not None and self.omx_proc.poll() is None
        return self.running and not self.finished

    def is_finished(self):
        """Did the video reach the end naturally?"""
        if self.use_omx:
            # omxplayer exits when the video ends
            return self.omx_proc is not None and self.omx_proc.poll() is not None
        return self.finished

    def stop(self):
        """Stop playback and clean up all processes."""
        self.running = False
        self.finished = False
        self._pause_event.set()  # Unblock frame thread so it can exit

        # Kill FFmpeg
        if self.proc:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None

        # Kill audio
        if self.audio_proc:
            try:
                self.audio_proc.kill()
                self.audio_proc.wait(timeout=2)
            except Exception:
                pass
            self.audio_proc = None

        # Kill omxplayer
        if self.omx_proc:
            try:
                self.omx_proc.stdin.write(b"q")
                self.omx_proc.stdin.flush()
            except Exception:
                pass
            try:
                self.omx_proc.terminate()
                self.omx_proc.wait(timeout=2)
            except Exception:
                self.omx_proc.kill()
            self.omx_proc = None

        # Wait for frame thread
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None

        with self.frame_lock:
            self.current_frame = None

    def pause(self):
        """Toggle pause state. Blocks frame-reading thread via Event."""
        if self.use_omx:
            if self.omx_proc and self.omx_proc.poll() is None:
                try:
                    self.omx_proc.stdin.write(b"p")
                    self.omx_proc.stdin.flush()
                except Exception:
                    pass
            self.paused = not self.paused
            return

        self.paused = not self.paused
        if self.paused:
            self.pause_start = time.monotonic()
            # Block the frame-reading thread
            self._pause_event.clear()
            # Kill audio (ffplay can't pause via stdin)
            if self.audio_proc and self.audio_proc.poll() is None:
                try:
                    self.audio_proc.kill()
                    self.audio_proc.wait(timeout=1)
                except Exception:
                    pass
                self.audio_proc = None
        else:
            if self.pause_start > 0:
                self.pause_offset += time.monotonic() - self.pause_start
                self.pause_start = 0
            # Unblock the frame-reading thread
            self._pause_event.set()
            # Restart audio from current position
            self._resume_audio()

    def _resume_audio(self):
        """Restart ffplay from the current time position after unpause."""
        if not self.ffplay_path or not self.filepath:
            return
        elapsed = time.monotonic() - self.start_time - self.pause_offset
        resume = max(0, elapsed)
        audio_cmd = [
            self.ffplay_path, "-nodisp", "-autoexit",
            "-loglevel", "quiet", "-volume", str(int(self.volume)),
            "-ss", str(resume),
            self.filepath
        ]
        try:
            self.audio_proc = subprocess.Popen(
                audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            self.audio_proc = None

    def adjust_volume(self, delta):
        """Adjust volume by delta (e.g. +10 or -10). Range: 0-100.
        Restarts the audio stream so the change takes effect immediately."""
        self.volume = max(0, min(100, self.volume + delta))
        self._apply_volume_live()

    def _apply_volume_live(self):
        """Relaunch ffplay at the current position so a new volume applies now."""
        if self.use_omx or self.paused or not self.running:
            return
        if not self.ffplay_path or not self.filepath:
            return
        if self.audio_proc and self.audio_proc.poll() is None:
            try:
                self.audio_proc.kill()
                self.audio_proc.wait(timeout=1)
            except Exception:
                pass
        self.audio_proc = None
        self._resume_audio()

    def seek(self, seconds):
        """Seek forward/backward by seconds. Restarts FFmpeg from new position."""
        if self.use_omx:
            if self.omx_proc and self.omx_proc.poll() is None:
                try:
                    if seconds > 0:
                        self.omx_proc.stdin.write(b"\x1b[C")
                    else:
                        self.omx_proc.stdin.write(b"\x1b[D")
                    self.omx_proc.stdin.flush()
                except Exception:
                    pass
            return

        if not self.filepath or not self.ffmpeg_path:
            return

        # Calculate new position (fold in any in-progress pause)
        now = time.monotonic()
        paused_extra = (now - self.pause_start) if (self.paused and self.pause_start > 0) else 0.0
        elapsed = now - self.start_time - self.pause_offset - paused_extra
        new_pos = max(0, elapsed + seconds)
        if self.duration > 0:
            new_pos = min(new_pos, self.duration)

        # Save state
        filepath = self.filepath

        # Kill current processes
        self.running = False
        self._pause_event.set()  # Unblock thread
        if self.proc:
            try:
                self.proc.kill()
                self.proc.wait(timeout=1)
            except Exception:
                pass
            self.proc = None
        if self.audio_proc:
            try:
                self.audio_proc.kill()
                self.audio_proc.wait(timeout=1)
            except Exception:
                pass
            self.audio_proc = None

        # Wait for frame thread
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None

        with self.frame_lock:
            self.current_frame = None

        # Restart from new position
        W, H = self.canvas_w, self.canvas_h
        frame_size = W * H * 3
        cmd = [
            self.ffmpeg_path, "-ss", str(new_pos),
            "-i", filepath,
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                   f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-an", "-loglevel", "quiet", "-"
        ]
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=frame_size
            )
        except Exception:
            self.proc = None
            self.finished = True
            return

        # Restart audio from seek position
        if self.ffplay_path:
            audio_cmd = [
                self.ffplay_path, "-nodisp", "-autoexit",
                "-loglevel", "quiet", "-volume", str(int(self.volume)),
                "-ss", str(new_pos), filepath
            ]
            try:
                self.audio_proc = subprocess.Popen(
                    audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                self.audio_proc = None

        self.running = True
        self.finished = False
        self.start_time = time.monotonic() - new_pos
        self.pause_offset = 0
        self.paused = False
        self._pause_event.set()

        self.thread = threading.Thread(target=self._read_frames, daemon=True)
        self.thread.start()

    def update_time(self):
        """Update time_pos based on wall clock (for progress bar)."""
        if self.paused:
            return
        elapsed = time.monotonic() - self.start_time - self.pause_offset
        self.time_pos = max(0, elapsed)

    def format_time(self, seconds):
        """Format seconds as MM:SS or H:MM:SS."""
        if seconds is None or seconds < 0:
            return "--:--"
        s = int(seconds)
        if s >= 3600:
            return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
        return f"{s // 60}:{s % 60:02d}"

    def progress(self):
        """Return progress as 0.0 to 1.0."""
        if self.duration and self.duration > 0:
            return max(0, min(1.0, self.time_pos / self.duration))
        return 0.0


# ─── Filename Parsing ─────────────────────────────────────────────────────────

def parse_season_episode(filename):
    name = Path(filename).stem
    m = re.search(r'[sS](\d+)[.\s]*[eE](\d+)', name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def parse_episode_number(filename):
    se = parse_season_episode(filename)
    if se[0] is not None and se[1] is not None:
        return se[1]
    name = Path(filename).stem
    m = re.search(r'^(\d+)', name)
    if m:
        return int(m.group(1))
    return None


def parse_episode_name(filename):
    name = Path(filename).stem
    name = re.sub(r'^[sS]\d+[.\s]*[eE]\d+\s*[-.]?\s*', '', name)
    name = re.sub(r'^\d+\s*[-.]?\s*', '', name)
    name = name.strip(' .-_')
    return name if name else None


def find_thumbnail(dir_path, names, video_stem=None):
    img_exts = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
    for name in names:
        for ext in img_exts:
            p = os.path.join(dir_path, name + ext)
            if os.path.isfile(p):
                return p
    return None


def find_video_thumbnail(video_path):
    stem = Path(video_path).stem
    dir_path = os.path.dirname(video_path)
    t = find_thumbnail(dir_path, [stem])
    if t:
        return t
    se = parse_season_episode(video_path)
    if se[0] is not None:
        t = find_thumbnail(dir_path, [f"s{se[0]:02d}e{se[1]:02d}"])
        if t:
            return t
    return None


# ─── Config file ──────────────────────────────────────────────────────────────

def load_config():
    """Load config from ~/.config/tv-time-capsule/config.json.
    Returns dict with 'media_paths' list. Falls back to defaults."""
    default = {"media_paths": [DEFAULT_MEDIA_ROOT]}
    if not os.path.isfile(CONFIG_FILE):
        return default
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        paths = cfg.get("media_paths", [])
        if not paths:
            paths = [DEFAULT_MEDIA_ROOT]
        # Filter to existing directories only
        valid = [p for p in paths if os.path.isdir(p)]
        return {"media_paths": valid if valid else [DEFAULT_MEDIA_ROOT]}
    except (json.JSONDecodeError, IOError):
        return default


def save_default_config():
    """Write a default config file if none exists."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"media_paths": [DEFAULT_MEDIA_ROOT]}, f, indent=2)


# ─── Discovery ─────────────────────────────────────────────────────────────────

def discover_shows(media_paths):
    """Scan one or more media root directories and merge results.
    If two paths contain shows with the same name, episodes are merged."""
    if isinstance(media_paths, str):
        media_paths = [media_paths]

    shows = {}
    for media_root in media_paths:
        if not os.path.isdir(media_root):
            continue

        for entry in sorted(os.listdir(media_root)):
            show_dir = os.path.join(media_root, entry)
            if not os.path.isdir(show_dir):
                continue

            video_files = []
            for root, dirs, files in os.walk(show_dir):
                for f in sorted(files):
                    if Path(f).suffix.lower() in VIDEO_EXTENSIONS:
                        video_files.append(os.path.join(root, f))

            if not video_files:
                continue

            subdir_videos = [v for v in video_files if os.path.dirname(v) != show_dir]
            has_season_folders = len(subdir_videos) == len(video_files)

            show_thumb = find_thumbnail(show_dir, ['thumbnail', 'show', entry])

            if has_season_folders:
                seasons = {}
                for root, dirs, files in os.walk(show_dir):
                    for d in sorted(dirs):
                        season_dir = os.path.join(root, d)
                        se = parse_season_episode(d)
                        if se[0] is not None:
                            season_num = se[0]
                        else:
                            m = re.search(r'(\d+)', d)
                            season_num = int(m.group(1)) if m else len(seasons) + 1

                        s_videos = [os.path.join(season_dir, f) for f in sorted(os.listdir(season_dir))
                                    if Path(f).suffix.lower() in VIDEO_EXTENSIONS]
                        if not s_videos:
                            continue

                        season_thumb = find_thumbnail(show_dir, [f"s{season_num:02d}", d])
                        episodes = _parse_episodes(s_videos, season_num, season_dir)
                        seasons[season_num] = {
                            'episodes': episodes,
                            'thumbnail': season_thumb,
                        }

                if not seasons:
                    seasons[1] = {
                        'episodes': _parse_episodes(video_files, 1, show_dir),
                        'thumbnail': find_thumbnail(show_dir, ['s01']),
                    }

                new_show = {
                    'has_seasons': True,
                    'seasons': seasons,
                    'thumbnail': show_thumb,
                }
            else:
                grouped = _group_by_season(video_files)
                seasons = {}
                for s_num in sorted(grouped.keys()):
                    s_videos = grouped[s_num]
                    s_dir = os.path.dirname(s_videos[0]) if s_num == 0 else show_dir
                    actual_num = s_num if s_num != 0 else 1
                    episodes = _parse_episodes(s_videos, actual_num, s_dir)
                    seasons[actual_num] = {
                        'episodes': episodes,
                        'thumbnail': find_thumbnail(show_dir, [f"s{actual_num:02d}"]),
                    }

                has_multiple_seasons = len(seasons) > 1
                new_show = {
                    'has_seasons': has_multiple_seasons,
                    'seasons': seasons,
                    'thumbnail': show_thumb,
                }

            # Merge with existing show of the same name
            if entry in shows:
                existing = shows[entry]
                # Merge seasons: new seasons take precedence for same number
                for snum, sdata in new_show['seasons'].items():
                    if snum in existing['seasons']:
                        # Merge episodes: deduplicate by path
                        existing_paths = {e['path'] for e in existing['seasons'][snum]['episodes']}
                        for ep in sdata['episodes']:
                            if ep['path'] not in existing_paths:
                                existing['seasons'][snum]['episodes'].append(ep)
                        existing['seasons'][snum]['episodes'].sort(key=lambda e: e['number'])
                    else:
                        existing['seasons'][snum] = sdata
                # Use first available thumbnail
                if not existing.get('thumbnail') and new_show.get('thumbnail'):
                    existing['thumbnail'] = new_show['thumbnail']
                # If either has seasons, treat as multi-season
                existing['has_seasons'] = existing['has_seasons'] or new_show['has_seasons']
            else:
                shows[entry] = new_show

    return shows


def _group_by_season(video_files):
    with_season = {}
    without_season = []

    for vf in video_files:
        se = parse_season_episode(vf)
        if se[0] is not None:
            s_num = se[0]
            with_season.setdefault(s_num, []).append(vf)
        else:
            without_season.append(vf)

    result = {}
    for s_num in sorted(with_season.keys()):
        result[s_num] = with_season[s_num]
    if without_season:
        existing = set(result.keys())
        target = 1 if 1 not in existing else 0
        result[target] = without_season
    return result


def _parse_episodes(video_files, season_num, base_dir):
    episodes = []
    for i, vf in enumerate(sorted(video_files)):
        ep_num = parse_episode_number(os.path.basename(vf))
        if ep_num is None:
            ep_num = i + 1

        existing_nums = [e['number'] for e in episodes]
        if ep_num in existing_nums:
            ep_num = max(existing_nums) + 1

        thumbnail = find_video_thumbnail(vf)
        name = parse_episode_name(os.path.basename(vf))

        episodes.append({
            'number': ep_num,
            'name': name,
            'path': vf,
            'thumbnail': thumbnail,
        })

    episodes.sort(key=lambda e: e['number'])
    return episodes


# ─── Key Map ──────────────────────────────────────────────────────────────────

KEY_ACTIONS = [
    ("up",      "Up"),
    ("down",    "Down"),
    ("left",    "Left / Back"),
    ("right",   "Right / Select"),
    ("select",  "Select"),
    ("back",    "Back / Stop"),
]

DEFAULT_KEYMAP = {
    "up":    pygame.K_UP,
    "down":  pygame.K_DOWN,
    "left":  pygame.K_LEFT,
    "right": pygame.K_RIGHT,
    "select": pygame.K_RETURN,
    "back":  pygame.K_ESCAPE,
}

# ASCII-safe key display names (no unicode arrows)
KEY_NAMES = {
    pygame.K_LEFT: "Left", pygame.K_RIGHT: "Right",
    pygame.K_UP: "Up", pygame.K_DOWN: "Down",
    pygame.K_RETURN: "Enter", pygame.K_KP_ENTER: "NumEnter",
    pygame.K_ESCAPE: "Esc", pygame.K_BACKSPACE: "Backspace",
    pygame.K_SPACE: "Space", pygame.K_TAB: "Tab",
    pygame.K_DELETE: "Del", pygame.K_INSERT: "Ins",
    pygame.K_HOME: "Home", pygame.K_END: "End",
    pygame.K_PAGEUP: "PgUp", pygame.K_PAGEDOWN: "PgDn",
    pygame.K_F1: "F1", pygame.K_F2: "F2", pygame.K_F3: "F3", pygame.K_F4: "F4",
    pygame.K_F5: "F5", pygame.K_F6: "F6", pygame.K_F7: "F7", pygame.K_F8: "F8",
    pygame.K_F9: "F9", pygame.K_F10: "F10", pygame.K_F11: "F11", pygame.K_F12: "F12",
    pygame.K_0: "0", pygame.K_1: "1", pygame.K_2: "2", pygame.K_3: "3",
    pygame.K_4: "4", pygame.K_5: "5", pygame.K_6: "6", pygame.K_7: "7",
    pygame.K_8: "8", pygame.K_9: "9",
    pygame.K_a: "A", pygame.K_b: "B", pygame.K_c: "C", pygame.K_d: "D",
    pygame.K_e: "E", pygame.K_f: "F", pygame.K_g: "G", pygame.K_h: "H",
    pygame.K_i: "I", pygame.K_j: "J", pygame.K_k: "K", pygame.K_l: "L",
    pygame.K_m: "M", pygame.K_n: "N", pygame.K_o: "O", pygame.K_p: "P",
    pygame.K_q: "Q", pygame.K_r: "R", pygame.K_s: "S", pygame.K_t: "T",
    pygame.K_u: "U", pygame.K_v: "V", pygame.K_w: "W", pygame.K_x: "X",
    pygame.K_y: "Y", pygame.K_z: "Z",
    pygame.K_COMMA: ",", pygame.K_PERIOD: ".", pygame.K_SLASH: "/",
    pygame.K_SEMICOLON: ";", pygame.K_QUOTE: "'", pygame.K_BACKQUOTE: "`",
    pygame.K_MINUS: "-", pygame.K_EQUALS: "=",
    pygame.K_LEFTBRACKET: "[", pygame.K_RIGHTBRACKET: "]",
    pygame.K_BACKSLASH: "\\",
    pygame.K_LSHIFT: "LShift", pygame.K_RSHIFT: "RShift",
    pygame.K_LCTRL: "LCtrl", pygame.K_RCTRL: "RCtrl",
    pygame.K_LALT: "LAlt", pygame.K_RALT: "RAlt",
    pygame.K_KP0: "Num0", pygame.K_KP1: "Num1", pygame.K_KP2: "Num2",
    pygame.K_KP3: "Num3", pygame.K_KP4: "Num4", pygame.K_KP5: "Num5",
    pygame.K_KP6: "Num6", pygame.K_KP7: "Num7", pygame.K_KP8: "Num8",
    pygame.K_KP9: "Num9",
    pygame.K_KP_PLUS: "Num+", pygame.K_KP_MINUS: "Num-",
    pygame.K_KP_MULTIPLY: "Num*", pygame.K_KP_DIVIDE: "Num/",
}


def key_display_name(keycode):
    return KEY_NAMES.get(keycode, f"Key({keycode})")


def load_keymap(state):
    saved = state.get("keymap", {})
    km = dict(DEFAULT_KEYMAP)
    for action in DEFAULT_KEYMAP:
        if action in saved:
            km[action] = saved[action]
    return km


# ─── State ─────────────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def get_resume_ep(state, show, season):
    return state.get(show, {}).get(f"s{season:02d}", {}).get("ep", 0)


def set_resume_ep(state, show, season, ep):
    if show not in state:
        state[show] = {}
    state[show][f"s{season:02d}"] = {"ep": ep, "ts": datetime.now().isoformat()}
    save_state(state)


# ─── Main Application ─────────────────────────────────────────────────────────

class TVTimeCapsule:
    SHOW_LIST = 0
    SEASON_SELECT = 1
    EPISODE_SELECT = 2
    KEY_CONFIG = 3
    KEY_CAPTURE = 4
    PLAYING = 5
    CONFIRM_EXIT = 6

    def __init__(self, media_paths, fullscreen=True, force_43=False, test_mode=False, scanlines=False):
        global _USE_FREETYPE
        pygame.init()

        # Probe whether pygame.font works. On Python 3.14+ it fails with a
        # circular-import error; we fall back to _freetype. The failure is
        # expected, so silence pygame's noisy RuntimeWarning during the probe.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pygame.font.Font(None, 24)
        except Exception:
            _USE_FREETYPE = True
            pygame._freetype.init()

        self.test_mode = test_mode
        self.force_43 = force_43
        self.scanlines = scanlines

        # Always go fullscreen on the real display
        self.display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        real_w, real_h = self.display.get_size()

        # Virtual canvas size — all UI is drawn at this resolution,
        # then scaled to fill the real screen.
        self.canvas_w = SCREEN_W   # 720
        self.canvas_h = SCREEN_H   # 480
        self.sw = self.canvas_w
        self.sh = self.canvas_h

        # Viewport position on real screen (for 4:3 letterboxing)
        if force_43:
            scale = min(real_w / self.canvas_w, real_h / self.canvas_h)
            self.viewport_w = int(self.canvas_w * scale)
            self.viewport_h = int(self.canvas_h * scale)
            self.viewport_x = (real_w - self.viewport_w) // 2
            self.viewport_y = (real_h - self.viewport_h) // 2
        else:
            self.viewport_w = real_w
            self.viewport_h = real_h
            self.viewport_x = 0
            self.viewport_y = 0

        self.real_w = real_w
        self.real_h = real_h

        # Off-screen canvas for rendering at fixed resolution
        # SRCALPHA so omxplayer's hardware video layer shows through on Pi
        self.canvas = pygame.Surface((self.canvas_w, self.canvas_h), pygame.SRCALPHA)
        self.screen = self.canvas   # All drawing goes to canvas

        pygame.display.set_caption("TV Time Capsule")
        pygame.mouse.set_visible(False)

        # Detect video player
        ffmpeg_path = detect_ffmpeg()
        ffplay_path = detect_ffplay()
        omx_cmd = detect_omxplayer() if is_pi() else None

        if ffmpeg_path and _np_frombuffer is not None:
            # Embedded FFmpeg playback (preferred)
            self.player = EmbeddedPlayer(self.canvas_w, self.canvas_h)
            self.player.ffmpeg_path = ffmpeg_path
            self.player.ffplay_path = ffplay_path
            self.player_cmd = ffmpeg_path
            self.embedded_player = True
        elif omx_cmd:
            # Omxplayer fallback on Pi
            self.player = EmbeddedPlayer(self.canvas_w, self.canvas_h)
            self.player.use_omx = True
            self.player.omx_cmd = omx_cmd
            self.player_cmd = omx_cmd
            self.embedded_player = True
        else:
            self.player = None
            self.player_cmd = None
            self.embedded_player = False

        # ─── Font hierarchy: 3 sizes only ───
        self.font_lg = _make_font(60)    # Large: channel numbers, splash, key config values
        self.font_md = _make_font(36)    # Medium: titles, labels, card text
        self.font_sm = _make_font(24)    # Small: info, hints, footer

        # Pre-render the scanline overlay (lazy — only if enabled)
        self._scanline_surf = None

        self.media_paths = media_paths if isinstance(media_paths, list) else [media_paths]
        self.state = load_state()
        self.keymap = load_keymap(self.state)
        self.running = True
        self.clock = pygame.time.Clock()

        self.view = self.SHOW_LIST
        self.cursor = 0
        self.config_cursor = 0

        # Channel number input
        self.channel_digits = ""
        self.channel_timer = 0
        self.channel_flash = ""
        self.channel_flash_time = 0
        self.channel_error = ""
        self.channel_error_time = 0
        self.channel_pending = 0
        self.channel_pending_time = 0

        # Playback state
        self.playing_show = None
        self.playing_season = None
        self.playing_episode = None
        self.playing_episodes = []
        self.playing_index = 0
        self.volume_overlay_timer = 0
        self.progress_overlay_timer = 0

        self.shows = discover_shows(self.media_paths)
        self.show_names = sorted(self.shows.keys())
        self.cur_show = None
        self.cur_season = None

        self._img_cache = {}
        self._img_cache_order = []  # LRU tracking for Pi memory limits
        self._img_cache_max = 8     # Max thumbnails cached (safe for 256MB Pi)
        self._duration_cache = {}   # Lazy ffprobe duration cache (path → "MM:SS")

        pygame.key.set_repeat(400, 130)

    # ─── Scanline overlay ────────────────────────────────────────────────

    def _make_scanlines(self):
        """Create a semi-transparent scanline overlay for CRT effect."""
        surf = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        for y in range(0, SCREEN_H, 3):
            pygame.draw.line(surf, C.SCANLINE, (0, y), (SCREEN_W, y))
        return surf

    # ─── Duration lookup ─────────────────────────────────────────────────

    def _get_duration(self, filepath):
        """Lazy ffprobe duration lookup, cached. Returns 'MM:SS' or empty string."""
        if filepath in self._duration_cache:
            return self._duration_cache[filepath]
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", filepath],
                capture_output=True, text=True, timeout=3
            )
            info = json.loads(result.stdout)
            dur = float(info.get("format", {}).get("duration", 0))
            if dur > 0:
                m, s = divmod(int(dur), 60)
                if dur >= 3600:
                    h, m = divmod(m, 60)
                    text = f"{h}:{m:02d}:{s:02d}"
                else:
                    text = f"{m}:{s:02d}"
            else:
                text = ""
        except Exception:
            text = ""
        self._duration_cache[filepath] = text
        return text

    # ─── Image handling ────────────────────────────────────────────────────

    def load_image(self, path, max_size):
        key = (path, max_size)
        if key in self._img_cache:
            # Move to end of LRU order
            if key in self._img_cache_order:
                self._img_cache_order.remove(key)
            self._img_cache_order.append(key)
            return self._img_cache[key]

        if not path or not os.path.isfile(path):
            self._img_cache[key] = None
            return None

        try:
            img = self._load_image_surface(path)
            if img is None:
                self._img_cache[key] = None
                return None
            src_w, src_h = img.get_size()
            if src_w == 0 or src_h == 0:
                self._img_cache[key] = None
                return None
            s = min(max_size[0] / src_w, max_size[1] / src_h)
            new_w = max(1, int(src_w * s))
            new_h = max(1, int(src_h * s))
            # Use scale (not smoothscale) for ARMv6 / Pi Model B compatibility
            img = pygame.transform.scale(img, (new_w, new_h))
            # LRU eviction: cap cache at _img_cache_max entries
            while len(self._img_cache_order) >= self._img_cache_max:
                old_key = self._img_cache_order.pop(0)
                if old_key in self._img_cache:
                    del self._img_cache[old_key]
            self._img_cache[key] = img
            self._img_cache_order.append(key)
            return img
        except Exception:
            self._img_cache[key] = None
            return None

    @staticmethod
    def _load_image_surface(path):
        """Load an image file as a pygame Surface.
        Tries pygame's native loader first, falls back to Pillow for
        systems where SDL_image lacks PNG/JPEG support (e.g. macOS wheels).
        """
        # Try pygame's native loader (works for BMP, and for PNG/JPEG when
        # SDL_image is compiled with extended format support).
        try:
            return pygame.image.load(path).convert()
        except Exception:
            pass

        # Fall back to Pillow → pygame surface
        try:
            from PIL import Image as PILImage
            pil_img = PILImage.open(path).convert("RGB")
            data = pil_img.tobytes("raw", "RGB")
            return pygame.image.fromstring(data, pil_img.size, "RGB")
        except Exception:
            return None

    # ─── Drawing helpers ─────────────────────────────────────────────────

    def present(self):
        """Scale the canvas to the real display and flip.
        Adds black pillarboxing for 4:3 mode."""
        self.display.fill(C.BLACK)
        scaled = pygame.transform.scale(self.canvas, (self.viewport_w, self.viewport_h))
        self.display.blit(scaled, (self.viewport_x, self.viewport_y))
        pygame.display.flip()

    def _apply_scanlines(self):
        """Overlay CRT scanlines on the current frame (if enabled)."""
        if self.scanlines:
            if self._scanline_surf is None:
                self._scanline_surf = self._make_scanlines()
            self.screen.blit(self._scanline_surf, (0, 0))

    def _draw_footer(self, text):
        """Draw a consistent footer bar at the bottom of the screen."""
        bar_h = 34
        fy = self.sh - bar_h
        pygame.draw.rect(self.screen, C.BG_FOOTER, (0, fy, self.sw, bar_h))
        pygame.draw.line(self.screen, C.BLUE, (0, fy), (self.sw, fy), 1)
        # Truncate if text is too wide for the screen
        max_w = self.sw - 32
        t = self.font_sm.render(text, True, C.DIM)
        if t.get_width() > max_w:
            while self.font_sm.size(text + "...")[0] > max_w and len(text) > 3:
                text = text[:-1]
            t = self.font_sm.render(text + "...", True, C.DIM)
        self.screen.blit(t, t.get_rect(centerx=self.sw // 2, centery=fy + bar_h // 2))

    def _draw_header(self, left_text, right_text="", ch_num=None):
        """Draw a consistent header bar at the top of the screen."""
        bar_h = 48
        pygame.draw.rect(self.screen, C.BG_HEADER, (0, 0, self.sw, bar_h))
        pygame.draw.line(self.screen, C.BLUE, (0, bar_h), (self.sw, bar_h), 1)

        # Left: breadcrumb/title text — larger, bright white
        lt = self.font_md.render(left_text, True, C.BRIGHT)
        self.screen.blit(lt, (16, (bar_h - lt.get_height()) // 2))

        # Right: channel number if provided
        if ch_num is not None:
            rt = self.font_md.render(str(ch_num), True, C.GREEN)
            self.screen.blit(rt, (self.sw - rt.get_width() - 16,
                                  (bar_h - rt.get_height()) // 2))

        return bar_h

    # ─── Navigation helpers ───────────────────────────────────────────────

    def _count_total_eps(self, show_data):
        """Count total episodes across all seasons."""
        return sum(len(s.get('episodes', [])) for s in show_data.get('seasons', {}).values())

    def _wrap_text(self, text, font, max_width):
        """Word-wrap text to fit within max_width pixels. Returns list of lines."""
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            if font.size(test_line)[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines if lines else [text]

    def seasons_for_show(self, show):
        return sorted(self.shows.get(show, {}).get('seasons', {}).keys())

    def current_items(self):
        if self.view == self.SHOW_LIST:
            return [{'name': n, 'data': self.shows[n]} for n in self.show_names]
        elif self.view == self.SEASON_SELECT:
            show = self.shows.get(self.cur_show, {})
            seasons = sorted(show.get('seasons', {}).keys())
            return [{'name': f'Season {s}', 'number': s,
                     'data': show['seasons'][s]} for s in seasons]
        else:
            show = self.shows.get(self.cur_show, {})
            season_data = show.get('seasons', {}).get(self.cur_season, {})
            return list(season_data.get('episodes', []))

    def total_items(self):
        items = self.current_items()
        return len(items) if items else 0

    # ─── Main draw dispatch ──────────────────────────────────────────────

    def draw(self):
        if self.view == self.SHOW_LIST:
            self.draw_show_browser()
        elif self.view == self.SEASON_SELECT:
            self.draw_season_browser()
        elif self.view == self.EPISODE_SELECT:
            self.draw_episode_browser()
        self.draw_channel_overlay()

    # ─── Channel overlay ─────────────────────────────────────────────────

    def draw_channel_overlay(self):
        """Channel number overlay — building digits, commit flash, or error."""
        now = pygame.time.get_ticks()

        # Error message overlay
        if self.channel_error and self.channel_error_time > 0:
            elapsed = now - self.channel_error_time
            if elapsed < CHANNEL_ERROR_MS:
                alpha = 255
                if elapsed > CHANNEL_ERROR_MS // 2:
                    fade_progress = (elapsed - CHANNEL_ERROR_MS // 2) / (CHANNEL_ERROR_MS // 2)
                    alpha = int(255 * (1.0 - fade_progress))

                err_surf = self.font_lg.render(self.channel_error, True, C.GREEN)
                box_w = err_surf.get_width() + 60
                box_h = err_surf.get_height() + 30
                box_x = (self.sw - box_w) // 2
                box_y = self.sh // 2 - box_h // 2

                bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
                bg_surf.fill((0, 10, 5, min(220, alpha)))
                pygame.draw.rect(bg_surf, (*C.GREEN[:3], min(alpha, 200)),
                                 (0, 0, box_w, box_h), 2, border_radius=6)
                self.screen.blit(bg_surf, (box_x, box_y))

                if alpha < 255:
                    err_surf.set_alpha(alpha)
                self.screen.blit(err_surf,
                                (box_x + (box_w - err_surf.get_width()) // 2,
                                 box_y + (box_h - err_surf.get_height()) // 2))
                return
            else:
                self.channel_error = ""
                self.channel_error_time = 0

        # Commit flash overlay (shown after channel is committed)
        if self.channel_flash and self.channel_flash_time > 0:
            elapsed = now - self.channel_flash_time
            if elapsed < CHANNEL_FLASH_MS:
                alpha = 255
                if elapsed > CHANNEL_FLASH_MS // 2:
                    fade_progress = (elapsed - CHANNEL_FLASH_MS // 2) / (CHANNEL_FLASH_MS // 2)
                    alpha = int(255 * (1.0 - fade_progress))

                box_w = 160
                box_h = 100
                box_x = self.sw - box_w - 16
                box_y = 16

                bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
                bg_surf.fill((0, 10, 5, min(200, alpha)))
                pygame.draw.rect(bg_surf, (*C.GREEN[:3], min(alpha, 180)),
                                 (0, 0, box_w, box_h), 2, border_radius=6)
                self.screen.blit(bg_surf, (box_x, box_y))

                ch_surf = self.font_lg.render(self.channel_flash, True, C.GREEN)
                if alpha < 255:
                    ch_surf.set_alpha(alpha)
                self.screen.blit(ch_surf, (box_x + (box_w - ch_surf.get_width()) // 2,
                                           box_y + (box_h - ch_surf.get_height()) // 2))
                return
            else:
                self.channel_flash = ""
                self.channel_flash_time = 0

        # Building digits overlay — fixed-width 3-digit display, left-aligned
        if self.channel_digits:
            # Fixed box sized for 3 digits
            sample = self.font_lg.render("888", True, C.GREEN)
            digit_w = sample.get_width()
            digit_h = sample.get_height()
            box_w = digit_w + 40
            box_h = digit_h + 30
            box_x = self.sw - box_w - 16
            box_y = 16

            bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
            bg_surf.fill((0, 10, 5, 200))
            pygame.draw.rect(bg_surf, C.GREEN, (0, 0, box_w, box_h), 2, border_radius=6)
            self.screen.blit(bg_surf, (box_x, box_y))

            # Build display: digits left-aligned, cursor at next position
            cursor_on = (now // 400) % 2 == 0
            display = self.channel_digits
            if len(display) < 3 and cursor_on:
                display += "_"
            # Pad to 3 positions so it stays left-aligned
            while len(display) < 3:
                display += " "
            ch_surf = self.font_lg.render(display, True, C.GREEN)
            self.screen.blit(ch_surf, (box_x + (box_w - ch_surf.get_width()) // 2,
                                       box_y + (box_h - ch_surf.get_height()) // 2))

    # ─── Show browser ────────────────────────────────────────────────────

    def draw_show_browser(self):
        """Cable-TV show browser: one show at a time, full-screen.

        Layout:
          [HEADER BAR: show name + channel number]
          [UP NAV BAR: full-width, shows show above if available]
          [CONTENT: thumbnail or wrapped show title]
          [DOWN NAV BAR: full-width, shows show below if available]
          [FOOTER BAR: controls hint]
        """
        self.screen.fill(C.BG)
        shows = self.show_names
        if not shows:
            t = self.font_md.render("No shows found", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            self._apply_scanlines()
            return

        idx = self.cursor % len(shows)
        show_name = shows[idx]
        show_data = self.shows[show_name]
        ch_num = idx + 1

        # ── Header ──
        header_h = self._draw_header(show_name.upper(), ch_num=ch_num)

        # ── Up navigation bar (full width) ──
        nav_h = 28
        up_y = header_h
        if idx > 0:
            up_name = shows[idx - 1].upper()
            pygame.draw.rect(self.screen, C.BG_CARD, (0, up_y, self.sw, nav_h))
            up_surf = self.font_sm.render(f"\u25b2  {up_name}", True, C.CYAN)
            self.screen.blit(up_surf, up_surf.get_rect(left=16, centery=up_y + nav_h // 2))
        else:
            pygame.draw.rect(self.screen, (14, 20, 35), (0, up_y, self.sw, nav_h))
        pygame.draw.line(self.screen, (25, 40, 70), (0, up_y + nav_h), (self.sw, up_y + nav_h), 1)

        # ── Content area ──
        footer_h = 30
        content_y = up_y + nav_h + 4
        content_bottom = self.sh - footer_h - nav_h - 4
        content_h = content_bottom - content_y
        if content_h < 40:
            content_h = 40

        # ── Down navigation bar (full width) ──
        down_y = content_bottom
        if idx < len(shows) - 1:
            down_name = shows[idx + 1].upper()
            pygame.draw.rect(self.screen, C.BG_CARD, (0, down_y, self.sw, nav_h))
            down_surf = self.font_sm.render(f"\u25bc  {down_name}", True, C.CYAN)
            self.screen.blit(down_surf, down_surf.get_rect(left=16, centery=down_y + nav_h // 2))
        else:
            pygame.draw.rect(self.screen, (14, 20, 35), (0, down_y, self.sw, nav_h))
        pygame.draw.line(self.screen, (25, 40, 70), (0, down_y), (self.sw, down_y), 1)

        # ── Central content: thumbnail or wrapped show title ──
        n_total = self._count_total_eps(show_data)
        seasons = self.seasons_for_show(show_name)
        if len(seasons) > 1:
            info = f"{len(seasons)} seasons - {n_total} episodes"
        else:
            info = f"{n_total} episodes"

        thumb = self.load_image(show_data.get('thumbnail'),
                                 (self.sw - 80, content_h - 40))
        if thumb:
            tx = (self.sw - thumb.get_width()) // 2
            ty = content_y + (content_h - thumb.get_height() - 20) // 2
            self.screen.blit(thumb, (tx, ty))

            # Info line below thumbnail
            it = self.font_sm.render(info, True, C.DIM)
            info_y = ty + thumb.get_height() + 6
            # Make sure info doesn't go below content area
            if info_y + it.get_height() > content_bottom:
                info_y = content_bottom - it.get_height() - 2
            self.screen.blit(it, it.get_rect(centerx=self.sw // 2, top=info_y))
        else:
            # No thumbnail - wrap the show title and center it
            max_w = self.sw - 60
            lines = self._wrap_text(show_name.upper(), self.font_lg, max_w)

            line_h = self.font_lg.size("Mg")[1] + 6  # extra spacing for readability
            info_h = self.font_sm.size(info)[1]
            total_h = len(lines) * line_h + 10 + info_h
            text_start_y = content_y + max(0, (content_h - total_h) // 2)

            for i, line in enumerate(lines):
                surf = self.font_lg.render(line, True, C.WHITE)
                self.screen.blit(surf, surf.get_rect(centerx=self.sw // 2,
                                                      top=text_start_y + i * line_h))

            # Info line below the title
            it = self.font_sm.render(info, True, C.DIM)
            it_y = text_start_y + len(lines) * line_h + 10
            if it_y + it.get_height() > content_bottom:
                it_y = content_bottom - it.get_height() - 2
            self.screen.blit(it, it.get_rect(centerx=self.sw // 2, top=it_y))

        # ── Footer ──
        self._draw_footer("ENTER play  |  # channel  |  H help")
        self._apply_scanlines()

    # ─── Season browser ──────────────────────────────────────────────────

    def draw_season_browser(self):
        """Season browser: vertical stack of season cards."""
        self.screen.fill(C.BG)
        seasons = self.seasons_for_show(self.cur_show)
        show_data = self.shows.get(self.cur_show, {})
        total = len(seasons)

        if not seasons:
            t = self.font_md.render("No seasons", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            self._apply_scanlines()
            return

        # Header — channel number reflects the highlighted item on THIS page
        header_h = self._draw_header(f"{self.cur_show.upper()}",
                                     ch_num=str(self.cursor + 1))

        # Stack area
        footer_h = 30
        stack_top = header_h + 10
        stack_bottom = self.sh - footer_h - 10
        stack_h = stack_bottom - stack_top
        item_h = min(70, (stack_h - (STACK_VISIBLE - 1) * 4) // STACK_VISIBLE)
        gap = 4

        first_visible = max(0, self.cursor - STACK_VISIBLE + 1)
        first_visible = min(first_visible, max(0, total - STACK_VISIBLE))

        # Up arrow
        if first_visible > 0:
            arr = self.font_sm.render("\u25b2 more above", True, C.DIM)
            self.screen.blit(arr, arr.get_rect(centerx=self.sw // 2, top=stack_top - 2))

        for i in range(STACK_VISIBLE):
            item_idx = first_visible + i
            if item_idx >= total:
                break

            y = stack_top + i * (item_h + gap)
            # Ensure card doesn't go below stack area
            if y + item_h > stack_bottom:
                break

            selected = (item_idx == self.cursor)
            season_num = seasons[item_idx]
            season_data = show_data['seasons'][season_num]

            rect = pygame.Rect(30, y, self.sw - 60, item_h)

            # Card background
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.CYAN, rect.inflate(2, 2), 2, border_radius=8)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=8)

            # Channel number — unique per page (1-based position in this list)
            ch_label = str(item_idx + 1)
            ch_surf = self.font_md.render(ch_label, True, C.GREEN if selected else C.DIM)
            self.screen.blit(ch_surf, (rect.x + 14,
                                       rect.y + (rect.height - ch_surf.get_height()) // 2))

            # Season label
            s_label = f"Season {season_num}"
            sl = self.font_md.render(s_label, True, C.BRIGHT if selected else C.WHITE)
            sl_x = rect.x + 100
            # Truncate if too wide
            max_label_w = rect.right - sl_x - 100
            if sl.get_width() > max_label_w and max_label_w > 30:
                label_text = s_label
                while self.font_md.size(label_text + "...")[0] > max_label_w and len(label_text) > 3:
                    label_text = label_text[:-1]
                sl = self.font_md.render(label_text + "...", True, C.BRIGHT if selected else C.WHITE)
            self.screen.blit(sl, (sl_x, rect.y + (rect.height - sl.get_height()) // 2))

            # Episode count / status (right side)
            season_eps = season_data.get('episodes', [])
            n_eps = len(season_eps)
            resume = get_resume_ep(self.state, self.cur_show, season_num)
            watched = sum(1 for e in season_eps if e['number'] <= resume) if resume > 0 else 0
            nxt = next((e for e in season_eps if e['number'] > resume), None)
            if n_eps > 0 and watched >= n_eps:
                info = "[done]"
                info_color = C.DIM
            elif watched > 0 and nxt is not None:
                info = f"E-{nxt['number']:02d} next"
                info_color = C.GREEN
            else:
                info = f"{n_eps} ep{'s' if n_eps != 1 else ''}"
                info_color = C.DIM

            it = self.font_sm.render(info, True, info_color)
            self.screen.blit(it, (rect.right - it.get_width() - 14,
                                   rect.y + (rect.height - it.get_height()) // 2))

        # Down arrow
        if first_visible + STACK_VISIBLE < total:
            arr = self.font_sm.render("\u25bc more below", True, C.DIM)
            self.screen.blit(arr, arr.get_rect(centerx=self.sw // 2, top=stack_top + STACK_VISIBLE * (item_h + gap)))

        # Footer
        self._draw_footer("Up/Dn  |  Right open  |  Left back  |  # ch  |  H help")
        self._apply_scanlines()

    # ─── Episode browser ─────────────────────────────────────────────────

    def draw_episode_browser(self):
        """Episode browser: vertical stack of episode cards."""
        self.screen.fill(C.BG)
        show_data = self.shows.get(self.cur_show, {})
        season_data = show_data.get('seasons', {}).get(self.cur_season, {})
        episodes = season_data.get('episodes', [])
        total = len(episodes)

        if not episodes:
            t = self.font_md.render("No episodes", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            self._apply_scanlines()
            return

        # Header — channel number reflects the highlighted episode on THIS page
        header_h = self._draw_header(
            f"{self.cur_show.upper()}  -  S-{self.cur_season:02d}",
            ch_num=str(self.cursor + 1))

        # Stack area
        footer_h = 30
        stack_top = header_h + 10
        stack_bottom = self.sh - footer_h - 10
        stack_h = stack_bottom - stack_top
        item_h = min(70, (stack_h - (STACK_VISIBLE - 1) * 4) // STACK_VISIBLE)
        gap = 4

        resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
        next_up = next((e['number'] for e in episodes if e['number'] > resume), None)

        first_visible = max(0, self.cursor - STACK_VISIBLE + 1)
        first_visible = min(first_visible, max(0, total - STACK_VISIBLE))

        # Up arrow
        if first_visible > 0:
            arr = self.font_sm.render("\u25b2 more above", True, C.DIM)
            self.screen.blit(arr, arr.get_rect(centerx=self.sw // 2, top=stack_top - 2))

        for i in range(STACK_VISIBLE):
            item_idx = first_visible + i
            if item_idx >= total:
                break

            ep = episodes[item_idx]
            y = stack_top + i * (item_h + gap)
            if y + item_h > stack_bottom:
                break

            rect = pygame.Rect(30, y, self.sw - 60, item_h)
            selected = (item_idx == self.cursor)
            ep_num = ep['number']
            is_watched = resume > 0 and ep_num <= resume
            is_next = (ep_num == next_up)

            # Card background
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.CYAN, rect.inflate(2, 2), 2, border_radius=8)
            elif is_next:
                pygame.draw.rect(self.screen, C.NEXT_UP, rect, border_radius=8)
            elif is_watched:
                pygame.draw.rect(self.screen, C.WATCHED, rect, border_radius=8)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=8)

            # Episode thumbnail (small, left side)
            thumb = self.load_image(ep.get('thumbnail'), (item_h - 12, item_h - 12))
            label_x = rect.x + 14
            if thumb:
                tx = rect.x + 10
                ty = rect.y + (rect.height - thumb.get_height()) // 2
                self.screen.blit(thumb, (tx, ty))
                label_x = rect.x + thumb.get_width() + 18

            # Right side: channel number — unique per page (1-based position)
            ch_label = str(item_idx + 1)
            ec = self.font_sm.render(ch_label, True, C.GREEN if selected else C.DIM)

            # Status indicator (right of card)
            status_text = ""
            status_color = C.DIM
            if is_next and not selected:
                status_text = ">"
            elif is_watched and not is_next:
                status_text = "*"
                status_color = C.DIM
            st = self.font_sm.render(status_text, True, status_color) if status_text else None

            # Calculate available width for text
            right_margin = ec.get_width() + 14
            if st:
                right_margin += st.get_width() + 6
            avail_w = rect.right - label_x - right_margin

            # ── Line 1: "E-01  Episode Name" ──
            ep_label = f"E-{ep_num:02d}"
            ep_name = ep.get('name') or ''

            # Build the combined line: "E-01  Name" — truncate name to fit
            el = self.font_md.render(ep_label, True, C.BRIGHT if selected else C.WHITE)
            gap_w = self.font_md.size("  ")[0]

            if ep_name:
                # How much room is left for the name after the number + gap?
                name_avail = avail_w - el.get_width() - gap_w
                name_text = ep_name
                if name_avail > 30:
                    en = self.font_md.render(name_text, True, C.WHITE)
                    if en.get_width() > name_avail:
                        while (self.font_md.size(name_text + "...")[0] > name_avail
                               and len(name_text) > 3):
                            name_text = name_text[:-1]
                        en = self.font_md.render(name_text + "...", True, C.WHITE)
                else:
                    en = None
            else:
                en = None

            # Vertically center the one or two lines
            dur_text = self._get_duration(ep['path'])
            has_dur = bool(dur_text)
            line1_h = el.get_height()
            line2_h = self.font_sm.size("0:00")[1] if has_dur else 0
            total_text_h = line1_h + (line2_h + 2 if has_dur else 0)
            text_top = rect.y + (rect.height - total_text_h) // 2

            # Draw line 1: "E-01  Name"
            self.screen.blit(el, (label_x, text_top))
            if en:
                self.screen.blit(en, (label_x + el.get_width() + gap_w, text_top))

            # ── Line 2: Duration ──
            if has_dur:
                dur = self.font_sm.render(dur_text, True, C.DIM)
                dur_y = text_top + line1_h + 2
                if dur_y + dur.get_height() <= rect.y + rect.height - 2:
                    self.screen.blit(dur, (label_x, dur_y))

            # Right side: channel number
            self.screen.blit(ec, (rect.right - ec.get_width() - 14,
                                   rect.y + (rect.height - ec.get_height()) // 2))

            # Status indicator
            if st:
                self.screen.blit(st, (rect.right - ec.get_width() - st.get_width() - 22,
                                       rect.y + (rect.height - st.get_height()) // 2))

        # Down arrow
        if first_visible + STACK_VISIBLE < total:
            arr = self.font_sm.render("\u25bc more below", True, C.DIM)
            self.screen.blit(arr, arr.get_rect(centerx=self.sw // 2, top=stack_top + STACK_VISIBLE * (item_h + gap)))

        # Footer
        self._draw_footer("Up/Dn  |  Right play  |  Left back  |  # ch  |  H help")
        self._apply_scanlines()

    # ── Playback drawing (embedded video) ─────────────────────────────────

    def draw_playback(self):
        """Render video frame with overlays during playback.

        Embedded mode: video frame fills the canvas, overlays on top.
        Omxplayer mode: video renders on hardware layer — we draw
        transparent overlays only (no black fill).
        """
        if self.player and self.player.use_omx:
            # omxplayer renders on its own hardware layer — don't fill black
            pass
        else:
            self.screen.fill(C.BLACK)

        if self.player:
            frame = self.player.get_frame()
            if frame:
                # Scale video frame to canvas
                scaled = pygame.transform.scale(frame, (self.sw, self.sh))
                self.screen.blit(scaled, (0, 0))
            elif not self.player.use_omx:
                # No frame yet — show loading indicator
                t = self.font_md.render("Loading...", True, C.WHITE)
                self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))

        # Draw overlays on top of video
        self.draw_progress_overlay()
        self.draw_volume_overlay()
        self.draw_pause_overlay()

    # ─── Progress overlay (during playback) ─────────────────────────────────

    def draw_progress_overlay(self):
        """Progress bar overlay — top info bar + bottom scrub line.
        Green color scheme like a real CRT TV."""
        if not self.player:
            return

        now = pygame.time.get_ticks()
        elapsed = now - self.progress_overlay_timer

        if not self.player.paused and self.progress_overlay_timer > 0 and elapsed > OVERLAY_SHOW_MS:
            return

        if self.player.paused:
            fade = 255
        elif self.progress_overlay_timer > 0 and elapsed < OVERLAY_SHOW_MS:
            remaining = OVERLAY_SHOW_MS - elapsed
            fade = min(255, int(255 * remaining / 500)) if remaining < 500 else 255
        else:
            return

        self.player.update_time()
        progress = self.player.progress()
        time_str = f"{self.player.format_time(self.player.time_pos)} / {self.player.format_time(self.player.duration)}"

        # Top bar: show/episode info + time
        bar_h = 44
        bar_surf = pygame.Surface((self.sw, bar_h), pygame.SRCALPHA)
        bar_surf.fill((0, 10, 5, min(200, fade)))
        self.screen.blit(bar_surf, (0, 0))

        ep = self.playing_episode or {}
        ep_num = ep.get('number', 0)
        ep_name = ep.get('name') or ''
        label = f"S-{self.playing_season or 1:02d} - E-{ep_num:02d}"
        if ep_name:
            label += f"  {ep_name}"
        lt = self.font_sm.render(label, True, C.GREEN)
        lt.set_alpha(fade)
        self.screen.blit(lt, (16, (bar_h - lt.get_height()) // 2))

        rt = self.font_sm.render(time_str, True, C.GREEN)
        rt.set_alpha(fade)
        self.screen.blit(rt, (self.sw - rt.get_width() - 16, (bar_h - rt.get_height()) // 2))

        # Bottom scrub bar
        bar_y = self.sh - 28
        bar_w = self.sw - 40
        bar_x = 20
        bar_h = 6

        # Track background
        track = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
        track.fill((20, 60, 35, min(220, fade)))
        self.screen.blit(track, (bar_x, bar_y))

        # Filled progress
        fill_w = max(1, int(bar_w * progress))
        fill = pygame.Surface((fill_w, bar_h), pygame.SRCALPHA)
        fill.fill((*C.GREEN[:3], min(255, fade)))
        self.screen.blit(fill, (bar_x, bar_y))

        # Playhead dot
        dot_x = bar_x + fill_w
        dot_y = bar_y + bar_h // 2
        dot_r = 7
        dot_surf = pygame.Surface((dot_r * 2, dot_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(dot_surf, (*C.BRIGHT, min(255, fade)), (dot_r, dot_r), dot_r)
        self.screen.blit(dot_surf, (dot_x - dot_r, dot_y - dot_r))

    # ─── Volume overlay ───────────────────────────────────────────────────

    def draw_volume_overlay(self):
        """Simple retro volume bar — upper-right corner, no background, no fade."""
        if not self.player:
            return

        now = pygame.time.get_ticks()
        elapsed = now - self.volume_overlay_timer

        if self.volume_overlay_timer <= 0 or elapsed >= OVERLAY_SHOW_MS:
            return

        vol = min(self.player.volume, 100)

        # "VOLUME [||||||||||]" — larger, upper-right corner
        label = self.font_md.render("VOLUME", True, C.GREEN)
        n_bars = 10
        bar_w = 12
        bar_h = 28
        bar_gap = 3
        filled = int(n_bars * vol / 100)

        total_bar_w = n_bars * bar_w + (n_bars - 1) * bar_gap
        total_w = label.get_width() + 16 + total_bar_w
        x = self.sw - total_w - 16
        y = 16

        self.screen.blit(label, (x, y + (bar_h - label.get_height()) // 2))

        bar_x = x + label.get_width() + 16
        for i in range(n_bars):
            bx = bar_x + i * (bar_w + bar_gap)
            color = C.GREEN if i < filled else C.GREEN_DIM
            pygame.draw.rect(self.screen, color, (bx, y, bar_w, bar_h))

    # ─── Pause overlay ────────────────────────────────────────────────────

    def draw_pause_overlay(self):
        """Show PAUSED indicator when video is paused."""
        if not self.player or not self.player.paused:
            return

        # Static PAUSED text
        txt = self.font_lg.render("PAUSED", True, C.GREEN)
        self.screen.blit(txt, txt.get_rect(centerx=self.sw // 2, centery=self.sh // 2))

    # ─── Splash screen ────────────────────────────────────────────────────

    def draw_splash(self):
        """Show a 10-second controls splash screen. Dismissable by any key."""
        start = pygame.time.get_ticks()
        duration = 10000  # 10 seconds

        # Build control lines - ASCII only, no unicode arrows
        km = self.keymap
        lines = [
            ("NAVIGATION", None),
            ("browse shows", f"{key_display_name(km.get('up','Up'))}/{key_display_name(km.get('down','Down'))}  up / down"),
            ("enter / select", f"{key_display_name(km.get('right','Right'))} or {key_display_name(km.get('select','Enter'))}"),
            ("go back", f"{key_display_name(km.get('left','Left'))} or {key_display_name(km.get('back','Esc'))}"),
            ("", None),
            ("CHANNELS", None),
            ("jump to channel", "type any number  (auto-enters after 1.5s)"),
            ("", None),
            ("DURING PLAYBACK", None),
            ("volume up / down", f"{key_display_name(km.get('up','Up'))}/{key_display_name(km.get('down','Down'))}"),
            ("seek +/-10s", f"{key_display_name(km.get('left','Left'))}/{key_display_name(km.get('right','Right'))}"),
            ("pause / resume", "Space or Enter"),
            ("stop & return", f"{key_display_name(km.get('back','Esc'))}"),
            ("", None),
            ("SETTINGS", None),
            ("key configuration", "Tab"),
        ]

        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    return
                if event.type == pygame.KEYDOWN:
                    return  # Any key dismisses

            elapsed = pygame.time.get_ticks() - start
            if elapsed >= duration:
                return

            remaining = max(0, (duration - elapsed) // 1000)

            self.screen.fill(C.BG)

            # Title
            title = self.font_lg.render("TV TIME CAPSULE", True, C.BRIGHT)
            self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=40))

            # Divider under title
            pygame.draw.line(self.screen, C.BLUE, (40, 75), (self.sw - 40, 75), 1)

            # Control lines
            y = 92
            for label, detail in lines:
                if detail is None:
                    if label:
                        # Section header
                        hdr = self.font_md.render(label, True, C.CYAN)
                        self.screen.blit(hdr, (50, y))
                        y += hdr.get_height() + 2
                    else:
                        y += 8
                else:
                    # Key line: label on left, detail on right.
                    lt = self.font_sm.render(label, True, C.WHITE)
                    dt = self.font_sm.render(detail, True, C.GREEN)
                    max_y = self.sh - 80
                    if y + max(lt.get_height(), dt.get_height()) + 4 > max_y:
                        break
                    left_x = 70
                    right_x = self.sw - dt.get_width() - 70
                    if right_x < left_x + lt.get_width() + 20:
                        # Columns would collide — drop the detail to its own line
                        self.screen.blit(lt, (left_x, y + 2))
                        y += lt.get_height() + 2
                        if y + dt.get_height() + 4 > max_y:
                            break
                        self.screen.blit(dt, (max(20, self.sw - dt.get_width() - 70), y + 2))
                        y += dt.get_height() + 4
                    else:
                        self.screen.blit(lt, (left_x, y + 2))
                        self.screen.blit(dt, (right_x, y + 2))
                        y += max(lt.get_height(), dt.get_height()) + 4

            # Divider above footer
            pygame.draw.line(self.screen, C.BLUE, (40, self.sh - 70), (self.sw - 40, self.sh - 70), 1)

            # Countdown + dismiss hint
            hint = self.font_sm.render(f"Press any key to continue...  {remaining}s", True, C.DIM)
            self.screen.blit(hint, hint.get_rect(centerx=self.sw // 2, centery=self.sh - 35))

            self._apply_scanlines()
            self.present()
            self.clock.tick(15)

    # ─── Now-playing splash ──────────────────────────────────────────────

    def draw_now_playing(self, show, season, episode, channel):
        """Splash screen before video plays. Green accent."""
        self.screen.fill(C.BLACK)

        ep_num = episode['number']
        ep_name = episode.get('name') or ''

        # Channel number (green, upper right) — matches the episode page
        ch = str(channel)
        ch_surf = self.font_lg.render(ch, True, C.GREEN)
        self.screen.blit(ch_surf, (self.sw - ch_surf.get_width() - 40, 30))

        # Episode number (white)
        label = f"S-{season:02d} - E-{ep_num:02d}"
        s = self.font_md.render(label, True, C.WHITE)
        self.screen.blit(s, s.get_rect(centerx=self.sw // 2, centery=self.sh // 2 - 40))

        # Episode name (blue)
        if ep_name:
            n = self.font_md.render(ep_name, True, C.BLUE)
            self.screen.blit(n, n.get_rect(centerx=self.sw // 2, centery=self.sh // 2 + 10))

        # Show name (dim)
        sn = self.font_sm.render(show.upper(), True, C.DIM)
        self.screen.blit(sn, sn.get_rect(centerx=self.sw // 2, centery=self.sh // 2 + 55))

        self.present()
        pygame.time.wait(1500)

        self.screen.fill(C.BLACK)
        self.present()
        pygame.time.wait(200)

    # ─── Key configuration ────────────────────────────────────────────────

    # ─── Confirm exit dialog ────────────────────────────────────────────

    def draw_confirm_exit(self):
        """'Are you sure?' exit confirmation dialog."""
        self.screen.fill(C.BG)

        # Dim overlay
        overlay = pygame.Surface((self.sw, self.sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        # Dialog box
        box_w = 400
        box_h = 160
        box_x = (self.sw - box_w) // 2
        box_y = (self.sh - box_h) // 2

        pygame.draw.rect(self.screen, C.BG_CARD, (box_x, box_y, box_w, box_h), border_radius=10)
        pygame.draw.rect(self.screen, C.BLUE, (box_x, box_y, box_w, box_h), 2, border_radius=10)

        # Title
        title = self.font_md.render("Quit?", True, C.BRIGHT)
        self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=box_y + 40))

        # Buttons — simple Yes / No
        btn_w = 100
        btn_h = 44
        btn_y = box_y + 95
        gap = 40
        total_btn_w = btn_w * 2 + gap
        btn_start_x = box_x + (box_w - total_btn_w) // 2

        # Yes button
        yes_x = btn_start_x
        yes_rect = pygame.Rect(yes_x, btn_y, btn_w, btn_h)
        pygame.draw.rect(self.screen, C.BG_CARD_SEL, yes_rect, border_radius=6)
        pygame.draw.rect(self.screen, C.CYAN, yes_rect, 2, border_radius=6)
        yes_txt = self.font_sm.render("Yes", True, C.BRIGHT)
        self.screen.blit(yes_txt, yes_txt.get_rect(center=yes_rect.center))

        # No button
        no_x = btn_start_x + btn_w + gap
        no_rect = pygame.Rect(no_x, btn_y, btn_w, btn_h)
        pygame.draw.rect(self.screen, C.BG_CARD, no_rect, border_radius=6)
        pygame.draw.rect(self.screen, C.DIM, no_rect, 2, border_radius=6)
        no_txt = self.font_sm.render("No", True, C.DIM)
        self.screen.blit(no_txt, no_txt.get_rect(center=no_rect.center))

        self._apply_scanlines()

    # ─── Key configuration ────────────────────────────────────────────────

    def draw_key_config(self, capturing=False):
        """Key configuration screen with white/blue theme."""
        self.screen.fill(C.BG)

        title = self.font_lg.render("KEY SETUP", True, C.BLUE)
        self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=40))

        if capturing:
            hint = self.font_md.render("Press a key...  (Esc cancels)", True, C.GREEN)
        else:
            hint = self.font_sm.render("ENTER assign  |  ESC done  |  TAB reset", True, C.DIM)
        self.screen.blit(hint, hint.get_rect(centerx=self.sw // 2, centery=82))

        y_start = 118
        row_h = 50
        # Leave room for the bound-key value on the right
        label_max_x = self.sw - 180

        for i, (action_id, action_label) in enumerate(KEY_ACTIONS):
            y = y_start + i * row_h
            if y + row_h > self.sh - 30:
                break

            selected = (i == self.config_cursor)

            bar_rect = pygame.Rect(30, y, self.sw - 60, row_h - 6)
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, bar_rect, border_radius=6)
                pygame.draw.rect(self.screen, C.CYAN, bar_rect.inflate(2, 2), 2, border_radius=7)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, bar_rect, border_radius=6)

            # Truncate label if it would overflow into the key-name area
            label_color = C.BRIGHT if selected else C.WHITE
            label_text = action_label
            label_surf = self.font_md.render(label_text, True, label_color)
            if label_surf.get_width() > label_max_x - 50:
                while (self.font_md.size(label_text + "...")[0] > label_max_x - 50
                       and len(label_text) > 3):
                    label_text = label_text[:-1]
                label_surf = self.font_md.render(label_text + "...", True, label_color)
            self.screen.blit(label_surf, (50, y + (row_h - label_surf.get_height()) // 2 - 3))

            bound_key = self.keymap.get(action_id, DEFAULT_KEYMAP.get(action_id))
            key_name = key_display_name(bound_key)

            if capturing and selected:
                if (pygame.time.get_ticks() // 500) % 2 == 0:
                    key_surf = self.font_lg.render("_", True, C.GREEN)
                else:
                    key_surf = self.font_lg.render("-", True, C.GREEN)
            else:
                key_surf = self.font_md.render(key_name, True, C.BRIGHT if selected else C.DIM)
            self.screen.blit(key_surf, (self.sw - key_surf.get_width() - 50,
                                         y + (row_h - key_surf.get_height()) // 2 - 3))

        self._apply_scanlines()
        self.present()

    def enter_key_config(self):
        self.view = self.KEY_CONFIG
        self.config_cursor = 0

    def exit_key_config(self):
        self.view = self.SHOW_LIST
        self.cursor = 0

    def reset_keymap(self):
        self.keymap = dict(DEFAULT_KEYMAP)
        self.state["keymap"] = {k: v for k, v in self.keymap.items()}
        save_state(self.state)

    # ─── Navigation ────────────────────────────────────────────────────────

    def move_cursor(self, direction):
        total = self.total_items()
        if not total:
            return
        # Clamp (no wrap) so the on-screen "more above/below" hints stay accurate.
        self.cursor = max(0, min(total - 1, self.cursor + direction))

    def select(self):
        items = self.current_items()
        if not items or self.cursor >= len(items):
            return

        if self.view == self.SHOW_LIST:
            self.cur_show = self.show_names[self.cursor]
            show = self.shows[self.cur_show]
            if not show['has_seasons']:
                seasons = sorted(show['seasons'].keys())
                if seasons:
                    self.cur_season = seasons[0]
                    self.view = self.EPISODE_SELECT
                else:
                    return
            else:
                self.view = self.SEASON_SELECT
            self.cursor = 0

            if self.view == self.EPISODE_SELECT:
                resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
                eps = show['seasons'][self.cur_season]['episodes']
                self.cursor = self._next_up_index(eps, resume)

        elif self.view == self.SEASON_SELECT:
            seasons = self.seasons_for_show(self.cur_show)
            if self.cursor < len(seasons):
                self.cur_season = seasons[self.cursor]
                self.view = self.EPISODE_SELECT
                self.cursor = 0
                resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
                eps = self.shows[self.cur_show]['seasons'][self.cur_season]['episodes']
                self.cursor = self._next_up_index(eps, resume)

        elif self.view == self.EPISODE_SELECT:
            self.play_from_cursor()

    def go_back(self):
        if self.view == self.EPISODE_SELECT:
            show = self.shows.get(self.cur_show, {})
            if show.get('has_seasons', False):
                self.view = self.SEASON_SELECT
                seasons = self.seasons_for_show(self.cur_show)
                if self.cur_season in seasons:
                    self.cursor = seasons.index(self.cur_season)
                else:
                    self.cursor = 0
            else:
                self.view = self.SHOW_LIST
                if self.cur_show in self.show_names:
                    self.cursor = self.show_names.index(self.cur_show)
                else:
                    self.cursor = 0

        elif self.view == self.SEASON_SELECT:
            self.view = self.SHOW_LIST
            if self.cur_show in self.show_names:
                self.cursor = self.show_names.index(self.cur_show)
            else:
                self.cursor = 0
        # On SHOW_LIST, left arrow does nothing — use Escape to quit

    def jump_to_channel(self, channel_num):
        items = self.current_items()

        if self.view == self.SHOW_LIST:
            if 1 <= channel_num <= len(self.show_names):
                self.cursor = channel_num - 1
                return True
            else:
                if len(self.show_names) == 0:
                    self.channel_error = "No Shows"
                elif channel_num > len(self.show_names):
                    self.channel_error = f"Ch {channel_num} Not Found"
                else:
                    self.channel_error = "Channel Not Found"
                self.channel_error_time = pygame.time.get_ticks()
                return False

        elif self.view == self.SEASON_SELECT:
            seasons = self.seasons_for_show(self.cur_show)
            if 1 <= channel_num <= len(seasons):
                self.cursor = channel_num - 1
                return True
            else:
                self.channel_error = f"Season {channel_num} Not Found"
                self.channel_error_time = pygame.time.get_ticks()
                return False

        elif self.view == self.EPISODE_SELECT:
            episodes = self.current_items()
            if 1 <= channel_num <= len(episodes):
                self.cursor = channel_num - 1
                return True
            else:
                self.channel_error = f"Episode {channel_num} Not Found"
                self.channel_error_time = pygame.time.get_ticks()
                return False

        return False

    def play_from_cursor(self):
        if not self.player_cmd and not self.player:
            self.channel_error = "NO PLAYER"
            self.channel_error_time = pygame.time.get_ticks()
            return
        show = self.shows.get(self.cur_show, {})
        season_data = show.get('seasons', {}).get(self.cur_season, {})
        episodes = season_data.get('episodes', [])
        if not episodes:
            return

        start = min(self.cursor, len(episodes) - 1)

        self.playing_show = self.cur_show
        self.playing_season = self.cur_season
        self.playing_episode = episodes[start]
        self.playing_episodes = episodes
        self.playing_index = start
        self.view = self.PLAYING

        # Show splash — channel is the episode's 1-based position on its page
        self.draw_now_playing(self.cur_show, self.cur_season, episodes[start], start + 1)

        # Start player
        self.player = EmbeddedPlayer(self.canvas_w, self.canvas_h)
        # Set player capabilities based on what's available
        ffmpeg_path = detect_ffmpeg()
        ffplay_path = detect_ffplay()
        omx_cmd = detect_omxplayer() if is_pi() else None

        if ffmpeg_path and _np_frombuffer is not None:
            self.player.ffmpeg_path = ffmpeg_path
            self.player.ffplay_path = ffplay_path
            self.embedded_player = True
        elif omx_cmd:
            self.player.use_omx = True
            self.player.omx_cmd = omx_cmd
            self.embedded_player = True
        else:
            self.embedded_player = False

        resume_secs = None  # Could add resume-from-position later

        if not self.player.start(episodes[start]['path'], resume_pos=resume_secs):
            self.player = None
            self.channel_error = "PLAY FAILED"
            self.channel_error_time = pygame.time.get_ticks()
            self.view = self.EPISODE_SELECT
            return

        self.progress_overlay_timer = 0
        self.volume_overlay_timer = 0

    def _next_up_index(self, episodes, resume):
        """Index of the first not-yet-completed episode (or the last one)."""
        for i, e in enumerate(episodes):
            if e['number'] > resume:
                return i
        return max(0, len(episodes) - 1)

    def _mark_completed(self):
        """Record that the currently-playing episode finished.
        Drives both resume position and the 'watched' marks."""
        ep = self.playing_episode
        if ep is None:
            return
        prev = get_resume_ep(self.state, self.playing_show, self.playing_season)
        set_resume_ep(self.state, self.playing_show, self.playing_season,
                      max(prev, ep['number']))

    def stop_playback(self):
        """Stop playback and return to episode list. No autoplay."""
        if self.player:
            self.player.stop()
            self.player = None

        # Reload state and land on the next-up (first uncompleted) episode.
        self.state = load_state()
        resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
        episodes = (self.shows.get(self.cur_show, {})
                    .get('seasons', {}).get(self.cur_season, {})
                    .get('episodes', []))
        if episodes:
            self.cursor = self._next_up_index(episodes, resume)

        self.view = self.EPISODE_SELECT

    # ─── Main loop ─────────────────────────────────────────────────────────

    def run(self):
        # Show controls splash on startup
        self.draw_splash()

        while self.running:
            # ═══════════════════════════════════════════════════════════════════
            # PLAYBACK MODE: embedded video rendering
            # ═══════════════════════════════════════════════════════════════════
            if self.view == self.PLAYING:
                # Check if video finished naturally (no autoplay).
                # Mark the episode completed only when it actually ends.
                if self.player and self.player.is_finished():
                    self._mark_completed()
                    self.stop_playback()
                    continue

                # Process keyboard events — ONLY playback controls here
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.stop_playback()
                        self.running = False
                        break
                    elif event.type == pygame.KEYDOWN:
                        km = self.keymap

                        if event.key == km.get("back", pygame.K_ESCAPE):
                            # Stop playback and return to episode list
                            self.stop_playback()
                            break

                        elif event.key == km.get("up", pygame.K_UP):
                            if self.player:
                                self.player.adjust_volume(10)
                                self.volume_overlay_timer = pygame.time.get_ticks()

                        elif event.key == km.get("down", pygame.K_DOWN):
                            if self.player:
                                self.player.adjust_volume(-10)
                                self.volume_overlay_timer = pygame.time.get_ticks()

                        elif event.key == km.get("right", pygame.K_RIGHT):
                            if self.player:
                                self.player.seek(PROGRESS_SEEK_S)
                                self.progress_overlay_timer = pygame.time.get_ticks()

                        elif event.key == km.get("left", pygame.K_LEFT):
                            if self.player:
                                self.player.seek(-PROGRESS_SEEK_S)
                                self.progress_overlay_timer = pygame.time.get_ticks()

                        elif event.key == pygame.K_SPACE or event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            if self.player:
                                self.player.pause()
                                if self.player.paused:
                                    self.progress_overlay_timer = pygame.time.get_ticks()

                # Update time position for progress bar
                if self.player and self.player.is_playing():
                    self.player.update_time()

                # Render: video frame + overlays
                self.draw_playback()
                self.present()
                self.clock.tick(30)
                continue

            # ═══════════════════════════════════════════════════════════════════
            # BROWSING MODE: menu navigation
            # ═══════════════════════════════════════════════════════════════════

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

                elif event.type == pygame.KEYDOWN:
                    # Key capture mode
                    if self.view == self.KEY_CAPTURE:
                        if event.key == pygame.K_ESCAPE:
                            # Cancel capture without rebinding
                            self.view = self.KEY_CONFIG
                            continue
                        if event.key == pygame.K_TAB:
                            continue
                        action_id = KEY_ACTIONS[self.config_cursor][0]
                        self.keymap[action_id] = event.key
                        self.state["keymap"] = {k: v for k, v in self.keymap.items()}
                        save_state(self.state)
                        self.view = self.KEY_CONFIG
                        continue

                    # Key config screen
                    elif self.view == self.KEY_CONFIG:
                        if event.key == pygame.K_ESCAPE:
                            self.exit_key_config()
                        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            self.view = self.KEY_CAPTURE
                        elif event.key == pygame.K_UP:
                            self.config_cursor = (self.config_cursor - 1) % len(KEY_ACTIONS)
                        elif event.key == pygame.K_DOWN:
                            self.config_cursor = (self.config_cursor + 1) % len(KEY_ACTIONS)
                        elif event.key == pygame.K_TAB:
                            self.reset_keymap()
                        continue

                    # Confirm exit screen
                    elif self.view == self.CONFIRM_EXIT:
                        if event.key == pygame.K_ESCAPE:
                            self.view = self.SHOW_LIST
                        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            self.running = False
                        continue

                    # Channel number input
                    if pygame.K_0 <= event.key <= pygame.K_9 or pygame.K_KP0 <= event.key <= pygame.K_KP9:
                        if pygame.K_0 <= event.key <= pygame.K_9:
                            digit = event.key - pygame.K_0
                        else:
                            digit = event.key - pygame.K_KP0

                        # Cancel any pending auto-select
                        self.channel_pending = 0
                        self.channel_pending_time = 0

                        self.channel_digits += str(digit)
                        self.channel_timer = pygame.time.get_ticks()
                        continue

                    if self.channel_digits:
                        self.channel_digits = ""
                        self.channel_timer = 0

                    # Cancel pending auto-select on any other key
                    self.channel_pending = 0
                    self.channel_pending_time = 0

                    # Normal navigation
                    km = self.keymap
                    if event.key == pygame.K_TAB:
                        self.enter_key_config()
                        continue

                    if event.key == pygame.K_h:
                        # Re-open the controls / help splash on demand
                        self.draw_splash()
                        continue

                    if event.key == km.get("up", pygame.K_UP):
                        self.move_cursor(-1)
                    elif event.key == km.get("down", pygame.K_DOWN):
                        self.move_cursor(1)
                    elif event.key == km.get("select", pygame.K_RETURN) or event.key == km.get("right", pygame.K_RIGHT):
                        self.select()
                    elif event.key == km.get("left", pygame.K_LEFT):
                        self.go_back()
                    elif event.key == km.get("back", pygame.K_ESCAPE):
                        if self.view == self.SHOW_LIST:
                            self.view = self.CONFIRM_EXIT
                        else:
                            self.go_back()
                    elif event.key == pygame.K_q:
                        self.running = False

            # Channel timeout — first highlight, then auto-select after delay
            if self.channel_digits and self.channel_timer > 0:
                now = pygame.time.get_ticks()
                if now - self.channel_timer >= CHANNEL_TIMEOUT_MS:
                    channel = int(self.channel_digits) if self.channel_digits else 0
                    if channel > 0:
                        success = self.jump_to_channel(channel)
                        if success:
                            self.channel_flash = self.channel_digits
                            self.channel_flash_time = now
                            # Start pending auto-select timer
                            self.channel_pending = channel
                            self.channel_pending_time = now
                    self.channel_digits = ""
                    self.channel_timer = 0

            # Pending auto-select: after brief highlight, actually enter
            if self.channel_pending > 0 and self.channel_pending_time > 0:
                now = pygame.time.get_ticks()
                if now - self.channel_pending_time >= CHANNEL_PENDING_MS:
                    self.select()
                    self.channel_pending = 0
                    self.channel_pending_time = 0

            if self.view == self.CONFIRM_EXIT:
                self.draw_confirm_exit()
                self.present()
            elif self.view in (self.KEY_CONFIG, self.KEY_CAPTURE):
                self.draw_key_config(capturing=(self.view == self.KEY_CAPTURE))
            else:
                self.draw()
                self.present()
            self.clock.tick(30)

        # Clean up any active player
        if self.player:
            self.player.stop()
        pygame.quit()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TV Time Capsule")
    parser.add_argument("--media-dir", default=None,
                        help="Override media directory (bypasses config file)")
    parser.add_argument("--force-43", action="store_true",
                        help="Force 4:3 aspect ratio (standard definition TV)")
    parser.add_argument("--scanlines", action="store_true",
                        help="Enable CRT scanline overlay effect")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    # Determine media paths: CLI flag > config file > default
    if args.media_dir:
        media_paths = [args.media_dir]
    else:
        save_default_config()
        cfg = load_config()
        media_paths = cfg["media_paths"]

    if args.test:
        # In test mode, always include the bundled media dir
        bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
        if bundled not in media_paths:
            media_paths = [bundled] + media_paths

    shows = discover_shows(media_paths)
    if not shows:
        print(f"No shows found in: {', '.join(media_paths)}")
        print(f"Expected: <media-dir>/Show Name/s01/s01e01.mp4")
        print(f"Configure paths in: {CONFIG_FILE}")
    else:
        total_eps = sum(
            len(season['episodes'])
            for show in shows.values()
            for season in show['seasons'].values()
        )
        print(f"Found {len(shows)} show(s), {total_eps} total episode(s)")
        for name, show in shows.items():
            for s_num, s_data in sorted(show['seasons'].items()):
                n = len(s_data['episodes'])
                thumb = "[ok]" if s_data.get('thumbnail') else " [ ]"
                print(f"  {name} -- S-{s_num:02d}: {n} episode(s) {thumb}")

    if not args.test and not shows:
        sys.exit(1)

    app = TVTimeCapsule(media_paths, force_43=args.force_43, test_mode=args.test, scanlines=args.scanlines)

    if not app.player_cmd and not app.player:
        # Check for required tools
        ffmpeg = detect_ffmpeg()
        if not ffmpeg:
            print("\nWARNING: ffmpeg not found. Video playback requires ffmpeg.")
            print("  Install: brew install ffmpeg  (macOS)")
            print("           sudo apt install ffmpeg  (Linux/Pi)")
        if _np_frombuffer is None:
            print("\nWARNING: numpy not found. Embedded video requires numpy.")
            print("  Install: pip install numpy")

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()