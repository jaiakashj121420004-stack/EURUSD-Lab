# Daily automation -- keeping your data fresh automatically (ROADMAP Phase 9)

This sets up your laptop to pull the day's new price bars and re-run the research pipeline by
itself every night, so you never have to remember to do it by hand. It needs your laptop to be on
(or wake itself -- see the optional step at the end) and MT5 to be installed and logged in.

## What it does each time it runs

1. Pulls only the NEW bars from MT5 since the last pull (not the whole history again).
2. Re-runs the hypothesis tests and rebuilds the report, using that fresh data.
3. Refreshes the replay trainer's cache, so `python -m nylab replay` also has the new days.
4. Checks whether your news-calendar file is more than a week old and reminds you to re-export
   it if so (it's a separate manual step -- see the README -- because there's no automatic API
   for it).

It's safe to run more than once on the same day -- nothing gets counted or saved twice, you'll
just see the same result again.

## One-time setup: Windows Task Scheduler

1. Press the **Windows key**, type **Task Scheduler**, and open it.
2. In the panel on the right, click **Create Basic Task...**
3. **Name:** `EURUSD Lab Daily Update` -- click **Next**.
4. **Trigger:** choose **Daily** -- click **Next**.
5. **Start date/time:** pick **4:30:00 AM** (this is deliberately a bit after New York's
   17:30 trading-day rollover, whether it's US winter or summer time right now -- 4:30 AM IST is
   safely after that either way). Leave "Recur every 1 days". Click **Next**.
6. **Action:** choose **Start a program** -- click **Next**.
7. **Program/script:** click **Browse...** and pick `cmd.exe` (normally in
   `C:\Windows\System32\cmd.exe`).
8. **Add arguments (optional):** paste this exactly, replacing the path if your folder is
   somewhere other than `C:\Trading\eurusd-lab`:
   ```
   /c "C:\Trading\eurusd-lab\run_daily.bat"
   ```
9. **Start in (optional):** paste your project folder path, e.g. `C:\Trading\eurusd-lab`
10. Click **Next**, review the summary, then click **Finish**.

That's it -- it'll run automatically from tonight. Nothing appears on screen when it runs (it's
meant to run quietly in the background); check `logs\run_daily.log` in your project folder any
time to see what happened, or open `reports\daily-<today's date>\report.html` for the result.

## Checking it worked

The morning after it first runs, open a Command Prompt in your project folder and look at the
last few lines of the log:
```
type logs\run_daily.log
```
You want to see `run_daily.bat finished OK` near the bottom. If it says `FAILED`, the most common
reason is MT5 wasn't open and logged in at the scheduled time -- open MT5, log in, and leave it
running before 4:30 AM tomorrow.

## Optional: waking your laptop for this

If your laptop is usually asleep at 4:30 AM, Task Scheduler can wake it:
1. In Task Scheduler, find `EURUSD Lab Daily Update` in the task list, right-click it, **Properties**.
2. Go to the **Conditions** tab, tick **Wake the computer to run this task**.
3. Click **OK**.

Your laptop also needs "Allow wake timers" enabled in its power settings (Settings > System >
Power & battery > Screen and sleep > Additional power settings > choose your plan > Change plan
settings > Change advanced power settings > Sleep > Allow wake timers > Enable), and MT5 needs to
already be open and logged in when it wakes (MT5 doesn't auto-login on its own unless you've
ticked "Auto-login" in its own login dialog) -- otherwise skip this and just make sure MT5 is
running and your laptop is on before bed.

## Running it by hand any time

You don't need to wait for the schedule -- open a Command Prompt in your project folder and run:
```
run_daily.bat
```
(Opening it this way, instead of double-clicking the file, keeps the window open afterwards so
you can read the result.)
