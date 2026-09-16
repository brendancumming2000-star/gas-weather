"""No network is needed for these ingestion/units/calendar regression checks."""
from datetime import datetime, timedelta, timezone
import io
import csv

import eccodes
import numpy as np
import pytest

from data_sources.gfs import (forecast_calendar, kelvin_to_fahrenheit, parse_index,
                              polar_cap_mean, zonal_mean_wind, _validate_message)
from data_sources.normals import parse_normals_csv

UTC = timezone.utc


def test_kelvin_conversion_freezing_boiling_and_minus_forty():
    assert kelvin_to_fahrenheit(273.15) == pytest.approx(32)
    assert kelvin_to_fahrenheit(373.15) == pytest.approx(212)
    assert kelvin_to_fahrenheit(233.15) == pytest.approx(-40)


def test_calendar_is_complete_future_utc_days_and_stays_inside_384_hours():
    run = datetime(2026, 9, 14, 18, tzinfo=UTC)
    # Local September 14 is already September 15 UTC.
    now = datetime(2026, 9, 14, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    days = forecast_calendar(run, now)
    assert days[0] == ("2026-09-16", [30, 36, 42, 48])
    assert days[-1] == ("2026-09-30", [366, 372, 378, 384])
    assert len(days) == 15
    assert len({lead for _, leads in days for lead in leads}) == 60


def test_old_model_cannot_silently_shorten_forecast_horizon():
    with pytest.raises(ValueError, match="cannot cover"):
        forecast_calendar(datetime(2026, 9, 14, 12, tzinfo=UTC), datetime(2026, 9, 15, 4, tzinfo=UTC))


def test_naive_forecast_datetimes_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        forecast_calendar(datetime(2026, 9, 14, 18), datetime(2026, 9, 15, 4, tzinfo=UTC))


def test_index_uses_actual_record_boundaries_and_initialization():
    text = "1:0:d=2026091418:HGT:10 mb:6 hour fcst:\n2:100:d=2026091418:TMP:10 mb:6 hour fcst:\n3:250:d=2026091418:UGRD:10 mb:6 hour fcst:\n"
    rows = parse_index(text)
    assert [(r.start, r.end) for r in rows] == [(0, 99), (100, 249), (250, None)]
    assert rows[1].variable == "TMP"
    assert rows[1].init == datetime(2026, 9, 14, 18, tzinfo=UTC)
    with pytest.raises(ValueError, match="no valid"):
        parse_index("<html>Service unavailable</html>")


def test_zonal_wind_uses_entire_60n_circle_and_excludes_other_latitudes():
    assert zonal_mean_wind([10, 20, -30, 500], [60, 60, 60, 61]) == pytest.approx(0)
    with pytest.raises(ValueError, match="60°N"):
        zonal_mean_wind([10, 20], [59, 61])


def test_polar_cap_mean_weights_area_and_excludes_tropics():
    # cos(60)=.5, cos(0)=1; equatorial value must be completely excluded.
    assert polar_cap_mean([200, 220, 999], [60, 60, 0]) == pytest.approx(210)
    expected = (200 * np.cos(np.deg2rad(60)) + 220 * np.cos(np.deg2rad(80))) / (np.cos(np.deg2rad(60)) + np.cos(np.deg2rad(80)))
    assert polar_cap_mean([200, 220], [60, 80]) == pytest.approx(expected)


def test_encoded_grib_time_must_match_requested_run_and_lead():
    handle = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        eccodes.codes_set(handle, "dataDate", 20260914)
        eccodes.codes_set(handle, "dataTime", 1800)
        eccodes.codes_set(handle, "step", 6)
        run = datetime(2026, 9, 14, 18, tzinfo=UTC)
        _validate_message(handle, run, 6)
        with pytest.raises(ValueError, match="valid time"):
            _validate_message(handle, run, 12)
        with pytest.raises(ValueError, match="initialization"):
            _validate_message(handle, run + timedelta(hours=6), 6)
    finally:
        eccodes.codes_release(handle)


def test_noaa_csv_normals_are_native_fahrenheit_not_tenths_or_hdd_of_mean():
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=["DATE", "DLY-TAVG-NORMAL", "DLY-HTDD-NORMAL"])
    writer.writeheader()
    for i in range(366):
        date = datetime(2000, 1, 1) + timedelta(days=i)
        writer.writerow({"DATE": date.strftime("%m-%d"), "DLY-TAVG-NORMAL": " 66.0", "DLY-HTDD-NORMAL": " 2.1"})
    normals = parse_normals_csv(text.getvalue())
    assert normals["02-29"] == {"normal_temp_f": 66.0, "normal_hdd": 2.1}
    # Mean daily HDD remains positive even when the normal daily temperature is
    # above 65°F; deriving HDD from the mean would incorrectly return zero.
    assert normals["01-01"]["normal_hdd"] > max(65 - normals["01-01"]["normal_temp_f"], 0)


