"""Incremental weather-only gas demand; no absolute-demand or price prediction."""
import numpy as np

def demand_impact(hdd_changes, coefficient):
    values = np.asarray(hdd_changes, dtype=float)
    if values.ndim != 1:
        raise ValueError('Demand impact requires a one-dimensional daily HDD vector')
    if not np.isfinite(coefficient) or coefficient < 0:
        raise ValueError('HDD coefficient must be finite and nonnegative')
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError('Demand impact requires finite daily HDD differences')
    daily = values * coefficient
    return {'daily_bcf':daily, 'cumulative_bcf':float(daily.sum()),
            'mean_bcf_per_day':float(daily.mean()), 'days':len(daily)}


def combined_demand_impact(hdd_changes, cdd_changes, heating_coefficient, cooling_coefficient):
    """Illustrative heating plus power-generation gas-demand change in Bcf.

    Inputs are population-weighted daily degree-day differences on the same
    dates. Both coefficients are rough, uncalibrated assumptions. Missing data
    raises even when its coefficient is zero; missing demand is never zero.
    """
    heating = np.asarray(hdd_changes, dtype=float)
    cooling = np.asarray(cdd_changes, dtype=float)
    if heating.ndim != 1 or cooling.ndim != 1:
        raise ValueError('Demand impact requires one-dimensional daily HDD and CDD vectors')
    if heating.shape != cooling.shape:
        raise ValueError('Heating and cooling daily vectors must have matching shapes and dates')
    if heating.size == 0 or not np.isfinite(heating).all() or not np.isfinite(cooling).all():
        raise ValueError('Demand impact requires finite daily HDD and CDD differences')
    for label, coefficient in [('Heating', heating_coefficient), ('Cooling', cooling_coefficient)]:
        value = np.asarray(coefficient, dtype=float)
        if value.ndim != 0 or not np.isfinite(value) or value < 0:
            raise ValueError(f'{label} coefficient must be a finite nonnegative scalar')
    heating_daily = heating * float(heating_coefficient)
    cooling_daily = cooling * float(cooling_coefficient)
    daily = heating_daily + cooling_daily
    if not np.isfinite(daily).all():
        raise ValueError('Demand impact exceeds finite numeric range')
    return {'heating_daily_bcf': heating_daily, 'cooling_daily_bcf': cooling_daily,
            'daily_bcf': daily, 'cumulative_bcf': float(daily.sum()),
            'mean_bcf_per_day': float(daily.mean()), 'days': len(daily)}
