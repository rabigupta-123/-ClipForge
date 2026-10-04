"""
ClipForge - global configuration.
All paths are resolved relative to this file so the app runs from anywhere.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(BASE_DIR, "jobs")
TMP_DIR = os.path.join(BASE_DIR, "tmp")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

for _d in (JOBS_DIR, TMP_DIR, STATIC_DIR, TEMPLATES_DIR):
    os.makedirs(_d, exist_ok=True)

# Binary locations. On Render (Docker) these are /usr/bin/*.
# Override with env vars if needed.
FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")
YT_DLP = os.environ.get("YTDLP_BIN", "yt-dlp")

# Limits (free tier friendly)
MAX_CLIP_SECONDS = 60
MAX_TTV_SECONDS = 60
DEFAULT_RES = "1920x1080"
DEFAULT_CRF = 21          # lower = better quality (slower). 21 is a good HD default.
PRESET = "veryfast"       # speed/quality tradeoff for free compute

# Caption defaults
CAPTION_DEFAULTS = {
    "size": 28,            # font size in px (relative to 1080p canvas)
    "color": "white",
    "position": "bottom",  # bottom | top | center
    "bold": 1,
    "outline": 2,
}

# Pollinations (free, no API key required)
POLLINATIONS_IMAGE = "https://image.pollinations.ai/prompt/"
POLLINATIONS_TTS = "https://text.pollinations.ai/"

# Voices supported by Pollinations openai-audio
VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

# A generous HTTP timeout for external (free) services
EXT_TIMEOUT = 90
