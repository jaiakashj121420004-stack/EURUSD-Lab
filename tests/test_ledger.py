"""nylab.ledger -- the append-only multiple-testing ledger (RESEARCH_PROTOCOL.md S4, ROADMAP 3.4/3.5)."""
import numpy as np
import pandas as pd

from nylab import ledger as ledger_mod


def test_append_is_append_only_and_never_rewrites(tmp_path):
    path = str(tmp_path / "ledger.csv")
    ledger_mod.append([dict(run_id="r1", timestamp="t1", kind="hypothesis", id="H001", version="1.0",
                             n=100, stat=1.2, p=0.2, is_metric=0.5, oos_metric=0.5, verdict="noise", notes="")],
                       path=path)
    ledger_mod.append([dict(run_id="r2", timestamp="t2", kind="hypothesis", id="H002", version="1.0",
                             n=200, stat=2.2, p=0.02, is_metric=0.6, oos_metric=0.6, verdict="candidate", notes="")],
                       path=path)
    df = ledger_mod.load(path)
    assert len(df) == 2
    assert list(df["run_id"]) == ["r1", "r2"]  # first row untouched by the second append


def test_distinct_m_counts_unique_id_version_pairs(tmp_path):
    path = str(tmp_path / "ledger.csv")
    ledger_mod.append([
        dict(run_id="r1", timestamp="t", kind="hypothesis", id="H001", version="1.0", n=1, stat=0, p=1,
             is_metric=None, oos_metric=None, verdict="noise", notes=""),
        dict(run_id="r1", timestamp="t", kind="hypothesis", id="H002", version="1.0", n=1, stat=0, p=1,
             is_metric=None, oos_metric=None, verdict="noise", notes=""),
    ], path=path)
    assert ledger_mod.distinct_m(path) == 2


