#!/usr/bin/env python3
"""MySQL setup CLI for The Plate Scraper.

Used by setup-theplatescraper.ps1 (or run by hand):

  python tools/mysql_setup.py --status
  python tools/mysql_setup.py --test     --host 127.0.0.1 --port 3306 --user root --password secret
  python tools/mysql_setup.py --create   --host 127.0.0.1 --user root --password secret --database theplatescraper
  python tools/mysql_setup.py --migrate  --host 127.0.0.1 --user root --password secret
  python tools/mysql_setup.py --activate --host 127.0.0.1 --user root --password secret

--create runs the full wizard headlessly: CREATE DATABASE + schema.sql.
--migrate copies the JSON data store (db.json / seeds) into MySQL.
--activate flips the server's live store to MySQL (JSON stays as hot backup).
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import server  # noqa: E402


def cfg_from_args(a):
    return {
        "host": a.host or "127.0.0.1",
        "port": int(a.port or 3306),
        "user": a.user or "root",
        "password": a.password or "",
        "database": a.database or "theplatescraper",
    }


def main():
    ap = argparse.ArgumentParser(description="The Plate Scraper — MySQL wizard (CLI)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default=os.environ.get("MYSQLPASSWORD", ""))
    ap.add_argument("--database", default="theplatescraper")
    ap.add_argument("--status", action="store_true", help="show driver/store status")
    ap.add_argument("--test", action="store_true", help="test the connection")
    ap.add_argument("--create", action="store_true", help="create database + run schema.sql")
    ap.add_argument("--migrate", action="store_true", help="copy JSON data into MySQL")
    ap.add_argument("--activate", action="store_true", help="make MySQL the live store")
    a = ap.parse_args()

    ok = True
    if a.status or not (a.test or a.create or a.migrate or a.activate):
        print("Driver (pymysql) : %s" % ("installed" if server.mysql_driver_available() else "MISSING — run: pip install pymysql"))
        print("Live store       : %s" % ("mysql" if server.mysql_active() else "json (data/db.json)"))
        print("Saved config     : %s" % (json.dumps(server.mysql_cfg()) or "(none)"))

    if not server.mysql_driver_available() and (a.test or a.create or a.migrate or a.activate):
        print("ERROR: pymysql is not installed. Run:  pip install -r requirements.txt")
        sys.exit(1)

    cfg = cfg_from_args(a)

    if a.test:
        try:
            print("Connected. MySQL server version:", server.mysql_ping(cfg))
        except Exception as e:
            ok = False
            print("Connection failed:", str(e).splitlines()[0])

    if a.create:
        try:
            ver = server.mysql_create_database(cfg)
            print("Database '%s' ready (schema applied). Server %s" % (cfg["database"], ver))
        except Exception as e:
            ok = False
            print("Create failed:", str(e).splitlines()[0])

    if a.migrate:
        try:
            db = server._load_json_db() if os.path.exists(server.DB_PATH) else server.seed_db()
            server.mysql_save_db(db, cfg)
            print("Migrated: %d recipes, %d users, %d affiliate stores, %d clicks." % (
                len(db["recipes"]), len(db["users"]), len(db["aff"]["stores"]), len(db["aff"]["clicks"])))
        except Exception as e:
            ok = False
            print("Migrate failed:", str(e).splitlines()[0])

    if a.activate:
        cfg["active"] = True
        server.save_mysql_cfg(cfg)
        print("MySQL is now the live store (JSON mirror kept as hot backup).")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
