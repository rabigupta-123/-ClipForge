#!/bin/bash
# Alternative build script for platforms WITHOUT Docker (e.g. Render "Native" runtime).
# Docker (render.yaml / railway.json) is the recommended path and guarantees ffmpeg + fonts.
set -e

pip install -r requirements.txt

# Ensure ffmpeg + ffprobe are present (static build, no apt needed)
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Downloading static ffmpeg..."
  curl -sL "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz" -o /tmp/ff.tar.xz
  mkdir -p /tmp/ffx && tar -xf /tmp/ff.tar.xz -C /tmp/ffx
  BIN_DIR=$(find /tmp/ffx -name ffmpeg -path '*/bin/*' | head -1 | xargs dirname)
  cp "$BIN_DIR/ffmpeg" /usr/local/bin/ffmpeg
  cp "$BIN_DIR/ffprobe" /usr/local/bin/ffprobe
  chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe
fi
ffmpeg -version | head -1
