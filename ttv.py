"""
ttv.py - "text to video" up to 1 minute, HD, with captions. Two modes:
  * image_story : each sentence becomes an AI-generated image + voice narration.
  * text_cards  : each sentence becomes an animated text card (burned caption on
                  a moving gradient background).
Both burn styled captions and layer a soft, generated ambient music track.
All AI is from Pollinations (free, no API key). Music is synthesized with ffmpeg
so no asset files are required.
"""
import os
import re
import math
import random
import urllib.request
import urllib.parse

import config
import media_utils as mu


def _split_groups(script, target):
    sents = re.split(r"(?<=[.!?])\s+|\n+", (script or "").strip())
    sents = [s.strip() for s in sents if s.strip()]
    if not sents:
        sents = ["Your video"]
    n = max(3, min(12, round(target / 5)))
    per = max(1, math.ceil(len(sents) / n))
    groups = [" ".join(sents[i:i + per]) for i in range(0, len(sents), per)]
    seg = target / len(groups)
    return groups, seg


def _pollinations_image(prompt, out_path, seed=None):
    """Download an AI image from Pollinations. Falls back to a solid color on error."""
    seed = seed if seed is not None else random.randint(1, 10**9)
    q = urllib.parse.quote(prompt[:900])
    url = (f"{config.POLLINATIONS_IMAGE}{q}?width=1920&height=1080"
           f"&nologo=true&model=flux&seed={seed}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=config.EXT_TIMEOUT).read()
        if data[:3] in (b"\xff\xd8\xff",):  # JPEG magic
            with open(out_path, "wb") as f:
                f.write(data)
            return True
    except Exception:
        pass
    # fallback: generate a placeholder image with ffmpeg
    mu.run([config.FFMPEG, "-y", "-f", "lavfi", "-i",
            f"color=c=0x223366:s=1920x1080", "-frames:v", "1", out_path],
           timeout=60)
    return False


def _pollinations_tts(text, voice, out_path):
    """Download TTS audio from Pollinations. Returns True on success."""
    q = urllib.parse.quote(text[:1000])
    url = (f"{config.POLLINATIONS_TTS}{q}?model=openai-audio&voice={voice}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=config.EXT_TIMEOUT).read()
        if len(data) > 100:
            with open(out_path, "wb") as f:
                f.write(data)
            return True
    except Exception:
        pass
    # fallback: silent audio of ~seg length is filled later by caller
    return False


def _render_segment(image_path, bg_color, audio_path, duration, srt_path,
                    caption, out_path, w=1920, h=1080):
    """Render one segment clip (image or colored card) with optional caption+audio."""
    vf_parts = []
    if image_path and os.path.exists(image_path):
        # input is the looping image; scale/crop/zoom it
        vf_parts.append(
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},zoompan=z='min(zoom+0.0006,1.12)':d=1:s={w}x{h}:fps=30,"
            f"format=yuv420p,setsar=1")
    else:
        # input is already a color source (see below); just normalize
        vf_parts.append("format=yuv420p,setsar=1")
    if srt_path and os.path.exists(srt_path):
        vf_parts.append(mu.subtitles_filter(srt_path, caption))
    vf = ",".join(vf_parts)

    cmd = [config.FFMPEG, "-y"]
    if image_path and os.path.exists(image_path):
        cmd += ["-loop", "1", "-i", image_path]
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c={bg_color}:s={w}x{h}:d={duration}"]
    if audio_path and os.path.exists(audio_path):
        cmd += ["-i", audio_path]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
    cmd += ["-t", f"{duration:.3f}", "-vf", vf, "-r", "30",
            "-c:v", "libx264", "-preset", config.PRESET, "-crf",
            str(config.DEFAULT_CRF), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-shortest", out_path]
    mu.run(cmd, timeout=300)
    return out_path


def ttv_generate(script, out_path, opts=None, cb=None):
    """
    opts: dict with keys:
      mode: 'image_story' | 'text_cards'
      duration: seconds (<=60)
      voice: one of config.VOICES
      music: bool
      caption: dict {mode:'auto'|'custom'|'none', text, size, color, position}
    """
    opts = opts or {}
    mode = opts.get("mode", "image_story")
    duration = min(config.MAX_TTV_SECONDS, max(5, int(opts.get("duration", 60))))
    voice = opts.get("voice", "alloy")
    use_music = bool(opts.get("music", True))
    caption = opts.get("caption", {"mode": "auto"})
    cap_mode = caption.get("mode", "auto")

    work = os.path.dirname(out_path)
    groups, seg = _split_groups(script, duration)
    n = len(groups)
    if cb: cb("plan", 5, f"Planning {n} segments ({mode}).")

    seg_paths = []
    bg_colors = ["0x10101a", "0x1a1030", "0x07212e", "0x2a0f1a", "0x102418"]
    for i, text in enumerate(groups):
        if cb: cb("generate", 10 + int(70 * i / n),
                  f"Generating segment {i+1}/{n}...")
        srt_path = os.path.join(work, f"seg{i}.srt")
        img_path = os.path.join(work, f"img{i}.png")
        aud_path = os.path.join(work, f"aud{i}.mp3")
        seg_out = os.path.join(work, f"seg{i}.mp4")

        # captions for this segment
        if cap_mode == "none":
            srt_path = None
        elif cap_mode == "custom" and caption.get("text"):
            # show the same custom caption on every segment
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(mu.build_srt([(0, seg, caption["text"])]))
        else:  # auto
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(mu.build_srt([(0, seg, text)]))

        audio_ok = False
        if mode == "image_story":
            _pollinations_image(text, img_path, seed=random.randint(1, 10**9))
            audio_ok = _pollinations_tts(text, voice, aud_path)
            _render_segment(img_path, bg_colors[i % len(bg_colors)],
                            aud_path if audio_ok else None, seg, srt_path,
                            caption, seg_out)
        else:  # text_cards
            audio_ok = _pollinations_tts(text, voice, aud_path)
            _render_segment(None, bg_colors[i % len(bg_colors)],
                            aud_path if audio_ok else None, seg, srt_path,
                            caption, seg_out)
        seg_paths.append(seg_out)

    if cb: cb("assemble", 85, "Concatenating segments...")
    raw = out_path + ".raw.mp4"
    mu.concat_videos(seg_paths, raw, resolution=config.DEFAULT_RES)

    if use_music:
        if cb: cb("music", 92, "Adding ambient music...")
        music = os.path.join(work, "music.m4a")
        mu.generate_ambient_music(music, duration + 1)
        mu.add_audio(raw, music, out_path, music=music, music_vol=0.12)
        os.remove(music)
    else:
        os.replace(raw, out_path)

    mu.cleanup_workdir(work, keep=[out_path])
    if cb: cb("done", 100, "Video ready!")
    return out_path
