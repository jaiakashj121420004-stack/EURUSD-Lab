"""nylab.report.deeplink -- ROADMAP 8.1's "open in replay" link. Builds a `nylab replay` URL
that opens a specific trading day paused at a specific NY wall-clock time, using the
`?date=YYYY-MM-DD&until=HH:MM` query-string convention documented in REPLAY_TRAINER.md (this
project's FIRST such deep-link scheme -- none existed before Phase 8) and read by
nylab/replay/static/app.js's boot code.

`entry_h` uses this whole project's `h` convention: hours since the trading day's OWN midnight,
which can be negative (a pre-midnight session, e.g. Asia around h=-4) or >= 24 is never actually
used here but handled anyway for robustness. `?date=` in the URL is therefore not always literally
`td` -- for a negative `entry_h` the wall-clock moment falls on the CALENDAR day before `td`, so
the date in the link is shifted back to match, exactly like nylab/replay/static/app.js's own
`tdPlusHours()` helper already does when computing `state.until` from an hour offset -- the two
must agree, or a deep link would open the right day but the wrong (or a nonexistent) time."""
from __future__ import annotations

import math
from typing import Union

import pandas as pd


def replay_url(td: Union[str, pd.Timestamp], entry_h: float, host: str = "127.0.0.1",
                port: int = 8765) -> str:
    """`td`: the trading day (pd.Timestamp or 'YYYY-MM-DD' string) as recorded in a trades
    DataFrame's own `td` column. `entry_h`: the NY hour (day-relative) to pause at -- typically
    a trade row's own `entry_time_h`. Returns a full http://host:port/?date=...&until=HH:MM URL
    for nylab/replay/static/app.js's boot code to consume."""
    td_ts = pd.Timestamp(td).normalize()
    day_offset = math.floor(entry_h / 24.0)
    actual_date = td_ts + pd.Timedelta(days=day_offset)
    wall_h = entry_h - day_offset * 24.0
    total_minutes = round(wall_h * 60)
    hh, mm = divmod(int(total_minutes), 60)
    date_str = actual_date.strftime("%Y-%m-%d")
    until_str = f"{hh:02d}:{mm:02d}"
    return f"http://{host}:{port}/?date={date_str}&until={until_str}"
