"""nylab.replay.server -- local HTTP server + JSON router for the replay trainer.

Python standard-library http.server only (REPLAY_TRAINER.md S1: "no build step, no npm").
Data is loaded ONCE at startup from the parquet cache built by `python -m nylab run`
(REPLAY_TRAINER.md S1) -- run that first if this server complains the cache is missing.
"""
from __future__ import annotations

import base64
import csv
import json
import os
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nylab import cache as cache_mod
from nylab import config as cfg
from nylab.replay import api, sim

STATIC_DIR = Path(__file__).parent / "static"
JOURNAL_CSV = Path("research/replay/trades.csv")
SHOTS_DIR = Path("research/replay/shots")
PRESETS_JSON = Path("research/replay/presets.json")
JOURNAL_COLUMNS = [
    "logged_at", "td", "side", "entry", "sl", "tp", "exit", "reason",
    "risk_pips", "R_gross", "R_net", "setup_tag", "rules_followed", "emotion", "notes",
]


def _content_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8", ".js": "application/javascript",
        ".css": "text/css", ".json": "application/json", ".png": "image/png",
        ".svg": "image/svg+xml",
    }.get(path.suffix, "application/octet-stream")


def make_handler(store: api.Store, thin_flags):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep the console quiet; errors still raise

        def _json(self, obj, status=200):
            body = json.dumps(obj, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str):
            rel = path.lstrip("/") or "index.html"
            fp = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() not in fp.parents and fp != STATIC_DIR.resolve():
                self.send_error(403); return
            if not fp.is_file():
                self.send_error(404); return
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _content_type(fp))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/days":
                    weekdays = [int(x) for x in q["weekdays"].split(",")] if q.get("weekdays") else None
                    exclude_thin = q.get("exclude_thin", "true").lower() != "false"
                    self._json(api.list_days(store, q.get("from"), q.get("to"), weekdays, exclude_thin, thin_flags))
                elif u.path == "/api/bars":
                    self._json(api.get_bars(store, q["td"], q.get("tf", "M5"), q["until"],
                                             int(q.get("context_days", 10))))
                elif u.path == "/api/levels":
                    self._json(api.get_levels(store, q["td"], q["until"]))
                elif u.path == "/api/news":
                    self._json(api.get_news(store, q["td"], q["until"]))
                elif u.path == "/api/prop":
                    self._json(cfg.load_prop())
                elif u.path == "/api/presets":
                    if PRESETS_JSON.exists():
                        self._json(json.loads(PRESETS_JSON.read_text()))
                    else:
                        self._json([])
                elif u.path.startswith("/api/"):
                    self._json({"error": f"unknown endpoint {u.path}"}, 404)
                else:
                    self._static(u.path)
            except KeyError as e:
                self._json({"error": f"missing required parameter: {e}"}, 400)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 500)

        def do_POST(self):
            u = urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "invalid JSON body"}, 400); return
            try:
                if u.path == "/api/sim/fill_check":
                    self._json(sim.check_bar(payload["position"], payload["bar"]))
                elif u.path == "/api/sim/lots":
                    lots = sim.lots_from_risk(payload["balance"], payload["risk_pct"],
                                               payload["sl_distance_pips"], payload.get("pip_value_per_lot", 10.0))
                    self._json({"lots": lots})
                elif u.path == "/api/sim/maven_state":
                    self._json(sim.maven_state(payload["starting_balance"], payload["current_balance"],
                                                payload["day_start_balance"], payload["peak_balance"],
                                                payload["program"]))
                elif u.path == "/api/journal/append":
                    self._append_journal(payload)
                    self._json({"ok": True})
                elif u.path == "/api/journal/screenshot":
                    self._save_screenshot(payload)
                elif u.path == "/api/presets":
                    self._save_preset(payload)
                    self._json({"ok": True})
                else:
                    self._json({"error": f"unknown endpoint {u.path}"}, 404)
            except KeyError as e:
                self._json({"error": f"missing required field: {e}"}, 400)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 500)

        def _append_journal(self, row: dict):
            JOURNAL_CSV.parent.mkdir(parents=True, exist_ok=True)
            is_new = not JOURNAL_CSV.exists()
            with open(JOURNAL_CSV, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=JOURNAL_COLUMNS)
                if is_new:
                    w.writeheader()
                out = {k: row.get(k, "") for k in JOURNAL_COLUMNS}
                out["logged_at"] = datetime.now(timezone.utc).isoformat()
                w.writerow(out)

        def _save_screenshot(self, payload: dict):
            SHOTS_DIR.mkdir(parents=True, exist_ok=True)
            data_url = payload["png_base64"]
            b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
            name = payload.get("filename") or f"shot_{datetime.now():%Y%m%d_%H%M%S}.png"
            (SHOTS_DIR / name).write_bytes(base64.b64decode(b64))
            self._json({"ok": True, "path": str(SHOTS_DIR / name)})

        def _save_preset(self, payload: dict):
            PRESETS_JSON.parent.mkdir(parents=True, exist_ok=True)
            presets = json.loads(PRESETS_JSON.read_text()) if PRESETS_JSON.exists() else []
            presets = [p for p in presets if p.get("name") != payload.get("name")]
            presets.append(payload)
            PRESETS_JSON.write_text(json.dumps(presets, indent=2))

    return Handler


def serve(cache_dir: str = "data/cache", host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    cache_path = Path(cache_dir)
    if not (cache_path / "bars_M5.parquet").exists():
        sys.exit(
            f"No cache found at {cache_path}/. Run `python -m nylab run <your_csv>` first "
            f"(it writes the parquet cache the replay trainer reads)."
        )
    bars, days = cache_mod.load(cache_dir)
    store = api.Store(bars, days)

    from nylab.data import quality
    thin_flags = quality.flag_days(bars, days["day_range"])

    handler = make_handler(store, thin_flags)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"EURUSD Session Research Lab -- replay trainer running at {url}")
    print(f"  {len(days)} trading days loaded from {cache_path}/ (offline, no internet needed)")
    print("  Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
        httpd.shutdown()
