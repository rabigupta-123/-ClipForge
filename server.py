"""
server.py - ClipForge web server (Python standard library only -> zero pip deps).
Serves the UI, exposes a small JSON API, and runs long video jobs on a
background worker thread so HTTP requests never time out (important on free hosts).
"""
import os
import re
import json
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import config
import clip
import ttv

JOBS = {}                       # job_id -> dict
QUEUE = __import__("queue").Queue()
LOCK = threading.Lock()

# --------------------------------------------------------------------------- #
# Job worker
# --------------------------------------------------------------------------- #
def _progress(job, stage, pct, msg):
    with LOCK:
        job["stage"] = stage
        job["progress"] = pct
        job["message"] = msg
        job["status"] = "processing"


def worker():
    while True:
        job_id = QUEUE.get()
        try:
            with LOCK:
                job = JOBS[job_id]
            cb = lambda s, p, m: _progress(job, s, p, m)
            if job["type"] == "clip":
                out = os.path.join(job["workdir"], "clip.mp4")
                clip.clip_youtube(job["url"], out, caption=job["caption"], cb=cb)
                with LOCK:
                    job["result"] = out
                    job["status"] = "done"
                    job["progress"] = 100
                    job["message"] = "Clip ready!"
            elif job["type"] == "ttv":
                out = os.path.join(job["workdir"], "video.mp4")
                ttv.ttv_generate(job["script"], out, opts=job["opts"], cb=cb)
                with LOCK:
                    job["result"] = out
                    job["status"] = "done"
                    job["progress"] = 100
                    job["message"] = "Video ready!"
        except Exception as e:  # surface errors to the user
            with LOCK:
                job["status"] = "error"
                job["error"] = str(e)[:500]
                job["message"] = "Failed: " + str(e)[:200]
        finally:
            QUEUE.task_done()


threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _read_body(handler, max_bytes=200_000):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length > max_bytes:
        return None
    raw = handler.rfile.read(length) if length else b""
    try:
        return json.loads(raw.decode("utf-8", "ignore") or "{}")
    except Exception:
        return None


def _send_json(handler, obj, code=200):
    body = json.dumps(obj).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".ico": "image/x-icon",
}


def _serve_static(handler, path):
    rel = os.path.normpath(path).lstrip("/")
    # rel is like "static/style.css"
    full = os.path.join(config.BASE_DIR, rel)
    if not os.path.isfile(full):
        handler.send_error(404)
        return
    ext = os.path.splitext(full)[1]
    handler.send_response(200)
    handler.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
    handler.send_header("Content-Length", str(os.path.getsize(full)))
    handler.end_headers()
    with open(full, "rb") as f:
        handler.wfile.write(f.read())


def _serve_file(handler, job_id):
    with LOCK:
        job = JOBS.get(job_id)
        result = job.get("result") if job else None
    if not result or not os.path.isfile(result):
        handler.send_error(404)
        return
    handler.send_response(200)
    handler.send_header("Content-Type", "video/mp4")
    handler.send_header("Content-Length", str(os.path.getsize(result)))
    handler.send_header("Content-Disposition",
                        f'inline; filename="clipforge_{job_id}.mp4"')
    handler.end_headers()
    with open(result, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            handler.wfile.write(chunk)


# --------------------------------------------------------------------------- #
# Request handler
# --------------------------------------------------------------------------- #
YT_RE = re.compile(r"(youtube\.com|youtu\.be)")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    def do_GET(self):
        p = urlparse(self.path)
        path = p.path
        if path in ("/", "/index.html"):
            self._send_index()
        elif path.startswith("/static/"):
            _serve_static(self, path)
        elif path == "/api/health":
            _send_json(self, {"ok": True, "ffmpeg": _ffmpeg_ok()})
        elif path.startswith("/api/status/"):
            jid = path.rsplit("/", 1)[-1]
            with LOCK:
                job = JOBS.get(jid)
                data = dict(job) if job else None
            if not data:
                _send_json(self, {"error": "not found"}, 404)
            else:
                data.pop("workdir", None)
                _send_json(self, data)
        elif path.startswith("/api/file/"):
            _serve_file(self, path.rsplit("/", 1)[-1])
        else:
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == "/api/clip":
            self._post_clip()
        elif p.path == "/api/ttv":
            self._post_ttv()
        else:
            _send_json(self, {"error": "unknown endpoint"}, 404)

    # -- handlers ---------------------------------------------------------- #
    def _send_index(self):
        with open(os.path.join(config.TEMPLATES_DIR, "index.html"), "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _post_clip(self):
        data = _read_body(self)
        if data is None:
            return _send_json(self, {"error": "invalid json"}, 400)
        url = (data.get("url") or "").strip()
        if not YT_RE.search(url):
            return _send_json(self, {"error": "Please provide a YouTube URL."}, 400)
        caption = data.get("caption") or {"mode": "none"}
        jid = uuid.uuid4().hex[:12]
        workdir = os.path.join(config.JOBS_DIR, jid)
        os.makedirs(workdir, exist_ok=True)
        with LOCK:
            JOBS[jid] = {
                "id": jid, "type": "clip", "status": "queued",
                "progress": 0, "message": "Queued...", "stage": "queue",
                "url": url, "caption": caption, "workdir": workdir,
                "result": None, "error": None,
            }
        QUEUE.put(jid)
        _send_json(self, {"job_id": jid, "status_url": f"/api/status/{jid}",
                          "file_url": f"/api/file/{jid}"})

    def _post_ttv(self):
        data = _read_body(self)
        if data is None:
            return _send_json(self, {"error": "invalid json"}, 400)
        script = (data.get("script") or "").strip()
        if len(script) < 3:
            return _send_json(self, {"error": "Please enter some text."}, 400)
        caption = data.get("caption") or {"mode": "auto"}
        opts = {
            "mode": data.get("mode", "image_story"),
            "duration": min(config.MAX_TTV_SECONDS,
                            max(5, int(data.get("duration", 60) or 60))),
            "voice": data.get("voice", "alloy"),
            "music": bool(data.get("music", True)),
            "caption": caption,
        }
        jid = uuid.uuid4().hex[:12]
        workdir = os.path.join(config.JOBS_DIR, jid)
        os.makedirs(workdir, exist_ok=True)
        with LOCK:
            JOBS[jid] = {
                "id": jid, "type": "ttv", "status": "queued",
                "progress": 0, "message": "Queued...", "stage": "queue",
                "script": script[:200], "opts": opts, "workdir": workdir,
                "result": None, "error": None,
            }
        QUEUE.put(jid)
        _send_json(self, {"job_id": jid, "status_url": f"/api/status/{jid}",
                          "file_url": f"/api/file/{jid}"})


def _ffmpeg_ok():
    try:
        import subprocess
        r = subprocess.run([config.FFMPEG, "-version"], capture_output=True,
                           timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"ClipForge running on http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
