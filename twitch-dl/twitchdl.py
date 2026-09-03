#!/usr/bin/env python3
"""
twitch-dl — paste a Twitch URL, it downloads on your server (not your PC).

One file, Python stdlib only. Needs yt-dlp on the server
(+ ffmpeg for quality-merging and section cuts).

Quick start:
    pip install yt-dlp            # plus install ffmpeg
    python3 twitchdl.py           # -> http://localhost:8081

Config via env vars (or edit the defaults below):
    TWD_PORT      port to listen on            (default 8081)
    TWD_PASSCODE  passcode asked on the page   (default "change-me" — CHANGE IT)
    TWD_DIR       where files land             (default ./downloads)
    TWD_YTDLP     yt-dlp binary                (default "yt-dlp")
    TWD_FFMPEG    ffmpeg/ffmpeg dir for yt-dlp (default: found on PATH)
    TWD_ALLOW     comma-separated host allowlist, suffix-matched.
                  Empty string = allow any host (not recommended).
                  (default "twitch.tv")
"""
import json
import os
import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

PORT = int(os.environ.get("TWD_PORT", "8081"))
PASSCODE = os.environ.get("TWD_PASSCODE", "change-me")
DL_DIR = os.environ.get("TWD_DIR", "downloads")
YTDLP = os.environ.get("TWD_YTDLP", "yt-dlp")
FFMPEG_LOC = os.environ.get("TWD_FFMPEG", "")
ALLOW = os.environ.get("TWD_ALLOW", "twitch.tv")

os.makedirs(DL_DIR, exist_ok=True)
JOBS = {}
LOCK = threading.Lock()
ALLOW_SET = {h.strip().lower() for h in ALLOW.split(",") if h.strip()}

TS_RE = re.compile(r"^[0-9]+(:[0-5]?[0-9]){0,2}(\.[0-9]+)?$")
PCT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
SKIP_EXT = (".part", ".ytdl", ".tmp", ".temp", ".frost")

CTYPES = {
    ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm",
    ".ts": "video/mp2t", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".jpg": "image/jpeg", ".png": "image/png",
}


def host_allowed(host):
    if not ALLOW_SET:
        return True
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in ALLOW_SET)


def run_job(job):
    cmd = [YTDLP, "--newline", "--no-playlist", "--no-warnings", "--restrict-filenames",
           "-f", "bv*+ba/b", "--merge-output-format", "mp4",
           "-o", DL_DIR.rstrip("/\\") + "/%(title).60B [%(id)s].%(ext)s"]
    if FFMPEG_LOC:
        cmd += ["--ffmpeg-location", FFMPEG_LOC]
    if job.get("start") or job.get("end"):
        sect = "*%s-%s" % (job.get("start") or "0", job.get("end") or "inf")
        cmd += ["--download-sections", sect, "--force-keyframes-at-cuts"]
    cmd.append(job["url"])

    before = set(os.listdir(DL_DIR))
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
        for line in p.stdout:
            line = line.rstrip()
            with LOCK:
                job["log"] = (job["log"] + [line])[-300:]
                m = PCT_RE.search(line)
                if m:
                    job["pct"] = float(m.group(1))
        p.wait()
        job["rc"] = p.returncode
    except FileNotFoundError:
        job["rc"] = -1
        with LOCK:
            job["log"] = job["log"] + ["ERROR: %r not found — pip install yt-dlp" % YTDLP]
    except Exception as e:  # noqa: BLE001
        job["rc"] = -1
        with LOCK:
            job["log"] = job["log"] + ["ERROR: %s" % e]

    new = [f for f in set(os.listdir(DL_DIR)) - before if not f.endswith(SKIP_EXT)]
    if job["rc"] == 0 and new:
        job["file"] = max(new, key=lambda f: os.path.getmtime(os.path.join(DL_DIR, f)))
        job["status"] = "done"
    else:
        job["status"] = "error"
    job["pct"] = 100.0 if job["status"] == "done" else job.get("pct", 0.0)


INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>twitch-dl</title>
<style>
body{background:#0e1116;color:#c9d1d9;font:15px/1.5 system-ui,sans-serif;margin:0;padding:28px;display:flex;justify-content:center}
main{width:100%;max-width:680px}
h1{font-size:18px;margin:0 0 2px;color:#e6edf3}
h2{font-size:13px;margin:26px 0 10px;color:#7d8590;text-transform:uppercase;letter-spacing:.08em}
.sub{color:#7d8590;font-size:13px;margin-bottom:18px}
input{background:#161b22;border:1px solid #30363d;color:#e6edf3;border-radius:6px;padding:9px 12px;font:inherit;width:100%;box-sizing:border-box}
input:focus{outline:none;border-color:#2f81f7}
.row{display:flex;gap:8px;margin-bottom:8px}
.row input{margin:0}
button{background:#2f81f7;color:#fff;border:0;border-radius:6px;padding:9px 16px;font:inherit;font-weight:600;cursor:pointer;white-space:nowrap}
button:hover{background:#4c8dff}
.card{border:1px solid #30363d;border-radius:8px;padding:10px 12px;margin-bottom:8px;background:#161b22}
.bar{height:4px;background:#21262d;border-radius:2px;overflow:hidden;margin:8px 0 6px}
.bar i{display:block;height:100%;background:#2f81f7;width:0;transition:width .4s}
.log{font:11px/1.45 ui-monospace,monospace;color:#7d8590;white-space:pre-wrap;max-height:72px;overflow:auto}
a{color:#58a6ff;text-decoration:none}
a:hover{text-decoration:underline}
video{width:100%;border-radius:8px;margin-top:10px;background:#000}
.chip{font-size:11px;padding:1px 8px;border-radius:10px;border:1px solid #30363d;margin-right:6px}
.ok{color:#3fb950;border-color:#238636}.err{color:#f85149}.run{color:#d29922}
.dim{color:#7d8590;font-size:12px}
</style></head><body><main>
<h1>&#9875; twitch-dl</h1>
<div class="sub">paste a twitch url &mdash; it lands on the server, not your pc</div>
<div class="row"><input id="url" placeholder="https://www.twitch.tv/videos/..." autofocus></div>
<div class="row">
<input id="start" placeholder="start (opt) 12:34">
<input id="end" placeholder="end (opt) 13:40">
<input id="pc" type="password" placeholder="passcode">
<button id="go">haul it in</button>
</div>
<div id="jobs"></div>
<h2>cargo hold</h2>
<div id="files" class="dim">empty</div>
<script>
const $=id=>document.getElementById(id);
$('go').onclick=async()=>{
 const u=$('url').value.trim(); if(!u)return;
 const r=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({url:u,passcode:$('pc').value,start:$('start').value.trim(),end:$('end').value.trim()})});
 const j=await r.json();
 if(!r.ok){alert(j.error||'nope');return}
 $('url').value='';$('start').value='';$('end').value='';tick();
};
const esc=s=>(s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const mb=b=>b>1048576?(b/1048576).toFixed(1)+' MB':Math.max(1,Math.round(b/1024))+' KB';
async function tick(){
 try{
  const s=await (await fetch('/api/status')).json();
  $('jobs').innerHTML=s.jobs.map(j=>`<div class="card">
   <div><span class="chip ${j.status=='done'?'ok':j.status=='error'?'err':'run'}">${j.status}</span>${esc(j.url)}
   ${j.file?` &mdash; <a href="/f/${encodeURIComponent(j.file)}">${esc(j.file)}</a>`:''}</div>
   <div class="bar"><i style="width:${j.pct||0}%"></i></div>
   <div class="log">${esc(j.log.join('\\n'))}</div></div>`).join('');
  const f=await (await fetch('/api/files')).json();
  $('files').innerHTML=f.files.length?f.files.map(x=>{
   const n=encodeURIComponent(x.name);
   return `<div class="card"><div>${esc(x.name)} <span class="dim">(${mb(x.size)})</span>
   <a href="#" onclick="return play('${n}')">&#9654; play</a> &middot;
   <a href="/f/${n}" download>save</a></div><div id="v-${n}"></div></div>`;}).join(''):'empty';
 }catch(e){}
}
function play(n){const d=document.getElementById('v-'+n);
 if(d.innerHTML){d.innerHTML='';return false}
 d.innerHTML=`<video controls autoplay src="/f/${n}"></video>`;return false}
setInterval(tick,1500);tick();
</script></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "twitch-dl/1.0"

    def log_message(self, *a):  # quiet
        pass

    # ---- helpers ----
    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    # ---- routes ----
    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):
        self.do_GET()

    def _get(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, INDEX.encode())
        elif path == "/api/status":
            with LOCK:
                jobs = sorted(JOBS.values(), key=lambda j: j["started"], reverse=True)
                snap = [{k: v for k, v in j.items() if k != "log"} | {"log": j["log"][-12:]}
                        for j in jobs]
            self._json({"jobs": snap})
        elif path == "/api/files":
            out = []
            for f in os.listdir(DL_DIR):
                p = os.path.join(DL_DIR, f)
                if os.path.isfile(p) and not f.endswith(SKIP_EXT):
                    out.append({"name": f, "size": os.path.getsize(p),
                                "mtime": os.path.getmtime(p)})
            out.sort(key=lambda x: -x["mtime"])
            self._json({"files": out})
        elif path.startswith("/f/"):
            self._serve_file(path[3:])
        else:
            self._json({"error": "not found"}, 404)

    def _serve_file(self, raw):
        name = os.path.basename(unquote(raw))
        path = os.path.join(DL_DIR, name)
        if not name or not os.path.isfile(path):
            self._json({"error": "no such file"}, 404)
            return
        size = os.path.getsize(path)
        ctype = CTYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")

        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if m and (m.group(1) or m.group(2)):
                a, b = m.group(1), m.group(2)
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                else:  # suffix: last N bytes
                    start = max(0, size - int(b))
                    end = size - 1
                if start >= size:
                    self._send(416, b"", "application/json",
                               extra=[("Content-Range", "bytes */%d" % size)])
                    return
                end = min(end, size - 1)
                code = 206

        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Disposition", "inline; filename*=UTF-8''%s" % name.replace("'", ""))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_POST(self):
        try:
            if self.path.split("?", 1)[0] != "/api/start":
                self._json({"error": "not found"}, 404)
                return
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n).decode() or "{}")
            except ValueError:
                self._json({"error": "bad json"}, 400)
                return

            if body.get("passcode") != PASSCODE:
                self._json({"error": "wrong passcode"}, 403)
                return
            url = (body.get("url") or "").strip()
            u = urlparse(url)
            if u.scheme not in ("http", "https") or not u.netloc:
                self._json({"error": "that's not a url"}, 400)
                return
            if not host_allowed(u.hostname):
                self._json({"error": "host not allowed (allowlist: %s)" % ALLOW}, 403)
                return
            start, end = (body.get("start") or "").strip(), (body.get("end") or "").strip()
            for ts in (start, end):
                if ts and not TS_RE.match(ts):
                    self._json({"error": "timestamps look like 12:34 or 83"}, 400)
                    return

            job = {"id": uuid.uuid4().hex[:8], "url": url, "start": start, "end": end,
                   "status": "running", "pct": 0.0, "file": None, "rc": None,
                   "started": time.time(), "log": []}
            with LOCK:
                JOBS[job["id"]] = job
            threading.Thread(target=run_job, args=(job,), daemon=True).start()
            self._json({"id": job["id"], "ok": True})
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("twitch-dl listening on 0.0.0.0:%d  (dir: %s)" % (PORT, DL_DIR))
    print("passcode is %r — change it with TWD_PASSCODE" % PASSCODE)
    srv.serve_forever()
