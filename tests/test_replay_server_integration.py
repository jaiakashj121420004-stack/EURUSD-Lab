"""Integration smoke test: actually start `python -m nylab replay` as a subprocess and hit
every route once, including the static files (index.html/app.js/vendor JS) and a couple of
API endpoints. Complements test_replay_api.py (which tests the no-leak logic directly) by
proving the HTTP wiring itself works end to end, fully offline.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / "tests" / "fixtures" / "_replay_cache"


@pytest.fixture(scope="module")
def running_server(tmp_path_factory):
    if not (CACHE_DIR / "bars_M5.parquet").exists():
        pytest.skip("run test_replay_api.py first to build the test cache")
    # Never touch the real research/replay/ journal/presets/shots (audit fix 2026-09-28).
    env = dict(os.environ, NYLAB_REPLAY_DATA_DIR=str(tmp_path_factory.mktemp("replay_data")))

    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "nylab", "replay", "--cache-dir", str(CACHE_DIR),
         "--port", "8790", "--no-browser"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )
    ok = False
    for _ in range(20):
        try:
            urllib.request.urlopen("http://127.0.0.1:8790/api/prop", timeout=1)
            ok = True
            break
        except Exception:
            time.sleep(0.5)
    if not ok:
        out = proc.stdout.read(4000)
        proc.kill()
        pytest.fail(f"replay server never came up:\n{out}")
    yield "http://127.0.0.1:8790"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _get(base, path):
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=3) as r:
            return r.status, r.read()
    except HTTPError as e:
        return e.code, e.read()


def test_static_files_served(running_server):
    for path in ("/", "/app.js", "/style.css", "/vendor/lightweight-charts.standalone.production.js"):
        status, body = _get(running_server, path)
        assert status == 200
        assert len(body) > 0


def test_days_and_bars_and_levels_endpoints(running_server):
    status, body = _get(running_server, "/api/days?exclude_thin=false")
    payload = json.loads(body)
    days = payload["days"]
    assert status == 200 and payload["count"] > 100 and len(days) > 100
    td = days[10]["date"]

    status, body = _get(running_server, f"/api/bars?td={td}&tf=M5&until={td}T09:30:00")
    bars = json.loads(body)["bars"]
    assert status == 200 and len(bars) > 0
    assert all(b["time"] <= bars[-1]["time"] for b in bars)

    status, body = _get(running_server, f"/api/levels?td={td}&until={td}T09:30:00")
    levels = json.loads(body)
    assert status == 200
    # ny_close is only available at h=16, we asked for h=9.5 -- must not be present
    assert "ny_close" not in levels["levels"]
    assert "lon_high" in levels["levels"]  # available at h=5, well before 9.5


def test_prop_endpoint_has_maven_programs(running_server):
    status, body = _get(running_server, "/api/prop")
    prop = json.loads(body)
    assert "standard_2step" in prop["programs"]
    assert prop["programs"]["standard_2step"]["daily_dd_pct"] == 4


def _post(base, path, payload):
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, json.loads(r.read())


def test_bad_day_filter_returns_400(running_server):
    """api.DayFilterError (unknown DSL column, missing session-character column, ...) must come
    back as a clean 400 with a message, not a bare 500."""
    import urllib.parse
    q = urllib.parse.urlencode({"dsl": "totally_made_up_column_xyz > 0"})
    status, body = _get(running_server, f"/api/days?{q}")
    assert status == 400
    assert "totally_made_up_column_xyz" in json.loads(body)["error"]


def test_days_filter_by_raid_flag_over_http(running_server):
    status, body = _get(running_server, "/api/days?exclude_thin=false&raids=ny_takes_lon_high&hide_outcome=false")
    payload = json.loads(body)
    assert status == 200
    assert payload["spoiler_filter_used"] is True
    assert all(r["outcome"]["ny_takes_lon_high"] for r in payload["days"])


def test_days_default_hides_outcome_columns_over_http(running_server):
    status, body = _get(running_server, "/api/days?exclude_thin=false")
    payload = json.loads(body)
    assert status == 200
    assert all(r["outcome"] is None for r in payload["days"][:20])


def test_journal_endpoints_round_trip(running_server):
    """POST a trade, then GET /api/journal and /api/journal/stats and see it reflected."""
    status, result = _post(running_server, "/api/journal/append", {
        "td": "2024-01-15", "side": "long", "entry": 1.1000, "sl": 1.0990, "tp": 1.1020,
        "exit": 1.1020, "reason": "target", "risk_pips": 10, "R_gross": 2.0, "R_net": 1.9,
        "setup_tag": "london_sweep", "rules_followed": "Y", "emotion": 3, "notes": "test trade",
        "preset": "", "challenge": "",
    })
    assert status == 200 and result["ok"] is True

    status, body = _get(running_server, "/api/journal")
    rows = json.loads(body)
    assert status == 200 and any(r["setup_tag"] == "london_sweep" for r in rows)

    status, body = _get(running_server, "/api/journal/stats")
    stats = json.loads(body)
    assert status == 200
    assert stats["n_trades"] >= 1
    assert any(g["group"] == "london_sweep" for g in stats["by_setup_tag"])


def test_presets_save_list_and_delete(running_server):
    status, result = _post(running_server, "/api/presets", {"name": "test_preset_xyz", "weekdays": [0, 1]})
    assert status == 200 and result["ok"] is True

    status, body = _get(running_server, "/api/presets")
    presets = json.loads(body)
    assert status == 200 and any(p["name"] == "test_preset_xyz" for p in presets)

    status, result = _post(running_server, "/api/presets/delete", {"name": "test_preset_xyz"})
    assert status == 200 and result["ok"] is True
    status, body = _get(running_server, "/api/presets")
    presets = json.loads(body)
    assert not any(p["name"] == "test_preset_xyz" for p in presets)


def test_sim_pending_fill_and_compute_r_endpoints(running_server):
    """Phase 2 gap-close: the limit/stop pending-order check and the shared compute_r helper
    are reachable over HTTP, not just as direct Python calls (test_replay_api.py covers the
    logic itself)."""
    status, result = _post(running_server, "/api/sim/pending_fill_check", {
        "order": {"side": "long", "entry": 1.10000, "order_type": "limit"},
        "bar": {"high": 1.10100, "low": 1.09950},
    })
    assert status == 200 and result == {"filled": True, "entry": 1.10000}

    status, result = _post(running_server, "/api/sim/compute_r", {
        "side": "long", "entry": 1.10500, "exit_price": 1.10700, "sl": 1.10400,
    })
    assert status == 200
    assert abs(result["R_gross"] - 2.0) < 1e-6
