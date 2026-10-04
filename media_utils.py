"""
media_utils.py - thin, safe wrappers around ffmpeg / ffprobe plus caption helpers.
Everything here is offline-capable (no network) so it can be unit-tested in any sandbox.
"""
import os
import re
import json
import subprocess
import math
import config

# --------------------------------------------------------------------------- #
# Low level runners
# --------------------------------------------------------------------------- #
def run(cmd, timeout=600, capture=True, check=True):
    """Run an ffmpeg/ffprobe command. cmd may be a list or string."""
    if isinstance(cmd, str):
        cmd = cmd.split()
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
    )
    out = proc.stdout.decode("utf-8", "ignore") if proc.stdout else ""
    err = proc.stderr.decode("utf-8", "ignore") if proc.stderr else ""
    if check and proc.returncode != 0:
        # ffmpeg prints errors to stderr
        snippet = "\n".join(err.strip().splitlines()[-12:])
        raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}): {snippet}")
    return out, err


def have_filter(name):
    out, _ = run([config.FFMPEG, "-filters"], capture=True, check=True)
    return name in out


def ffmpeg_has_libass():
    return have_filter("subtitles")


# --------------------------------------------------------------------------- #
# Probe
# --------------------------------------------------------------------------- #
def probe_duration(path):
    """Return duration in seconds (float) using ffprobe."""
    out, _ = run([
        config.FFPROBE, "-v", "error", "-show_entries",
        "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", path
    ], check=True)
    try:
        return float(out.strip())
    except Exception:
        return 0.0


def probe_resolution(path):
    out, _ = run([
        config.FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", path
    ], check=True)
    try:
        d = json.loads(out)
        s = d["streams"][0]
        return int(s.get("width", 0)), int(s.get("height", 0))
    except Exception:
        return 0, 0


# --------------------------------------------------------------------------- #
# Caption / subtitle helpers
# --------------------------------------------------------------------------- #
def _srt_time(t):
    """Format seconds as HH:MM:SS,mmm for SRT."""
    t = max(0.0, float(t))
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        ms = 999
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(cues):
    """
    cues: list of (start_sec, end_sec, text)
    Returns SRT string. Text newlines become SRT newlines.
    """
    blocks = []
    for i, (start, end, text) in enumerate(cues, 1):
        text = (text or "").replace("\r", "")
        blocks.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


def force_style(color="white", size=28, position="bottom", bold=1, outline=2):
    """
    Build an ffmpeg subtitles force_style string.
    Colors are converted to ASS &HBBGGRR format.
    """
    ass_color = _css_to_ass(color)
    align = {"bottom": 2, "top": 8, "center": 5}.get(position, 2)
    return (
        f"FontSize={int(size)},"
        f"FontName=DejaVu Sans,"
        f"PrimaryColour={ass_color},"
        f"OutlineColour=&H00000000,"
        f"Outline={int(outline)},"
        f"Shadow=1,"
        f"Alignment={align},"
        f"Bold={int(bold)},"
        f"MarginV=40"
    )


def _css_to_ass(color):
    """Convert common CSS color names / #rrggbb to ASS &HBBGGRR."""
    named = {
        "white": "FFFFFF", "black": "000000", "yellow": "FFFF00",
        "red": "FF0000", "green": "00FF00", "blue": "0000FF",
        "cyan": "FFFF00", "magenta": "FF00FF", "orange": "FFA500",
        "pink": "FFC0CB", "lime": "00FF00",
    }
    c = color.strip().lower()
    if c in named:
        hexv = named[c]
    elif c.startswith("#"):
        hexv = c[1:]
        if len(hexv) == 3:
            hexv = "".join(ch * 2 for ch in hexv)
    else:
        hexv = "FFFFFF"
    hexv = hexv.ljust(6, "0")[:6]
    r, g, b = hexv[0:2], hexv[2:4], hexv[4:6]
    # ASS expects &HBBGGRR
    return f"&H{b}{g}{r}"


def subtitles_filter(srt_path, caption):
    """
    Return an ffmpeg video filter string that burns `srt_path` with styling.
    caption: dict with size/color/position/bold/outline.
    """
    fs = force_style(
        color=caption.get("color", "white"),
        size=caption.get("size", 28),
        position=caption.get("position", "bottom"),
        bold=caption.get("bold", 1),
        outline=caption.get("outline", 2),
    )
    # escape ':' and '\' in the path for the filtergraph
    p = srt_path.replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{p}':force_style='{fs}'"


# --------------------------------------------------------------------------- #
# Synthetic helpers (offline test support + text-card backgrounds)
# --------------------------------------------------------------------------- #
def make_color_clip(path, duration, w=1920, h=1080, color="0x10101a",
                    motion=True):
    """Create a solid-color (optionally slowly zooming) video clip, no audio."""
    vf = f"color=c={color}:s={w}x{h}:d={duration}"
    if motion:
        # subtle zoom to feel less static
        vf += f",zoompan=z='min(zoom+0.0008,1.12)':d=1:s={w}x{h}:fps=30"
    vf += f",format=yuv420p,setsar=1"
    run([
        config.FFMPEG, "-f", "lavfi", "-i", vf, "-t", str(duration),
        "-r", "30", "-pix_fmt", "yuv420p", "-an", path
    ], timeout=120)
    return path


