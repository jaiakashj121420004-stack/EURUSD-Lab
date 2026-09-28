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
from typing import Optional, Union
from urllib.parse import quote

import pandas as pd


def replay_url(td: Union[str, pd.Timestamp], entry_h: float, host: str = "127.0.0.1",
                port: int = 8765, hi_top: Optional[float] = None, hi_bot: Optional[float] = None,
                hi_label: Optional[str] = None,
                hi_from: Optional[Union[str, pd.Timestamp]] = None,
                hi_to: Optional[Union[str, pd.Timestamp]] = None) -> str:
    """`td`: the trading day (pd.Timestamp or 'YYYY-MM-DD' string) as recorded in a trades
    DataFrame's own `td` column. `entry_h`: the NY hour (day-relative) to pause at -- typically
    a trade row's own `entry_time_h`. Returns a full http://host:port/?date=...&until=HH:MM URL
    for nylab/replay/static/app.js's boot code to consume.

    `hi_top`/`hi_bot`/`hi_label` (2026-09-28, hand-check follow-up): an optional price band to
    highlight on arrival -- added because a real fair-value-gap/sweep is often only ~1 pip tall,
    completely invisible on a chart zoomed out to a whole trading day (Akash's own report,
    "where do I have to look for the gap?"). When given, app.js draws a bright labelled band at
    that price and zooms the chart in around `until` so a 1-pip move is actually visible instead
    of a fraction of a pixel. `hi_top`/`hi_bot` don't need to be ordered -- the two are just the
    band's two edges.

    `hi_from`/`hi_to` (2026-09-28, hand-check follow-up part 2): optional plain NY wall-clock
    timestamps bounding the highlight in TIME too, not just price -- Akash's follow-up on the
    first version was that a band spanning the whole visible chart still reads as "the whole day
    is at this price" rather than "the gap is HERE". When both are given, app.js draws a bounded
    box over exactly the bars that formed the gap/sweep instead of a full-width band. Accepts
    anything pd.Timestamp understands; formatted with no timezone suffix so app.js's toEpoch()
    reinterprets the same wall-clock numbers as NY time, exactly like `until` already does."""
    td_ts = pd.Timestamp(td).normalize()
    day_offset = math.floor(entry_h / 24.0)
    actual_date = td_ts + pd.Timedelta(days=day_offset)
    wall_h = entry_h - day_offset * 24.0
    total_minutes = round(wall_h * 60)
    hh, mm = divmod(int(total_minutes), 60)
    date_str = actual_date.strftime("%Y-%m-%d")
    until_str = f"{hh:02d}:{mm:02d}"
    url = f"http://{host}:{port}/?date={date_str}&until={until_str}"
    if hi_top is not None and hi_bot is not None:
        url += f"&hiTop={hi_top:.5f}&hiBot={hi_bot:.5f}"
        if hi_label:
            url += f"&hiLabel={quote(hi_label)}"
        if hi_from is not None and hi_to is not None:
            from_str = pd.Timestamp(hi_from).strftime("%Y-%m-%dT%H:%M:%S")
            to_str = pd.Timestamp(hi_to).strftime("%Y-%m-%dT%H:%M:%S")
            url += f"&hiFrom={from_str}&hiTo={to_str}"
    return url
