"""Beginner labels must follow both demand components and honest coverage."""
import numpy as np
import pandas as pd
import pytest

from config import DEMAND_SIGNAL_WEIGHTS, DEMAND_SIGNAL_SCALES
from data_sources.normals import attach_degree_day_normals
from models.hdd import compare_forecasts, national_daily, regional_frame
from models.interpretation import (
    combined_signal, daily_demand, demand_direction, revision_demand, summarize_demand,
)

REGIONS = [{'name': 'A', 'weight': .5}, {'name': 'B', 'weight': .5}]


def temperature_rows(day, cold=55, hot=85):
    return [{'date': day, 'region': 'A', 'temp_f': cold, 'normal_hdd': 4},
            {'date': day, 'region': 'B', 'temp_f': hot, 'normal_hdd': 0}]


@pytest.mark.parametrize('heating,cooling,expected,label', [
    (2, -4, 0, 'Little change in gas demand'),
    (2, -6, -.8, 'Less gas demand'),
    (-2, 5, .4, 'More gas demand'),
])
def test_net_interpretation_respects_opposing_heating_and_cooling(heating, cooling, expected, label):
    daily = pd.DataFrame({'date': ['2026-09-15', '2026-09-16'],
                          'anomaly': [heating, heating], 'cdd_anomaly': [cooling, cooling]})
    frame = daily_demand(daily, .8, .4)
    summary = summarize_demand(frame)
    assert summary['heating'] == pytest.approx(heating * .8)
    assert summary['cooling'] == pytest.approx(cooling * .4)
    assert summary['total'] == pytest.approx(expected)
    assert summary['cumulative'] == pytest.approx(expected * 2)
    assert summary['days'] == 2
    assert demand_direction(summary['total']) == label


def test_missing_cooling_normal_cannot_become_a_heating_only_combined_estimate():
    rows = temperature_rows('2026-09-15')
    reference = {'regions': {'A': {'days': {'09-15': {'normal_cdd': 2}}}}}
    enriched = attach_degree_day_normals(rows, normals=reference)
    daily = national_daily(regional_frame(enriched, REGIONS))
    frame = daily_demand(daily, .8, .4)
    assert np.isfinite(frame.heating).all()
    assert frame.cooling.isna().all()
    assert frame.total.isna().all()
    assert summarize_demand(frame) is None
    # Setting an assumption to zero must not silently declare missing weather known.
    assert summarize_demand(daily_demand(daily, .8, 0)) is None
    assert 'normal_cdd' not in rows[0]


def test_missing_one_forecast_day_cannot_silently_shorten_summary():
    frame = pd.DataFrame({'date': ['2026-09-15', '2026-09-16'],
                          'heating': [1., 2.], 'cooling': [2., np.nan], 'total': [3., np.nan]})
    assert summarize_demand(frame) is None


@pytest.mark.parametrize('missing_column', ['weighted_change', 'weighted_cdd_change'])
def test_missing_regional_revision_is_rejected_instead_of_counted_as_zero(missing_column):
    earlier = regional_frame(temperature_rows('2026-09-15'), REGIONS)
    current = regional_frame(temperature_rows('2026-09-15', 60, 95), REGIONS)
    comparison = compare_forecasts(current, earlier)
    comparison.loc[comparison.region == 'A', missing_column] = np.nan
    with pytest.raises(ValueError, match='finite'):
        revision_demand(comparison, .8, .4)


@pytest.mark.parametrize('hot,expected', [(95, 0), (97, .4)])
def test_same_date_revision_can_cancel_or_flip_a_heating_decline(hot, expected):
    earlier = regional_frame(temperature_rows('2026-09-14', 0, 100)
                             + temperature_rows('2026-09-15', 55, 85), REGIONS)
    current = regional_frame(temperature_rows('2026-09-15', 60, hot)
                             + temperature_rows('2026-09-16', 20, 120), REGIONS)
    comparison = compare_forecasts(current, earlier)
    frame = revision_demand(comparison, .8, .4)
    summary = summarize_demand(frame)
    assert frame.date.tolist() == ['2026-09-15']
    assert summary['heating'] == -2
    assert summary['cooling'] == pytest.approx(expected + 2)
    assert summary['total'] == pytest.approx(expected)
    assert summary['cumulative'] == pytest.approx(expected)
    assert summary['days'] == 1


def test_cooling_drives_combined_score_even_with_no_heating_change():
    daily = pd.DataFrame({'date': ['2026-09-15'], 'anomaly': [0.], 'cdd_anomaly': [10.]})
    warm_summary = summarize_demand(daily_demand(daily, .8, .4))
    warm_table, warm_score, warm_label, warm_coverage = combined_signal(warm_summary['total'])
    cool_summary = summarize_demand(daily_demand(daily.assign(cdd_anomaly=-10), .8, .4))
    _, cool_score, cool_label, cool_coverage = combined_signal(cool_summary['total'])
    assert warm_score == pytest.approx(DEMAND_SIGNAL_WEIGHTS['Versus usual weather'])
    assert cool_score == -warm_score
    assert warm_label == 'Supportive for demand'
    assert cool_label == 'Weaker demand'
    assert warm_coverage == cool_coverage == DEMAND_SIGNAL_WEIGHTS['Versus usual weather']
    assert warm_table.loc[warm_table.Factor == 'Versus the 24h-old forecast', 'Contribution'].iloc[0] == 0


def test_combined_score_missing_inputs_abstain_without_renormalizing_weights():
    weight = DEMAND_SIGNAL_WEIGHTS['Versus the 24h-old forecast']
    scale = DEMAND_SIGNAL_SCALES['Versus the 24h-old forecast']
    table, score, label, coverage = combined_signal(None, scale)
    assert score == pytest.approx(weight)
    assert coverage == pytest.approx(weight)
    assert not table.loc[table.Factor == 'Versus usual weather', 'Used'].iloc[0]
    assert table.loc[table.Factor == 'Versus usual weather', 'Estimate (Bcf/day)'].isna().all()
    assert label == 'Supportive for demand'
    table, score, label, coverage = combined_signal(np.nan, np.inf)
    assert score == 0
    assert coverage == 0
    assert label == 'Unavailable'
    assert not table.Used.any()


def test_combined_score_uses_daily_average_so_horizon_length_does_not_magnify_it():
    short = pd.DataFrame({'date': ['2026-09-15'], 'anomaly': [1.], 'cdd_anomaly': [2.]})
    long = pd.concat([short] * 15, ignore_index=True)
    short_summary = summarize_demand(daily_demand(short, .8, .4))
    long_summary = summarize_demand(daily_demand(long, .8, .4))
    assert long_summary['cumulative'] == pytest.approx(15 * short_summary['cumulative'])
    assert combined_signal(long_summary['total'])[1] == pytest.approx(combined_signal(short_summary['total'])[1])
