"""ROADMAP Phase 5.6 tests: nylab/label_validate.py -- day sampling (stratified floor + random
fill, never trimming the floor), payload building, HTML rendering, and answer scoring."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import label_validate as lv


def _fake_days(n=200, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    labels = ["chop", "normal", "quiet", "reversal", "range_both"]
    df = pd.DataFrame(index=idx)
    for sid, prefix in lv._PREFIX.items():
        vals = rng.choice(labels, size=n, p=[0.5, 0.2, 0.15, 0.1, 0.05])
        df[f"{prefix}_character"] = vals
    # plant exactly ONE "trend" day for nyam_full, buried deep in the pool -- the whole point
    # of the stratified floor is that a 1/200 label still gets picked, not just luck.
    df.loc[idx[137], "nyam_full_character"] = "trend"
    df["day_type"] = rng.choice(["normal_day", "trend_day", "inside_day"], size=n)
    df["dow"] = idx.dayofweek
    return df


def test_sample_days_never_drops_the_stratified_floor():
    days = _fake_days()
    out = lv.sample_days(days, n=30, seed=7)
    assert days.index[137] in out  # the single planted nyam_full "trend" day must survive


def test_sample_days_returns_at_least_n_and_no_duplicates():
    days = _fake_days()
    out = lv.sample_days(days, n=30, seed=7)
    assert len(out) >= 30
    assert len(out) == len(set(out))
    assert list(out) == sorted(out)


def test_sample_days_deterministic_for_fixed_seed():
    days = _fake_days()
    a = lv.sample_days(days, n=30, seed=99)
    b = lv.sample_days(days, n=30, seed=99)
    assert a == b


def _fake_bars_for(tds, seed=2):
    rng = np.random.default_rng(seed)
    rows = []
    for td in tds:
        hs = np.arange(lv.BAR_LO, lv.BAR_HI, 5 / 60.0)
        walk = rng.normal(0, 0.0002, len(hs)).cumsum() + 1.1
        for h, o in zip(hs, walk):
            rows.append(dict(td=td, h=h, open=o, high=o + 0.0001, low=o - 0.0001, close=o + 0.00002))
    return pd.DataFrame(rows)


def test_build_payload_shape_and_bar_window_filter():
    days = _fake_days()
    tds = lv.sample_days(days, n=5, seed=3)
    bars = _fake_bars_for(tds)
    sessions_cfg = {"asia": (-4.0, 0.0), "lon": (0.0, 5.0), "nyam": (5.0, 12.0),
                    "nyam_kz": (5.0, 8.0), "nypm": (12.0, 16.0)}
    payload = lv.build_payload(bars, days, sessions_cfg, tds)
    assert len(payload["days"]) == len(tds)
    d0 = payload["days"][0]
    assert all(lv.BAR_LO <= b[0] < lv.BAR_HI for b in d0["bars"])
    assert {s["id"] for s in d0["sessions"]} == set(lv.SESSIONS_TO_VALIDATE)
    assert d0["day_type"] in ("normal_day", "trend_day", "inside_day")


def test_render_html_embeds_data_and_has_no_leftover_placeholders():
    days = _fake_days()
    tds = lv.sample_days(days, n=5, seed=3)
    bars = _fake_bars_for(tds)
    sessions_cfg = {"asia": (-4.0, 0.0), "lon": (0.0, 5.0), "nyam": (5.0, 12.0),
                    "nyam_kz": (5.0, 8.0), "nypm": (12.0, 16.0)}
    payload = lv.build_payload(bars, days, sessions_cfg, tds)
    html = lv.render_html(payload)
    assert "%%" not in html
    assert "<html>" in html and "</html>" in html
    assert "downloadAnswers" in html
    assert str(len(payload["days"])) in html


def test_score_agreement_rates_and_80pct_flag():
    payload = {"days": [
        {"td": "2024-01-01", "day_type": "normal_day",
         "sessions": [{"id": "asia", "label": "chop"}, {"id": "lon", "label": "trend"}]},
        {"td": "2024-01-02", "day_type": "trend_day",
         "sessions": [{"id": "asia", "label": "chop"}, {"id": "lon", "label": "trend"}]},
        {"td": "2024-01-03", "day_type": "normal_day",
         "sessions": [{"id": "asia", "label": "chop"}, {"id": "lon", "label": "trend"}]},
    ]}
    answers = {
        "2024-01-01|session:asia": {"call": "agree"},
        "2024-01-02|session:asia": {"call": "agree"},
        "2024-01-03|session:asia": {"call": "disagree"},
        "2024-01-01|session:lon": {"call": "agree"},
        "2024-01-02|session:lon": {"call": "disagree"},
        "2024-01-03|session:lon": {"call": "disagree"},
        "2024-01-01|day_type": {"call": "agree"},
        "2024-01-02|day_type": {"call": "agree"},
        "2024-01-03|day_type": {"call": "agree"},
    }
    out = lv.score(answers, payload)
    chop = out[(out.family == "character") & (out.label == "chop")].iloc[0]
    assert chop["n"] == 3 and chop["agree_rate"] == pytest.approx(2 / 3) and not chop["passes_80pct"]
    trend = out[(out.family == "character") & (out.label == "trend")].iloc[0]
    assert trend["n"] == 3 and trend["agree_rate"] == pytest.approx(1 / 3) and not trend["passes_80pct"]
    normal_day = out[(out.family == "day_type") & (out.label == "normal_day")].iloc[0]
    assert normal_day["n"] == 2 and normal_day["agree_rate"] == pytest.approx(1.0) and normal_day["passes_80pct"]


def test_score_ignores_unanswered_and_missing_label_rows():
    payload = {"days": [
        {"td": "2024-01-01", "day_type": None,
         "sessions": [{"id": "asia", "label": "chop"}, {"id": "lon", "label": None}]},
    ]}
    out = lv.score({}, payload)
    assert len(out) == 0
