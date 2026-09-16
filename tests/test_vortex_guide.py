"""Watch-state regressions: season, freshness, and initial versus forecast reversal."""
import pytest

from components.vortex_guide import vortex_watch


def forecast(initial=20, final=-5, complete=True, issued="2026-01-15T06:00:00Z"):
    return {"model_run": issued, "polar_vortex": {"complete": complete, "rows": [
        {"date": "2026-01-15", "u10_ms": initial},
        {"date": "2026-01-16", "u10_ms": final},
    ]}}


def test_september_never_displays_a_midwinter_reversal_alert():
    title, _ = vortex_watch(forecast(), now="2026-09-15T12:00:00Z")
    assert title == "Winter watch is not active"


@pytest.mark.parametrize("issued", [None, "invalid", "2026-01-14T06:00:00Z", "2026-01-16T00:00:00Z"])
def test_missing_stale_and_future_issues_cannot_show_current_winter_alerts(issued):
    title, _ = vortex_watch(forecast(issued=issued), now="2026-01-15T12:00:00Z")
    assert title == "Current winter clue unavailable"


def test_existing_easterly_flow_is_not_announced_as_a_new_reversal():
    title, _ = vortex_watch(forecast(initial=-1), now="2026-01-15T12:00:00Z")
    assert title == "Unusual winter winds already present"
    title, _ = vortex_watch(forecast(), now="2026-01-15T12:00:00Z")
    assert title == "A winter wind change to watch"


def test_partial_nonreversing_forecast_cannot_exclude_a_wind_reversal():
    title, _ = vortex_watch(forecast(final=10, complete=False), now="2026-01-15T12:00:00Z")
    assert title == "Current winter clue unavailable"
    title, _ = vortex_watch(forecast(final=10), now="2026-01-15T12:00:00Z")
    assert title == "No winter wind reversal forecast"
