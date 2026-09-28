"""ROADMAP 8.1: nylab.report.deeplink -- the ?date=&until= replay deep-link URL builder."""
from __future__ import annotations

import pandas as pd
import pytest

from nylab.report import deeplink


def test_replay_url_basic_same_day_time():
    url = deeplink.replay_url("2024-03-15", 8.5)
    assert url == "http://127.0.0.1:8765/?date=2024-03-15&until=08:30"


def test_replay_url_accepts_timestamp():
    url = deeplink.replay_url(pd.Timestamp("2024-03-15"), 3.25)
    assert url == "http://127.0.0.1:8765/?date=2024-03-15&until=03:15"


def test_replay_url_negative_hour_rolls_back_to_previous_calendar_day():
    # h=-1.75 means 22:15 on the calendar day BEFORE td (Asia-session-style negative hour).
    url = deeplink.replay_url("2024-03-15", -1.75)
    assert url == "http://127.0.0.1:8765/?date=2024-03-14&until=22:15"


def test_replay_url_hour_past_24_rolls_forward_a_day():
    url = deeplink.replay_url("2024-03-15", 25.5)
    assert url == "http://127.0.0.1:8765/?date=2024-03-16&until=01:30"


def test_replay_url_exact_midnight():
    url = deeplink.replay_url("2024-03-15", 0.0)
    assert url == "http://127.0.0.1:8765/?date=2024-03-15&until=00:00"


def test_replay_url_custom_host_and_port():
    url = deeplink.replay_url("2024-03-15", 9.0, host="192.168.1.5", port=9000)
    assert url.startswith("http://192.168.1.5:9000/?date=2024-03-15&until=09:00")


def test_replay_url_rounds_to_nearest_minute():
    # 7.999999h ~= 07:59:59.996 -> rounds up to 08:00, not down to 07:59.
    url = deeplink.replay_url("2024-03-15", 7.999999)
    assert "until=08:00" in url
