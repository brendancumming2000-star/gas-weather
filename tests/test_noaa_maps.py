"""NOAA map provenance, date selection, and partial failure behavior."""
from datetime import date, datetime, timezone
from io import BytesIO
import json

from PIL import Image
import pytest

from data_sources import noaa_maps as maps

CLOCK = datetime(2026, 9, 15, 14, tzinfo=timezone.utc)
DAILY = """Prognostic Discussion for 6 to 10 and 8 to 14 day outlooks
NWS Climate Prediction Center College Park, MD
300 PM EDT Mon September 14 2026
6-10 DAY OUTLOOK FOR SEP 20 - 24 2026
8-14 DAY OUTLOOK FOR SEP 22 - 28 2026
"""
WEEKLY = """Prognostic Discussion for Week 3-4 Temperature and Precipitation Outlooks
NWS Climate Prediction Center College Park MD
300PM EDT Fri Sep 11 2026
Week 3-4 Forecast Discussion Valid Sat Sep 26 2026-Fri Oct 09 2026
"""
SEASONAL = """Prognostic Discussion for Long-Lead Seasonal Outlooks
NWS Climate Prediction Center College Park MD
830 AM EDT Thu Aug 20 2026
"""
PAGE = '''<div>OFFICIAL Forecasts Nov-Dec-Jan 2026-27</div>
<a href="/products/predictions/long_range/seasonal.php?lead=3"> NDJ 2026 - 27 </a>
<img src="/products/predictions/long_range/lead03/off03_temp.gif">
'''


@pytest.fixture
def network(monkeypatch):
    image = BytesIO()
    Image.new("RGB", (8, 8), "white").save(image, format="GIF")
    calls = []

    def text(url):
        calls.append(url)
        if "PMDMRD." in url:
            return DAILY
        if url.endswith("week34fcst.txt"):
            return WEEKLY
        if "fxus05" in url or "PMD90D" in url:
            return SEASONAL
        if "seasonal.php" in url:
            return PAGE
        raise AssertionError(f"Unexpected URL {url}")

    def data(url):
        calls.append(url)
        return image.getvalue()

    monkeypatch.setattr(maps, "get_text", text)
    monkeypatch.setattr(maps, "get_bytes", data)
    return calls, text, data


def test_previous_day_uses_eastern_midnight():
    before = maps.requested_context(datetime(2026, 9, 15, 3, 59, tzinfo=timezone.utc))
    after = maps.requested_context(datetime(2026, 9, 15, 4, 0, tzinfo=timezone.utc))
    assert before["requested_previous_date"] == "2026-09-13"
    assert after["requested_previous_date"] == "2026-09-14"


def test_winter_standard_time_and_season_rollover():
    before = maps.requested_context(datetime(2027, 2, 1, 4, 59, tzinfo=timezone.utc))
    after = maps.requested_context(datetime(2027, 2, 1, 5, 0, tzinfo=timezone.utc))
    assert before["requested_previous_date"] == "2027-01-30"
    assert before["requested_season"] == "NDJ 2026–27"
    assert after["requested_previous_date"] == "2027-01-31"
    assert after["requested_season"] == "NDJ 2027–28"


def test_daily_dates_are_read_and_checked():
    result = maps.parse_short_metadata(DAILY, date(2026, 9, 14), "8–14 day")
    assert result["valid_start"] == "2026-09-22"
    assert result["valid_end"] == "2026-09-28"
    with pytest.raises(ValueError, match="does not match requested"):
        maps.parse_short_metadata(DAILY, date(2026, 9, 13), "8–14 day")
    with pytest.raises(ValueError, match="valid dates"):
        maps.parse_short_metadata(DAILY.replace("22 - 28", "23 - 29"), date(2026, 9, 14), "8–14 day")


