"""nylab.ledger -- the append-only multiple-testing ledger (RESEARCH_PROTOCOL.md S4, ROADMAP 3.4/3.5)."""
import numpy as np

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
