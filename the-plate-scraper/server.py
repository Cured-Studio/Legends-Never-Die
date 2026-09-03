#!/usr/bin/env python3
"""The Plate Scraper — server for theplatescraper.com (Python stdlib only).

Run:  python3 server.py  [port]
"""
import hashlib
import html as htmllib
import json
import os
import random
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
PAGES = os.path.join(BASE, "pages")
STATIC = os.path.join(BASE, "static")
DB_PATH = os.path.join(DATA_DIR, "db.json")
LOCK = threading.Lock()
DOMAIN = "theplatescraper.com"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


# ----------------------------------------------------------------------------- utilities
def hash_pw(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()


# ----------------------------------------------------------------------------- storage layer
MYSQL_CFG_PATH = os.path.join(DATA_DIR, "mysql.json")
SCHEMA_PATH = os.path.join(DATA_DIR, "schema.sql")


def _load_json_db() -> dict:
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json_db(db: dict) -> None:
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DB_PATH)


def mysql_cfg() -> dict:
    try:
        with open(MYSQL_CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_mysql_cfg(cfg: dict) -> None:
    with open(MYSQL_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)


def mysql_driver_available() -> bool:
    try:
        import pymysql  # noqa: F401
        return True
    except Exception:
        return False


def mysql_active() -> bool:
    cfg = mysql_cfg()
    return bool(cfg.get("active")) and mysql_driver_available()


def mysql_connect(cfg: dict, database: bool = True):
    import pymysql
    return pymysql.connect(
        host=cfg.get("host") or "127.0.0.1",
        port=int(cfg.get("port") or 3306),
        user=cfg.get("user") or "root",
        password=cfg.get("password") or "",
        database=(cfg.get("database") or "theplatescraper") if database else None,
        charset="utf8mb4",
        autocommit=False,
        connect_timeout=8,
    )


def mysql_ping(cfg: dict):
    conn = mysql_connect(cfg, database=False)
    try:
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        return cur.fetchone()[0]
    finally:
        conn.close()


def read_schema_sql() -> str:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return f.read()


def mysql_create_database(cfg: dict):
    """Create the database and run the full schema. Returns version string.

    On shared hosts (e.g. InMotion cPanel) the app user usually can't
    CREATE DATABASE itself — the DB is made in cPanel "MySQL Databases"
    (often with a cPanel-username prefix). If CREATE fails but the
    database already exists, we simply use it and apply the schema.
    """
    conn = mysql_connect(cfg, database=False)
    try:
        cur = conn.cursor()
        db = cfg.get("database") or "theplatescraper"
        try:
            cur.execute("CREATE DATABASE IF NOT EXISTS `%s` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" % db)
        except Exception:
            # Shared-host mode: rely on a pre-created (cPanel) database.
            # select_db below will fail with a clear error if it doesn't exist.
            pass
        conn.select_db(db)
        for stmt in [s.strip() for s in read_schema_sql().split(";") if s.strip()]:
            if stmt.lstrip().upper().startswith(("CREATE", "USE", "DROP")) or "\n" in stmt or "CREATE" in stmt.upper():
                cur.execute(stmt)
        conn.commit()
        cur.execute("SELECT VERSION()")
        return cur.fetchone()[0]
    finally:
        conn.close()


def _row_user(r):
    def j(v, d):
        try:
            return json.loads(v) if isinstance(v, str) else (v if v is not None else d)
        except Exception:
            return d
    return {"email": r[0], "name": r[1], "salt": r[2], "hash": r[3], "tier": r[4],
            "created": r[5], "saved": j(r[6], []), "list": j(r[7], []),
            "scrapes": j(r[8], []), "custom": j(r[9], []), "listCursor": r[10] or 1000}


def mysql_load_db(cfg: dict) -> dict:
    conn = mysql_connect(cfg)
    try:
        cur = conn.cursor()
        db = {"users": {}, "sessions": {}, "recipes": {}, "substitutions": [], "aff":
              {"stores": [], "products": [], "links": {}, "clicks": []},
              "admin": {}, "feeds": [], "posts": [], "stats": {}}
        cur.execute("SELECT email, name, salt, pw_hash, tier, created, saved, shopping_list, scrapes, custom, list_cursor FROM users")
        for r in cur.fetchall():
            u = _row_user(r)
            db["users"][u["email"]] = u
        cur.execute("SELECT token, email FROM sessions")
        for r in cur.fetchall():
            db["sessions"][r[0]] = r[1]
        cur.execute("SELECT slug, data, added FROM recipes")
        for r in cur.fetchall():
            rec = json.loads(r[1]) if isinstance(r[1], str) else r[1]
            rec["added"] = r[2]
            db["recipes"][r[0]] = rec
        cur.execute("SELECT ing_id, data FROM substitutions")
        for r in cur.fetchall():
            db["substitutions"].append(json.loads(r[1]) if isinstance(r[1], str) else r[1])
        cur.execute("SELECT id, data FROM affiliate_stores")
        for r in cur.fetchall():
            db["aff"]["stores"].append(json.loads(r[1]) if isinstance(r[1], str) else r[1])
        cur.execute("SELECT id, store, data FROM affiliate_products")
        for r in cur.fetchall():
            db["aff"]["products"].append(json.loads(r[1]) if isinstance(r[1], str) else r[1])
        cur.execute("SELECT code, product, created FROM affiliate_links")
        for r in cur.fetchall():
            db["aff"]["links"][r[0]] = {"product": r[1], "created": r[2]}
        cur.execute("SELECT ts, code, path FROM affiliate_clicks ORDER BY ts")
        for r in cur.fetchall():
            db["aff"]["clicks"].append({"ts": r[0], "code": r[1], "path": r[2] or ""})
        cur.execute("SELECT id, data FROM feeds")
        for r in cur.fetchall():
            db["feeds"].append(json.loads(r[1]) if isinstance(r[1], str) else r[1])
        cur.execute("SELECT id, data FROM posts")
        for r in cur.fetchall():
            db["posts"].append(json.loads(r[1]) if isinstance(r[1], str) else r[1])
        cur.execute("SELECT k, v FROM meta")
        for r in cur.fetchall():
            v = json.loads(r[1]) if isinstance(r[1], str) else r[1]
            if r[0] == "admin":
                db["admin"] = v
            elif r[0] == "stats":
                db["stats"] = v
        return db
    finally:
        conn.close()


def mysql_save_db(db: dict, cfg: dict = None) -> None:
    cfg = cfg or mysql_cfg()
    conn = mysql_connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM users")
        for u in db["users"].values():
            cur.execute(
                "INSERT INTO users (email, name, salt, pw_hash, tier, created, saved, shopping_list, scrapes, custom, list_cursor) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (u["email"], u["name"], u["salt"], u["hash"], u.get("tier", "free"), u.get("created", 0),
                 json.dumps(u.get("saved", [])), json.dumps(u.get("list", [])),
                 json.dumps(u.get("scrapes", [])), json.dumps(u.get("custom", [])), u.get("listCursor", 1000)))
        cur.execute("DELETE FROM sessions")
        for tok, email in db["sessions"].items():
            cur.execute("INSERT INTO sessions (token, email) VALUES (%s,%s)", (tok, email))
        cur.execute("DELETE FROM recipes")
        for slug, rec in db["recipes"].items():
            cur.execute("INSERT INTO recipes (slug, data, added) VALUES (%s,%s,%s)",
                        (slug, json.dumps(rec, ensure_ascii=False), rec.get("added", 0)))
        cur.execute("DELETE FROM substitutions")
        for s in db["substitutions"]:
            cur.execute("INSERT INTO substitutions (ing_id, data) VALUES (%s,%s)",
                        (s["id"], json.dumps(s, ensure_ascii=False)))
        cur.execute("DELETE FROM affiliate_stores")
        for s in db["aff"]["stores"]:
            cur.execute("INSERT INTO affiliate_stores (id, data) VALUES (%s,%s)",
                        (s["id"], json.dumps(s, ensure_ascii=False)))
        cur.execute("DELETE FROM affiliate_products")
        for p in db["aff"]["products"]:
            cur.execute("INSERT INTO affiliate_products (id, store, data) VALUES (%s,%s,%s)",
                        (p["id"], p.get("store", ""), json.dumps(p, ensure_ascii=False)))
        cur.execute("DELETE FROM affiliate_links")
        for code, l in db["aff"]["links"].items():
            cur.execute("INSERT INTO affiliate_links (code, product, created) VALUES (%s,%s,%s)",
                        (code, l.get("product", ""), l.get("created", 0)))
        cur.execute("DELETE FROM affiliate_clicks")
        if db["aff"]["clicks"]:
            cur.executemany("INSERT INTO affiliate_clicks (ts, code, path) VALUES (%s,%s,%s)",
                            [(c["ts"], c["code"], c.get("path", "")) for c in db["aff"]["clicks"]])
        cur.execute("DELETE FROM feeds")
        for f in db["feeds"]:
            cur.execute("INSERT INTO feeds (id, data) VALUES (%s,%s)",
                        (f["id"], json.dumps(f, ensure_ascii=False)))
        cur.execute("DELETE FROM posts")
        for p in db["posts"]:
            cur.execute("INSERT INTO posts (id, data) VALUES (%s,%s)",
                        (p["id"], json.dumps(p, ensure_ascii=False)))
        cur.execute("DELETE FROM meta")
        cur.execute("INSERT INTO meta (k, v) VALUES (%s,%s)", ("admin", json.dumps(db["admin"], ensure_ascii=False)))
        cur.execute("INSERT INTO meta (k, v) VALUES (%s,%s)", ("stats", json.dumps(db.get("stats", {}), ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def load_db() -> dict:
    if mysql_active():
        try:
            return mysql_load_db(mysql_cfg())
        except Exception as e:  # noqa: BLE001
            print("MySQL read failed, falling back to JSON store: %s" % e)
    return _load_json_db()


def save_db(db: dict) -> None:
    _save_json_db(db)  # always keep a JSON mirror (hot backup + offline fallback)
    if mysql_active():
        try:
            mysql_save_db(db)
        except Exception as e:  # noqa: BLE001
            print("MySQL write failed (JSON mirror updated): %s" % e)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "recipe"


def strip_tags(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", "\n", s)
    s = htmllib.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def unique_slug(db: dict, base: str) -> str:
    slug = slugify(base)
    n = 2
    while slug in db["recipes"]:
        slug = f"{slug}-{n}"
        n += 1
    return slug


# ----------------------------------------------------------------------------- seeding
def seed_db() -> dict:
    with open(os.path.join(DATA_DIR, "recipes.json"), encoding="utf-8") as f:
        recipes = json.load(f)
    with open(os.path.join(DATA_DIR, "substitutions.json"), encoding="utf-8") as f:
        subs = json.load(f)

    users = {}

    def add_user(email, name, pw, tier="free"):
        salt = secrets.token_hex(16)
        users[email] = {
            "email": email, "name": name, "salt": salt, "hash": hash_pw(pw, salt),
            "tier": tier, "created": time.time() - 40 * 86400,
            "saved": [], "list": [], "scrapes": [], "custom": [], "listCursor": 1000,
        }

    add_user("demo@theplatescraper.com", "Dana Cooks", "demo1234", "premium")
    add_user("admin@theplatescraper.com", "Site Owner", "plate-admin-2026", "legend")
    users["demo@theplatescraper.com"]["saved"] = ["one-pot-lemon-garlic-butter-chicken", "creamy-coconut-chickpea-curry"]
    users["demo@theplatescraper.com"]["scrapes"] = [
        {"ts": time.time() - 86400 * 3, "title": "Weeknight Honey-Broth Chicken Thighs", "source": "butterandbasil.example"},
        {"ts": time.time() - 86400 * 1, "title": "Sunday Gravy Over Pappardelle", "source": "nonnanotes.example"},
    ]

    stores = [
        {"id": "st-amazon", "name": "Amazon", "program": "Amazon Associates", "id_ref": "theplatescraper-20", "rate": 0.04, "color": "#FF9900"},
        {"id": "st-walmart", "name": "Walmart", "program": "Walmart Affiliate", "id_ref": "T8842-TPS", "rate": 0.05, "color": "#0071CE"},
        {"id": "st-target", "name": "Target", "program": "Target Partner", "id_ref": "tps7731", "rate": 0.05, "color": "#CC0000"},
        {"id": "st-williams", "name": "Williams Sonoma", "program": "Impact Network", "id_ref": "458812-19", "rate": 0.08, "color": "#1B3A5C"},
        {"id": "st-lob", "name": "Lodge Cast Iron", "program": "CJ Affiliate", "id_ref": "T40233-114", "rate": 0.10, "color": "#333333"},
    ]
    products = [
        {"id": "p-dutch", "store": "st-williams", "name": "5-Qt Enameled Cast Iron Dutch Oven", "price": 350.00, "note": "Weeknight soups & stews", "slug_tag": "chili-mac"},
        {"id": "p-skill", "store": "st-lob", "name": "Lodge 10.25\" Black Cast Iron Skillet", "price": 39.95, "note": "Chicken parmesan, fajitas", "slug_tag": "cast-iron-chicken-parmesan"},
        {"id": "p-tongs", "store": "st-amazon", "name": "10\" Stainless Steel Tongs", "price": 14.99, "note": "Sheet pan flipping", "slug_tag": "sheet-pan-sausage"},
        {"id": "p-thermo", "store": "st-walmart", "name": "Instant-Read Digital Thermometer", "price": 24.50, "note": "Pull chicken at 165°F", "slug_tag": "one-pot-lemon-garlic-butter-chicken"},
        {"id": "p-board", "store": "st-target", "name": "Acacia Cutting Board 18×12", "price": 42.99, "note": "Knife-skills corner", "slug_tag": "creamy-tuscan-chicken-gnocchi"},
        {"id": "p-colander", "store": "st-amazon", "name": "Stainless Colander 12\"", "price": 21.75, "note": "Pasta & orzo", "slug_tag": "15-minute-pesto-orzo"},
        {"id": "p-whisk", "store": "st-walmart", "name": "Balloon Whisk 6\"", "price": 9.48, "note": "Honey-soy glaze", "slug_tag": "crispy-honey-soy-salmon"},
        {"id": "p-spice", "store": "st-target", "name": "Curry Spice Sampler (6 jars)", "price": 28.00, "note": "Coconut curry night", "slug_tag": "creamy-coconut-chickpea-curry"},
    ]
    links = {
        "go-8fk2": {"product": "p-dutch", "created": time.time() - 20 * 86400},
        "go-3pmq": {"product": "p-skill", "created": time.time() - 20 * 86400},
        "go-9rtd": {"product": "p-tongs", "created": time.time() - 16 * 86400},
        "go-4wxn": {"product": "p-thermo", "created": time.time() - 12 * 86400},
        "go-7hcb": {"product": "p-board", "created": time.time() - 12 * 86400},
        "go-2jas": {"product": "p-colander", "created": time.time() - 8 * 86400},
        "go-6vyf": {"product": "p-whisk", "created": time.time() - 8 * 86400},
        "go-5klz": {"product": "p-spice", "created": time.time() - 4 * 86400},
    }

    # Deterministic demo click history (last 14 days).
    rng = random.Random(20260903)
    clicks = []
    weights = {"go-8fk2": 5, "go-3pmq": 9, "go-9rtd": 6, "go-4wxn": 8,
               "go-7hcb": 4, "go-2jas": 7, "go-6vyf": 5, "go-5klz": 10}
    pool = [c for c, w in weights.items() for _ in range(w)]
    for _ in range(148):
        code = rng.choice(pool)
        ts = time.time() - rng.randint(0, 14 * 24 * 60 * 60)
        clicks.append({"ts": ts, "code": code, "path": rng.choice(["/gear", "/recipe/" + "chili-mac", "/recipe/cast-iron-chicken-parmesan", "/home"])})
    clicks.sort(key=lambda c: c["ts"])

    def add_feed(fid, name, site, url, owner, hours_ago):
        return {
            "id": fid, "name": name, "site": site, "url": url,
            "owner": owner, "added": time.time() - 90 * 86400,
            "lastCheck": time.time() - hours_ago * 3600,
            "items": [], "demo": True,
        }

    def feed_item(rid, title, author, hours_ago, link, content, recipe=True):
        return {"id": rid, "title": title, "author": author,
                "ts": time.time() - hours_ago * 3600, "link": link,
                "content": content, "recipe": recipe, "read": False, "rewritten": False}

    feeds = [
        add_feed("feed-butterbasil", "Butter & Basil Kitchen", "butterandbasil.example",
                 "https://butterandbasil.example/feed", "admin@theplatescraper.com", 2),
        add_feed("feed-nonnanotes", "Nonna's Notes", "nonnanotes.example",
                 "https://nonnanotes.example/rss", "admin@theplatescraper.com", 5),
        add_feed("feed-ninefiv", "The 9-to-5 Chef", "ninefiv.chef",
                 "https://ninefiv.chef/feed.xml", "admin@theplatescraper.com", 26),
    ]
    feeds[0]["items"] = [
        feed_item("bb-1", "Weeknight Honey-Broth Chicken Thighs", "Marta Reyes", 26,
                  "https://butterandbasil.example/honey-broth-chicken",
                  "<p>A 30-minute saucy skillet dinner that lives on repeat. Brown the thighs, deglaze with broth, and finish with honey, lemon and butter until the sauce turns glossy. Serve over rice, polenta, or toast if you want to scrape the pan, which you will.</p>"
                  "<ul class='ingredients'><li>4 bone-in, skin-on chicken thighs</li><li>2 tablespoons olive oil</li>"
                  "<li>1/2 yellow onion, diced</li><li>3 cloves garlic, smashed</li><li>1 teaspoon dried thyme</li>"
                  "<li>1.5 cups chicken broth</li><li>2 tablespoons honey</li><li>1 lemon, halved</li></ul>"
                  "<ol class='instructions'><li>Pat the chicken dry and season it well.</li>"
                  "<li>Sear the thighs skin-side down until deep golden, then flip.</li>"
                  "<li>Soften the onion and garlic in the same pan.</li>"
                  "<li>Add the broth and honey, nestle the chicken back in, and simmer until cooked through and saucy.</li>"
                  "<li>Finish with lemon and parsley.</li></ol>"),
        feed_item("bb-2", "A Pantry Tour: 12 Things I Never Let Run Out", "Marta Reyes", 72,
                  "https://butterandbasil.example/pantry-tour",
                  "<p>My pantry has about 12 workhorse items and if any of them run low I treat it like a fire alarm. They range from good olive oil to the kind of stock you can buy once and feel rich for a month. Here's the list, in order of how badly I need each one.</p>"),
        feed_item("bb-3", "Charred Corn and Cotija Salsa, 10 Minutes Flat", "Marta Reyes", 96,
                  "https://butterandbasil.example/charred-corn-salsa",
                  "<p>Char corn on a ripping-hot grill, shave the kernels off, and chop them with cotija, lime, cilantro, and a little chili powder. It is the salsa version of a standing ovation. Serve it on everything, including things it should probably not go on.</p>"
                  "<ul class='ingredients'><li>4 ears corn, husked</li><li>1/2 cup cotija, crumbled</li>"
                  "<li>1 lime, juiced</li><li>1/4 cup cilantro, chopped</li><li>1/2 tsp chili powder</li><li>1 small jalapeno, minced</li></ul>"
                  "<ol class='instructions'><li>Char the corn on a very hot grill until blackened in spots.</li>"
                  "<li>Shave the kernels off the cob.</li>"
                  "<li>Chop everything together, season, and taste for salt.</li></ol>"),
        feed_item("bb-4", "Why Your Soups Taste Flat (It's Not Salt, It's Acid)", "Marta Reyes", 150,
                  "https://butterandbasil.example/soup-acid",
                  "<p>Half the time when a soup tastes flat it isn't missing salt, it's missing acid. A squeeze of lemon, a splash of vinegar, or even a spoonful of tomato paste wakes a whole pot up. Here's how I diagnose a dull soup in under a minute, and the order in which I reach for fixes.</p>"),
    ]
    feeds[1]["items"] = [
        feed_item("nn-1", "Sunday Gravy Over Pappardelle, the Honest Version", "Rosa Marchetti", 40,
                  "https://nonnanotes.example/sunday-gravy",
                  "<p>Nonna's gravy is not a secret. It is time, meat, tomatoes, and patience. I make mine in four hours instead of five and it still makes the whole apartment smell like Sunday. Pappardelle is the only pasta I will serve it over. The wide noodle needs the sauce the way the sauce needs the noodle.</p>"
                  "<ul class='ingredients'><li>1 lb pork shoulder, cut into cubes</li><li>1/2 lb beef short rib, cut into chunks</li>"
                  "<li>1/2 lb Italian sausage, crumbled</li><li>2 cans San Marzano tomatoes, crushed by hand</li>"
                  "<li>1 onion, diced</li><li>4 cloves garlic, sliced</li><li>2 carrots, sliced</li>"
                  "<li>1/2 cup dry red wine</li><li>12 oz fresh pappardelle</li><li>1/2 cup grated pecorino</li></ul>"
                  "<ol class='instructions'><li>Brown the pork and beef in a big pot, in batches, over high heat.</li>"
                  "<li>Crack the sausage in and brown it too.</li>"
                  "<li>Soften the onion and garlic, add the wine, and let it bubble down.</li>"
                  "<li>Add tomatoes, carrots, a pinch of sugar, and the bay. Simmer 3 hours, stirring now and then.</li>"
                  "<li>Cook the pappardelle, ladle the gravy over it, and shower it with pecorino.</li></ol>"),
        feed_item("nn-2", "Olive Oil Focaccia You Can Make With a Rolling Pin", "Rosa Marchetti", 110,
                  "https://nonnanotes.example/olive-oil-focaccia",
                  "<p>You do not need dough hooks or a fancy proofing box for focaccia. You need a big bowl, a rolling pin, and the patience to let the dough rest. I punch the dimples with olive oil soaked fingers and press in cherry tomatoes and flaky salt. Out of the oven it is soft, oily, and gone in ten minutes.</p>"
                  "<ul class='ingredients'><li>3 cups bread flour</li><li>1/2 tsp instant yeast</li><li>1 tsp salt</li>"
                  "<li>1 cup warm water</li><li>1/2 cup good olive oil, plus more</li><li>1 cup cherry tomatoes, halved</li>"
                  "<li>Flaky salt</li><li>Fresh rosemary</li></ul>"
                  "<ol class='instructions'><li>Mix the flour, yeast, salt, water, and half the oil into a sticky dough.</li>"
                  "<li>Rest 30 minutes, then turn out and roll into a 12-inch round on a sheet pan.</li>"
                  "<li>Brush with the rest of the oil and rest until puffy, about an hour.</li>"
                  "<li>Dimple, press in tomatoes, and shower with salt and rosemary.</li>"
                  "<li>Bake at 450 degrees for 18-20 minutes until deeply golden.</li></ol>"),
        feed_item("nn-3", "What My Grandmother Knew About Bread", "Rosa Marchetti", 170,
                  "https://nonnanotes.example/grandmothers-bread",
                  "<p>Nonna never measured a thing. She knew by the sound the dough made when she slapped it, and she knew the oven by the way it held heat. I have written down the few rules she actually said out loud, and they still work better than any technique I have read since. Dough should be lively, not perfect.</p>"),
    ]
    feeds[2]["items"] = [
        feed_item("nf-1", "30-Minute Salsa Verde Chicken Bowl", "Jordan Ellis", 28,
                  "https://ninefiv.chef/salsa-verde-chicken-bowl",
                  "<p>Between the last meeting and the school pickup I have exactly thirty minutes, and this bowl is the plan. Salsa verde on roasted chicken, rice, black beans, and avocado. Nothing on the list is hard to find, and the only thing that matters is the corn.</p>"
                  "<ul class='ingredients'><li>4 chicken thighs, boneless</li><li>3/4 cup tomatillo salsa verde</li>"
                  "<li>2 cups cooked rice</li><li>1 can black beans, rinsed</li><li>1 avocado, sliced</li>"
                  "<li>1 lime, cut into wedges</li><li>1/2 cup shredded cheese</li><li>1 tsp chili powder</li></ul>"
                  "<ol class='instructions'><li>Season the chicken with chili powder and sear it in a hot skillet until golden.</li>"
                  "<li>Spoon the salsa over the chicken, cover, and cook until it reaches 165 degrees.</li>"
                  "<li>Build bowls with rice, beans, avocado, and the salsa-lacquered chicken.</li>"
                  "<li>Top with cheese and a big squeeze of lime.</li></ol>"),
        feed_item("nf-2", "The 4 Spices That Do 80% of the Work in My Kitchen", "Jordan Ellis", 96,
                  "https://ninefiv.chef/four-spices",
                  "<p>I have pared my spice rack down to four jars and I am not sorry: smoked paprika, cumin, a good curry powder, and black pepper. Together they cover chili, curry, sheet pan vegetables, eggs, and anything that needs to stop tasting like a cafeteria tray. Here is how I use each one without thinking.</p>"),
        feed_item("nf-3", "Sheet Pan Fish Tacos Before the Kids Are Home", "Jordan Ellis", 160,
                  "https://ninefiv.chef/sheet-pan-fish-tacos",
                  "<p>Crispy fish on a sheet pan, a five-ingredient lime crema, and the taco fixings all ready before 5 p.m. The fish gets cornstarch for the shatter and paprika for color. The crema is the part everyone steals from the bowl, so make double.</p>"
                  "<ul class='ingredients'><li>1 lb white fish fillets, cut in chunks</li><li>3 tbsp cornstarch</li>"
                  "<li>1 tsp smoked paprika</li><li>1 cup sour cream</li><li>2 limes, juiced</li>"
                  "<li>1/4 cup cilantro, chopped</li><li>12 small corn tortillas</li><li>1 cup cabbage, shredded</li></ul>"
                  "<ol class='instructions'><li>Toss the fish with cornstarch, paprika, and salt; spread on a sheet pan.</li>"
                  "<li>Bake at 450 degrees for 10-12 minutes until crisp at the edges.</li>"
                  "<li>Whisk the sour cream, lime juice, and cilantro into a crema.</li>"
                  "<li>Warm the tortillas, pile on cabbage, fish, and crema, and eat immediately.</li></ol>"),
    ]

    # Two posts the owner has already rewritten + published from the feeds,
    # so the public blog has content from day one.
    posts = []
    for i, (feed, idx, days_ago) in enumerate(((feeds[1], 0, 6), (feeds[2], 1, 12))):
        it = feed["items"][idx]
        r = rewrite_post(it["title"], it["content"], feed["site"], it["author"], it["link"])
        posts.append({
            "id": "post-seed%d" % i, "title": r["newTitle"], "intro": r["intro"],
            "body": r["body"], "houseNote": r["houseNote"], "signoff": r["signoff"],
            "credit": r["credit"], "tags": r["tags"], "status": "published",
            "sourceLink": r["sourceLink"], "author": "admin@theplatescraper.com",
            "ts": time.time() - days_ago * 86400,
        })

    return {
        "users": users,
        "sessions": {},
        "recipes": {r["slug"]: r for r in recipes},
        "substitutions": subs,
        "aff": {"stores": stores, "products": products, "links": links, "clicks": clicks},
        "admin": {"email": "admin@theplatescraper.com", "name": "Site Owner",
                  "salt": "seeded-salt", "hash": hash_pw("plate-admin-2026", "seeded-salt")},
        "feeds": feeds,
        "posts": posts,
        "stats": {"scrapes_served": 1243, "rewrites": 212, "members": 1873},
    }


# ----------------------------------------------------------------------------- scraper
SAMPLE_PAGE = """<!doctype html>
<html><head><title>Weeknight Honey-Broth Chicken Thighs - Butter &amp; Basil Kitchen</title>
<meta property="og:title" content="Weeknight Honey-Broth Chicken Thighs">
<meta property="og:site_name" content="Butter &amp; Basil Kitchen">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Recipe","name":"Weeknight Honey-Broth Chicken Thighs",
"author":{"@type":"Person","name":"Marta Reyes"},
"recipeYield":"4 servings","totalTime":"PT30M",
"ingredients":["4 bone-in, skin-on chicken thighs","2 tablespoons olive oil","1/2 yellow onion, diced",
"3 cloves garlic, smashed","1 teaspoon dried thyme","1/2 teaspoon black pepper","1.5 cups chicken broth",
"2 tablespoons honey","1 lemon, halved","Fresh parsley, for garnish"],
"recipeInstructions":["Pat the chicken dry and season both sides generously with salt.",
"Heat the olive oil in a large skillet over medium-high heat. Sear the thighs, skin-side down, 6 minutes, until deep golden.",
"Flip and cook 3 minutes more. Remove to a plate.",
"In the same pan, soften the onion with the garlic, thyme and pepper, 3 minutes.",
"Pour in the broth and honey, scrape up the browned bits, and nestle the chicken back in. Simmer uncovered 10-12 minutes, until the thighs reach 165F and the sauce thickens to a glaze.",
"Squeeze the lemon over everything and scatter with parsley. Serve with whatever you can scrape into a bowl."]}
</script></head>
<body><h1>Weeknight Honey-Broth Chicken Thighs</h1>
<p>A 30-minute saucy skillet dinner — browned butter, honey and broth pulled together.</p>
<ul id="ingredient__list"><li>4 bone-in, skin-on chicken thighs</li>
<li>2 tablespoons olive oil</li><li>1/2 yellow onion, diced</li><li>3 cloves garlic, smashed</li>
<li>1 teaspoon dried thyme</li><li>1/2 teaspoon black pepper</li><li>1.5 cups chicken broth</li>
<li>2 tablespoons honey</li><li>1 lemon, halved</li><li>Fresh parsley, for garnish</li></ul>
<ol id="instructions__list"><li>Pat the chicken dry and season both sides generously with salt.</li>
<li>Heat the olive oil in a large skillet over medium-high heat. Sear the thighs, skin-side down, 6 minutes, until deep golden.</li>
<li>Flip and cook 3 minutes more. Remove to a plate.</li>
<li>In the same pan, soften the onion with the garlic, thyme and pepper, 3 minutes.</li>
<li>Pour in the broth and honey, scrape up the browned bits, and nestle the chicken back in. Simmer uncovered 10-12 minutes.</li>
<li>Squeeze the lemon over everything and scatter with parsley.</li></ol>
</body></html>"""

NUM = r"(?:\d+(?:[./]\d+)?)?\s*(?:\d+/\d+|\d+(?:[./]\d+)?)?"
QTY_RE = re.compile(r"^\s*(" + NUM + r")\s+(.+)$", re.I)
UNIT_RE = re.compile(
    r"^(each|large|medium|small|whole|slice|slices|cup|cups|tbsp|tsp|oz|lb|lbs|g|kg|ml|pinch|cloves?|stalks?|head|bunch|can|cans|packet|packets|bundle|sprig|sprigs|leaf|leaves|pound|tablespoons|teaspoons|clove|cloves|head|heads|bunches?|ribbons?|scoop|scoops|dash|splash|stick|sticks|wedge|wedges|ear|ears|clove|clove|pinch|pinches|serving|servings)\b", re.I)


def split_ingredient(line: str):
    line = line.strip().strip("-•*").strip()
    if not line:
        return None
    m = QTY_RE.match(line)
    if m:
        qty, rest = (m.group(1) or "").strip(), m.group(2).strip()
    else:
        qty, rest = "", line
    if not rest:
        return None
    um = UNIT_RE.match(rest)
    if um:
        unit = um.group(1)
        unit = unit.lower().capitalize() if unit.lower() in ("each", "whole", "pinch", "dash", "splash") else unit.lower()
        item = rest[um.end():].lstrip(" ,")
    else:
        unit, item = "", rest
    item = re.sub(r"\s*\(([^)]*)\)\s*$", r" \1", item).strip()
    if not item:
        return None
    return {"qty": qty, "unit": unit, "item": item}


def qty_to_float(qty: str):
    qty = (qty or "").strip()
    if not qty:
        return None
    if "/" in qty:
        a, b = qty.split("/", 1)
        try:
            return float(a) / float(b)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(qty)
    except ValueError:
        return None


def jsonld_recipes(page: str):
    out = []
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("@type") == "Recipe":
                out.append(it)
            if isinstance(it.get("@graph"), list):
                for g in it["@graph"]:
                    if isinstance(g, dict) and g.get("@type") == "Recipe":
                        out.append(g)
            if isinstance(it.get("mainEntity"), dict) and it["mainEntity"].get("@type") == "Recipe":
                out.append(it["mainEntity"])
    return out


def ld_ingredients(rec: dict):
    items = rec.get("ingredients", [])
    out = []
    for raw in items:
        if isinstance(raw, dict):
            raw = raw.get("name") or raw.get("text") or ""
        s = split_ingredient(str(raw))
        if s:
            out.append(s)
    return out


def ld_steps(rec: dict):
    def walk(steps):
        out = []
        for s in steps or []:
            if isinstance(s, str):
                out.append(s.strip())
            elif isinstance(s, dict):
                t = (s.get("text") or "").strip()
                if t:
                    out.append(t)
                if s.get("itemsListElement"):
                    out.extend(walk(s["itemsListElement"]))
        return out
    return walk(rec.get("recipeInstructions")) or walk(rec.get("instructions"))


def html_meta(page: str):
    title = ""
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', page, re.I)
    if not m:
        m = re.search(r'<title[^>]*>(.*?)</title>', page, re.S | re.I)
    if m:
        title = strip_tags(m.group(1))
    site = ""
    m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\'](.*?)["\']', page, re.I)
    if m:
        site = htmllib.unescape(m.group(1))
    author = ""
    m = re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\'](.*?)["\']', page, re.I)
    if m:
        author = htmllib.unescape(m.group(1))
    return title, site, author


def html_blocks(page: str):
    """Find ingredient <ul>/<ol> and step <ol>/<ul> blocks from raw HTML."""
    ings, steps = [], []
    blocks = re.findall(r"(<(?:ul|ol)\b[^>]*>.*?</(?:ul|ol)>)", page, re.S | re.I)

    def is_ingredienty(lis):
        good, total = 0, 0
        for li in lis:
            t = strip_tags(li)
            if not t:
                continue
            total += 1
            if QTY_RE.match(t) or UNIT_RE.match(t) or re.match(r"^[A-Za-zÀ-ÿ]+( [a-zà-ÿ]+){0,5}$", t):
                good += 1
        return total >= 3 and good / max(total, 1) >= 0.5

    def parse_items(block):
        items = [strip_tags(x).strip() for x in re.findall(r"<li[^>]*>(.*?)</li>", block, re.S | re.I)]
        return [i for i in items if i]

    for block in blocks:
        items = parse_items(block)
        if not items:
            continue
        head = page[max(0, page.find(block) - 400):page.find(block)]
        heading = strip_tags(re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", head, re.S | re.I)[-1]) if re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", head, re.S | re.I) else ""
        low = (block + heading).lower()
        if "ingredient" in low:
            if not ings:
                ings = items
        elif re.search(r"instruction|direction|method|step|preparation", low) and not steps:
            steps = items
        elif not ings and is_ingredienty(items) and len(items) >= 4:
            ings = items
        elif not steps and block.lower().startswith("<ol") and len(items) >= 3:
            steps = items
    return ings, steps


def scrape_plain_text(text: str):
    lines = [l.strip() for l in text.splitlines()]
    ings, steps, title, servings = [], [], "", None
    mode, ing_header, step_header = None, None, None
    for raw in lines:
        l = raw.strip()
        if not l:
            continue
        low = l.lower()
        if re.match(r"^(ingredients?|serves?|makes?|prep)\b", low) or low in ("ingredients", "ingredient list"):
            mode = "ings" if "ingredient" in low else mode
            if "serv" in low or "makes" in low:
                m = re.search(r"(\d+)", l)
                if m:
                    servings = int(m.group(1))
            continue
        if re.match(r"^(instructions?|directions?|method|steps?|how to make)\b", low):
            mode = "steps"
            continue
        if mode is None:
            if len(l) > 4 and not QTY_RE.match(l) and len(l.split()) <= 10:
                title = l.rstrip(":")
            continue
        if mode == "ings":
            s = split_ingredient(l)
            if s:
                ings.append(s)
        else:
            s = re.sub(r"^\d+[.)]\s*", "", l)
            if s:
                steps.append(s)
    return {"title": title, "servings": servings, "ingredients": ings, "steps": steps}


def scrape_html(page: str, url: str = "", source: str = ""):
    warnings = []
    recs = jsonld_recipes(page)
    ings, steps, title, site, author = [], [], "", "", ""
    servings = None
    if recs:
        rec = recs[0]
        title = rec.get("name") or ""
        ings = ld_ingredients(rec)
        steps = ld_steps(rec)
        yield_raw = rec.get("recipeYield") or rec.get("yield") or ""
        if isinstance(yield_raw, list):
            yield_raw = yield_raw[0] if yield_raw else ""
        m = re.search(r"(\d+)", str(yield_raw))
        servings = int(m.group(1)) if m else None
        if isinstance(rec.get("author"), dict):
            author = rec["author"].get("name", "")
        elif isinstance(rec.get("author"), str):
            author = rec["author"]
    else:
        title, site, author = html_meta(page)
        ings, steps = html_blocks(page)
    if not ings:
        plain = scrape_plain_text(strip_tags(page))
        ings, steps = plain["ingredients"], plain["steps"]
        title = title or plain["title"]
        servings = servings or plain["servings"]
    if servings is None:
        m = re.search(r"(?:serves?|makes?|yield|servings?)[:\s]+(\d+)", page, re.I)
        if m:
            servings = int(m.group(1))
    ings = [i if isinstance(i, dict) else split_ingredient(i) for i in ings]
    ings = [i for i in ings if i]
    if not title:
        title = "Scraped Recipe"
    if not source:
        source = site or (urlparse(url).netloc if url else "")
    if not ings:
        warnings.append("No ingredient list found — fill it in by hand below.")
    if not steps:
        warnings.append("No step-by-step instructions found.")
    m = re.search(r"(?:(\d+)\s*min|PT(\d+)M|(\d+)[\s-]*minutes?)", page, re.I)
    cook_time = None
    if m:
        for g in (m.group(1), m.group(2), m.group(3)):
            if g is None:
                continue
            try:
                cook_time = int(g)
                break
            except ValueError:
                pass
    return {
        "title": title, "source": source, "url": url, "author": author,
        "servings": servings, "cookTime": cook_time, "ingredients": ings, "steps": steps,
        "warnings": warnings,
    }


def scrape_url(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ThePlateScraper/1.0; +https://%s/scraper)" % DOMAIN,
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            page = r.read(2_000_000).decode("utf-8", "ignore")
        return page, None
    except Exception as e:
        return None, str(e)


# ----------------------------------------------------------------------------- RSS
SAMPLE_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Demo Feed — {site}</title>
<link>https://{site}/</link>
<description>Demo RSS feed used inside the preview sandbox</description>
<item>
<title>Sample Recipe Post: Butter-Pan Lemon Salmon</title>
<link>https://{site}/butter-pan-lemon-salmon</link>
<pubDate>{d1}</pubDate>
<author>demo@{site}</author>
<description>&lt;p&gt;A simple pan of salmon in a lemon-butter glaze. &lt;/p&gt;
&lt;ul class='ingredients'&gt;&lt;li&gt;4 salmon fillets&lt;/li&gt;&lt;li&gt;4 tbsp butter&lt;/li&gt;&lt;li&gt;2 lemons, sliced&lt;/li&gt;&lt;li&gt;2 cloves garlic, sliced&lt;/li&gt;&lt;/ul&gt;
&lt;ol class='instructions'&gt;&lt;li&gt;Season the salmon and sear it in a hot pan.&lt;/li&gt;&lt;li&gt;Add butter, lemons, and garlic and baste until cooked.&lt;/li&gt;&lt;/ol&gt;</description>
</item>
<item>
<title>Kitchen Notes: Why I Season My Pasta Water</title>
<link>https://{site}/seasoned-pasta-water</link>
<pubDate>{d2}</pubDate>
<author>demo@{site}</author>
<description>&lt;p&gt;Salted pasta water does more for a sauce than most cooks give it credit for. It seasons the starch from the inside and the starchy water itself becomes part of the sauce. Here is how much I use and why.&lt;/p&gt;</description>
</item>
</channel></rss>"""


def fetch_feed(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ThePlateScraper/1.0; +https://%s/feed)" % DOMAIN,
        "Accept": "application/rss+xml, application/xml, text/xml, text/html",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read(1_500_000).decode("utf-8", "ignore"), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def parse_feed(xml: str):
    items = []
    for block in re.findall(r"<item[\s>].*?</item>", xml, re.S | re.I) or re.findall(
            r"<entry[\s>].*?</entry>", xml, re.S | re.I):
        def grab(tag):
            m = re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), block, re.S | re.I)
            return strip_tags(m.group(1)).strip() if m else ""
        title = grab("title") or "Untitled"
        link = ""
        m = re.search(r"<link[^>]*>(.*?)</link>", block, re.S | re.I) or re.search(
            r'<link[^>]*href=["\']([^"\']+)', block, re.I)
        if m:
            link = m.group(1).strip()
        pub = grab("pubDate") or grab("published") or grab("updated")
        author = grab("dc:creator") or grab("author") or ""
        content = grab("description") or grab("summary") or grab("content:encoded") or grab("content")
        ts = time.time()
        if pub:
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S",
                        "%b %d, %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    ts = time.mktime(time.strptime(pub[:28].strip(), fmt))
                    break
                except ValueError:
                    continue
        low = (content + title).lower()
        is_rec = bool(re.search(r"ingredient", low)) or sum(
            1 for l in content.splitlines() if QTY_RE.match(l.strip())) >= 3
        items.append({"title": title, "link": link, "ts": ts, "author": author,
                      "content": content, "recipe": is_rec})
    items.sort(key=lambda i: i["ts"], reverse=True)
    return items[:25]


def feed_from_url(url: str):
    xml, err = fetch_feed(url)
    if xml:
        return parse_feed(xml), None, False
    netloc = urlparse(url).netloc or "example.com"
    xml = SAMPLE_FEED_XML.format(
        site=netloc,
        d1=time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.localtime(time.time() - 3600 * 26)),
        d2=time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.localtime(time.time() - 3600 * 90)),
    )
    return parse_feed(xml), (
        "Live feed fetching isn't available inside this preview sandbox (%s). "
        "I pulled the channel from a bundled sample so you can see the reader + rewriter end to end. "
        "Deployed at %s it fetches any real RSS/Atom URL." % (err.splitlines()[0][:70], DOMAIN)), True


# ----------------------------------------------------------------------------- rewriter
REWRITE_WORDS = {
    "simmer": "cook gently", "season": "add salt and pepper to taste",
    "whisk": "stir briskly", "toss": "fold it together", "dredge": "coat",
    "sizzle": "hiss", "fragrant": "smelling incredible", "tender": "fall-apart",
    "crispy": "crackly", "crisp": "crackling", "flavorful": "packed with flavor",
    "delicious": "ridiculously good", "tasty": "genuinely good", "gourmet": "special",
    "homemade": "made from scratch", "effortless": "barely-there", "simple": "no-fuss",
    "perfect": "exactly right", "beautiful": "gorgeous", "fresh": "bright",
    "combine": "bring together", "mix": "stir together", "pour": "add in",
    "add": "work in", "grated": "shaved", "diced": "chopped small",
    "minced": "minced fine", "chopped": "roughly chopped", "sliced": "sliced thin",
    "shredded": "shredded fine", "secret": "little trick", "method": "method",
    "dish": "plate", "recipe": "method",
}


def thesaurus_swap(text: str, seed: int) -> str:
    rng = random.Random(seed)
    for word, repl in REWRITE_WORDS.items():
        if repl == word:
            continue
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.I)

        def _sub(m, _r=repl):
            if rng.random() < 0.55:
                v = _r
                if m.group(0)[0].isupper():
                    v = v[0].upper() + v[1:]
                return v
            return m.group(0)

        text = pattern.sub(_sub, text)
    return text


TITLE_TEMPLATES = [
    "{t}, but the way I actually make it on a weeknight",
    "Stealing {t} for my own kitchen (with one important tweak)",
    "The {t} that made me a convert",
    "{t} — my Plate Scraper remix",
    "I made {t} three times in a week. Here's what I changed.",
]
NOTE_TEMPLATES = [
    "{t} — my notes after cooking along",
    "Cooking along with {t} (and what I'd change)",
    "{t}, minus the fluff",
    "I read {t}. Verdict inside.",
]


def _dish_name(title: str) -> str:
    t = re.split(r"\s[—–]\s+", title)[0].strip()
    t = re.sub(r"\s*[\(（].*?[\)）]\s*", " ", t)
    return " ".join(t.split()) or title.strip()
INTRO_TEMPLATES = [
    "This one came through the feed from {site} and I immediately set the radio on to make it. "
    "I cooked it as written, then made a few small calls of my own — the changes are in the notes below.",
    "The original post lives over on {site} and it earned a spot in my rotation in one night. "
    "My version keeps what works and trims the parts that slow a busy week down.",
    "Feeds first, then the stove: this recipe hit my reader on {site} and it's been on the stove twice since.",
]
HOUSE_NOTES = [
    "House note: I double the {x} every time and it's the only change that matters.",
    "House note: if it's a one-person kitchen, halve the {x} and you're still better off.",
    "House note: the {x} goes in at the very end here, and it changes everything.",
    "House note: use the best {x} you have. This is one of the rare recipes where it shows.",
]
SIGNOFF = "— The Plate Scraper kitchen (adapted with permission of the internet's best cooks)"


def rewrite_post(title: str, content_html: str, site: str, author: str, link: str):
    plain = strip_tags(content_html)
    seed = sum(ord(c) for c in title) % 100000
    rec = None
    if re.search(r"ingredient", plain, re.I) or len(plain) > 200:
        parsed = scrape_html(content_html, url=link, source=site)
        if parsed["ingredients"]:
            rec = parsed
    dish = _dish_name(title)
    if len(dish) > 60:
        dish = dish[:60]
    templates = TITLE_TEMPLATES if rec else NOTE_TEMPLATES
    new_title = templates[seed % len(templates)].format(t=dish)
    intro = INTRO_TEMPLATES[(seed // 3) % len(INTRO_TEMPLATES)].format(site=site or "a recipe blog")
    paras = [p.strip() for p in re.split(r"\n\s*\n|\.</p>|</li>", plain) if len(p.strip()) > 40]
    body = []
    for i, p in enumerate(paras[:6]):
        if rec and rec["steps"] and i >= max(1, len(paras) // 2):
            break
        body.append(thesaurus_swap(p, seed + i))
    if rec and rec["steps"]:
        body.append("The steps, in my words: " + " ".join(
            thesaurus_swap(s, seed + 40 + i) for i, s in enumerate(rec["steps"][:4])))
    first_ing = rec["ingredients"][0]["item"].split(",")[0].strip() if rec and rec["ingredients"] else "aromatics"
    note = HOUSE_NOTES[(seed // 7) % len(HOUSE_NOTES)].format(x=first_ing)
    tags = (["recipe", "rewritten"] if rec else ["kitchen-notes", "rewritten"])
    return {
        "newTitle": new_title,
        "intro": intro,
        "body": body,
        "houseNote": note,
        "signoff": SIGNOFF,
        "credit": "Adapted from “%s”%s on %s" % (
            title, " by " + author if author else "", site or "an RSS feed"),
        "tags": tags,
        "recipe": rec,
        "sourceLink": link,
    }


# ----------------------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PlateScraper/1.0"

    # ---- plumbing -----------------------------------------------------------
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, obj, code=200, headers=None):
        self._send(code, obj, headers=headers)

    def _body_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _cookie(self, name):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        m = c.get(name)
        return m.value if m else None

    def _db_user(self, db):
        tok = self._cookie("tps")
        if not tok:
            return None
        email = db["sessions"].get(tok)
        return db["users"].get(email) if email else None

    def _public_user(self, u):
        if not u:
            return None
        return {
            "email": u["email"], "name": u["name"], "tier": u["tier"],
            "saved": u["saved"], "scrapes": u["scrapes"][-10:],
            "created": u["created"], "is_admin": u["email"] == db_admin_email(),
        }

    def _is_owner(self):
        tok = self._cookie("tps")
        with LOCK:
            db = load_db()
        sess = db["sessions"].get(tok, "")
        if sess.startswith("ADMIN:"):
            return True
        u = self._db_user(db)
        return bool(u and u["email"] == db_admin_email())

    def _404(self):
        self._json({"ok": False, "error": "Not found"}, 404)

    # ---- routing ------------------------------------------------------------
    def do_GET(self):
        try:
            self._route("GET")
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": f"Server error: {e}"}, 500)

    def do_POST(self):
        try:
            self._route("POST")
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": f"Server error: {e}"}, 500)

    def _route(self, method):
        path = urlparse(self.path).path
        q = parse_qs(urlparse(self.path).query)

        if path == "/healthz":
            return self._json({"ok": True, "uptime": int(time.time() - T0)})

        # tracked affiliate redirect (server-side click logging)
        m = re.fullmatch(r"/go/([a-z0-9-]+)", path)
        if m and method == "GET":
            return self._track_redirect(m.group(1))

        # recipe detail pretty-URL
        m = re.fullmatch(r"/recipe/([a-z0-9-]+)", path)
        if m:
            self._serve_static(os.path.join(PAGES, "recipe.html"))
            return
        if path == "/":
            return self._serve_static(os.path.join(PAGES, "index.html"))

        if path.startswith("/api/"):
            return self._api(method, path, q)

        if path.startswith("/static/") or path in ("/style.css", "/app.js") or path.startswith("/images/"):
            if path in ("/style.css", "/app.js"):
                return self._serve_static(os.path.join(STATIC, path.lstrip("/")))
            if path.startswith("/static/"):
                return self._serve_static(os.path.join(STATIC, path[len("/static/"):]))
            if path.startswith("/images/"):
                return self._serve_static(os.path.join(STATIC, "images", path[len("/images/"):]))
        # HTML pages at root
        if path.endswith(".html"):
            return self._serve_static(os.path.join(PAGES, path.lstrip("/")))
        self._404()

    def _serve_static(self, fp):
        if not os.path.isfile(fp):
            return self._404()
        ext = os.path.splitext(fp)[1].lower()
        with open(fp, "rb") as f:
            data = f.read()
        self._send(200, data, MIME.get(ext, "application/octet-stream"))

    # ---- affiliate ----------------------------------------------------------
    def _track_redirect(self, code):
        with LOCK:
            db = load_db()
            link = db["aff"]["links"].get(code)
            if link:
                db["aff"]["clicks"].append({"ts": time.time(), "code": code, "path": "go"})
                save_db(db)
        if not link:
            return self._json({"ok": False, "error": "Unknown link code"}, 404)
        product = next((p for p in link_products(db) if p["id"] == link["product"]), None)
        url = (product or {}).get("dest_url") or "https://theplatescraper.com/gear.html"
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- API ----------------------------------------------------------------
    def _api(self, method, path, q):
        p = path[len("/api/"):]
        b = self._body_json() if method == "POST" else {}

        # --- owner check + owner-only tooling (scraper, feed room, wizard) ---
        if p == "owner" and method == "GET":
            return self._json({"ok": True, "owner": self._is_owner()})
        if p == "scrape" or p == "scrape/save" or p.startswith("rss/"):
            if not self._is_owner():
                return self._json({"ok": False, "error": "Owner tools — sign in with the site owner account."}, 401)
        if p.startswith("setup/") and p not in ("setup/status", "setup/schema"):
            if not self._is_owner():
                return self._json({"ok": False, "error": "Owner tools — sign in with the site owner account."}, 401)

        # --- public blog (posts the owner publishes from the Feed Room) ---
        if p == "blog" and method == "GET":
            with LOCK:
                db = load_db()
            posts = [x for x in db.get("posts", []) if x.get("status") == "published"]
            posts.sort(key=lambda x: x.get("ts", 0), reverse=True)
            self._json({"ok": True, "posts": posts})
            return

        m = re.fullmatch(r"blog/([\w-]+)", p)
        if m and method == "GET":
            with LOCK:
                db = load_db()
            post = next((x for x in db.get("posts", [])
                         if x["id"] == m.group(1) and x.get("status") == "published"), None)
            if not post:
                return self._404()
            self._json({"ok": True, "post": post})
            return

        # --- auth ---
        if p == "register" and method == "POST":
            name = (b.get("name") or "").strip()
            email = (b.get("email") or "").strip().lower()
            pw = b.get("password") or ""
            if not name or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(pw) < 6:
                return self._json({"ok": False, "error": "Please provide a name, a valid email, and a password of 6+ characters."}, 400)
            with LOCK:
                db = load_db()
                if email in db["users"]:
                    return self._json({"ok": False, "error": "That email already has an account. Try signing in."}, 409)
                salt = secrets.token_hex(16)
                user = {
                    "email": email, "name": name, "salt": salt, "hash": hash_pw(pw, salt),
                    "tier": "free", "created": time.time(),
                    "saved": [], "list": [], "scrapes": [], "custom": [], "listCursor": 1000,
                }
                db["users"][email] = user
                db["stats"]["members"] = db["stats"].get("members", 1873) + 1
                tok = secrets.token_urlsafe(32)
                db["sessions"][tok] = email
                save_db(db)
            self._json({"ok": True, "user": self._public_user(user)}, 201,
                       headers={"Set-Cookie": f"tps={tok}; Path=/; HttpOnly; SameSite=Lax"})
            return

        if p == "login" and method == "POST":
            email = (b.get("email") or "").strip().lower()
            pw = b.get("password") or ""
            with LOCK:
                db = load_db()
                user = db["users"].get(email)
                if not user or user["hash"] != hash_pw(pw, user["salt"]):
                    return self._json({"ok": False, "error": "Email or password doesn't match."}, 401)
                tok = secrets.token_urlsafe(32)
                db["sessions"][tok] = email
                save_db(db)
            self._json({"ok": True, "user": self._public_user(user)}, 200,
                       headers={"Set-Cookie": f"tps={tok}; Path=/; HttpOnly; SameSite=Lax"})
            return

        if p == "logout" and method == "POST":
            tok = self._cookie("tps")
            with LOCK:
                db = load_db()
                db["sessions"].pop(tok, None)
                save_db(db)
            self._json({"ok": True}, 200, headers={"Set-Cookie": "tps=; Path=/; Max-Age=0"})
            return

        if p == "me" and method == "GET":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
            self._json({"ok": True, "user": self._public_user(u)})
            return

        # --- recipes ---
        if p == "recipes" and method == "GET":
            with LOCK:
                db = load_db()
                recs = list(db["recipes"].values())
            s = (q.get("search") or [""])[0].lower().strip()
            cat = (q.get("category") or [""])[0].strip()
            if cat and cat != "all":
                recs = [r for r in recs if r.get("category") == cat]
            if s:
                hay = lambda r: " ".join([r["title"], r.get("description", "")] + [i["item"] for i in r["ingredients"]]).lower()
                recs = [r for r in recs if s in hay(r)]
            sort = (q.get("sort") or ["popular"])[0]
            if sort == "newest":
                recs.sort(key=lambda r: r.get("added", 0), reverse=True)
            elif sort == "quickest":
                recs.sort(key=lambda r: r.get("time", 999))
            else:
                recs.sort(key=lambda r: r.get("rating", 0), reverse=True)
            with LOCK:
                db = load_db()
                u = self._db_user(db)
            for r in recs:
                r["savedByMe"] = bool(u and r["slug"] in u["saved"])
            self._json({"ok": True, "recipes": recs})
            return

        m = re.fullmatch(r"recipes/([a-z0-9-]+)/save", p)
        if m and method == "POST":
            slug = m.group(1)
            with LOCK:
                db = load_db()
                if slug not in db["recipes"]:
                    return self._json({"ok": False, "error": "Unknown recipe."}, 404)
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in to save recipes."}, 401)
                if slug in u["saved"]:
                    u["saved"].remove(slug)
                    saved = False
                else:
                    u["saved"].append(slug)
                    saved = True
                save_db(db)
            self._json({"ok": True, "saved": saved})
            return

        m = re.fullmatch(r"recipes/([a-z0-9-]+)", p)
        if m and method == "GET":
            slug = m.group(1)
            with LOCK:
                db = load_db()
                rec = db["recipes"].get(slug)
                u = self._db_user(db)
                aff = db["aff"]
            if not rec:
                return self._404()
            gear = []
            for pid in rec.get("gear", []):
                prod = next((x for x in aff["products"] if x["id"] == pid), None)
                if not prod:
                    continue
                store = next((s for s in aff["stores"] if s["id"] == prod["store"]), None)
                code = next((c for c, l in aff["links"].items() if l["product"] == prod["id"]), None)
                gear.append({
                    "id": prod["id"], "name": prod["name"], "price": prod["price"],
                    "note": prod.get("note", ""), "store": store["name"] if store else "",
                    "storeColor": store["color"] if store else "#888",
                    "code": code,
                })
            self._json({"ok": True, "recipe": rec, "savedByMe": bool(u and slug in u["saved"]),
                        "gear": gear, "substitutions": db["substitutions"]})
            return

        if p == "saved" and method == "GET":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                recs = db["recipes"]
            if not u:
                return self._json({"ok": False, "error": "Sign in first."}, 401)
            self._json({"ok": True, "recipes": [recs[s] for s in u["saved"] if s in recs]})
            return

        # --- scraper ---
        if p == "scrape" and method == "POST":
            mode = b.get("mode") or ("url" if b.get("url") else "paste")
            with LOCK:
                db = load_db()
                db["stats"]["scrapes_served"] += 1
                save_db(db)
            warnings = []
            if mode == "url":
                url = (b.get("url") or "").strip()
                if not re.match(r"^https?://", url):
                    url = "https://" + url
                page, err = scrape_url(url)
                if page:
                    recipe = scrape_html(page, url=url)
                else:
                    # Sandbox preview has no outbound network — run the full
                    # pipeline on a bundled sample page so the demo still works.
                    recipe = scrape_html(SAMPLE_PAGE, url=url, source="butterandbasil.example")
                    warnings.append(
                        "Live web fetch isn't available inside this preview sandbox (the error was: %s). "
                        "I ran the exact same parser on a bundled sample recipe so you can see the full pipeline. "
                        "Deployed at %s, this tab fetches any URL in real time." % (err.splitlines()[0][:80], DOMAIN))
            else:
                text = (b.get("html") or b.get("text") or "").strip()
                if len(text) < 30:
                    return self._json({"ok": False, "error": "Paste the page's HTML or plain recipe text first."}, 400)
                if "<" in text and ">" in text:
                    recipe = scrape_html(text, url=b.get("url") or "", source="Pasted HTML")
                else:
                    pr = scrape_plain_text(text)
                    recipe = {"title": pr["title"] or "Scraped Recipe", "source": "Pasted text", "url": "",
                              "author": "", "servings": pr["servings"], "cookTime": None,
                              "ingredients": pr["ingredients"], "steps": pr["steps"],
                              "warnings": (["No ingredient list found — add yours below."] if not pr["ingredients"] else []) +
                                           (["No instructions found — add yours below."] if not pr["steps"] else [])}
            self._json({"ok": True, "recipe": recipe, "warnings": warnings + recipe.pop("warnings", [])})
            return

        if p == "scrape/save" and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in to save scraped recipes to your library."}, 401)
                title = (b.get("title") or "").strip() or "Scraped Recipe"
                ings = b.get("ingredients") or []
                steps = b.get("steps") or []
                if not ings:
                    return self._json({"ok": False, "error": "The recipe needs at least one ingredient."}, 400)
                parsed = []
                for i in ings:
                    if isinstance(i, dict):
                        parsed.append({"qty": i.get("qty", ""), "unit": i.get("unit", ""), "item": i.get("item", ""), "aisle": "pantry", "note": ""})
                    else:
                        s = split_ingredient(str(i))
                        parsed.append(s or {"qty": "", "unit": "", "item": str(i).strip(), "aisle": "pantry", "note": ""})
                aisle_map = {
                    "chicken": "meat & seafood", "beef": "meat & seafood", "pork": "meat & seafood", "sausage": "meat & seafood",
                    "salmon": "meat & seafood", "shrimp": "meat & seafood", "fish": "meat & seafood", "tuna": "meat & seafood",
                    "butter": "dairy & eggs", "milk": "dairy & eggs", "cream": "dairy & eggs", "egg": "dairy & eggs",
                    "cheddar": "dairy & eggs", "mozzarella": "dairy & eggs", "parmesan": "dairy & eggs",
                    "garlic": "produce", "onion": "produce", "tomato": "produce", "lemon": "produce", "lime": "produce",
                    "spinach": "produce", "pepper": "produce", "potato": "produce", "mushroom": "produce", "carrot": "produce",
                    "basil": "produce", "parsley": "produce", "cilantro": "produce", "ginger": "produce", "chili": "produce",
                }
                for p in parsed:
                    low = p["item"].lower()
                    p["aisle"] = next((a for k, a in aisle_map.items() if k in low), "pantry")
                slug = unique_slug(db, title)
                rec = {
                    "slug": slug, "title": title, "category": b.get("category") or "Dinner",
                    "image": None, "time": b.get("cookTime") or 30, "servings": b.get("servings") or 4,
                    "difficulty": b.get("difficulty") or "Easy", "rating": 0, "reviews": 0,
                    "description": (b.get("notes") or "Saved with the Plate Scraper from " + (b.get("source") or "the web"))[:240],
                    "tags": ["scraped"], "source": b.get("source") or "", "url": b.get("url") or "",
                    "author": b.get("author") or (u["name"] + "'s kitchen"),
                    "ingredients": parsed, "steps": steps or ["Follow the original recipe's directions."],
                    "nutrition": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "sugar": 0, "sodium": 0},
                    "gear": [], "swaps": [], "added": time.time(), "custom": True,
                }
                db["recipes"][slug] = rec
                u["custom"].append(slug)
                u["scrapes"].append({"ts": time.time(), "title": title, "source": b.get("source") or "web"})
                save_db(db)
            self._json({"ok": True, "slug": slug})
            return

        # --- shopping list ---
        if p == "list" and method == "GET":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
            if not u:
                return self._json({"ok": True, "items": []})
            self._json({"ok": True, "items": u["list"]})
            return

        if p == "list/add" and method == "POST":
            items = b.get("items") or []
            if not isinstance(items, list) or not items:
                return self._json({"ok": False, "error": "Nothing to add."}, 400)
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in to sync your shopping list — guests keep it on this device."}, 401)
                for it in items:
                    key = (it.get("item") or it.get("name") or "").strip().lower()
                    if not key:
                        continue
                    unit = (it.get("unit") or "").strip().lower()
                    existing = next((x for x in u["list"]
                                     if x["name"].lower() == key and x.get("unit", "") == unit), None)
                    qn = it.get("qty")
                    try:
                        qn = float(qn) if qn not in (None, "") else None
                    except (TypeError, ValueError):
                        qn = None
                    if existing:
                        if qn and existing.get("qty"):
                            existing["qty"] = round(existing["qty"] + qn, 2)
                        elif qn and not existing.get("qty"):
                            existing["qty"] = qn
                        if it.get("recipe"):
                            existing.setdefault("recipes", [])
                            if it["recipe"] not in existing["recipes"]:
                                existing["recipes"].append(it["recipe"])
                    else:
                        u["listCursor"] += 1
                        u["list"].append({
                            "id": "i%d" % u["listCursor"],
                            "name": (it.get("item") or it.get("name")).strip(),
                            "qty": qn, "unit": unit,
                            "aisle": it.get("aisle") or "pantry",
                            "recipe": it.get("recipe") or "", "recipes": ([it["recipe"]] if it.get("recipe") else []),
                            "purchased": False,
                        })
                save_db(db)
            self._json({"ok": True, "items": u["list"]})
            return

        if p == "list/toggle" and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in first."}, 401)
                for it in u["list"]:
                    if it["id"] == b.get("id"):
                        it["purchased"] = not it["purchased"]
                        break
                save_db(db)
            self._json({"ok": True, "items": u["list"]})
            return

        if p == "list/remove" and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in first."}, 401)
                u["list"] = [it for it in u["list"] if it["id"] != b.get("id")]
                save_db(db)
            self._json({"ok": True, "items": u["list"]})
            return

        if p == "list/clear" and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in first."}, 401)
                mode = b.get("mode") or "purchased"
                if mode == "purchased":
                    u["list"] = [it for it in u["list"] if not it["purchased"]]
                else:
                    u["list"] = []
                save_db(db)
            self._json({"ok": True, "items": u["list"]})
            return

        # --- member profile / tier ---
        if p == "profile" and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in first."}, 401)
                name = (b.get("name") or "").strip()
                if name:
                    u["name"] = name[:40]
                save_db(db)
            self._json({"ok": True, "user": self._public_user(u)})
            return

        if p == "tier" and method == "POST":
            tier = b.get("tier")
            if tier not in ("premium", "legend"):
                return self._json({"ok": False, "error": "Unknown tier."}, 400)
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in first."}, 401)
                u["tier"] = tier  # simulated checkout
                save_db(db)
            self._json({"ok": True, "user": self._public_user(u), "note": "Demo checkout — no card was charged."})
            return

        # --- substitutions ---
        if p == "substitutions" and method == "GET":
            with LOCK:
                db = load_db()
            self._json({"ok": True, "substitutions": db["substitutions"]})
            return

        # --- gear (public affiliate products) ---
        if p == "gear" and method == "GET":
            with LOCK:
                db = load_db()
                aff = db["aff"]
            items = []
            for prod in aff["products"]:
                store = next((s for s in aff["stores"] if s["id"] == prod["store"]), None)
                code = next((c for c, l in aff["links"].items() if l["product"] == prod["id"]), None)
                if not store or not code:
                    continue
                items.append({
                    "id": prod["id"], "name": prod["name"], "price": prod["price"],
                    "note": prod.get("note", ""), "store": store["name"],
                    "storeColor": store["color"], "code": code,
                    "recipeSlug": prod.get("slug_tag", ""),
                })
            self._json({"ok": True, "items": items})
            return

        if p == "track" and method == "GET":
            code = (q.get("code") or [""])[0]
            with LOCK:
                db = load_db()
                link = db["aff"]["links"].get(code)
                prod = next((x for x in db["aff"]["products"] if x["id"] == (link or {}).get("product")), None) if link else None
                if link:
                    db["aff"]["clicks"].append({"ts": time.time(), "code": code, "path": "api"})
                    save_db(db)
            if not link or not prod:
                return self._404()
            self._json({"ok": True, "url": prod.get("dest_url") or "https://" + DOMAIN + "/gear.html",
                        "product": prod["name"], "store": prod["name"]})
            return

        # --- RSS reader / rewriter ---
        if p == "rss/feeds" and method == "GET":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
            feeds = []
            for f in db["feeds"]:
                feeds.append({
                    "id": f["id"], "name": f["name"], "site": f["site"], "url": f["url"],
                    "owner": f["owner"], "added": f["added"],
                    "lastCheck": f.get("lastCheck", 0),
                    "count": len(f.get("items", [])),
                    "unread": sum(1 for i in f.get("items", []) if not i.get("read")),
                    "mine": bool(u and (f["owner"] == u["email"] or f["owner"] == "admin@theplatescraper.com")),
                })
            self._json({"ok": True, "feeds": feeds})
            return

        if p == "rss/feeds" and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in to follow feeds."}, 401)
                name = (b.get("name") or "").strip()
                url = (b.get("url") or "").strip()
                if not re.match(r"^https?://", url):
                    url = "https://" + url
                if not name or not re.match(r"^https?://[^/\s]+\.[^/\s]+", url):
                    return self._json({"ok": False, "error": "Give the feed a name and a real feed URL."}, 400)
                fid = "feed-" + secrets.token_hex(4)
                db["feeds"].append({
                    "id": fid, "name": name[:60], "site": urlparse(url).netloc,
                    "url": url, "owner": u["email"], "added": time.time(),
                    "lastCheck": 0, "items": [], "demo": False,
                })
                save_db(db)
            self._json({"ok": True, "id": fid})
            return

        m = re.fullmatch(r"rss/feeds/([\w-]+)/remove", p)
        if m and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in first."}, 401)
                f = next((x for x in db["feeds"] if x["id"] == m.group(1)), None)
                if not f or (f["owner"] != u["email"] and u["email"] != "admin@theplatescraper.com"):
                    return self._json({"ok": False, "error": "That feed belongs to someone else."}, 403)
                db["feeds"] = [x for x in db["feeds"] if x["id"] != m.group(1)]
                save_db(db)
            self._json({"ok": True})
            return

        m = re.fullmatch(r"rss/feeds/([\w-]+)/check", p)
        if m and method == "POST":
            with LOCK:
                db = load_db()
                f = next((x for x in db["feeds"] if x["id"] == m.group(1)), None)
                if not f:
                    return self._404()
                items, warn, demo = feed_from_url(f["url"])
                f["lastCheck"] = time.time()
                f["demo"] = demo
                existing = {i["link"] or i["title"] for i in f.get("items", [])}
                added = 0
                for it in items:
                    key = it["link"] or it["title"]
                    if key in existing:
                        continue
                    it["id"] = "%s-%s" % (m.group(1)[:12], secrets.token_hex(3))
                    it["read"] = False
                    it["rewritten"] = False
                    f.setdefault("items", []).append(it)
                    added += 1
                f["items"] = sorted(f["items"], key=lambda i: i["ts"], reverse=True)[:40]
                save_db(db)
            self._json({"ok": True, "added": added, "items": f["items"], "warning": warn})
            return

        m = re.fullmatch(r"rss/feeds/([\w-]+)/items", p)
        if m and method == "GET":
            with LOCK:
                db = load_db()
                f = next((x for x in db["feeds"] if x["id"] == m.group(1)), None)
            if not f:
                return self._404()
            self._json({"ok": True, "feed": {
                "id": f["id"], "name": f["name"], "site": f["site"], "url": f["url"],
                "lastCheck": f.get("lastCheck", 0), "items": f.get("items", []),
            }})
            return

        m = re.fullmatch(r"rss/feeds/([\w-]+)/items/([\w-]+)/read", p)
        if m and method == "POST":
            with LOCK:
                db = load_db()
                f = next((x for x in db["feeds"] if x["id"] == m.group(1)), None)
                if f:
                    if b.get("all"):
                        for i in f.get("items", []):
                            i["read"] = True
                    else:
                        for i in f.get("items", []):
                            if i["id"] == m.group(2):
                                i["read"] = True
                    save_db(db)
            self._json({"ok": True})
            return

        if p == "rss/rewrite" and method == "POST":
            title = (b.get("title") or "").strip()
            content = (b.get("content") or "").strip()
            if not title or not content:
                return self._json({"ok": False, "error": "Nothing to rewrite."}, 400)
            with LOCK:
                db = load_db()
                db["stats"]["rewrites"] = db["stats"].get("rewrites", 0) + 1
                save_db(db)
            out = rewrite_post(title, content, b.get("site") or "", b.get("author") or "", b.get("link") or "")
            self._json({"ok": True, "post": out,
                        "engine": "rules-v1 (deterministic house-style rewriter; swap in an LLM key in production)"})
            return

        if p == "rss/posts" and method == "GET":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                posts = db.get("posts", [])
            if u:
                posts = [x for x in posts if x["author"] == u["email"] or x["author"] == "admin@theplatescraper.com"]
            else:
                posts = [x for x in posts if x["author"] == "admin@theplatescraper.com"]
            posts.sort(key=lambda x: x["ts"], reverse=True)
            self._json({"ok": True, "posts": posts})
            return

        if p == "rss/publish" and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in to save rewritten posts."}, 401)
                title = (b.get("title") or "").strip()
                if not title:
                    return self._json({"ok": False, "error": "The post needs a title."}, 400)
                pid = "post-" + secrets.token_hex(4)
                post = {
                    "id": pid, "title": title, "intro": (b.get("intro") or "").strip(),
                    "body": b.get("body") or [], "houseNote": (b.get("houseNote") or "").strip(),
                    "signoff": (b.get("signoff") or SIGNOFF), "credit": (b.get("credit") or "").strip(),
                    "tags": b.get("tags") or [], "status": b.get("status") or "draft",
                    "sourceLink": (b.get("sourceLink") or "").strip(),
                    "author": u["email"], "ts": time.time(),
                }
                db.setdefault("posts", []).append(post)
                save_db(db)
            self._json({"ok": True, "id": pid})
            return

        m = re.fullmatch(r"rss/posts/([\w-]+)/remove", p)
        if m and method == "POST":
            with LOCK:
                db = load_db()
                u = self._db_user(db)
                if not u:
                    return self._json({"ok": False, "error": "Sign in first."}, 401)
                keep = []
                for x in db.get("posts", []):
                    if x["id"] == m.group(1) and x["author"] == u["email"]:
                        continue
                    keep.append(x)
                db["posts"] = keep
                save_db(db)
            self._json({"ok": True})
            return

        # --- MySQL wizard ---
        if p == "setup/status" and method == "GET":
            cfg = mysql_cfg()
            status = {
                "ok": True,
                "driver": mysql_driver_available(),
                "active": mysql_active(),
                "store": "mysql" if mysql_active() else "json",
                "config": {k: (v if k != "password" else ("•" * 8 if v else "")) for k, v in cfg.items() if k != "active"},
                "tables": [],
                "serverVersion": None,
            }
            if cfg and cfg.get("host") and mysql_driver_available():
                try:
                    status["serverVersion"] = mysql_ping(cfg)
                except Exception as e:  # noqa: BLE001
                    status["error"] = str(e).splitlines()[0]
                try:
                    conn = mysql_connect(cfg)
                    cur = conn.cursor()
                    cur.execute("SHOW TABLES")
                    status["tables"] = [r[0] for r in cur.fetchall()]
                    conn.close()
                except Exception:
                    pass
            self._json(status)
            return

        if p == "setup/schema" and method == "GET":
            self._send(200, read_schema_sql(), "text/plain; charset=utf-8",
                       headers={"Content-Disposition": "attachment; filename=theplatescraper-schema.sql"})
            return

        if p in ("setup/test", "setup/create", "setup/migrate", "setup/activate", "setup/deactivate") and method == "POST":
            cfg = {
                "host": (b.get("host") or "127.0.0.1").strip(),
                "port": int(b.get("port") or 3306),
                "user": (b.get("user") or "root").strip(),
                "password": (b.get("password") or "").strip(),
                "database": (b.get("database") or "theplatescraper").strip() or "theplatescraper",
            }
            if not mysql_driver_available():
                return self._json({"ok": False, "error": "The MySQL driver isn't installed. On Windows run setup-theplatescraper.ps1 (or: pip install pymysql)."}, 409)
            if p == "setup/test":
                try:
                    ver = mysql_ping(cfg)
                    return self._json({"ok": True, "version": ver})
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(e).splitlines()[0]}, 400)
            if p == "setup/create":
                try:
                    ver = mysql_create_database(cfg)
                    save_mysql_cfg({**cfg, "active": False})
                    return self._json({"ok": True, "version": ver, "database": cfg["database"],
                                       "message": "Database and schema created. Next step: migrate data, then activate."})
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(e).splitlines()[0]}, 400)
            if p == "setup/migrate":
                if not (cfg.get("host") or b.get("password")):
                    return self._json({"ok": False, "error": "Enter your connection details first."}, 400)
                try:
                    with LOCK:
                        db = _load_json_db() if os.path.exists(DB_PATH) else seed_db()
                    mysql_save_db(db, cfg)
                    save_mysql_cfg({**cfg, "active": False})
                    n_recipes = len(db["recipes"])
                    n_users = len(db["users"])
                    n_clicks = len(db["aff"]["clicks"])
                    return self._json({"ok": True,
                                        "message": "Migrated %d recipes, %d users, %d affiliate clicks to MySQL." % (n_recipes, n_users, n_clicks)})
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(e).splitlines()[0]}, 400)
            if p == "setup/activate":
                cur = mysql_cfg()
                cur.update(cfg)
                cur["active"] = True
                save_mysql_cfg(cur)
                return self._json({"ok": True, "message": "MySQL is now the live store. The JSON file remains as a hot backup."})
            if p == "setup/deactivate":
                cur = mysql_cfg()
                cur["active"] = False
                save_mysql_cfg(cur)
                return self._json({"ok": True, "message": "Back on the JSON store. MySQL data is untouched."})

        # --- affiliate control panel (admin) ---
        if p.startswith("admin/"):
            return self._admin(method, p[len("admin/"):], b, q)

        self._404()

    # ---- admin API ----------------------------------------------------------
    def _admin(self, method, p, b, q):
        with LOCK:
            db = load_db()
        if p == "login" and method == "POST":
            email = (b.get("email") or "").strip().lower()
            pw = b.get("password") or ""
            adm = db["admin"]
            if email != adm["email"] or adm["hash"] != hash_pw(pw, adm["salt"]):
                return self._json({"ok": False, "error": "Those control panel credentials don't match."}, 401)
            tok = secrets.token_urlsafe(32)
            with LOCK:
                db = load_db()
                db["sessions"][tok] = "ADMIN:" + email
                save_db(db)
            self._json({"ok": True, "admin": True}, 200,
                       headers={"Set-Cookie": f"tps={tok}; Path=/; HttpOnly; SameSite=Lax"})
            return
        tok = self._cookie("tps")
        is_admin = db["sessions"].get(tok, "").startswith("ADMIN:")
        if not is_admin:
            return self._json({"ok": False, "error": "Control panel access required."}, 401)

        def aff():
            return db["aff"]

        if p == "overview" and method == "GET":
            a = aff()
            now = time.time()
            d7 = now - 7 * 86400
            d14 = now - 14 * 86400
            clicks = a["clicks"]
            c7 = sum(1 for c in clicks if c["ts"] >= d7)
            c14 = sum(1 for c in clicks if c["ts"] >= d14)
            by_product = {}
            for c in clicks:
                if c["ts"] < d14:
                    continue
                by_product[c["code"]] = by_product.get(c["code"], 0) + 1
            rows = []
            for code, n in by_product.items():
                link = a["links"].get(code)
                prod = next((x for x in a["products"] if x["id"] == (link or {}).get("product")), None)
                if not prod:
                    continue
                store = next((s for s in a["stores"] if s["id"] == prod["store"]), None)
                rows.append({
                    "code": code, "product": prod["name"], "store": store["name"] if store else "?",
                    "price": prod["price"], "rate": (store or {}).get("rate", 0),
                    "clicks": n, "estRevenue": round(n * prod["price"] * (store or {}).get("rate", 0) * 0.12, 2),
                })
            rows.sort(key=lambda r: r["clicks"], reverse=True)
            by_store = {}
            for r in rows:
                by_store[r["store"]] = by_store.get(r["store"], 0) + r["clicks"]
            days = []
            for i in range(13, -1, -1):
                start = now - (i + 1) * 86400
                end = now - i * 86400
                days.append({"label": time.strftime("%a", time.localtime(start)),
                             "count": sum(1 for c in clicks if start <= c["ts"] < end)})
            est14 = sum(r["estRevenue"] for r in rows)
            self._json({"ok": True, "overview": {
                "clicks7": c7, "clicks14": c14, "est14": round(est14, 2),
                "activeLinks": len(a["links"]), "stores": len(a["stores"]), "products": len(a["products"]),
                "members": db["stats"].get("members", 1873), "scrapes": db["stats"]["scrapes_served"],
                "topProducts": rows[:6], "byStore": by_store, "days": days,
                "convRate": 0.12,
            }})
            return

        if p == "stores" and method == "GET":
            a = aff()
            for s in a["stores"]:
                s["productCount"] = sum(1 for x in a["products"] if x["store"] == s["id"])
            self._json({"ok": True, "stores": a["stores"]})
            return

        if p == "stores" and method == "POST":
            name = (b.get("name") or "").strip()
            if not name:
                return self._json({"ok": False, "error": "Store name is required."}, 400)
            try:
                rate = float(b.get("rate", 0.05))
            except (TypeError, ValueError):
                rate = 0.05
            with LOCK:
                db = load_db()
                db["aff"]["stores"].append({
                    "id": "st-" + secrets.token_hex(3), "name": name,
                    "program": (b.get("program") or name).strip(),
                    "id_ref": (b.get("id_ref") or "").strip(),
                    "rate": min(max(rate, 0.0), 0.6),
                    "color": (b.get("color") or "#C75B39").strip() or "#C75B39",
                })
                save_db(db)
            self._json({"ok": True})
            return

        m = re.fullmatch(r"stores/([\w-]+)/remove", p)
        if m and method == "POST":
            with LOCK:
                db = load_db()
                a = db["aff"]
                sid = m.group(1)
                prods = [x for x in a["products"] if x["store"] == sid]
                codes = [c for c, l in a["links"].items() if any(x["id"] == l["product"] for x in prods)]
                a["products"] = [x for x in a["products"] if x["store"] != sid]
                for c in codes:
                    a["links"].pop(c, None)
                a["stores"] = [s for s in a["stores"] if s["id"] != sid]
                save_db(db)
            self._json({"ok": True})
            return

        if p == "products" and method == "GET":
            a = aff()
            out = []
            for x in a["products"]:
                store = next((s for s in a["stores"] if s["id"] == x["store"]), None)
                code = next((c for c, l in a["links"].items() if l["product"] == x["id"]), None)
                out.append({**x, "storeName": store["name"] if store else "?", "code": code})
            self._json({"ok": True, "products": out})
            return

        if p == "products" and method == "POST":
            name = (b.get("name") or "").strip()
            store = b.get("store") or ""
            if not name or not store:
                return self._json({"ok": False, "error": "Product name and store are required."}, 400)
            try:
                price = float(b.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            with LOCK:
                db = load_db()
                a = db["aff"]
                pid = "p-" + secrets.token_hex(3)
                a["products"].append({
                    "id": pid, "store": store, "name": name, "price": price,
                    "note": (b.get("note") or "").strip(), "slug_tag": (b.get("slug_tag") or "").strip().lower(),
                    "dest_url": (b.get("dest_url") or "https://theplatescraper.com/gear.html").strip(),
                })
                a["links"][pid.replace("p-", "go-")[:8]] = {"product": pid, "created": time.time()}
                save_db(db)
            self._json({"ok": True, "id": pid})
            return

        m = re.fullmatch(r"products/([\w-]+)/remove", p)
        if m and method == "POST":
            with LOCK:
                db = load_db()
                a = db["aff"]
                pid = m.group(1)
                a["products"] = [x for x in a["products"] if x["id"] != pid]
                for c, l in list(a["links"].items()):
                    if l["product"] == pid:
                        a["links"].pop(c, None)
                save_db(db)
            self._json({"ok": True})
            return

        if p == "links" and method == "GET":
            a = aff()
            out = []
            for code, l in a["links"].items():
                prod = next((x for x in a["products"] if x["id"] == l["product"]), None)
                store = next((s for s in a["stores"] if s["id"] == (prod or {}).get("store")), None)
                clicks14 = sum(1 for c in a["clicks"] if c["code"] == code and c["ts"] >= time.time() - 14 * 86400)
                out.append({
                    "code": code, "url": f"https://{DOMAIN}/go/{code}",
                    "product": prod["name"] if prod else "(removed)",
                    "store": store["name"] if store else "?",
                    "clicks14": clicks14,
                    "created": l["created"],
                    "estRevenue": round(clicks14 * (prod or {}).get("price", 0) * (store or {}).get("rate", 0) * 0.12, 2),
                })
            out.sort(key=lambda r: r["clicks14"], reverse=True)
            self._json({"ok": True, "links": out})
            return

        if p == "clicks" and method == "GET":
            a = aff()
            recent = sorted(a["clicks"], key=lambda c: c["ts"], reverse=True)[:40]
            out = []
            for c in recent:
                prod = next((x for x in a["products"] if x["id"] == (a["links"].get(c["code"]) or {}).get("product")), None)
                out.append({"ts": c["ts"], "code": c["code"], "path": c.get("path", ""),
                            "product": prod["name"] if prod else "—"})
            self._json({"ok": True, "clicks": out})
            return

        self._404()


def link_products(db):
    return db["aff"]["products"]


def db_admin_email():
    return "admin@theplatescraper.com"


T0 = time.time()


def main():
    if not os.path.exists(DB_PATH):
        os.makedirs(DATA_DIR, exist_ok=True)
        with LOCK:
            save_db(seed_db())
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"The Plate Scraper running on http://0.0.0.0:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
