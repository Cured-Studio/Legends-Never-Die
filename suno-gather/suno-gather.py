#!/usr/bin/env python3
"""
suno-gather — turn pasted Suno library JSON into one organized mp3 folder.

You do (per account, ~2 min, manual):
  1. log into suno.com, open your Library
  2. devtools (F12) -> Network tab -> filter: feed  (or just scroll the library
     until requests appear; the big JSON with all your clips)
  3. click the request -> Response -> right-click -> "Copy value"/select-all copy
  4. paste into a file: account01.json  (one file per account, any names)

This script does the rest:
  - finds every clip (audio_url) in any JSON shape you throw at it
  - dedupes across accounts (same song on two accounts = downloaded once)
  - downloads all mp3s -> out dir, named "Account - 01 - Title.mp3"
  - writes catalog.csv (title, account, created, url, duration if present)
  - prints total track count + total minutes (soundcloud free cap = 180)

usage:
  python3 suno-gather.py                     # reads ./suno-json, downloads to ./catalog
  python3 suno-gather.py --json-dir X --out Y
  python3 suno-gather.py --dry-run           # catalog only, no downloads

stdlib only. run it on your laptop (or the inmotion box).
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (suno-gather/1.0; personal catalog tool)"}

# ---------------------------------------------------------------- find clips
def walk_for_clips(node, found):
    """Recursively collect any dict that has an audio-bearing field."""
    if isinstance(node, dict):
        url = None
        for k in ("audio_url", "audioURL", "audio", "stream_audio_url"):
            v = node.get(k)
            if isinstance(v, str) and v.startswith("http"):
                url = v
                break
        if url:
            title = ""
            for k in ("title", "display_name", "name", "song_name"):
                v = node.get(k)
                if isinstance(v, str) and v.strip():
                    title = v.strip()
                    break
            created = node.get("created_at") or node.get("createdAt") or ""
            dur = ""
            for k in ("playtime_in_seconds", "playtime", "duration", "duration_s"):
                v = node.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    dur = v
                    break
            found.append({"url": url, "title": title or "untitled",
                          "created": str(created)[:19], "duration": dur,
                          "id": str(node.get("id") or "")})
    if isinstance(node, dict):
        for v in node.values():
            walk_for_clips(v, found)
    elif isinstance(node, list):
        for v in node:
            walk_for_clips(v, found)


def safe_name(s, maxlen=60):
    s = re.sub(r"[\\/:*?\"<>|]+", "", s).strip()
    return (s[:maxlen]).strip() or "untitled"


# ---------------------------------------------------------------- download
def fetch(url, dest, tries=3):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return "skip"
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r, open(dest + ".part", "wb") as f:
                while True:
                    b = r.read(1024 * 1024)
                    if not b:
                        break
                    f.write(b)
            os.replace(dest + ".part", dest)
            return "ok"
        except Exception as e:  # noqa: BLE001
            if attempt == tries:
                print("    ✘ %s (%s)" % (url, e))
                return "fail"
            time.sleep(2 * attempt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-dir", default="suno-json")
    ap.add_argument("--out", default="catalog")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.json_dir)
                   if f.endswith(".json")) if os.path.isdir(args.json_dir) else []
    if not files:
        print('no json files in %r — paste each account\'s library response'
              '\ninto files like account01.json in that folder (see --help)' % args.json_dir)
        sys.exit(1)

    seen_urls, tracks = set(), []
    for fn in files:
        account = os.path.splitext(fn)[0]
        try:
            data = json.load(open(os.path.join(args.json_dir, fn), encoding="utf-8"))
        except ValueError as e:
            print("!! %s is not valid json (%s) — skip" % (fn, e))
            continue
        found = []
        walk_for_clips(data, found)
        fresh = 0
        for t in found:
            if t["url"] in seen_urls:
                continue
            seen_urls.add(t["url"])
            t["account"] = account
            tracks.append(t)
            fresh += 1
        print("%-20s %3d clips (%d new)" % (account, len(found), fresh))

    if not tracks:
        print("no clips found — the copied response may be truncated or the wrong"
              " request. you want the library/feed XHR whose JSON contains your songs.")
        sys.exit(1)

    tracks.sort(key=lambda t: (t["account"], t["created"]))
    os.makedirs(args.out, exist_ok=True)
    counts = {}
    rows = []
    total_sec = 0.0
    known_dur = 0
    print("\n%3d unique tracks across %d accounts\n" % (len(tracks), len(files)))
    for t in tracks:
        counts[t["account"]] = counts.get(t["account"], 0) + 1
        n = counts[t["account"]]
        name = "%s - %02d - %s.mp3" % (t["account"], n, safe_name(t["title"]))
        dest = os.path.join(args.out, name)
        print("  %s" % name)
        status = "-"
        if not args.dry_run:
            status = fetch(t["url"], dest)
        if isinstance(t["duration"], (int, float)):
            total_sec += t["duration"]
            known_dur += 1
        rows.append({"file": name, "title": t["title"], "account": t["account"],
                     "created": t["created"], "duration_sec": t["duration"],
                     "status": status, "url": t["url"], "suno_id": t["id"]})

    with open(os.path.join(args.out, "catalog.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\ncatalog.csv written. totals:")
    print("  tracks: %d" % len(rows))
    if known_dur:
        print("  runtime (from %d/%d tracks w/ duration): %.0f min"
              % (known_dur, len(rows), total_sec / 60))
        print("  soundcloud free cap: 180 min — %s"
              % ("FITS ✓" if total_sec / 60 <= 180 else "OVER — will need trimming or a plan"))
    else:
        print("  (no durations in the json — total minutes TBD after download)")


if __name__ == "__main__":
    main()
