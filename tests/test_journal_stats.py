"""tests/test_journal_stats.py -- ROADMAP 6.7 stats-tab aggregation (nylab.replay.journal_stats).
Covers the specific empty-string-vs-NaN grouping gap found during Phase 6 smoke testing: a
trade journal round-tripped through csv.DictWriter/DictReader represents "no tag" as "" (empty
string), not NaN, so a naive .fillna("(none)") alone would leave blank-tag trades in their own
blank "" group instead of folding them into "(none)" alongside genuinely-missing rows."""
from __future__ import annotations

import pandas as pd

from nylab.replay import journal_stats


def _row(R_net, setup_tag="", preset="", td="2024-01-05"):
    return dict(td=td, R_net=R_net, setup_tag=setup_tag, preset=preset)


def test_empty_string_tags_group_with_missing_tags_as_none():
    df = pd.DataFrame([
        _row(1.0, setup_tag=""),
        _row(-0.5, setup_tag=""),
        _row(2.0, setup_tag="breakout"),
    ])
    result = journal_stats.build(df)
    groups = {g["group"]: g["n"] for g in result["by_setup_tag"]}
    assert groups == {"(none)": 2, "breakout": 1}
    assert "" not in groups


def test_build_handles_empty_journal():
    result = journal_stats.build(pd.DataFrame(columns=["td", "R_net", "setup_tag", "preset"]))
    assert result["n_trades"] == 0
    assert result["by_setup_tag"] == []
