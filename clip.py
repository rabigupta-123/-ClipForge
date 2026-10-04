"""
clip.py - "paste a YouTube link -> auto-clip the best 1 minute".
Strategy:
  1. Download best <=1080p stream with yt-dlp (free, no API key).
  2. Find the best 60s window:
       a. Try YouTube's "most replayed" heatmap scraped from the watch page.
       b. Fall back to local audio-energy analysis (ffmpeg ebur128) which always works.
  3. Cut + (optionally) burn captions, output 1080p mp4.
"""
import os
import re
import json
import urllib.request
import subprocess

import config
import media_utils as mu


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def download_youtube(url, workdir, cb=None):
    """Download best <=1080p mp4. Returns path to the merged file."""
    if cb: cb("download", 2, "Starting YouTube download (yt-dlp)...")
    out_tpl = os.path.join(workdir, "source.%(ext)s")
    cmd = [
        config.YT_DLP,
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--restrict-filenames",
        "--no-warnings",
        "-o", out_tpl,
        url,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=1800)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "ignore")[-800:]
        raise RuntimeError(f"yt-dlp failed: {err}")
    # find resulting file
    for f in os.listdir(workdir):
        if f.startswith("source.") and f.endswith(".mp4"):
            if cb: cb("download", 30, "Download complete.")
            return os.path.join(workdir, f)
    raise RuntimeError("yt-dlp finished but no mp4 was produced.")


def video_id_from_url(url):
    m = re.search(r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Most-replayed heatmap (no API key)
# --------------------------------------------------------------------------- #
def fetch_heatmap(video_id):
    """
    Return list of (time_fraction_0_1, intensity_0_1) or None.
    Scrapes the public watch page - the 'mostReplayedPlayerBarRenderer' block.
    """
    if not video_id:
        return None
    try:
        url = f"https://www.youtube.com/watch?v={video_id}&bpctr=9999"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/124.0 Safari/537.36"}
        )
        html = urllib.request.urlopen(req, timeout=config.EXT_TIMEOUT).read().decode(
            "utf-8", "ignore")
    except Exception:
        return None

    def _search(obj, key):
        """Recursively find first value for `key` in nested dict/list."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == key:
                    return v
                r = _search(v, key)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for it in obj:
                r = _search(it, key)
                if r is not None:
                    return r
        return None

    # 1) heatmapData: list of {timePercentage, intensity}
    data = _extract_json(html, "ytInitialPlayerResponse") or _extract_json(html, "ytInitialData")
    if data:
        hm = _search(data, "heatmapData")
        if isinstance(hm, list) and hm:
            pts = []
            for e in hm:
                try:
                    pts.append((float(e["timePercentage"]) / 100.0,
                                float(e.get("intensity", 0))))
                except Exception:
                    continue
            if len(pts) > 4:
                return pts
        # 2) flat heatmap array of floats
        hm2 = _search(data, "heatmap")
        if isinstance(hm2, list) and len(hm2) > 4 and all(
                isinstance(x, (int, float)) for x in hm2):
            n = len(hm2)
            return [(i / (n - 1), float(v)) for i, v in enumerate(hm2)]
    return None


def _extract_json(html, var_name):
    """Extract the top-level JSON object assigned to `var_name = {...}` in the
    page HTML. Uses a string-aware brace matcher so nested braces / braces inside
    string literals don't break the parse."""
    idx = html.find(var_name + " =")
    if idx == -1:
        idx = html.find(var_name + "=")
    if idx == -1:
        return None
    start = html.find("{", idx)
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    i = start
    n = len(html)
    while i < n:
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:i + 1])
                    except Exception:
                        return None
        i += 1
    return None


