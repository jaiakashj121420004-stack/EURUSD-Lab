# HANDOFF.md — how to finish this project (written 2026-09-28 after a full audit)

Read this, then `CLAUDE.md`, then the latest entries at the bottom of `docs/PROGRESS.md`, then
`docs/ROADMAP.md`. This file tells you where things stand, how to work safely in this setup, and the
exact order of the remaining work.

---

## 1. Source of truth (read first — a previous session got this wrong)

- The ONE real copy is **`C:\Trading\eurusd-lab` on Akash's Windows laptop** (reached through the
  linked-computer tools; in the device shell it is `$HOME/mnt/Trading/eurusd-lab`). It is a git repo on
  branch `main`, tracking **GitHub `jaiakashj121420004-stack/EURUSD-Lab` (public)**.
- Ignore any other copy you may find (`/home/claude/smoke`, `/mnt/user-data/uploads/...`, old
  summaries). An earlier session reported "Phases 7–10 not started" from a stale copy; they weren't.
- **Before claiming anything is done or not done, check `git log --oneline` and the files themselves.**
- The repo is PUBLIC. `.gitignore` keeps out: `data/`, broker CSVs, `reports/`, `research/ledger.csv`,
  the replay journal/presets/shots, label-validation answers, `.env`. Never commit Akash's data or keys.

## 2. Status at hand-off (verified 2026-09-28)

| Phase | Status |
|---|---|
| 0–4 | Done |
| 5.1–5.5 | Done |
| **5.6 label validation** | **OPEN** — round 4: `chop` 22/30 = 73.3% < 80%. Needs Akash's go-ahead (§4 step 2) |
| **5 accept — cross-session planted edge (AT-02 part 2)** | **NOT BUILT** (no fixture variant, no test) |
| 5.7, 5.8 | Done, confirmed on Akash's laptop |
| 6 Replay trainer v2 | Done |
| 7 ICT features & models | Done, except Akash's manual check of 10 FVGs + 10 sweeps |
| **8** | 8.2, 8.3 done; **8.1 and 8.4 partial** (details in §4 step 1) |
| 9, 10 | Not started |

Tests: **299/299** pass — sandbox on pandas 2.3.3 and 3.0.6, and on Akash's laptop (python 3.14.6,
pandas 3.0.6, numpy 2.5.3) via `run_tests.bat`. Real 5-year `nylab run` ≈ 45 s (budget 90 s).
Real-data results right now: 15 hypotheses `noise`, H016 `weak`; `london_sweep_reversal` = `negative`.

## 3. How to work in this setup (hard-won lessons)

**Shell:** the device shell is a Linux VM on his laptop with Python 3.10. Each command is killed after
≤180 s and background processes die when the command ends (`nohup`/`&` do NOT survive). So:
- Run pytest **file by file, in batches** that fit in one call; the slowest single file
  (`tests/test_models_silver_bullet_fvg.py`) takes ~70 s. Always pass `-p no:cacheprovider` and set
  `PYTHONDONTWRITEBYTECODE=1`.
- Test on **both** pandas ends (CLAUDE.md §5a). Recreate a pandas-3 env if it's gone:
  `python3 -m pip install --user uv && ~/.local/bin/uv python install 3.12 && ~/.local/bin/uv venv -p 3.12 ~/v3 && ~/.local/bin/uv pip install -p ~/v3/bin/python "pandas==3.0.6" "numpy==2.5.3" pyyaml pytest pyarrow matplotlib`
- Safest: `cp -r` the repo to `~/lab`, develop and test there, then copy only the changed files back
  and `diff -rq` to confirm.

**Unit tests are not enough.** On 2026-09-28 every unit test passed while `python -m nylab run` —
the main command — crashed. After ANY change, also run end to end:
`python -m nylab run tests/fixtures/EURUSD_M5_synth_clean_5y.csv --tz ny+7 --out ~/o/r --run-id t --no-cache --ledger-path ~/o/ledger.csv`
and on the real data with a **copied** ledger (`--ledger-path ~/o/ledger_copy.csv`) so test runs never
append to Akash's real `research/ledger.csv`. (Synthetic fixture CSVs are git-ignored; if missing,
regenerate with `tests/fixtures/make_synth.py`.)

**Git:**
- Use `git --no-optional-locks status`. File deletion in `C:\Trading` is off by default; a stray
  `.git/index.lock` you can't delete will block git on his laptop — ask for delete permission if needed.
- Commit on the laptop repo (author is already configured). **Pushing:** the device shell has no
  GitHub login. Either ask Akash to run `git push` in PowerShell in `C:\Trading\eurusd-lab`, or push
  from the cloud workspace: attach the repo (push access), `git bundle create` on the laptop into
  `C:\Trading`, stage it, clone/fetch it in the cloud, push, then bring the result back with a bundle
  so the laptop's `main` matches `origin/main`. Delete temporary bundles afterwards.
- Commit only after tests pass; one roadmap ticket = one focused commit.

