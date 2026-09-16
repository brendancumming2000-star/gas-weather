"""Cooling units, missing-data behavior, real-normal migration and mixed demand."""
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import io
import json

import numpy as np
import pandas as pd
import pytest

from data_sources import normals as source_normals
from models.gas_demand import combined_demand_impact
from models.hdd import cooling_degree_days, regional_frame, national_daily, compare_forecasts

REGIONS = [{'name': 'A', 'weight': .75}, {'name': 'B', 'weight': .25}]


def rows(day='2026-09-15', temperatures=(55, 85)):
    return [{'date': day, 'region': region['name'], 'temp_f': temperature,
             'normal_hdd': 2, 'normal_cdd': 3}
            for region, temperature in zip(REGIONS, temperatures)]


def normals_csv(include_cooling=True):
    output = io.StringIO()
    fields = ['DATE', 'DLY-TAVG-NORMAL', 'DLY-HTDD-NORMAL']
    if include_cooling:
        fields.append('DLY-CLDD-NORMAL')
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for i in range(366):
        day = (datetime(2000, 1, 1) + timedelta(days=i)).strftime('%m-%d')
        row = {'DATE': day, 'DLY-TAVG-NORMAL': 64.1, 'DLY-HTDD-NORMAL': 3.8}
        if include_cooling:
            row['DLY-CLDD-NORMAL'] = 2.9
        writer.writerow(row)
    return output.getvalue()


def test_cdd_clips_below_base_and_uses_daily_fahrenheit():
    np.testing.assert_array_equal(cooling_degree_days([20, 65, 75, 85]), [0, 0, 10, 20])
    assert np.isnan(cooling_degree_days([np.nan])[0])


def test_heating_and_cooling_coexist_across_regions_before_population_weighting():
    regional = regional_frame(rows(), REGIONS)
    daily = national_daily(regional).iloc[0]
    # Weighted mean is 62.5°F, but the hot region still needs air conditioning.
    assert daily.hdd == 7.5
    assert daily.cdd == 5
    assert daily.normal_cdd == 3
    assert daily.cdd_anomaly == 2
    assert regional.weighted_cdd_anomaly.sum() == 2


def test_missing_cooling_normal_does_not_become_zero_or_drop_region():
    missing = rows()
    missing[0]['normal_cdd'] = None
    daily = national_daily(regional_frame(missing, REGIONS)).iloc[0]
    assert daily.cdd == 5
    assert np.isnan(daily.normal_cdd)
    assert np.isnan(daily.cdd_anomaly)
    assert daily.normal_hdd == 2


@pytest.mark.parametrize('value', [np.inf, -np.inf, -1])
def test_invalid_cooling_normals_raise(value):
    invalid = rows()
    invalid[0]['normal_cdd'] = value
    with pytest.raises(ValueError, match='CDD|finite'):
        regional_frame(invalid, REGIONS)


def test_cooling_revisions_use_matching_valid_dates_and_preserve_heating_change():
    previous = regional_frame(rows('2026-09-14') + rows('2026-09-15'), REGIONS)
    current = regional_frame(rows('2026-09-15', (50, 90)) + rows('2026-09-16'), REGIONS)
    compared = compare_forecasts(current, previous)
    assert set(compared.date) == {'2026-09-15'}
    assert compared.weighted_change.sum() == 3.75
    assert compared.weighted_cdd_change.sum() == 1.25
    assert set(['cdd_current', 'cdd_previous', 'cdd_change', 'weighted_cdd_change']) <= set(compared)


def test_legacy_heating_comparison_does_not_imply_missing_cooling_is_zero():
    frame = pd.DataFrame([{'date': '2026-09-15', 'region': 'A', 'weight': 1., 'hdd': 0.}])
    compared = compare_forecasts(frame, frame)
    assert compared.weighted_change.iloc[0] == 0
    assert np.isnan(compared.weighted_cdd_change.iloc[0])


def test_combined_gas_has_separate_contributions_and_correct_daily_units():
    impact = combined_demand_impact([2, -1, 0], [-1, 3, 4], .8, .4)
    np.testing.assert_allclose(impact['heating_daily_bcf'], [1.6, -.8, 0])
    np.testing.assert_allclose(impact['cooling_daily_bcf'], [-.4, 1.2, 1.6])
    np.testing.assert_allclose(impact['daily_bcf'], [1.2, .4, 1.6])
    assert impact['cumulative_bcf'] == pytest.approx(3.2)
    assert impact['mean_bcf_per_day'] == pytest.approx(3.2 / 3)
    assert impact['days'] == 3


