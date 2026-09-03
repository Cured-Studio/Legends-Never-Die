#!/usr/bin/env python3
"""
clip-intake — first-look analysis of a gameplay clip.

Usage:  python3 clip-intake.py <video file> [outdir]

Produces, in <outdir> (default: <video dir>/intake-<name>/):
  * report.txt      duration / resolution / fps / audio rate
  * booms.txt       loudest audio-spike timestamps (salvoes, dev-strikes)
  * sheet-*.jpg     contact sheets, one frame every ~2s, for eyeballing
"""
import os
import re
import subprocess
import sys

import numpy as np


def find_ffmpeg():
    for env in ("TWD_FFMPEG", "FFMPEG"):
        if os.environ.get(env):
            return os.environ[env]
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


FF = find_ffmpeg()
SR = 22050


def probe(path):
    r = subprocess.run([FF, "-i", path], capture_output=True, text=True)
    txt = r.stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", txt)
    info = {"duration_raw": txt}
    if dur:
        info["duration"] = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
    m = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", txt)
    if m:
        info["w"], info["h"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?) fps", txt)
    if m:
        info["fps"] = float(m.group(1))
    m = re.search(r"Audio: (\S+).*?(\d+) Hz", txt)
    if m:
        info["audio"] = m.group(1) + " " + m.group(2) + "Hz"
    return info


def booms(path, out):
    raw = os.path.join(out, "pcm.raw")
    subprocess.run([FF, "-y", "-i", path, "-ac", "1", "-ar", str(SR),
                    "-f", "s16le", raw], capture_output=True)
    if not os.path.exists(raw):
        return []
    x = np.fromfile(raw, dtype=np.int16).astype(np.float32) / 32768.0
    os.remove(raw)
    if len(x) < SR:
        return []
    trim = (len(x) // SR) * SR
    rms = np.sqrt((x[:trim] ** 2).reshape(-1, SR).mean(axis=1))
    db = 20 * np.log10(rms + 1e-9)
    thr = db.max() - 12
    hits, i = [], 0
    while i < len(db):
        if db[i] > thr:
            j = i
            while j < len(db) and db[j] > thr - 6:
                j += 1
            seg = db[i:j]
            hits.append((i + int(np.argmax(seg)), float(seg.max() - db.max())))
            i = j + 2          # 2s cooldown between events
        else:
            i += 1
    hits.sort(key=lambda h: -h[1])
    return hits[:25]


def sheets(path, out, dur):
    n = max(1, int(dur // 2) if dur else 10)
    cols, rows = 5, max(1, (n + 4) // 5)
    made = []
    per_sheet = cols * rows
    total = min(n, 100)
    idx = 0
    sheet_n = 0
    while idx < total:
        sheet_n += 1
        f = os.path.join(out, "sheet-%02d.jpg" % sheet_n)
        skip = 2 * idx
        count = min(per_sheet, total - idx)
        rows_n = max(1, (count + cols - 1) // cols)
        cmd = [FF, "-y", "-ss", str(skip), "-i", path,
               "-frames:v", str(count),
               "-vf", "fps=1/2,scale=384:-1,tile=%dx%d" % (cols, rows_n),
               "-frames:v", "1", "-q:v", "4", f]
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(f) and os.path.getsize(f) > 0:
            made.append(f)
        idx += per_sheet
    return made


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    base = os.path.splitext(os.path.basename(path))[0]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(path)), "intake-" + base)
    os.makedirs(out, exist_ok=True)

    info = probe(path)
    lines = ["clip: " + path]
    lines.append("duration: %s" % (
        "%d:%05.2f" % (info["duration"] // 60, info["duration"] % 60)
        if "duration" in info else "unknown"))
    lines.append("resolution: %sx%s @ %sfps" % (info.get("w", "?"), info.get("h", "?"),
                                                info.get("fps", "?")))
    lines.append("audio: %s" % info.get("audio", "none detected"))

    hits = booms(path, out)
    with open(os.path.join(out, "booms.txt"), "w") as f:
        f.write("# loudest audio events (sec into clip, dB below peak)\n")
        for t, d in sorted(hits):
            f.write("%6.1fs  %4.1f dB\n" % (t, -abs(d)))
    lines.append("audio spikes found: %d (see booms.txt)" % len(hits))

    made = sheets(path, out, info.get("duration", 20))
    lines.append("contact sheets: %d" % len(made))
    for m in made:
        lines.append("  " + os.path.basename(m))

    rep = "\n".join(lines) + "\n"
    with open(os.path.join(out, "report.txt"), "w") as f:
        f.write(rep)
    print(rep)


if __name__ == "__main__":
    main()
