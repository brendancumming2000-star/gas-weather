"""Uncalibrated, auditable display heuristics. Missing inputs abstain."""
import numpy as np
import pandas as pd
from config import SIGNAL_WEIGHTS, SIGNAL_SCALES, EASTERN_REGIONS

def signal_table(anomaly=None, revision=None, eastern=None):
    vals = {'HDD anomaly':anomaly,'24h HDD revision':revision,'Eastern concentration':eastern}
    rows=[]
    for name,weight in SIGNAL_WEIGHTS.items():
        v=vals.get(name)
        available=v is not None and np.isfinite(v)
        normalized=float(np.clip(v/SIGNAL_SCALES[name],-1,1)) if available and name in SIGNAL_SCALES else 0.0
        rows.append({'Factor':name,'Value (weighted HDD)':float(v) if available else None,
                     'Direction':('Bullish ↑' if v>0 else 'Bearish ↓' if v<0 else 'Neutral') if available else 'Context / unavailable',
                     'Weight':weight,'Scaled value':normalized if available else None,
                     'Contribution':normalized*weight if available else 0.0,
                     'Status':'Available' if available else 'Abstains'})
    table=pd.DataFrame(rows)
    score=float(table.Contribution.sum())
    coverage=float(table.loc[table.Status=='Available','Weight'].sum())
    label=('Strongly Bullish' if score>=0.6 else 'Bullish' if score>=0.2 else
           'Strongly Bearish' if score<=-0.6 else 'Bearish' if score<=-0.2 else 'Neutral')
    if coverage == 0:
        label = 'Unavailable'
    return table,score,label,coverage

def eastern_risk(regional):
    if regional.empty or not {'region','date','anomaly','weight'} <= set(regional):
        return 'Unavailable','Complete regional forecasts and normals are needed.'
    east=regional[regional.region.isin(EASTERN_REGIONS)]
    if east.empty or not np.isfinite(east.anomaly).all():
        return 'Unavailable','Complete regional normals are needed.'
    daily=east.groupby('date').apply(lambda g: (g.anomaly*g.weight).sum()/g.weight.sum(), include_groups=False)
    daily.index = pd.to_datetime(daily.index, utc=True)
    daily = daily.sort_index().asfreq('D')
    sustained=daily.rolling(3,min_periods=3).mean().max()
    if not np.isfinite(sustained):
        return 'Unavailable','At least three consecutive days with complete eastern normals are needed.'
    label='High' if sustained>=10 else 'Moderate' if sustained>=5 else 'Low'
    return label,f'Largest 3-day eastern HDD anomaly: {sustained:+.1f} HDD/day. Display thresholds: Moderate ≥5, High ≥10; uncalibrated, not an outbreak probability.'

def vortex_risk(payload):
    rows=pd.DataFrame(payload.get('rows',[]))
    if rows.empty or not {'date','u10_ms'} <= set(rows):
        return 'Unavailable','No validated stratospheric wind observations.'
    dates=pd.to_datetime(rows.date,utc=True,errors='coerce')
    if dates.isna().any():
        return 'Unavailable','Stratospheric forecast dates are incomplete or invalid.'
    winter=dates.dt.month.isin([11,12,1,2,3])
    if not winter.any():
        return 'Unclassified','Outside November–March: seasonal easterlies are not a midwinter SSW signal.'
    wind=pd.to_numeric(rows.loc[winter,'u10_ms'],errors='coerce')
    if not np.isfinite(wind).all():
        return 'Unavailable','Incomplete winter zonal-wind series.'
    if wind.min()<0:
        if rows.u10_ms.iloc[0] > 0:
            return 'Moderate','Winter westerlies turn easterly in this sampled deterministic forecast. This watch flag does not establish a confirmed SSW or U.S. cold outbreak.'
        return 'Moderate','Easterly winter flow is already present in the initial state. This is context, not a newly forecast wind reversal or a U.S. cold prediction.'
    if payload.get('complete') is not True:
        return 'Unavailable','Stratospheric coverage is incomplete; available samples cannot exclude a wind reversal.'
    return 'Low','No winter 60°N / 10 hPa easterly wind in the complete sampled forecast. This does not rule out tropospheric cold outbreaks.'
