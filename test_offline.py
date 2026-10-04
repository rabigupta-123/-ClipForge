"""Offline smoke test: validates best-moment detection + full TTV assembly
using ffmpeg-synthesized inputs (no network needed)."""
import os, json
import config, media_utils as mu, ttv, clip

TMP = config.TMP_DIR
print("ffmpeg:", mu.run([config.FFMPEG, "-version"], capture=True)[0].splitlines()[0])

# --- 1) synthetic "video" with a loud section between 5s and 13s ---
src = os.path.join(TMP, "synth.mp4")
# silence(5s) + loud tone(8s) + silence(7s) via concat
mu.run([
    config.FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=20",
    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=5",
    "-f", "lavfi", "-i", "sine=frequency=800:duration=8:sample_rate=44100",
    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=7",
    "-filter_complex", "[1][2][3]concat=n=3:v=0:a=1[a]",
    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac",
    "-t", "20", "-pix_fmt", "yuv420p", "-shortest", src
], timeout=120)
dur = mu.probe_duration(src)
print("synth duration:", dur)

series = mu.audio_energy_windows(src)
start, end = mu.best_window_from_series(series, dur, window=8)
print(f"BEST WINDOW (expect ~8-14s): {start:.1f} -> {end:.1f}")
assert 4 <= start <= 13, f"best-window detector missed the loud section (got {start})"

# --- 2) full TTV pipeline (network blocked -> exercises fallbacks) ---
out = os.path.join(TMP, "ttv_test.mp4")
opts = {"mode": "image_story", "duration": 15, "voice": "alloy",
        "music": True, "caption": {"mode": "auto"}}
try:
    ttv.ttv_generate("Hello world. This is a test of ClipForge. "
                     "It makes short videos from text. Enjoy your clips.",
                     out, opts=opts)
    print("TTV produced:", out, "size:", os.path.getsize(out))
    od = mu.probe_duration(out)
    print("TTV duration:", round(od, 1))
    assert os.path.getsize(out) > 5000, "output too small"
    assert abs(od - 15) < 2, "duration off"
    print("TTV OK")
except Exception as e:
    print("TTV ERROR:", repr(e))
    raise

# --- 3) text_cards mode too ---
out2 = os.path.join(TMP, "ttv_cards.mp4")
try:
    ttv.ttv_generate("First idea. Second idea. Third idea.", out2,
                     opts={"mode": "text_cards", "duration": 12,
                           "voice": "nova", "music": False,
                           "caption": {"mode": "custom", "text": "My Caption"}})
    print("CARDS produced:", os.path.getsize(out2), "dur", round(mu.probe_duration(out2),1))
    print("CARDS OK")
except Exception as e:
    print("CARDS ERROR:", repr(e)); raise

print("\nALL OFFLINE TESTS PASSED")
