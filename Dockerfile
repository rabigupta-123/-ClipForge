# ClipForge - free YouTube clipper + text-to-video
# Uses Debian's ffmpeg (includes libx264 + libass) and DejaVu fonts for captions.
FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render / Railway inject PORT at runtime; the server defaults to 8000.
EXPOSE 8000
CMD ["python", "server.py"]