def test_rerunning_an_unchanged_hypothesis_does_not_increase_m(tmp_path):
    """RESEARCH_PROTOCOL S4: 're-running an unchanged hypothesis does not increase m'."""
    path = str(tmp_path / "ledger.csv")
    ledger_mod.append([dict(run_id="r1", timestamp="t", kind="hypothesis", id="H001", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path)
    m_before = ledger_mod.distinct_m(path, extra_ids=[("H001", "1.0")])
    ledger_mod.append([dict(run_id="r2", timestamp="t", kind="hypothesis", id="H001", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path)
    m_after = ledger_mod.distinct_m(path, extra_ids=[("H001", "1.0")])
    assert m_before == m_after == 1


def test_changing_version_does_increase_m(tmp_path):
    path = str(tmp_path / "ledger.csv")
    ledger_mod.append([dict(run_id="r1", timestamp="t", kind="hypothesis", id="H001", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path)
    m_v1 = ledger_mod.distinct_m(path, extra_ids=[("H001", "1.0")])
    m_v2 = ledger_mod.distinct_m(path, extra_ids=[("H001", "2.0")])
    assert m_v2 == m_v1 + 1


def test_matrix_family_weight_counts_rows_times_cols(tmp_path):
    """ROADMAP 5.4: a hypothesis with matrix_shape=(rows, cols) counts as rows*cols tests,
    not 1, via the 3-tuple (id, version, matrix_cells) extra_ids form."""
    path = str(tmp_path / "ledger.csv")
    m = ledger_mod.distinct_m(path, extra_ids=[("H001", "1.0", 1), ("H016", "1.0", 36)])
    assert m == 37


def test_matrix_cells_persisted_and_read_back(tmp_path):
    path = str(tmp_path / "ledger.csv")
    ledger_mod.append([
        dict(run_id="r1", timestamp="t", kind="hypothesis", id="H001", version="1.0", n=1, stat=0, p=1,
             is_metric=None, oos_metric=None, verdict="noise", notes="", matrix_cells=1),
        dict(run_id="r1", timestamp="t", kind="hypothesis", id="H016", version="1.0", n=1, stat=0, p=1,
             is_metric=None, oos_metric=None, verdict="noise", notes="", matrix_cells=36),
    ], path=path)
    assert ledger_mod.distinct_m(path) == 37
    # re-running the same (id, version) pairs again must not inflate m further.
    m_again = ledger_mod.distinct_m(path, extra_ids=[("H001", "1.0", 1), ("H016", "1.0", 36)])
    assert m_again == 37


def test_old_schema_ledger_without_matrix_cells_defaults_to_weight_1(tmp_path):
    """A ledger.csv written before ROADMAP 5.4 has no matrix_cells column at all --
    distinct_m() must still work (defaulting every row's weight to 1), not crash."""
    path = tmp_path / "ledger.csv"
    path.write_text(
        "run_id,timestamp,kind,id,version,n,stat,p,is_metric,oos_metric,verdict,notes\n"
        "r1,t,hypothesis,H001,1.0,100,1.0,0.3,0.5,0.5,noise,\n"
        "r1,t,hypothesis,H002,1.0,100,1.0,0.3,0.5,0.5,noise,\n"
    )
    assert ledger_mod.distinct_m(str(path)) == 2


def test_append_migrates_old_schema_ledger_in_place(tmp_path):
    """append() widens an old-schema file (no matrix_cells column) in place, WITHOUT changing
    any existing row's own values, so subsequent appends have one consistent column set."""
    path = tmp_path / "ledger.csv"
    path.write_text(
        "run_id,timestamp,kind,id,version,n,stat,p,is_metric,oos_metric,verdict,notes\n"
        "r1,t,hypothesis,H001,1.0,100,1.0,0.3,0.5,0.5,noise,\n"
    )
    ledger_mod.append([dict(run_id="r2", timestamp="t2", kind="hypothesis", id="H016", version="1.0",
                             n=50, stat=1.5, p=0.1, is_metric=0.3, oos_metric=0.3, verdict="noise",
                             notes="", matrix_cells=36)], path=str(path))
    df = ledger_mod.load(str(path))
    assert len(df) == 2
    assert df.loc[0, "run_id"] == "r1" and df.loc[0, "matrix_cells"] == 1  # migrated, unchanged otherwise
    assert df.loc[1, "run_id"] == "r2" and df.loc[1, "matrix_cells"] == 36


def test_dedupe_same_day_skips_a_repeat_of_the_same_id_version(tmp_path):
    """ROADMAP 9.2: the daily automation script's safety net -- re-running the same unchanged
    hypothesis later the SAME day should not write a second physical row."""
    path = str(tmp_path / "ledger.csv")
    today = pd.Timestamp.now(tz="UTC").isoformat()
    ledger_mod.append([dict(run_id="r1", timestamp=today, kind="hypothesis", id="H001", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path)
    ledger_mod.append([dict(run_id="r2", timestamp=today, kind="hypothesis", id="H001", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path, dedupe_same_day=True)
    df = ledger_mod.load(path)
    assert len(df) == 1
    assert df.loc[0, "run_id"] == "r1"  # the original row, untouched


def test_dedupe_same_day_still_writes_a_genuinely_new_id(tmp_path):
    path = str(tmp_path / "ledger.csv")
    today = pd.Timestamp.now(tz="UTC").isoformat()
    ledger_mod.append([dict(run_id="r1", timestamp=today, kind="hypothesis", id="H001", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path)
    ledger_mod.append([dict(run_id="r2", timestamp=today, kind="hypothesis", id="H002", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path, dedupe_same_day=True)
    df = ledger_mod.load(path)
    assert len(df) == 2
    assert set(df["id"]) == {"H001", "H002"}


def test_dedupe_same_day_does_not_skip_a_repeat_on_a_different_day(tmp_path):
    """A row from yesterday shouldn't block today's row for the same (id, version)."""
    path = str(tmp_path / "ledger.csv")
    yesterday = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).isoformat()
    today = pd.Timestamp.now(tz="UTC").isoformat()
    ledger_mod.append([dict(run_id="r1", timestamp=yesterday, kind="hypothesis", id="H001", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path)
    ledger_mod.append([dict(run_id="r2", timestamp=today, kind="hypothesis", id="H001", version="1.0",
                             n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")],
                       path=path, dedupe_same_day=True)
    df = ledger_mod.load(path)
    assert len(df) == 2


def test_dedupe_same_day_false_by_default_keeps_old_behavior(tmp_path):
    """Default (no flag) is the pre-9.2 behavior: every row gets written, always -- a manual
    `python -m nylab run` (no --dedupe-same-day) must be completely unaffected by this feature."""
    path = str(tmp_path / "ledger.csv")
    today = pd.Timestamp.now(tz="UTC").isoformat()
    row = dict(run_id="r", timestamp=today, kind="hypothesis", id="H001", version="1.0",
               n=1, stat=0, p=1, is_metric=None, oos_metric=None, verdict="noise", notes="")
    ledger_mod.append([row], path=path)
    ledger_mod.append([row], path=path)
    assert len(ledger_mod.load(path)) == 2


def test_bonferroni_alpha():
    assert ledger_mod.bonferroni_alpha(15) == 0.05 / 15
    assert ledger_mod.bonferroni_alpha(0) == 0.05  # no ledger yet -- don't divide by zero


def test_bh_significant_matches_textbook_example():
    """Classic BH worked example: 10 p-values, q=0.10 -- ranks 1-3 pass (i <= i/10 * 0.10... )
    using the standard step-up rule; verify against a hand-computed expectation."""
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    q = 0.05
    n = len(pvals)
    thresh = [(i + 1) / n * q for i in range(n)]
    # manual step-up: find largest i where sorted p <= threshold
    sig_manual = [False] * n
    passed = [p <= t for p, t in zip(pvals, thresh)]
    if any(passed):
        k = max(i for i, ok in enumerate(passed) if ok)
        sig_manual[: k + 1] = [True] * (k + 1)
    sig = ledger_mod.bh_significant(pvals, q=q)
    assert sig.tolist() == sig_manual


def test_bh_significant_all_null_gives_no_significance():
    rng = np.random.default_rng(0)
    pvals = rng.uniform(0.3, 1.0, size=20)  # all clearly non-significant
    sig = ledger_mod.bh_significant(pvals, q=0.10)
    assert not sig.any()


def test_bh_significant_handles_nan():
    sig = ledger_mod.bh_significant([0.001, float("nan"), 0.5], q=0.10)
    assert sig[1] == False
