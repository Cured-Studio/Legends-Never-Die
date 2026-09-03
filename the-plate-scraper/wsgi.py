"""The Plate Scraper — WSGI entry point.

For Apache Passenger on cPanel (InMotion's "Application Manager" /
"Setup Python App"), or any other WSGI server (gunicorn, uWSGI, ...).

cPanel "Application Manager" setup (InMotion reseller/shared):
    Application URL   : theplatescraper.com  (or a subdomain / sub-path)
    Application root  : ~/theplatescraper    (the folder containing this file)
    Startup file      : wsgi.py
    Entry point       : wsgi.application     (or leave blank to auto-detect)
    Dependencies      : requirements.txt  ->  "Run Pip Install" in cPanel

The standalone dev server (python3 server.py 8080) keeps working too —
this file just drives the exact same routing code without sockets.
"""
import email.utils
import io
import json
import os
import sys
from http.client import HTTPMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server as tps  # noqa: E402


class _Headless(tps.Handler):
    """Same handler as the socket server, driven from a WSGI environ."""

    def __init__(self, method, path, headers, body):
        self.command = method
        self.path = path
        self.headers = headers
        self.rfile = io.BytesIO(body or b"")
        self._status = 200
        self._headers = []
        self._wbuf = io.BytesIO()

    def send_response(self, code, message=None):  # noqa: N802
        self._status = code
        self._headers.append(("Server", "PlateScraper/1.0"))
        self._headers.append(("Date", email.utils.formatdate(usegmt=True)))

    def send_header(self, key, value):  # noqa: N802
        self._headers.append((key, value))

    def end_headers(self):  # noqa: N802
        pass

    @property
    def wfile(self):
        return self._wbuf


_REASONS = {
    200: "OK", 201: "Created", 204: "No Content", 302: "Found",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 409: "Conflict", 500: "Internal Server Error",
}


def application(environ, start_response):  # noqa: D401
    n = 0
    try:
        n = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        n = 0
    data = environ["wsgi.input"].read(n) if n else b""

    path = environ.get("PATH_INFO") or "/"
    qs = environ.get("QUERY_STRING")
    full_path = path + ("?" + qs if qs else "")

    headers = HTTPMessage()
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            headers[key[5:].replace("_", "-").title()] = value
    if environ.get("CONTENT_TYPE"):
        headers["Content-Type"] = environ["CONTENT_TYPE"]
    if n:
        headers["Content-Length"] = str(n)

    handler = _Headless(environ.get("REQUEST_METHOD", "GET"), full_path, headers, data)
    try:
        handler._route(handler.command)
    except Exception as e:  # noqa: BLE001
        payload = json.dumps({"ok": False, "error": "Server error: %s" % e}).encode("utf-8")
        start_response("500 Internal Server Error", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(payload))),
        ])
        return [payload]

    body = handler._wbuf.getvalue()
    # Never advertise a wrong body length to the proxy layer
    for i, (k, v) in enumerate(handler._headers):
        if k.lower() == "content-length" and v != str(len(body)):
            handler._headers[i] = (k, str(len(body)))
    start_response("%d %s" % (handler._status, _REASONS.get(handler._status, "OK")),
                   handler._headers)
    return [body]
