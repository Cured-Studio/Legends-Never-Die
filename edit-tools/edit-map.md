# Legends Never Die — Edit Map v2 (moments-based)

## Song facts (measured from the MP3, not guessed)
- **Duration: 2:13.04** — vocals end ~1:55, loudest build 1:50–2:10, fade out ~2:11
- **Tempo: ~96 BPM** → bar (4/4) = 2.5s → cut every 1–2 bars = every 2.5–5s
- **No recurring chorus** — instrumental loops straight through
- **"HULL IS MADE OF STEEL" sung 2× back-to-back** (doubled hook, ~1:00–1:20)
- Full energy from 0:00 (no quiet intro build)
- Source: Suno (unpublished), artist **plaguedrgen**, embedded 360×360 cover art

## Why SHORT clips are the point
Music-video pacing at 96 BPM wants a cut every 2.5–5 seconds. A 20–30s
continuous shot would be dead air. So: **capture many short moments, 3–10s
each, with 1–2s of padding**, and the edit stacks them on the beat.

## Moments wanted (name them `01a 01b 01c 02a …`)
| section | time | moments | content |
|---|---|---|---|
| 01 intro/carrier | 0:00–0:30 | 4–6 × ~5s | deck ops, planes launching, fleet sailing out (title card can hold here) |
| 02 verse 1 guns | 0:30–1:00 | 5–7 × ~5s | salvoes, AP shell flight, citadel/dev-strike ("WIPIN' OUT THE LOBBY" ≈0:55) |
| 03 hook ×2 | 1:00–1:20 | 3–4 × ~6s | angled & tanking, holding the line (2 passes = one per hook rep) |
| 04 torps | 1:20–1:26 | 1 × ~6s | launch or spread swimming out |
| 05 flak/smoke/run | 1:26–1:45 | 3–4 × ~5s | AA flak puffs, smoke, minimap visible, pack running the sea |
| 06 explosion/final | 1:45–2:00 | 2–3 × ~5s | biggest booms ("finally exploded" ≈1:40–1:45) |
| 07 victory | 2:00–2:13 | 1–2 × ~8s | results/victory screen (end card + cover art over fade) |

## Rules of thumb
- 3s is plenty for a hit; 1–2s ribbon flashes still work as downbeat punch-ins
- short money moment → 0.5× slow-mo stretches a 3s dev-strike to 6s and looks dope
- clips can be REUSED — second appearance with different trim or slo-mo is standard
- hard cut at exactly **0:30** onto the carrier/first salvo (first lyric downbeat)
- hard floor: ~24 moments total; duplicates beat gaps

## Capture/relay pipeline (agreed)
1. cut clips on twitch (titles = `01a` style names → become filenames)
2. relay to inmotion box (`~/bin/yt-dlp` standalone or share→download), or push direct
3. git push to Legends-Never-Die (files <100 MB — clips of ≤60s are way under)
4. intake robot (`edit-tools/clip-intake.py`) dissects each: probe, boom map, contact sheets
5. rough cut → review → iterate

## Footage log
| file | landed | duration | res/fps | verdict |
|---|---|---|---|---|
| *(waiting on first clip)* | | | | |

## Section 01 storyboard — "Droppin' the carrier" (agreed w/ user)
| time | visual | beat note |
|---|---|---|
| 0:00–0:08 | ocean establishing / fleet at speed, **title card in** (song title + plaguedrgen) | intro bars |
| 0:08–0:16 | carrier in frame / deck activity, engines spooling | build |
| 0:16–0:24 | **takeoff angle A** → **takeoff angle B** | cut each on a bar (~2.5s) |
| 0:24–0:30 | planes forming up over the fleet | tension hold |
| **0:30** | 💥 biggest launch shot lands ON the downbeat = "Droppin' the carrier" | hard cut |
| ~0:34 | **waypoint click on tactical map** = "new mission acquired" (click lands on the word) | literal sync |
| ~0:38 | salvo toward a battleship = "Takin' out battleships" | bridges into section 02 |

**Bookend:** returning/landing planes are saved for the 2:00–2:11 outro —
planes come home while the song fades. Open with a launch, close with a landing.

### Moments to capture for 01
- `01a map-waypoint` (~8s: map open → cursor → click → waypoint line appears)
- `01b takeoff-wide` (~4s) · `01c takeoff-angle2` (~4s) · `01d formup-flyover` (~5s)
- `01e planes-returning` (~6s) → **bank for the outro (07)**
- tip: friendly carriers launch at match start — park near one during the first
  20s of a match; returning planes show late-game. One match in a carrier
  yourself = unlimited deck angles.

## CAPTURE STRATEGY PIVOT: spectate, don't perform (agreed)
User will farm footage by **spectating matches**, not recording own playthroughs.
Why it's right: camera goes where the action is, no HUD of your own, every
match has someone's dev-strike, and you never have to actually hit anything.

- **how:** get sunk early (tier III yolo = fast ticket to spectator mode),
  then you're a camera operator for the rest of the match — cycle players,
  follow the carrier for launches, the DDs for torp spreads
- **gold mines:** carrier players at match start (guaranteed launch b-roll),
  destroyers in torpedo lanes, last-two-ships duels, match-end battle results
- **POV-only moments that still need ONE played session:** waypoint click on
  tactical map (01a), minimap glance (05), consumables/smoke from own deck.
  Record one casual match with "record last 5 min" ON to bank these.
- twitch clip titles stay `01a`-style; spectate clips can be `02x-<moment>`
  since section mapping happens at intake (boom map + contact sheets sort them)

## CAPTURE LOOP v2: xbox spectate-stream → laptop clips (agreed)
Xbox broadcasts the spectate session to twitch; laptop watches the own
channel live and makes the clips. No xbox capture manager, no upload dance.
- BEFORE first session: enable **store past broadcasts** (backup VOD of the
  whole session = clip leisurely afterward) + set xbox twitch app to max quality
- clips made on your own stream = zero rights drama, instant
- github relay straight from the laptop browser: keep clips **≤30s @1080p or
  ≤60s @720p** → stays under the 25MB web-upload cap, no git needed
- bigger cuts still route through the inmotion box (haul.py/yt-dlp)
