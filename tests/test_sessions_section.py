"""ROADMAP Phase 5.5 tests: nylab/report/sessions_section.py -- the S6 report section.
Runs a short real pipeline (loader -> days -> sessions -> hyp_loader/hyp_engine) so the section
builder gets genuine SESSION tables / day-table columns / an H frame with a real matrix-family
row (H016), then checks the HTML fragment it produces is well-formed and contains every
section header, plus a couple of pure-logic checks on build_figs()."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import config as cfg
from nylab import days as days_mod
from nylab import sessions as sessions_mod
from nylab import hyp_engine, hyp_loader
from nylab import calendar_features
from nylab.data import timezones
from nylab.report import charts as charts_mod
from nylab.report import sessions_section as ss


def _synth_bars(n_days=40, seed=11):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01 00:00", periods=n_days * 288, freq="5min")
    walk = rng.normal(0, 0.00015, len(idx)).cumsum() + 1.10000
    high = walk + rng.uniform(0, 0.00012, len(idx))
    low = walk - rng.uniform(0, 0.00012, len(idx))
    close = walk + rng.normal(0, 0.00003, len(idx))
    df = pd.DataFrame({"server": idx, "open": walk, "high": high, "low": low, "close": close})
    return df


def _synth_calendar(trading_days):
    rng = np.random.default_rng(3)
    rows = []
    for i, td in enumerate(trading_days[::3]):
        rows.append(dict(time_ny=td + pd.Timedelta(hours=3.5), currency="USD", importance=3,
                          event_name="Non-Farm Payrolls", actual=1.0 + rng.normal(0, 0.1),
                          forecast=0.5, previous=0.4))
    for i, td in enumerate(trading_days[::5]):
        rows.append(dict(time_ny=td + pd.Timedelta(hours=4.0), currency="EUR", importance=3,
                          event_name="ECB Main Refinancing Rate", actual=0.2 + rng.normal(0, 0.1),
                          forecast=0.3, previous=0.3))
    cal = pd.DataFrame(rows)
    return calendar_features.compute_surprise(cal)


def _build_pipeline():
    raw = _synth_bars()
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    windows = cfg.legacy_windows()
    d = days_mod.build_days(raw, windows)
    trading_days = pd.DatetimeIndex(d.index)
    cal = _synth_calendar(trading_days)
    d = days_mod.attach_calendar_features(d, cal, cfg.sessions())
    sessions_cfg = cfg.sessions()
    session_tables = sessions_mod.build_all_sessions(raw, d, cal, sessions_cfg, windows["pip"])
    d = sessions_mod.attach_session_features(d, session_tables)
    day_types = sessions_mod.build_day_types(d)
    d = d.join(day_types)
    return raw, d, session_tables, sessions_cfg, cal, windows["pip"]


def _build_H(d, tmp_path):
    hyps = hyp_loader.load_all()
    split_date = d.index[int(len(d) * 0.7)]
    ledger_path = str(tmp_path / "ledger.csv")
    H, rows, m, alpha = hyp_engine.evaluate(d, hyps, split_date, run_id="test_5_5", ledger_path=ledger_path)
    return H, m


def test_build_figs_returns_heatmap_key():
    raw, d, session_tables, sessions_cfg, cal, pip = _build_pipeline()
    figs = ss.build_figs(raw, pip)
    if charts_mod.plt is not None:
        assert "hour_dow_heatmap" in figs
        assert isinstance(figs["hour_dow_heatmap"], str) and len(figs["hour_dow_heatmap"]) > 100


def test_build_returns_html_with_all_section_headers(tmp_path):
    raw, d, session_tables, sessions_cfg, cal, pip = _build_pipeline()
    H, m = _build_H(d, tmp_path)
    figs = ss.build_figs(raw, pip)
    html = ss.build(raw, d, session_tables, sessions_cfg, cal, H, pip, figs)
    assert isinstance(html, str)
    for n in range(5, 11):
        assert f"<h2>{n} ·" in html or f"<h2>{n} " in html, n
    # relational-hypotheses table must show H016's matrix_cells=36 when H016 is in this H frame
    if (H["id"] == "H016").any():
        assert "36" in html.split("<h2>10")[1]


def test_build_without_calendar_skips_news_section_gracefully(tmp_path):
    raw, d, session_tables, sessions_cfg, cal, pip = _build_pipeline()
    hyps = hyp_loader.load_all()
    split_date = d.index[int(len(d) * 0.7)]
    H, rows, m, alpha = hyp_engine.evaluate(d, hyps, split_date, run_id="test_5_5b",
                                             ledger_path=str(tmp_path / "ledger_b.csv"))
    figs = ss.build_figs(raw, pip)
    html = ss.build(raw, d, session_tables, sessions_cfg, None, H, pip, figs)
    assert "news-impact section skipped" in html


def test_build_html_is_well_formed_table_tags(tmp_path):
    raw, d, session_tables, sessions_cfg, cal, pip = _build_pipeline()
    hyps = hyp_loader.load_all()
    split_date = d.index[int(len(d) * 0.7)]
    H, rows, m, alpha = hyp_engine.evaluate(d, hyps, split_date, run_id="test_5_5c",
                                             ledger_path=str(tmp_path / "ledger_c.csv"))
    figs = ss.build_figs(raw, pip)
    html = ss.build(raw, d, session_tables, sessions_cfg, cal, H, pip, figs)
    assert html.count("<table>") == html.count("</table>")
    # rows sometimes carry a class attribute ("<tr class='muted'>"), so match on the open tag
    # prefix rather than the exact literal "<tr>".
    assert html.count("<tr") == html.count("</tr>")
