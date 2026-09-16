"""Temperature and degree-day mathematics, independent of ingestion and UI."""
import numpy as np
import pandas as pd
from config import REGIONS

def fahrenheit(values, unit='K'):
    a = np.asarray(values, dtype=float)
    if unit.upper() == 'K':
        if np.any(a < 0):
            raise ValueError('Kelvin cannot be negative')
        return (a - 273.15) * 9 / 5 + 32
    if unit.upper() == 'C':
        return a * 9 / 5 + 32
    if unit.upper() == 'F':
        return a
    raise ValueError(f'Unsupported temperature unit: {unit}')

def heating_degree_days(temp_f):
    return np.maximum(65.0 - np.asarray(temp_f, dtype=float), 0.0)

def cooling_degree_days(temp_f):
    """Base-65°F cooling need: a 75°F daily mean contributes 10 CDD."""
    return np.maximum(np.asarray(temp_f, dtype=float) - 65.0, 0.0)

def regional_frame(rows, regions=REGIONS):
    frame = pd.DataFrame(rows).copy()
    if frame.empty:
        return frame
    required = {'date','region','temp_f'}
    if not required <= set(frame):
        raise ValueError(f'Forecast missing {required - set(frame)}')
    dates = pd.to_datetime(frame['date'], errors='coerce', utc=True)
    if dates.isna().any():
        raise ValueError('Forecast dates must be present and valid')
    frame['date'] = dates.dt.strftime('%Y-%m-%d')
    if frame.duplicated(['date','region']).any():
        raise ValueError('Duplicate regional forecast dates')
    if not np.isfinite(frame.temp_f).all() or not frame.temp_f.between(-130,140).all():
        raise ValueError('Invalid Fahrenheit forecast values')
    weights = {r['name']: r['weight'] for r in regions}
    if not np.isclose(sum(weights.values()), 1) or min(weights.values()) < 0:
        raise ValueError('Population weights must be nonnegative and sum to one')
    if set(frame.region) != set(weights):
        raise ValueError('Forecast must cover all configured regions')
    if not frame.groupby('date').region.nunique().eq(len(weights)).all():
        raise ValueError('Incomplete regional coverage for one or more dates')
    frame['weight'] = frame.region.map(weights)
    frame['hdd'] = heating_degree_days(frame.temp_f)
    frame['weighted_hdd'] = frame.hdd * frame.weight
    if 'normal_hdd' not in frame:
        frame['normal_hdd'] = np.nan
    frame['normal_hdd'] = pd.to_numeric(frame.normal_hdd, errors='coerce')
    if not np.isfinite(frame.normal_hdd.dropna()).all():
        raise ValueError('Available normal HDD values must be finite')
    if frame.normal_hdd.dropna().lt(0).any():
        raise ValueError('Normal HDD cannot be negative')
    frame['weighted_normal'] = frame.normal_hdd * frame.weight
    frame['anomaly'] = frame.hdd - frame.normal_hdd
    frame['weighted_anomaly'] = frame.anomaly * frame.weight
    # Clip each regional temperature before weighting, just as for heating.
    frame['cdd'] = cooling_degree_days(frame.temp_f)
    frame['weighted_cdd'] = frame.cdd * frame.weight
    if 'normal_cdd' not in frame:
        frame['normal_cdd'] = np.nan
    frame['normal_cdd'] = pd.to_numeric(frame.normal_cdd, errors='coerce')
    if not np.isfinite(frame.normal_cdd.dropna()).all():
        raise ValueError('Available normal CDD values must be finite')
    if frame.normal_cdd.dropna().lt(0).any():
        raise ValueError('Normal CDD cannot be negative')
    frame['weighted_normal_cdd'] = frame.normal_cdd * frame.weight
    frame['cdd_anomaly'] = frame.cdd - frame.normal_cdd
    frame['weighted_cdd_anomaly'] = frame.cdd_anomaly * frame.weight
    return frame.sort_values(['date','region']).reset_index(drop=True)

def national_daily(regional):
    if regional.empty:
        return pd.DataFrame()
    # min_count prevents a missing region's climatology looking like zero HDD.
    out = regional.groupby('date').agg(hdd=('weighted_hdd','sum'),
        normal_hdd=('weighted_normal',lambda x: x.sum(min_count=len(x))))
    out['anomaly'] = out.hdd - out.normal_hdd
    out['cdd'] = (regional.groupby('date').weighted_cdd.agg(lambda x: x.sum(min_count=len(x)))
                  if 'weighted_cdd' in regional else np.nan)
    out['normal_cdd'] = (regional.groupby('date').weighted_normal_cdd.agg(lambda x: x.sum(min_count=len(x)))
                         if 'weighted_normal_cdd' in regional else np.nan)
    out['cdd_anomaly'] = out.cdd - out.normal_cdd
    return out.reset_index()

def compare_forecasts(current, previous):
    """Compare identical valid-date / region pairs, never rolling-window totals."""
    if current.empty or previous.empty:
        return pd.DataFrame()
    # Heating-only callers remain supported; an unknown cooling series stays
    # missing instead of being inferred as zero from an HDD value of zero.
    if 'cdd' not in current:
        current = current.assign(cdd=cooling_degree_days(current.temp_f) if 'temp_f' in current else np.nan)
    if 'cdd' not in previous:
        previous = previous.assign(cdd=cooling_degree_days(previous.temp_f) if 'temp_f' in previous else np.nan)
    merged = current[['date','region','weight','hdd','cdd']].merge(
        previous[['date','region','hdd','cdd']], on=['date','region'], suffixes=('_current','_previous'), validate='one_to_one')
    merged['change'] = merged.hdd_current - merged.hdd_previous
    merged['weighted_change'] = merged.change * merged.weight
    merged['cdd_change'] = merged.cdd_current - merged.cdd_previous
    merged['weighted_cdd_change'] = merged.cdd_change * merged.weight
    return merged.sort_values(['date','region'])

def revision_summary(comparison, current_dates):
    if comparison.empty:
        return {'days':0,'total':None,'days7':0,'total7':None}
    days = sorted(set(current_dates))
    first7 = comparison[comparison.date.isin(days[:7])]
    return {'days':comparison.date.nunique(),'total':float(comparison.weighted_change.sum()),
            'days7':first7.date.nunique(),'total7':float(first7.weighted_change.sum()) if len(first7) else None}
