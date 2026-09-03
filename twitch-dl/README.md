# ⚓ twitch-dl

Paste a Twitch URL into a blank page → it downloads **on your server**, not your PC.
Watch it straight from the server when it's done.

One file. Python stdlib only (no Flask/etc). It drives `yt-dlp` under the hood.

## Setup (on your server)

```bash
pip install yt-dlp        # plus ffmpeg:
#   ubuntu/debian:  sudo apt install ffmpeg
#   windows:        winget install ffmpeg   (or choco install ffmpeg)
python3 twitchdl.py       # -> http://your-server:8081
```

Keep it running: `nohup python3 twitchdl.py >twitchdl.log 2>&1 &`
(Windows: just leave the terminal open, or set it up as a scheduled task.)

## Config (env vars — or edit the top of the file)

| var | default | what |
|---|---|---|
| `TWD_PORT` | `8081` | port to listen on |
| `TWD_PASSCODE` | `change-me` | **change this before exposing the page** |
| `TWD_DIR` | `downloads` | where files land (gitignored) |
| `TWD_YTDLP` | `yt-dlp` | path to yt-dlp if not on PATH |
| `TWD_FFMPEG` | *(PATH)* | ffmpeg binary/folder if not on PATH |
| `TWD_ALLOW` | `twitch.tv` | host allowlist (comma-separated, suffix-matched). Empty = allow any host — risky |

Example:

```bash
TWD_PORT=9000 TWD_PASSCODE=yoursecret python3 twitchdl.py
```

## Using it

1. Open the page, paste a VOD or clip URL (`twitch.tv/videos/…`, `clips.twitch.tv/…`)
2. Optional **start/end** boxes grab just a slice of a VOD (e.g. `12:34` → `13:40`)
   — perfect for cutting the 60 seconds around a dev-strike out of a 2-hour stream
3. Hit **haul it in** — live progress + log right on the page
4. When it's done it appears in **cargo hold**: ▶ play in-browser, or **save** to download from server → PC

## Notes & gotchas

- **VODs expire**: 14 days (60 for partners) after the broadcast — download before then.
  Highlights/clips don't expire.
- Sub-only VODs need auth — that's a yt-dlp OAuth thing, ask and we'll wire it in.
- Twitch caps streams around 1080p60; you get whatever the VOD stored.
- Files are served to **anyone with the link** once downloaded — keep the passcode real
  and don't port-forward this to the open internet without changing defaults.
- Stopping the script stops in-flight downloads (finished files stay).
