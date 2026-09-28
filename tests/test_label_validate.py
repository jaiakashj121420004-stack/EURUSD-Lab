"""ROADMAP Phase 5.6 tests: nylab/label_validate.py -- day sampling (stratified floor + random
fill, never trimming the floor; and stratified floor + near-threshold curated fill), payload
building, HTML rendering, and answer scoring."""
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
    # plant exactly ONE "trend" day for nyam_sb, buried deep in the pool -- the whole point
    # of the stratified floor is that a 1/200 label still gets picked, not just luck.
    df.loc[idx[137], "nyam_sb_character"] = "trend"
    df["day_type"] = rng.choice(["normal_day", "trend_day", "inside_day"], size=n)
    df["dow"] = idx.dayofweek
    return df


def _fake_days_with_features(n=200, seed=1):
    """Same label columns as `_fake_days`, plus the continuous feature columns
    `sample_days_curated`'s boundary-distance ranking needs (range_rel/er/close_loc per
    validated session; day_high/day_low/day_close/pdh/pdl for day_type) -- uniform random in
    each feature's plausible range so some fake days land near a threshold and some don't."""
    days = _fake_days(n=n, seed=seed)
    rng = np.random.default_rng(seed + 100)
    for sid, prefix in lv._PREFIX.items():
        days[f"{prefix}_range_rel"] = rng.uniform(0.2, 2.0, n)
        days[f"{prefix}_er"] = rng.uniform(0.0, 1.0, n)
        days[f"{prefix}_close_loc"] = rng.uniform(0.0, 1.0, n)
    day_open = rng.uniform(1.05, 1.15, n)
    day_range = rng.uniform(0.002, 0.02, n)
    day_high = day_open + day_range * rng.uniform(0.3, 0.7, n)
    day_low = day_open - day_range * rng.uniform(0.3, 0.7, n)
    days["day_open"] = day_open
    days["day_high"] = day_high
    days["day_low"] = day_low
    days["day_close"] = day_low + rng.uniform(0.0, 1.0, n) * (day_high - day_low)
    days["pdh"] = pd.Series(day_high, index=days.index).shift(1).bfill()
    days["pdl"] = pd.Series(day_low, index=days.index).shift(1).bfill()
    return days


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


def test_sample_days_curated_never_drops_the_stratified_floor():
    days = _fake_days_with_features()
    out = lv.sample_days_curated(days, n=20, seed=43)
    assert days.index[137] in out  # same planted rare-label day as the random-strategy test


def test_sample_days_curated_returns_at_least_n_and_no_duplicates():
    days = _fake_days_with_features()
    out = lv.sample_days_curated(days, n=20, seed=43)
    assert len(out) >= 20
    assert len(out) == len(set(out))
    assert list(out) == sorted(out)


def test_sample_days_curated_deterministic_for_fixed_seed():
    days = _fake_days_with_features()
    a = lv.sample_days_curated(days, n=20, seed=43)
    b = lv.sample_days_curated(days, n=20, seed=43)
    assert a == b


def test_sample_days_curated_exclude_days_removes_them_from_the_pool():
    """ROADMAP 5.6 audit fix (2026-09-28): a genuinely fresh verification round must not be able
    to re-select a day Akash has already judged."""
    days = _fake_days_with_features()
    baseline = lv.sample_days_curated(days, n=20, seed=43)
    to_exclude = frozenset(baseline[:5])  # 5 days that WOULD have been picked
    out = lv.sample_days_curated(days, n=20, seed=43, exclude_days=to_exclude)
    assert not (set(out) & to_exclude)
    assert len(out) >= 20  # the floor/fill guarantee still holds, just from the remaining pool


def test_sample_days_curated_exclude_days_empty_is_a_no_op():
    days = _fake_days_with_features()
    a = lv.sample_days_curated(days, n=20, seed=43)
    b = lv.sample_days_curated(days, n=20, seed=43, exclude_days=frozenset())
    assert a == b


