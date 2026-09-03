#!/usr/bin/env python3
"""
haul — pull a file from a URL down onto THIS machine (server), not your PC.

usage:
  python3 haul.py <url> [more urls...]      # downloads into ./downloads
  python3 haul.py -o /srv/clips <url>       # pick the landing dir
  python3 haul.py                           # no args? it'll ask for a url
  python3 haul.py --serve [dir]             # just serve a dir at :8082

flags:
  -o DIR     where files land          (default ./downloads)
  --name N   rename the downloaded file
  --serve    after hauling, serve the dir in your browser (port 8082)
  --serve-only DIR    don't download, just serve

stdlib only — no pip installs needed. works on windows + linux.
"""
import os
import sys
import time
import urllib.request
import urllib.error

CHUNK = 1024 * 1024
UA = {"User-Agent": "haul/1.0 (+python-urllib)"}


def ask_url():
    print("paste a url and hit enter (ctrl+c to bail):")
    return input("> ").strip()


def dest_name(url, forced):
    if forced:
        return forced
    name = url.split("?")[0].rstrip("/").split("/")[-1]
    return name or "download.bin"


def haul(url, out_dir, forced_name=None):
    os.makedirs(out_dir, exist_ok=True)
    name = dest_name(url, forced_name)
    final = os.path.join(out_dir, name)
    part = final + ".part"

    if os.path.exists(final):
        print("✔ already hauled: %s (%.1f MB) — skipping"
              % (final, os.path.getsize(final) / 1048576))
        return final

    have = os.path.getsize(part) if os.path.exists(part) else 0
    tries = 0
    while True:
        tries += 1
        try:
            req = urllib.request.Request(url, headers=UA)
            if have:
                req.add_header("Range", "bytes=%d-" % have)
            with urllib.request.urlopen(req, timeout=60) as r:
                code = r.getcode()
                total = int(r.headers.get("Content-Length") or 0)
                if have and code == 206 and total:
                    total += have  # server resumed: total is what's left
                elif code == 200:
                    have = 0      # server ignored range: start over

                mode = "ab" if have else "wb"
                done, t0 = have, time.time()
                with open(part, mode) as f:
                    while True:
                        block = r.read(CHUNK)
                        if not block:
                            break
                        f.write(block)
                        done += len(block)
                        if total:
                            pct = done * 100 // total
                            spd = done / max(0.1, time.time() - t0)
                            sys.stdout.write(
                                "\r  %s  %d%%  %.1f/%.1f MB  %.1f MB/s   "
                                % (name, pct, done / 1048576, total / 1048576,
                                   spd / 1048576))
                            sys.stdout.flush()
                sys.stdout.write("\n")
            if total and done < total:
                raise IOError("short read: %d of %d bytes" % (done, total))
            os.replace(part, final)
            print("✔ hauled: %s (%.1f MB)" % (final, done / 1048576))
            return final
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, IOError) as e:
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if tries >= 4:
                print("\n✘ gave up on %s after %d tries: %s" % (url, tries, e))
                return None
            wait = 2 ** tries
            print("\n  … hiccup (%s) — retrying in %ds (resume from %.1f MB)"
                  % (e, wait, have / 1048576))
            time.sleep(wait)


# ---------- tiny file server so you can WATCH from the server ----------
# note: no Range support (seeking) — for scrubbing video use twitchdl.py's /f/ view
def serve(directory, port=8082):
    from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
    import functools
    os.chdir(directory)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print("serving %s at http://0.0.0.0:%d  (ctrl+c to stop)" % (directory, port))
    srv.serve_forever()


def main():
    args = sys.argv[1:]
    out_dir, forced, do_serve, urls = "downloads", None, False, []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-o":
            i += 1
            out_dir = args[i]
        elif a == "--name":
            i += 1
            forced = args[i]
        elif a == "--serve":
            do_serve = True
        elif a == "--serve-only":
            i += 1
            serve(args[i])
            return
        else:
            urls.append(a)
        i += 1

    if not urls:
        u = ask_url()
        if u:
            urls = [u]

    for u in urls:
        haul(u, out_dir, forced)

    if do_serve:
        serve(out_dir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nanchored. partial files keep their .part tail — rerun to resume.")
