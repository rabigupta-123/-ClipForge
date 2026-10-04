# 🎬 ClipForge — Free YouTube Clipper + Text-to-Video

A **100% free** web app that:

1. **YouTube Clipper** — paste a YouTube link → it automatically finds the *best
   moment* (YouTube "most replayed" heatmap, with a local audio-energy fallback)
   and cuts a **1-minute (max) HD clip**.
2. **Text-to-Video** — type a script → generates an **HD (1080p) video up to 1
   minute** using free AI images + voice (Pollinations). Two modes:
   - 🖼️ **AI Image Story** — each sentence becomes an AI-generated image + narration.
   - 🔤 **Text Cards** — each sentence becomes an animated text card.
3. **Captions** — add styled, burned-in subtitles (auto from content, custom text,
   or none) with adjustable size, color, and position.

No API keys, no cost. The only external services used are **YouTube** and
**Pollinations** (both free, no signup). Video processing is done locally with
**ffmpeg** + **yt-dlp**.

---

## How it works

```
Browser ──POST /api/clip or /api/ttv──▶  Python server (stdlib http.server)
                                              │
                              background worker thread
                                  ├─ yt-dlp        (download YouTube)
                                  ├─ ffmpeg        (cut / assemble / burn captions)
                                  └─ Pollinations  (free AI images + TTS)
                                              │
                              GET /api/status/<id>  (poll progress)
                              GET /api/file/<id>    (stream result)
```

Jobs run on a background worker so HTTP requests never time out (important on
free hosting where requests are capped at ~100s).

**Best-moment detection**
- Tries YouTube's `mostReplayedPlayerBarRenderer` heatmap scraped from the watch
  page (no API key).
- Falls back to a local **ebur128 loudness analysis** (ffmpeg) to pick the
  60-second window with the highest engagement — always works, even if the
  heatmap is missing.

---

## Run locally

Requires **Python 3.11+**, **ffmpeg**, **ffprobe**, and **yt-dlp**.

```bash
# Debian / Ubuntu
sudo apt-get update && sudo apt-get install -y ffmpeg yt-dlp

# macOS (brew)
brew install ffmpeg yt-dlp

# then:
cd clipforge
pip install -r requirements.txt
python server.py
# open http://localhost:8000
```

> The web server uses **only the Python standard library** (no Flask), so there
> are no web-framework dependencies to install.

---

## Deploy free to the cloud

### Option A — Render (recommended, free tier)
1. Push this folder to a **GitHub** repo.
2. In Render: **New + → Web Service → connect the repo**.
3. Render auto-detects `render.yaml` (Docker). Free plan, `0.0.0.0:PORT`.
4. Done — your site goes live on a `*.onrender.com` URL.

### Option B — Railway (free tier)
1. Push to GitHub, then **New Project → Deploy from GitHub**.
2. Railway uses `railway.json` + the `Dockerfile`.
3. Live URL provided by Railway.

> **Free-tier caveat:** the instance sleeps after inactivity and has limited CPU.
> The first request after sleep may take a while (cold start + a long video job).
> Keep clips reasonable and you're fine for personal use.

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/clip` | `{url, duration, caption:{mode,text,size,color,position}}` |
| POST | `/api/ttv`  | `{script, mode, duration, voice, music, caption}` |
| GET  | `/api/status/<id>` | job progress / result |
| GET  | `/api/file/<id>` | stream the finished mp4 |

`caption.mode` ∈ `auto | custom | none`. `ttv.mode` ∈ `image_story | text_cards`.
`duration` ≤ 60s for both.

---

## Project layout

```
clipforge/
├── server.py          # stdlib web server + job queue/worker
├── clip.py            # YouTube download + best-moment + cut
├── ttv.py             # text-to-video (image story + text cards)
├── media_utils.py     # ffmpeg/ffprobe wrappers, captions, best-window
├── config.py          # paths & limits
├── templates/index.html
├── static/style.css, static/app.js
├── requirements.txt   # yt-dlp (stdlib only otherwise)
├── Dockerfile         # python + ffmpeg + fonts
├── render.yaml        # Render free deploy
├── railway.json       # Railway deploy
└── README.md
```

---

## Notes & limits (being honest about "free")

- **YouTube ToS**: downloading/redistributing videos may violate YouTube's Terms
  of Service. This tool is intended for personal/clipped/fair-use content.
- **Pollinations** is free but rate-limited; on heavy load image/voice steps may
  retry or fall back to a placeholder image / silent audio.
- **Whisper auto-captions** for clips are optional (uncomment `faster-whisper` in
  `requirements.txt`) — they're slow and memory-hungry on free tiers.
- Everything runs on **your** deployed instance; no data leaves except the
  YouTube fetch and the free AI calls.
