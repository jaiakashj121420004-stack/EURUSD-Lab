"""nylab.replay.server -- local HTTP server + JSON router for the replay trainer.

Python standard-library http.server only (REPLAY_TRAINER.md S1: "no build step, no npm").
Data is loaded ONCE at startup from the parquet cache built by `python -m nylab run`
(REPLAY_TRAINER.md S1) -- run that first if this server complains the cache is missing.
"""
from __future__ import annotations

import base64
import csv
import json
import math
import os
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nylab import cache as cache_mod
from nylab import calendar_io
from nylab import config as cfg
from nylab.replay import api, journal_stats, sim

STATIC_DIR = Path(__file__).parent / "static"
# Audit fix 2026-09-28: overridable so the test suite writes into a throwaway folder. Before
# this, tests/test_replay_server_integration.py appended a fake "test trade" row to Akash's REAL
# practice journal on every test run (12 such rows were found and removed on 2026-09-28).
REPLAY_DATA_DIR = Path(os.environ.get("NYLAB_REPLAY_DATA_DIR", "research/replay"))
JOURNAL_CSV = REPLAY_DATA_DIR / "trades.csv"
SHOTS_DIR = REPLAY_DATA_DIR / "shots"
PRESETS_JSON = REPLAY_DATA_DIR / "presets.json"
JOURNAL_COLUMNS = [
    "logged_at", "td", "side", "entry", "sl", "tp", "exit", "reason",
    "risk_pips", "R_gross", "R_net", "setup_tag", "rules_followed", "emotion", "notes",
    "preset", "challenge",  # ROADMAP 6.3/6.6/6.7: which saved filter preset (if any) and
    # whether this trade was placed during a Challenge-mode run -- both optional, blank for
    # ordinary free-practice trades, used by the Stats tab (6.7) and the challenge report (6.6).
]


def _content_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8", ".js": "application/javascript",
        ".css": "text/css", ".json": "application/json", ".png": "image/png",
        ".svg": "image/svg+xml",
    }.get(path.suffix, "application/octet-stream")


def _json_safe(obj):
    """Recursively replaces NaN/Infinity with None -- Python's json module happily emits the
    non-standard `NaN`/`Infinity` tokens (nylab.stats.r_stats can produce both, e.g. sqn when
    stdev is 0), which is NOT valid JSON and breaks the browser's JSON.parse. Every API response
    goes through this so a stats/edge-case value never silently breaks the frontend."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _parse_bool(v, default):
    if v is None:
        return default
    return v.lower() not in ("false", "0", "no")


def _parse_days_query(q: dict) -> dict:
    """REPLAY_TRAINER.md S3 filters -> nylab.replay.api.list_days() kwargs. Every filter is
    optional -- an absent query param means "don't filter on this", not "filter to nothing"."""
    kwargs = dict(
        date_from=q.get("from"), date_to=q.get("to"),
        weekdays=[int(x) for x in q["weekdays"].split(",")] if q.get("weekdays") else None,
        exclude_thin=_parse_bool(q.get("exclude_thin"), True),
        hide_outcome=_parse_bool(q.get("hide_outcome"), True),
        news_flags=q["news"].split(",") if q.get("news") else None,
        raid_flags=q["raids"].split(",") if q.get("raids") else None,
        adr_min=float(q["adr_min"]) if q.get("adr_min") else None,
        adr_max=float(q["adr_max"]) if q.get("adr_max") else None,
        dsl=q.get("dsl") or None,
    )
    # Session-character filters arrive as char_<session_id>=chop,quiet (one query param per
    # session id, since sessions and their allowed characters are both open-ended lists).
    session_character = {}
    for key, val in q.items():
        if key.startswith("char_") and val:
            session_character[key[len("char_"):]] = val.split(",")
    if session_character:
        kwargs["session_character"] = session_character
    return kwargs


def make_handler(store: api.Store, thin_flags):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep the console quiet; errors still raise

        def _json(self, obj, status=200):
            body = json.dumps(_json_safe(obj), default=str).encode("utf-8")
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
                    self._json(api.list_days(store, thin_flags=thin_flags, **_parse_days_query(q)))
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
                elif u.path == "/api/journal":
                    self._json(self._read_journal())
                elif u.path == "/api/journal/stats":
                    self._json(journal_stats.build(self._read_journal_df()))
                elif u.path.startswith("/api/"):
                    self._json({"error": f"unknown endpoint {u.path}"}, 404)
                else:
                    self._static(u.path)
            except api.DayFilterError as e:
                self._json({"error": str(e)}, 400)
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
                elif u.path == "/api/sim/pending_fill_check":
                    self._json(sim.check_pending_fill(payload["order"], payload["bar"]))
                elif u.path == "/api/sim/compute_r":
                    self._json(sim.compute_r(payload["side"], payload["entry"], payload["exit_price"],
                                              payload["sl"], payload.get("cost_pips", 1.0), payload.get("pip", 0.0001)))
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
                elif u.path == "/api/presets/delete":
                    self._delete_preset(payload)
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

        def _read_journal(self) -> list[dict]:
            if not JOURNAL_CSV.exists():
                return []
            with open(JOURNAL_CSV, newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))

        def _read_journal_df(self):
            import pandas as pd
            rows = self._read_journal()
            return pd.DataFrame(rows) if rows else pd.DataFrame(columns=JOURNAL_COLUMNS)

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

        def _delete_preset(self, payload: dict):
            if not PRESETS_JSON.exists():
                return
            presets = json.loads(PRESETS_JSON.read_text())
            presets = [p for p in presets if p.get("name") != payload.get("name")]
            PRESETS_JSON.write_text(json.dumps(presets, indent=2))

    return Handler


def serve(cache_dir: str = "data/cache", host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = True, calendar_path: str = "data/calendar.parquet"):
    cache_path = Path(cache_dir)
    if not (cache_path / "bars_M5.parquet").exists():
        sys.exit(
            f"No cache found at {cache_path}/. Run `python -m nylab run <your_csv>` first "
            f"(it writes the parquet cache the replay trainer reads)."
        )
    bars, days = cache_mod.load(cache_dir)

    cal = None
    if calendar_path and os.path.exists(calendar_path):
        try:
            cal = calendar_io.load_cache(calendar_path)
        except Exception as e:  # noqa: BLE001 -- a bad/stale calendar file must not crash the trainer
            print(f"  WARNING: could not load calendar cache {calendar_path} ({e}) -- news markers disabled.")
            cal = None
    store = api.Store(bars, days, cal=cal)

    from nylab.data import quality
    thin_flags = quality.flag_days(bars, days["day_range"])

    handler = make_handler(store, thin_flags)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"EURUSD Session Research Lab -- replay trainer running at {url}")
    print(f"  {len(days)} trading days loaded from {cache_path}/ (offline, no internet needed)")
    print(f"  news calendar: {'loaded, ' + str(len(cal)) + ' events' if cal is not None else 'not loaded (no news markers)'}")
    print("  Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
        httpd.shutdown()