def test_previously_reviewed_days_reads_every_meta_file_in_the_dir(tmp_path):
    import json
    (tmp_path / "sample_42_meta.json").write_text(json.dumps(
        {"days": [{"td": "2022-03-11"}, {"td": "2022-04-13"}]}))
    (tmp_path / "sample_44_meta.json").write_text(json.dumps(
        {"days": [{"td": "2023-08-17"}, {"td": "2022-03-11"}]}))  # overlap with the first file
    (tmp_path / "not_a_meta_file.json").write_text(json.dumps({"unrelated": True}))
    out = lv.previously_reviewed_days(str(tmp_path))
    assert out == {pd.Timestamp("2022-03-11"), pd.Timestamp("2022-04-13"), pd.Timestamp("2023-08-17")}


def test_previously_reviewed_days_empty_dir_returns_empty_set(tmp_path):
    assert lv.previously_reviewed_days(str(tmp_path)) == set()


def test_previously_reviewed_days_skips_unparseable_file(tmp_path):
    (tmp_path / "sample_1_meta.json").write_text("not valid json{{{")
    (tmp_path / "sample_2_meta.json").write_text('{"days": [{"td": "2024-01-01"}]}')
    assert lv.previously_reviewed_days(str(tmp_path)) == {pd.Timestamp("2024-01-01")}


def test_sample_days_curated_prefers_near_boundary_days_over_random_fill():
    """The whole point of the curated strategy: beyond the shared stratified floor, its FILL
    days should sit closer to a rule boundary (lower `_day_ambiguity_score`) than the uniform-
    random fill `sample_days` would pick, on average. This is a deterministic comparison (both
    functions are seeded), not a statistical one, so there's no flakiness risk."""
    days = _fake_days_with_features()
    floor, _ = lv._stratified_floor(days, seed=43)
    # n well above the floor size (28 for this fixture/seed) so both strategies actually add
    # fill days beyond it -- with n <= floor size there's nothing to compare.
    n = len(floor) + 30
    curated = lv.sample_days_curated(days, n=n, seed=43)
    randomized = lv.sample_days(days, n=n, seed=43)

    def mean_fill_score(tds):
        fill = [td for td in tds if td not in floor]
        scores = [lv._day_ambiguity_score(days.loc[td]) for td in fill]
        scores = [s for s in scores if not np.isnan(s)]
        return np.mean(scores) if scores else None

    curated_mean = mean_fill_score(curated)
    random_mean = mean_fill_score(randomized)
    assert curated_mean is not None and random_mean is not None
    assert curated_mean < random_mean


def test_character_boundary_distance_is_zero_right_on_a_threshold():
    row = pd.Series({"x_range_rel": 0.6, "x_er": 1.0, "x_close_loc": 0.5})
    assert lv._character_boundary_distance(row, "x") == pytest.approx(0.0)


def test_character_boundary_distance_nan_when_a_feature_is_missing():
    row = pd.Series({"x_range_rel": np.nan, "x_er": 1.0, "x_close_loc": 0.5})
    assert np.isnan(lv._character_boundary_distance(row, "x"))


def test_day_type_boundary_distance_uses_day_range_normalization():
    # day_high sits exactly on pdh -> distance 0 regardless of the day's own range size.
    row = pd.Series({"day_high": 1.1050, "day_low": 1.1000, "day_close": 1.1020,
                      "pdh": 1.1050, "pdl": 1.0950})
    assert lv._day_type_boundary_distance(row) == pytest.approx(0.0)


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
                    "lon_ny_gap": (5.0, 7.0), "nyam_kz": (5.0, 8.0), "nyam_sb": (8.0, 9.0),
                    "nypm": (12.0, 16.0)}
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
                    "lon_ny_gap": (5.0, 7.0), "nyam_kz": (5.0, 8.0), "nyam_sb": (8.0, 9.0),
                    "nypm": (12.0, 16.0)}
    payload = lv.build_payload(bars, days, sessions_cfg, tds)
    html = lv.render_html(payload)
    assert "%%" not in html
    assert "<html" in html and "</html>" in html
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
