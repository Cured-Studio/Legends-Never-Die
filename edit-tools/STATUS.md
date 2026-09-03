# Legends Never Die — where we left off

## The mission
Music video: **plaguedrgen — "Legends Never Die"** (2:13, ~96 BPM, Suno, unpublished)
synced to USER'S OWN World of Warships footage (xbox, spectate-mode capture).

## Done
- song decoded: 2:13 / 96 BPM / no chorus / "HULL IS MADE OF STEEL" doubled 1:00–1:20
- edit map v2 + section-01 storyboard (carrier launch open, hard cut @ 0:30,
  waypoint click on "acquired", planes return during fade = bookend)
- capture loop agreed: xbox spectate-stream → twitch → laptop clips (`01a` names)
  → github web upload (≤25MB ≈ 30s@1080p) → intake robot
- tools shipped: twitch-dl/ (web UI + haul.py), edit-tools/clip-intake.py,
  suno-gather/ (the facetious robot)
- cover-1600.jpg (suno art upscaled) made for soundcloud, not yet uploaded

## Waiting on user
1. soundcloud drop (girlfriend's mail-route playlist, haverhill MA) — cover + paste-ready
   description already delivered; 50-track question resolved as "artist picks versions"
2. spectate session → clips pushed to repo (moments 3–10s, named 01a-style)
3. someday: server identity = inmotion reseller (cPanel), haul.py runbook delivered

## Next agent steps when clips land
- fetch via api.github.com contents API (raw.githubusercontent + twitch + cloudfront = blocked)
- run edit-tools/clip-intake.py per clip (probe, boom map, contact sheets)
- user eyeballs sheets → lock in-points → rough cut with ffmpeg
  (venv: /home/user/.venv-video — rebuild with `pip install numpy imageio-ffmpeg yt-dlp` if reset ate it)
- final video ships via github Release (2GB cap), not a commit
