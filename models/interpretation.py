"""Plain-language interpretations of the same auditable heating/cooling math."""
import numpy as np
import pandas as pd
from config import DEMAND_SIGNAL_WEIGHTS, DEMAND_SIGNAL_SCALES, DISPLAY_CHANGE_BCF_PER_DAY
from models.gas_demand import combined_demand_impact


def daily_demand(daily, heating_coefficient, cooling_coefficient):
    """Differences from normal. A missing component makes the total unavailable."""
    if daily.empty:
        return pd.DataFrame()
    out=daily[['date']].copy()
    out['heating']=daily['anomaly'].to_numpy()*heating_coefficient
    out['cooling']=daily['cdd_anomaly'].to_numpy()*cooling_coefficient
    out['total']=out['heating']+out['cooling']
    return out


def revision_demand(comparison, heating_coefficient, cooling_coefficient):
    if comparison.empty:
        return pd.DataFrame()
    out=comparison.groupby('date',as_index=False).agg(
        hdd_change=('weighted_change',lambda x:x.sum(min_count=len(x))),
        cdd_change=('weighted_cdd_change',lambda x:x.sum(min_count=len(x))))
    result=combined_demand_impact(out.hdd_change,out.cdd_change,heating_coefficient,cooling_coefficient)
    out['heating']=result['heating_daily_bcf']
    out['cooling']=result['cooling_daily_bcf']
    out['total']=result['daily_bcf']
    return out


def summarize_demand(frame):
    if frame.empty or not {'heating','cooling','total'}<=set(frame):
        return None
    if not np.isfinite(frame[['heating','cooling','total']].to_numpy(dtype=float)).all():
        return None
    return {'days':len(frame),'heating':float(frame.heating.mean()),'cooling':float(frame.cooling.mean()),
            'total':float(frame.total.mean()),'cumulative':float(frame.total.sum())}


def demand_direction(value):
    if value is None or not np.isfinite(value): return 'Not enough data'
    if value>=DISPLAY_CHANGE_BCF_PER_DAY: return 'More gas demand'
    if value<=-DISPLAY_CHANGE_BCF_PER_DAY: return 'Less gas demand'
    return 'Little change in gas demand'


def component_sentence(value, activity, baseline='usual for these dates'):
    if value is None or not np.isfinite(value):
        return f'{activity}: the comparison is unavailable.'
    if abs(value)<DISPLAY_CHANGE_BCF_PER_DAY:
        return f'{activity} is close to {baseline} under the current assumptions.'
    direction='more' if value>0 else 'less'
    return f'{activity} points to about {abs(value):.2f} Bcf/day {direction} gas use than {baseline}.'


def combined_signal(normal_average=None, revision_average=None):
    inputs={'Versus usual weather':normal_average,'Versus the 24h-old forecast':revision_average}
    rows=[]
    for factor,weight in DEMAND_SIGNAL_WEIGHTS.items():
        value=inputs[factor]
        available=value is not None and np.isfinite(value)
        scaled=float(np.clip(value/DEMAND_SIGNAL_SCALES[factor],-1,1)) if available else 0.0
        rows.append({'Factor':factor,'Estimate (Bcf/day)':float(value) if available else None,
                     'Weight':weight,'Scale (Bcf/day)':DEMAND_SIGNAL_SCALES[factor],
                     'Contribution':weight*scaled,'Used':available})
    table=pd.DataFrame(rows)
    score=float(table.Contribution.sum())
    coverage=float(table.loc[table.Used,'Weight'].sum())
    label='Unavailable' if coverage==0 else 'Supportive for demand' if score>=0.2 else 'Weaker demand' if score<=-0.2 else 'Mixed / small effect'
    return table,score,label,coverage
