"""Embedded FFmpeg / omxplayer video playback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

import pygame

try:
    import numpy as _numpy_mod

    np_frombuffer = _numpy_mod.frombuffer
    np_uint8 = _numpy_mod.uint8
except ImportError:
    np_frombuffer = None
    np_uint8 = None


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
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                filepath,
            ],
            capture_output=True,
            text=True,
            timeout=5,
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
        self.proc = None  # FFmpeg video process
        self.audio_proc = None  # ffplay audio process
        self.thread = None  # Frame-reading thread
        self.running = False  # Is playback active?
        self.finished = False  # Did the video reach the end naturally?
        self.paused = False
        self.volume = 100
        self.time_pos = 0.0
        self.duration = 0.0
        self.fps = 24.0
        self.frame_time = 1.0 / 24.0
        self.start_time = 0.0  # monotonic time when playback started
        self.pause_offset = 0.0  # accumulated pause time in seconds
        self.pause_start = 0.0  # when current pause began (monotonic)
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
            self.ffmpeg_path,
            "-i",
            filepath,
        ]
        if resume_pos and resume_pos > 0:
            cmd.extend(["-ss", str(resume_pos)])
        cmd.extend(
            [
                "-vf",
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-an",  # No audio from FFmpeg — we play audio separately
                "-loglevel",
                "quiet",
                "-",
            ]
        )

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
                self.ffplay_path,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(int(self.volume)),
            ]
            if resume_pos and resume_pos > 0:
                audio_cmd.extend(["-ss", str(resume_pos)])
            audio_cmd.append(filepath)
            try:
                self.audio_proc = subprocess.Popen(
                    audio_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                self.audio_proc = None

        self.running = True
        resume = float(resume_pos or 0)
        self.time_pos = max(0.0, resume)
        # Anchor wall-clock so progress/bookmarks include the skipped prefix.
        self.start_time = time.monotonic() - self.time_pos

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
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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

                arr = np_frombuffer(raw, dtype=np_uint8).reshape((H, W, 3))
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
        """Wait briefly for audio, then mark done.

        Do not block for the full media duration — a seek past EOF can leave
        ffplay stuck, which used to stall on "Loading..." for a long time.
        """
        if self.audio_proc:
            try:
                self.audio_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    self.audio_proc.kill()
                    self.audio_proc.wait(timeout=1)
                except Exception:
                    pass
            self.audio_proc = None
        self.finished = True
        self.running = False

    def _shutdown_decoders(self):
        """Kill ffmpeg/ffplay/frame thread without flipping ``finished``."""
        self.running = False
        self._pause_event.set()
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
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None

    def _finish_at_end(self):
        """Treat playback as complete (e.g. seek past EOF on a short clip)."""
        if self.duration > 0:
            self.time_pos = self.duration
        self._shutdown_decoders()
        self.finished = True
        self.paused = False

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
            self.ffplay_path,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "quiet",
            "-volume",
            str(int(self.volume)),
            "-ss",
            str(resume),
            self.filepath,
        ]
        try:
            self.audio_proc = subprocess.Popen(
                audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            self.audio_proc = None

    def adjust_volume(self, delta):
        """Adjust volume by delta (e.g. +10 or -10). Range: 0-100.

        Restarts the audio stream so the change takes effect immediately.
        """
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
        paused_extra = (
            (now - self.pause_start) if (self.paused and self.pause_start > 0) else 0.0
        )
        elapsed = now - self.start_time - self.pause_offset - paused_extra
        new_pos = max(0.0, elapsed + seconds)

        # Seeking to/past EOF (common on short clips with +10s seeks) must end
        # playback — restarting ffmpeg at duration yields no frames and hangs
        # on "Loading..." while the clock runs past the real length.
        end_guard = 0.35
        if self.duration > 0 and new_pos >= max(0.0, self.duration - end_guard):
            self._finish_at_end()
            return

        if self.duration > 0:
            new_pos = min(new_pos, max(0.0, self.duration - end_guard))

        filepath = self.filepath
        self._shutdown_decoders()
        # Keep the last decoded frame on screen while the new stream buffers.
        self.time_pos = new_pos

        # Restart from new position
        W, H = self.canvas_w, self.canvas_h
        frame_size = W * H * 3
        cmd = [
            self.ffmpeg_path,
            "-ss",
            str(new_pos),
            "-i",
            filepath,
            "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-an",
            "-loglevel",
            "quiet",
            "-",
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
                self.ffplay_path,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(int(self.volume)),
                "-ss",
                str(new_pos),
                filepath,
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
        self.pause_start = 0
        self.paused = False
        self._pause_event.set()

        self.thread = threading.Thread(target=self._read_frames, daemon=True)
        self.thread.start()

    def update_time(self):
        """Update time_pos based on wall clock (for progress bar)."""
        if self.paused:
            return
        elapsed = time.monotonic() - self.start_time - self.pause_offset
        self.time_pos = max(0.0, elapsed)
        if self.duration > 0:
            self.time_pos = min(self.time_pos, self.duration)
            # Wall-clock can drift past EOF after a near-end seek; finish cleanly.
            if self.running and self.time_pos >= self.duration - 0.05:
                self._finish_at_end()

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
