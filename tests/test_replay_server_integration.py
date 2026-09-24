"""Integration smoke test: actually start `python -m nylab replay` as a subprocess and hit
every route once, including the static files (index.html/app.js/vendor JS) and a couple of
API endpoints. Complements test_replay_api.py (which tests the no-leak logic directly) by
proving the HTTP wiring itself works end to end, fully offline.
"""
import json
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
def running_server():
    if not (CACHE_DIR / "bars_M5.parquet").exists():
        pytest.skip("run test_replay_api.py first to build the test cache")

    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "nylab", "replay", "--cache-dir", str(CACHE_DIR),
         "--port", "8790", "--no-browser"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
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
    with urllib.request.urlopen(f"{base}{path}", timeout=3) as r:
        return r.status, r.read()


def test_static_files_served(running_server):
    for path in ("/", "/app.js", "/style.css", "/vendor/lightweight-charts.standalone.production.js"):
        status, body = _get(running_server, path)
        assert status == 200
        assert len(body) > 0


def test_days_and_bars_and_levels_endpoints(running_server):
    status, body = _get(running_server, "/api/days?exclude_thin=false")
    days = json.loads(body)
    assert status == 200 and len(days) > 100
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
