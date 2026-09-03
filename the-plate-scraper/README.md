# The Plate Scraper — theplatescraper.com

A complete, independent **recipe site** for cooks — with a private back office (recipe scraper, RSS reader + house-style rewriter, affiliate panel, MySQL wizard) for the site owner. Runs on **plain Python (standard library only)** — no frameworks, no build step. Optional **MySQL** backend with a visual wizard + one-command Windows setup.

## Reader-facing site

| Tool | Where | What it does |
|---|---|---|
| 📖 **Recipe Library** | `/recipes.html` | Tested original recipes, search by name/ingredient, category filters, one-tap serving scale, "swap ↗" links per ingredient. |
| 📖 **Blog** | `/blog.html` | Published posts — including recipes adapted from the blogs we follow, always with source credit. Fed by the Feed Room rewriter. |
| 🔁 **Substitution Guide** | `/substitutions.html` | 26 pantry staples with exact ratios and honest notes. Linked from every ingredient on every recipe. |
| 🛒 **Shopping List** | `/shopping.html` | Aisle-grouped, quantities merged, tap-to-check. Guest list lives in the browser; members' lists sync server-side. |
| 👩‍🍳 **Members Area** | `/dashboard.html` | Sign up / sign in (PBKDF2 + salted sessions), saved recipes, synced lists, tier upgrades (demo checkout). |
| 🍳 **Kitchen Gear** | `/gear.html` | Public affiliate shop — tracked links. |

## Owner back office (requires the owner account)

| Tool | Where | What it does |
|---|---|---|
| 🧲 **Recipe Scraper** | `/scraper.html` | Paste a recipe URL (or raw HTML/plain text) → clean, editable recipe card (JSON-LD `Recipe` schema, `<ul>/<ol>` blocks, plain text). Save into the library, scale, send to the list. |
| 📡 **Feed Room (RSS)** | `/feedroom.html` | Follow recipe blogs' RSS/Atom feeds, read new posts, **Rewrite in house style** — new title, intro, synonym-passed body, house note, full source credit. Publish → appears on the public blog. Or pull the recipe straight into the library. |
| 🎛 **Affiliate Control Panel** | `/affiliate.html` | Stores & products CRUD (auto-generates `/go/CODE` tracked links), 14-day click charts, per-link estimated commission, live click feed. Clicks logged server-side on `/go/CODE` redirects. |
| 🗄 **MySQL Wizard** | `/setup.html` | 5-step wizard: status → connect → create DB + schema → migrate JSON data → activate. JSON file always stays as a hot backup; if MySQL ever drops, the server falls back to JSON automatically. |

Owner account: `admin@theplatescraper.com` — works either as a signed-in member or via the control-panel login; both unlock the owner tools.

## Quick start

```bash
cd the-plate-scraper
python3 server.py 8080        # JSON store (data/db.json), zero dependencies
```

Open http://localhost:8080

**Demo accounts**

| Role | Email | Password |
|---|---|---|
| Member | `demo@theplatescraper.com` | `demo1234` |
| Site owner (control panel + MySQL wizard) | `admin@theplatescraper.com` | `plate-admin-2026` |

## Deploying to InMotion (cPanel shared / reseller)

InMotion's reseller plans include Python (via cPanel's Passenger-based
**Application Manager** / **Setup Python App**) and unlimited MySQL databases, so this
codebase runs there with one extra file — `wsgi.py` is already included:

1. **Upload** the `the-plate-scraper/` folder to `~/theplatescraper` (File Manager or Git).
2. **MySQL**: in cPanel → *MySQL Databases*, create the database + user
   (e.g. `john123_theplatescraper`) and grant all privileges. Reseller plans
   allow as many as you need.
3. **Python app**: cPanel → *Application Manager* (or *Setup Python App*) →
   **Create Application**:
   - Application URL: `theplatescraper.com` (or a subdomain/sub-path)
   - Application root: `~/theplatescraper`
   - Startup file: `wsgi.py` (entry point `wsgi.application`)
   - Then **Run Pip Install** on `requirements.txt` (installs `pymysql`).
4. **MySQL Wizard**: open `/setup.html`, enter host `localhost` and the exact
   cPanel-prefixed database name → the *Create* step now tolerates shared hosts
   (it applies the schema to the cPanel-created database), then **Migrate** →
   **Activate**.
5. Point the domain's DNS at the host (or use the included subdomain) and you're live.

Notes:
- The standalone `python3 server.py` mode keeps working for local dev / VPS.
- On cPanel, static files are served through the app (the WSGI layer reads them
  from `static/`) — fine at this scale; if you later want Apache to serve them
  directly, add rewrite rules in front.
- SSH is included on InMotion reseller — handy for running the CLI wizard
  (`tools/mysql_setup.py`) or tailing logs.

## MySQL backend

### Option A — one command (Windows, PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-theplatescraper.ps1
```

The script finds Python, creates `.venv`, installs `pymysql`, then runs the wizard headlessly
(test → `CREATE DATABASE` → `schema.sql` → migrate → activate), starts the server, and opens the browser.
Useful flags: `-DbPassword 'secret' -Port 8090 -SkipDb -NoBrowser`.

### Option B — the visual wizard

1. Start the server (JSON mode).
2. Open `/setup.html`, sign in with the owner account.
3. Enter host/port/user/password → **Create** → **Migrate** → **Activate**.

### Option C — CLI only

```bash
pip install -r requirements.txt
python tools/mysql_setup.py --host 127.0.0.1 --user root --password *** --database theplatescraper --create
python tools/mysql_setup.py --host 127.0.0.1 --user root --password *** --database theplatescraper --migrate
python tools/mysql_setup.py --host 127.0.0.1 --user root --password *** --database theplatescraper --activate
```

Schema lives in `data/schema.sql` (11 tables: `users`, `sessions`, `recipes`, `substitutions`,
`affiliate_stores`, `affiliate_products`, `affiliate_links`, `affiliate_clicks`, `feeds`, `posts`, `meta`).
Requires MySQL 5.7+ / MariaDB 10.2+ for JSON columns.

## Layout

```
server.py                  # stdlib HTTP server, API, scraper, rewriter, MySQL layer
setup-theplatescraper.ps1  # one-shot Windows setup (venv + MySQL + launch + browser)
requirements.txt           # pymysql (only dependency, and only for MySQL mode)
tools/mysql_setup.py       # headless MySQL wizard CLI
data/schema.sql            # full MySQL DDL
data/recipes.json          # original recipe library (8 recipes)
data/substitutions.json    # 26-ingredient substitution database
data/db.json               # live JSON store (auto-created, also the MySQL hot backup)
data/mysql.json            # saved MySQL connection config (never committed in practice)
pages/*.html               # 13 pages (home, library, detail, scraper, feedroom, subs,
                           # shopping, members, dashboard, affiliate, gear, about, setup)
static/style.css           # design system (warm food-magazine theme)
static/app.js              # shared frontend (nav, api client, shopping list, tracking)
static/images/             # generated food photography
```

## Notes

- The preview sandbox has no outbound network: URL scraping and RSS fetching run the identical
  pipeline over bundled sample pages and say so in a banner. On a real host they fetch live URLs.
- All library recipes and feed content are original demo content.
- Affiliate commission figures use a configurable 12% click→purchase assumption; swap in real
  program data via the control panel.