def test_refresh_retains_source_initialization_timestamp(monkeypatch):
    """Downloading an old run again must never relabel its source as current."""
    import data_sources.gfs as gfs
    run = datetime(2020, 1, 1, 18, tzinfo=UTC)
    monkeypatch.setattr(gfs, "discover_latest_run", lambda now: run)
    monkeypatch.setattr(gfs, "forecast_calendar", lambda model_run, now: [("2020-01-02", [6, 12, 18, 24])])
    monkeypatch.setattr(gfs, "fetch_normals", lambda regions: {"regions": {}, "warnings": [], "source_url": "https://www.ncei.noaa.gov/"})
    def lead_result(model_run, lead, regions, with_polar):
        return {"lead": lead, "valid_time": (run + timedelta(hours=lead)).isoformat(), "temps_f": {"Test": 32.0}, "grid_points": {"Test": {"latitude": 40, "longitude": -90}}}
    monkeypatch.setattr(gfs, "_extract_lead", lead_result)
    payload = gfs.fetch_gfs([{"name": "Test", "latitude": 40, "longitude": -90}])
    assert payload["observed_at"] == payload["model_run"] == run.isoformat()
    assert datetime.fromisoformat(payload["retrieved_at"]) > run
    assert not payload["polar_vortex"]["complete"]
    assert "incomplete" in payload["polar_vortex"]["interpretation"].lower()


@pytest.mark.parametrize('older_hours, expected_days', [(6, 14), (24, 14), (48, 13)])
def test_archived_calendar_clips_unsupported_complete_days(older_hours, expected_days):
    from data_sources.gfs import archive_calendar
    current_run = datetime(2026, 9, 14, 18, tzinfo=UTC)
    dates = [date for date, _ in forecast_calendar(current_run, datetime(2026, 9, 15, 4, tzinfo=UTC))]
    prior_run = current_run - timedelta(hours=older_hours)
    old = archive_calendar(prior_run, dates)
    assert len(old) == expected_days
    assert old[0][0] == dates[0]
    assert all(len(leads) == 4 and min(leads) >= 0 and max(leads) <= 384 for _, leads in old)
    for day, leads in old:
        assert [(prior_run + timedelta(hours=lead)).strftime('%Y-%m-%d %H') for lead in leads] == [f'{day} {hour:02d}' for hour in (0, 6, 12, 18)]


def test_archive_rejects_days_before_initialization_and_after_horizon():
    from data_sources.gfs import archive_calendar
    run = datetime(2026, 9, 14, 18, tzinfo=UTC)
    with pytest.raises(ValueError, match='No complete requested'):
        archive_calendar(run, ['2026-09-14', '2026-10-01'])
    # Initial date is partly before model initialization, so drop that whole day.
    assert [d for d, _ in archive_calendar(run, ['2026-09-14', '2026-09-15'])] == ['2026-09-15']


def test_archived_fetch_reports_real_initialization_and_current_retrieval(monkeypatch):
    import data_sources.gfs as gfs
    run = datetime(2020, 1, 1, 18, tzinfo=UTC)
    monkeypatch.setattr(gfs, 'fetch_normals', lambda regions: {'regions': {}, 'warnings': [], 'source_url': 'https://www.ncei.noaa.gov/'})
    monkeypatch.setattr(gfs, '_extract_lead', lambda model_run, lead, regions, with_polar: {
        'lead': lead, 'valid_time': (run + timedelta(hours=lead)).isoformat(),
        'temps_f': {'Test': 32.0}, 'grid_points': {'Test': {'latitude': 40, 'longitude': -90}}})
    payload = gfs.fetch_archived_gfs(run.isoformat(), regions=[{'name': 'Test', 'latitude': 40, 'longitude': -90}], comparison_dates=['2020-01-02', '2020-01-20'])
    assert payload['observed_at'] == payload['model_run'] == run.isoformat()
    assert datetime.fromisoformat(payload['retrieved_at']) > run
    assert payload['retrieval_mode'] == 'archive'
    assert payload['excluded_dates'] == ['2020-01-20']
    assert payload['forecast_days'] == 1
    assert [r['date'] for r in payload['rows']] == ['2020-01-02']
    assert payload['polar_vortex']['expected_forecast_samples'] == 1