def test_daily_period_spanning_new_year():
    text = """Prognostic Discussion
300 PM EST Sat December 25 2027
6-10 DAY OUTLOOK FOR DEC 31 - JAN 4 2028"""
    result = maps.parse_short_metadata(text, date(2027, 12, 25), "6–10 day")
    assert result["valid_start"] == "2027-12-31"
    assert result["valid_end"] == "2028-01-04"


def test_daily_period_with_explicit_start_year():
    text = """Prognostic Discussion
300 PM EST Sat December 25 2027
6-10 DAY OUTLOOK FOR DEC 31 2027 - JAN 4 2028"""
    assert maps.parse_short_metadata(text, date(2027, 12, 25), "6–10 day")["valid_start"] == "2027-12-31"


def test_week_validity_cannot_use_another_issue():
    result = maps.parse_week_metadata(WEEKLY, date(2026, 9, 11))
    assert result["valid_end"] == "2026-10-09"
    with pytest.raises(ValueError, match="selected Friday"):
        maps.parse_week_metadata(WEEKLY, date(2026, 9, 18))
    with pytest.raises(ValueError, match="valid dates"):
        maps.parse_week_metadata(WEEKLY.replace("Oct 09", "Oct 08"), date(2026, 9, 11))


def test_issue_requires_dateline_not_prose_date():
    with pytest.raises(ValueError, match="dateline"):
        maps.parse_issue("A discussion written about September 14 2026")


def test_season_is_selected_from_link_text():
    assert maps.select_season_link(PAGE, 2026).endswith("?lead=3")
    with pytest.raises(ValueError, match="does not list"):
        maps.select_season_link(PAGE, 2027)


def test_season_navigation_match_is_not_selected_period():
    wrong_page = PAGE.replace("OFFICIAL Forecasts Nov-Dec-Jan 2026-27", "OFFICIAL Forecasts Oct-Nov-Dec 2026")
    with pytest.raises(ValueError, match="Selected seasonal page"):
        maps.parse_season_image(wrong_page, 2026, maps.SEASON_PAGE)


def test_season_image_must_come_from_official_host():
    bad = PAGE.replace('/products/predictions/long_range/lead03/off03_temp.gif',
                       'https://example.com/products/predictions/long_range/lead03/off03_temp.gif')
    with pytest.raises(ValueError, match="outside official"):
        maps.parse_season_image(bad, 2026, maps.SEASON_PAGE)


def test_fetch_all_maps_are_snapshots_with_separate_real_issue_dates(network):
    result = maps.fetch(CLOCK)
    assert not result["warnings"]
    assert result["requested_previous_date"] == "2026-09-14"
    assert result["requested_season"] == "NDJ 2026–27"
    assert [p["observed_at"] for p in result["previous_outlooks"]] == ["2026-09-14", "2026-09-14", "2026-09-11"]
    assert result["seasonal"]["observed_at"] == "2026-08-20"
    assert all(p["is_dated_archive"] for p in result["previous_outlooks"])
    assert all(p["image_base64"] and p["image_mime_type"] == "image/gif"
               for p in result["previous_outlooks"] + [result["seasonal"]])
    assert not any(".new.gif" in url for url in network[0])
    json.dumps(result)  # database/cache payload has no dates, bytes, or NaNs


def test_one_daily_image_failure_preserves_other_products(network, monkeypatch):
    original = network[2]
    def data(url):
        if "610temp" in url:
            raise RuntimeError("temporary outage")
        return original(url)
    monkeypatch.setattr(maps, "get_bytes", data)
    result = maps.fetch(CLOCK)
    assert [p["name"] for p in result["previous_outlooks"]] == ["8–14 day", "Weeks 3–4"]
    assert result["seasonal"]
    assert any("6–10 day" in warning for warning in result["warnings"])


def test_shared_daily_discussion_failure_preserves_week_and_season(network, monkeypatch):
    original = network[1]
    def text(url):
        if "PMDMRD" in url:
            raise RuntimeError("discussion outage")
        return original(url)
    monkeypatch.setattr(maps, "get_text", text)
    result = maps.fetch(CLOCK)
    assert [p["name"] for p in result["previous_outlooks"]] == ["Weeks 3–4"]
    assert result["seasonal"]
    assert result["warnings"]