**Rules that override convenience:** CLAUDE.md §3 (no look-ahead, OOS sacred, every test counted,
costs on, conservative fills, no edge claims without evidence, read-only MT5, NY time). A phase is
NOT done until **Akash runs `run_tests.bat` on his laptop and pastes the last line**. Akash wants any
change to trading rules / label thresholds / statistics methodology **explained plainly and confirmed
by him twice** before it is made. He is not a programmer and not an expert trader — plain English,
explain every statistic in one sentence, say "noise" when it's noise. Don't flatter his chart reads;
validate them independently.

## 4. Remaining work, in order

### Step 1 — Finish Phase 8
1. **8.4 Maven simulator into the report.** `maven_simulation.csv` is written but not shown. Add a
   report section (13) and a `maven` block in `summary.json`: per risk level P(pass all phases),
   P(pass each phase), median days, expected attempts. Plain-English note: bootstrapping a
   negative-expectancy model shows how much a pass is luck. **Ask Akash:** (a) which Maven program he
   is actually on (CLAUDE.md says unconfirmed; default is `standard_2step` +8%/+5%); (b) the exact
   fee per attempt for $5k — only then add it to `config/prop.yaml` as verified and pass `fee_usd`.
   Also fill `max trades/day` from the model config instead of assuming 1.
2. **8.1 "every backtest trade".** Right now only the 30 gallery trades get a PNG + replay link. Add an
   "open in replay" link for EVERY trade (a trades table/list in the report, or a `trades.html`
   beside `report.html`) using `nylab.report.deeplink.replay_url` + `snapshot.entry_hour`. PNGs for all
   ~640 trades would bloat the HTML: write them as files under `reports/<run>/trades/` or keep PNGs to
   the gallery — ask Akash which he prefers.
3. **Browser check with Akash:** have him run `python -m nylab replay`, open the report, click 2–3
   gallery links (include one with an entry after 17:00 NY if any exists) and confirm the right day and
   time open. The 2026-09-28 fix to `app.js` (`jumpToTime`, deep-link boot) was checked with node
   only, not in a real browser.
4. Update ROADMAP boxes, PROGRESS, `run_tests.bat` on his laptop → commit → push.

### Step 2 — Close Phase 5 properly
1. **Cross-session planted edge (AT-02 part 2).** Add a `make_synth.py` variant (or extend `planted`)
   that plants "London `chop` → NY AM KZ `reversal` on ~60% of such days", plus a test that the
   engine finds it (`candidate` or better) while AT-01 (clean fixture → no false edges) still holds.
   Note the 2026-09-28 fix: matrix-family BH now counts all 36 cells of a 6×6 matrix, so the planted
   effect must be strong enough to survive that — don't weaken the correction to make the test pass.
2. **5.6 label validation.** Ask Akash whether to run the fresh-sample verification pass for the 5
   "big range / extreme close but labelled chop" cases (PROGRESS 2026-09-27 round 4): new seed, days
   never shown before, check the proposed threshold change against the full 5-year distribution. If
   the change holds, propose it in plain English with examples, get his double confirmation, change
   `nylab/sessions.py`, bump versions of every dependent hypothesis (H016 etc.), run one more
   validation round, and freeze. Tick 5.6 only at ≥80% for every label.
3. **Decision for Akash:** global Benjamini-Hochberg currently runs over this run's tests (+ matrix
   cells), not the full ledger `m` that Bonferroni uses. Explain the trade-off; change only if he says so.

### Step 3 — Close Phase 7
Build a small helper (CLI or report section) that picks 10 random FVGs and 10 random sweeps from the
events table and gives a replay deep link for each, so Akash can hand-check them in review mode.
Record his verdicts in PROGRESS; investigate any disagreement against FEATURES_SPEC before changing code.

### Step 4 — Phase 9, daily automation (ROADMAP)
9.1 incremental bar export (`mt5_export.py` appends only bars after the last timestamp — Windows/MT5,
Akash runs it; you can't run MT5 in the VM). 9.2 `run_daily.bat` + a step-by-step Windows Task
Scheduler guide (run after 17:30 NY = 03:00/04:00 IST depending on US DST). 9.3 forward-test tracking
+ kill-criteria check (RESEARCH_PROTOCOL §7–8; write the kill criteria BEFORE forward testing).
9.4 weekly calendar re-export reminder. **Accept:** running twice on the same day is idempotent (no
duplicate bars, no duplicate ledger rows, same report). Give him exact PowerShell/.bat steps.

### Step 5 — Phase 10, the research loop (ongoing)
Follow CLAUDE.md §6: read `summary.json`, summarise in ≤10 lines with effects in pips/R, propose **at
most 3** hypotheses per session grounded in a Codex concept + a data observation, state the ledger
count and corrected threshold BEFORE running, and get his agreement. Start with ROADMAP Phase 10's
question list (Q1 is partly covered by H016). For any candidate, make a replay filter preset. Never
more than ~10 new hypotheses in a session without his agreement.

## 5. Known minor issues (not urgent)
- `app.js` `tdPlusHours` uses the browser's local timezone; fine in IST (no DST), could be off by an
  hour around DST changes in other timezones.
- One harmless pandas PerformanceWarning in `tests/test_replay_phase6.py`.
- `research/ledger.csv` has a `smoketest5` run from synthetic data; it reuses existing IDs, so `m` is
  unaffected. The ledger is append-only — never edit it.