def window_from_heatmap(heatmap, duration, window=60):
    """Pick the 60s window around the highest-intensity region of the heatmap."""
    # sample heatmap to a time->intensity curve
    pts = sorted(heatmap, key=lambda x: x[0])
    # treat time_fraction * duration as the x axis
    curve = [(tf * duration, inten) for tf, inten in pts]
    if not curve:
        return 0.0, min(window, duration)
    # find peak, then expand to `window` centered, clamped to [0, duration]
    peak_t = max(curve, key=lambda x: x[1])[0]
    start = max(0.0, peak_t - window / 2)
    end = min(duration, start + window)
    if end - start < window and duration > window:
        start = max(0.0, duration - window)
        end = duration
    return float(start), float(end)


# --------------------------------------------------------------------------- #
# Best window orchestration
# --------------------------------------------------------------------------- #
def find_best_window(url, path, duration, prefer_heatmap=True, cb=None):
    if prefer_heatmap:
        vid = video_id_from_url(url)
        hm = fetch_heatmap(vid)
        if hm:
            if cb: cb("analyze", 45, "Found YouTube 'most replayed' heatmap.")
            return window_from_heatmap(hm, duration)
    if cb: cb("analyze", 45, "Analyzing audio energy for the most engaging moments...")
    series = mu.audio_energy_windows(path)
    return mu.best_window_from_series(series, duration, window=config.MAX_CLIP_SECONDS)


# --------------------------------------------------------------------------- #
# Captions
# --------------------------------------------------------------------------- #
def build_clip_captions(caption, duration):
    """Return (srt_text, srt_path) for a clip-wide caption, or (None, None)."""
    mode = caption.get("mode", "none")
    if mode == "none":
        return None, None
    if mode == "custom":
        text = (caption.get("text") or "").strip()
        if not text:
            return None, None
        # split into readable lines
        lines = re.findall(r".{1,42}(?:\s+|$)", text.replace("\n", " "))
        srt = mu.build_srt([(0, duration, "\n".join(lines))])
        return srt, "clip_caption.srt"
    # 'auto' -> whisper path handled by caller if available
    return None, None


def transcribe_auto(path, cb=None):
    """Optional: local Whisper transcription (free but heavy). Returns SRT or None."""
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None
    if cb: cb("caption", 60, "Transcribing audio with local Whisper (slow on free tier)...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(path, beam_size=4)
    cues = [(s.start, s.end, s.text.strip()) for s in segs]
    return mu.build_srt(cues)


# --------------------------------------------------------------------------- #
# Main entry
# --------------------------------------------------------------------------- #
def clip_youtube(url, out_path, caption=None, cb=None):
    """
    url: YouTube link
    out_path: final mp4 path to write
    caption: dict {mode:'none'|'custom'|'auto', text, size, color, position}
    cb(stage, percent, message)
    """
    caption = caption or {"mode": "none"}
    work = os.path.dirname(out_path)
    src = download_youtube(url, work, cb)
    duration = mu.probe_duration(src)
    if duration <= 0:
        duration = config.MAX_CLIP_SECONDS

    start, end = find_best_window(url, src, duration,
                                  prefer_heatmap=True, cb=cb)
    clip_dur = end - start
    if cb: cb("cut", 70, f"Cutting best moment: {start:.0f}s - {end:.0f}s.")

    # captions
    srt_text, srt_name = build_clip_captions(caption, clip_dur)
    if caption.get("mode") == "auto":
        srt_text = transcribe_auto(src, cb)
        srt_name = "clip_caption.srt" if srt_text else None

    vf = []
    if srt_text and srt_name:
        srt_path = os.path.join(work, srt_name)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_text)
        vf.append(mu.subtitles_filter(srt_path, caption))
        if cb: cb("caption", 85, "Burning captions into the clip...")

    cmd = [config.FFMPEG, "-y", "-ss", f"{start:.3f}", "-i", src, "-t",
           f"{clip_dur:.3f}"]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-c:v", "libx264", "-preset", config.PRESET, "-crf",
            str(config.DEFAULT_CRF), "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-b:a", "192k", "-movflags", "+faststart", out_path]
    mu.run(cmd, timeout=1800)
    mu.cleanup_workdir(work, keep=[out_path])
    if cb: cb("done", 100, "Clip ready!")
    return out_path