@pytest.mark.parametrize('heating,cooling,hk,ck', [
    ([], [], .8, .4), ([1], [1, 2], .8, .4), ([[1]], [[2]], .8, .4),
    ([np.nan], [2], .8, .4), ([1], [None], .8, 0), ([1], [np.inf], .8, .4),
    ([1], [2], -.1, .4), ([1], [2], .8, -.1), ([1], [2], .8, np.inf),
    ([1], [2], [1], .4),
])
def test_combined_demand_rejects_missing_misaligned_or_nonfinite_inputs(heating, cooling, hk, ck):
    with pytest.raises(ValueError):
        combined_demand_impact(heating, cooling, hk, ck)


def test_raw_cooling_normal_is_not_cdd_of_the_average_temperature():
    normal = source_normals.parse_normals_csv(normals_csv())['09-15']
    assert normal['normal_temp_f'] == 64.1
    assert normal['normal_cdd'] == 2.9
    assert normal['normal_cdd'] != cooling_degree_days(normal['normal_temp_f'])


def test_old_normal_cache_refetches_cooling_and_then_reuses_complete_cache(tmp_path, monkeypatch):
    station = 'USW00014922'
    path = tmp_path / f'{station}.json'
    old_days = source_normals.parse_normals_csv(normals_csv(include_cooling=False))
    path.write_text(json.dumps({'station': station, 'days': old_days}))
    monkeypatch.setattr(source_normals, 'CACHE_DIR', tmp_path)
    calls = []

    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def mount(self, *args): pass
        def get(self, url, **kwargs):
            calls.append(url)
            return type('Response', (), {'text': normals_csv(), 'raise_for_status': lambda self: None})()

    monkeypatch.setattr(source_normals.requests, 'Session', Session)
    first = source_normals.fetch_station_normals(station)
    second = source_normals.fetch_station_normals(station)
    assert len(calls) == 1
    assert first == second
    assert second['schema_version'] == 2
    assert second['days']['09-15']['normal_cdd'] == 2.9


def test_failed_cache_migration_retains_old_reference_but_does_not_return_it(tmp_path, monkeypatch):
    station = 'USW00014922'
    path = tmp_path / f'{station}.json'
    original = json.dumps({'station': station, 'days': source_normals.parse_normals_csv(normals_csv(False))})
    path.write_text(original)
    monkeypatch.setattr(source_normals, 'CACHE_DIR', tmp_path)

    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def mount(self, *args): pass
        def get(self, *args, **kwargs): raise RuntimeError('offline')

    monkeypatch.setattr(source_normals.requests, 'Session', Session)
    with pytest.raises(RuntimeError, match='offline'):
        source_normals.fetch_station_normals(station)
    assert path.read_text() == original


def test_in_memory_normal_enrichment_preserves_existing_rows_and_unknown_values():
    original = rows()
    for row in original:
        row.pop('normal_cdd')
    saved = deepcopy(original)
    reference = {'regions': {'A': {'days': {'09-15': {'normal_cdd': 2.9, 'normal_hdd': 99}}}}}
    result = source_normals.attach_degree_day_normals(original, normals=reference)
    assert original == saved
    assert result[0]['normal_cdd'] == 2.9
    assert result[0]['normal_hdd'] == 2
    assert result[1]['normal_cdd'] is None


@pytest.mark.parametrize('mode', ['live', 'archive'])
def test_new_gfs_surface_rows_include_forecast_and_true_normal_cooling(monkeypatch, mode):
    from data_sources import gfs
    run = datetime(2020, 1, 1, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(gfs, 'fetch_normals', lambda regions: {
        'regions': {'A': {'days': {'01-02': {'normal_hdd': 1, 'normal_cdd': 2.9}}}},
        'warnings': [], 'source_url': source_normals.NORMALS_BASE})
    monkeypatch.setattr(gfs, '_extract_lead', lambda model_run, lead, regions, with_polar: {
        'lead': lead, 'valid_time': (run + timedelta(hours=lead)).isoformat(),
        'temps_f': {'A': 75}, 'grid_points': {'A': {'latitude': 40, 'longitude': -90}}})
    if mode == 'live':
        monkeypatch.setattr(gfs, 'discover_latest_run', lambda now: run)
        monkeypatch.setattr(gfs, 'forecast_calendar', lambda model_run, now: [('2020-01-02', [6, 12, 18, 24])])
        payload = gfs.fetch_gfs([{'name': 'A', 'latitude': 40, 'longitude': -90}])
    else:
        payload = gfs.fetch_archived_gfs(run, [{'name': 'A', 'latitude': 40, 'longitude': -90}], ['2020-01-02'])
    assert payload['rows'][0]['cdd'] == 10
    assert payload['rows'][0]['normal_cdd'] == 2.9
    assert payload['rows'][0]['hdd'] == 0