def test_future_weekly_issue_is_rejected(network, monkeypatch):
    original = network[1]
    def text(url):
        return WEEKLY.replace("Sep 11", "Sep 18") if url.endswith("week34fcst.txt") else original(url)
    monkeypatch.setattr(maps, "get_text", text)
    result = maps.fetch(CLOCK)
    assert [p["name"] for p in result["previous_outlooks"]] == ["6–10 day", "8–14 day"]
    assert result["seasonal"]


def test_friday_asof_uses_previous_friday(network, monkeypatch):
    seen = []
    def unavailable(url):
        seen.append(url)
        raise RuntimeError("missing")
    monkeypatch.setattr(maps, "get_text", unavailable)
    maps.fetch(datetime(2026, 9, 18, 20, tzinfo=timezone.utc))
    assert any("archives/2026/09/11/week34fcst.txt" in url for url in seen)
    assert not any("archives/2026/09/18/week34fcst.txt" in url for url in seen)


def test_future_season_issue_is_rejected(network, monkeypatch):
    original = network[1]
    def text(url):
        return SEASONAL.replace("Aug 20", "Sep 17") if "fxus05" in url else original(url)
    monkeypatch.setattr(maps, "get_text", text)
    result = maps.fetch(CLOCK)
    assert result["seasonal"] == {}
    assert len(result["previous_outlooks"]) == 3


def test_season_rollover_during_download_is_rejected(network, monkeypatch):
    original = network[1]
    count = 0
    def text(url):
        nonlocal count
        if "fxus05" in url:
            count += 1
            return SEASONAL if count == 1 else SEASONAL.replace("Aug 20", "Sep 17")
        return original(url)
    monkeypatch.setattr(maps, "get_text", text)
    result = maps.fetch(CLOCK)
    assert result["seasonal"] == {}
    assert any("changed during download" in warning for warning in result["warnings"])


def test_all_outage_is_missing_not_fabricated_maps(monkeypatch):
    def unavailable(url):
        raise RuntimeError("offline")
    monkeypatch.setattr(maps, "get_text", unavailable)
    result = maps.fetch(CLOCK)
    assert result["previous_outlooks"] == []
    assert result["seasonal"] == {}
    assert result["observed_at"] is None
    assert len(result["warnings"]) == 3


def test_html_or_truncated_image_is_not_cached(network, monkeypatch):
    monkeypatch.setattr(maps, "get_bytes", lambda url: b"<html>Service unavailable, please try later.</html>")
    result = maps.fetch(CLOCK)
    assert result["previous_outlooks"] == [] and not result["seasonal"]
    monkeypatch.setattr(maps, "get_bytes", lambda url: b"GIF89a" + b"\0" * 24)
    result = maps.fetch(CLOCK)
    assert result["previous_outlooks"] == [] and not result["seasonal"]


def test_weekly_archive_outage_can_show_older_issue_with_warning(network, monkeypatch):
    original = network[1]
    def text(url):
        if "archives/2026/09/11/week34fcst.txt" in url:
            raise RuntimeError("archive delay")
        if "archives/2026/09/04/week34fcst.txt" in url:
            return WEEKLY.replace("Sep 11", "Sep 04").replace("Sep 26", "Sep 19").replace("Oct 09", "Oct 02")
        return original(url)
    monkeypatch.setattr(maps, "get_text", text)
    result = maps.fetch(CLOCK)
    weekly = result["previous_outlooks"][-1]
    assert weekly["name"] == "Weeks 3–4"
    assert weekly["observed_at"] == "2026-09-04"
    assert weekly["expected_issue_date"] == "2026-09-11"
    assert not weekly["is_expected_weekly_issue"]
    assert "newer map may exist" in result["warnings"][0]