def make_silence(path, duration, sr=44100):
    run([
        config.FFMPEG, "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=mono",
        "-t", str(duration), path
    ], timeout=120)
    return path


# --------------------------------------------------------------------------- #
# Best-moment detection
# --------------------------------------------------------------------------- #
def audio_energy_windows(path, step=1.0):
    """
    Single-pass loudness time-series via ffmpeg ebur128.
    Returns list of (time_sec, momentary_loudness).
    """
    out, err = run([
        config.FFMPEG, "-hide_banner", "-i", path,
        "-af", "ebur128", "-f", "null", "-"
    ], capture=True, check=True)
    text = err  # ebur128 logs to stderr
    series = []
    # Lines look like:  [Parsed_ebur128_0 @ ...] t: 1.0  T: 1.0  M: -23.0 S: -30.0 I: -23.0 LRA: 2.0
    for line in text.splitlines():
        # ebur128 logs like:  t: 0.400  TARGET:-23 LUFS    M:-29.4 S:-120.7 ...
        m = re.search(r"t:\s*([\d.]+).*?M:\s*(-?[\d.]+)", line)
        if m:
            t = float(m.group(1))
            loud = float(m.group(2))
            # clamp silence to a low floor so it doesn't out-rank real audio
            # when averaging windows (loudness is in dB, so louder = higher value)
            v = max(loud, -100.0)
            series.append((t, v))
    return series


def best_window_from_series(series, total, window=60, step=None):
    """
    Given a (time, loudness) series, return the (start, end) 60s window
    with the highest smoothed average loudness. Pads at edges.
    """
    if not series:
        return 0.0, min(window, total)
    if step is None:
        # derive step from data
        step = max(0.1, series[1][0] - series[0][0]) if len(series) > 1 else 1.0
    # build dense array
    n = int(total / step) + 1
    arr = [-1000.0] * n  # floor so negative loudness values aren't clobbered by 0.0
    for t, v in series:
        idx = min(n - 1, int(t / step))
        arr[idx] = max(arr[idx], v)
    # also fill gaps via nearest
    w = max(1, int(window / step))
    best_sum, best_i = -1e18, 0
    for i in range(0, max(1, n - w + 1)):
        s = sum(arr[i:i + w]) / w
        if s > best_sum:
            best_sum, best_i = s, i
    start = best_i * step
    end = min(total, start + window)
    # avoid starting in the last few seconds
    if end - start < window and total > window:
        start = max(0.0, total - window)
        end = total
    return float(start), float(end)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def concat_videos(inputs, out, resolution="1920x1080"):
    """Concat a list of video files (same codecs/resolution) into one."""
    w, h = resolution.split("x")
    list_path = out + ".concat.txt"
    with open(list_path, "w") as f:
        for p in inputs:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    run([
        config.FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-vsync", "cfr", "-r", "30", "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-c:v", "libx264", "-preset", config.PRESET, "-crf", str(config.DEFAULT_CRF),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", out
    ], timeout=900)
    os.remove(list_path)
    return out


def add_audio(video_in, audio_in, out, music=None, music_vol=0.12, voice_vol=1.0):
    """Mux audio (voice) into a silent video; optionally mix under music."""
    if music:
        # duck music where voice is present: simple constant mix, music low
        run([
            config.FFMPEG, "-y", "-i", video_in, "-i", audio_in, "-i", music,
            "-filter_complex",
            f"[1:a]volume={voice_vol}[v];[2:a]volume={music_vol}[m];"
            f"[v][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-shortest", out
        ], timeout=600)
    else:
        run([
            config.FFMPEG, "-y", "-i", video_in, "-i", audio_in,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-shortest", out
        ], timeout=600)
    return out


def cleanup_workdir(workdir, keep):
    """Remove every file in `workdir` except those in `keep` (to save disk on
    free tiers so future jobs don't fail with 'no space left')."""
    keep = set(os.path.abspath(k) for k in keep)
    try:
        for f in os.listdir(workdir):
            p = os.path.abspath(os.path.join(workdir, f))
            if p in keep:
                continue
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass
    except Exception:
        pass


def generate_ambient_music(out, duration, seed=0):
    """Generate a soft, royalty-free ambient drone with ffmpeg only (no assets)."""
    # two detuned low sines + gentle lowpass + slow tremolo -> calm pad
    run([
        config.FFMPEG, "-y", "-f", "lavfi", "-i",
        f"sine=frequency=110:duration={duration}:sample_rate=44100",
        "-f", "lavfi", "-i",
        f"sine=frequency=164.81:duration={duration}:sample_rate=44100",
        "-f", "lavfi", "-i",
        f"sine=frequency=220:duration={duration}:sample_rate=44100",
        "-filter_complex",
        "[0:a][1:a][2:a]amix=inputs=3:duration=longest[a];"
        "[a]lowpass=frequency=900,volume=0.5,tremolo=f=0.15:d=0.6[aout]",
        "-map", "[aout]", "-t", str(duration), "-c:a", "aac", "-b:a", "128k", out
    ], timeout=300)
    return out
