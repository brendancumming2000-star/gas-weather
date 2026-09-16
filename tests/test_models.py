import numpy as np
import pytest
from models.hdd import fahrenheit, heating_degree_days, regional_frame, national_daily, compare_forecasts, revision_summary
from models.gas_demand import demand_impact
from models.signals import signal_table, vortex_risk

REGIONS=[{'name':'A','weight':0.75},{'name':'B','weight':0.25}]
def fixture(date='2026-01-01',a=30,b=70):
    return [{'date':date,'region':'A','temp_f':a,'normal_hdd':30}, {'date':date,'region':'B','temp_f':b,'normal_hdd':0}]

def test_temperatures():
    assert fahrenheit(273.15,'K')==pytest.approx(32)
    assert fahrenheit(-40,'C')==pytest.approx(-40)
    assert fahrenheit(65,'F')==65
    with pytest.raises(ValueError): fahrenheit(-1,'K')
    np.testing.assert_allclose(heating_degree_days([20,65,80]),[45,0,0])

def test_hdd_must_clip_before_weighting():
    f=regional_frame(fixture(a=60,b=80),REGIONS)
    n=national_daily(f)
    assert n.hdd.iloc[0]==3.75 # Not HDD(weighted average temperature), which is 0.

def test_incomplete_region_and_normals():
    with pytest.raises(ValueError): regional_frame(fixture()[:1],REGIONS)
    rows=fixture();rows[0]['normal_hdd']=None
    assert np.isnan(national_daily(regional_frame(rows,REGIONS)).normal_hdd.iloc[0])
    with pytest.raises(ValueError): regional_frame(fixture()+fixture(),REGIONS)

def test_valid_dates_not_rolling_totals():
    old=regional_frame(fixture('2026-01-01',a=-10)+fixture('2026-01-02',a=30),REGIONS)
    new=regional_frame(fixture('2026-01-02',a=25)+fixture('2026-01-03',a=70),REGIONS)
    c=compare_forecasts(new,old)
    assert set(c.date)=={'2026-01-02'}
    assert c.weighted_change.sum()==3.75
    assert revision_summary(c,new.date.unique())['days']==1

def test_gas_units_signs_and_daily_average():
    out=demand_impact([2,-1,3],0.8)
    assert out['cumulative_bcf']==pytest.approx(3.2)
    assert out['mean_bcf_per_day']==pytest.approx(3.2/3)
    assert out['days']==3
    for values,k in [([],0.8),([np.nan],0.8),([1],-0.1)]:
        with pytest.raises(ValueError): demand_impact(values,k)

def test_signal_missing_inputs_do_not_renormalize():
    table,score,label,coverage=signal_table(anomaly=30)
    assert score==pytest.approx(0.55)
    assert coverage==pytest.approx(0.55)
    assert label=='Bullish'
    assert table.loc[table.Factor=='24h HDD revision','Contribution'].iloc[0]==0

def test_summer_easterlies_not_ssw():
    label,_=vortex_risk({'rows':[{'date':'2026-09-15','u10_ms':-5}]})
    assert label=='Unclassified'


def test_incomplete_polar_coverage_cannot_rule_out_reversal():
    label,_=vortex_risk({'rows':[{'date':'2026-01-15','u10_ms':10}], 'complete':False})
    assert label=='Unavailable'

def test_existing_winter_easterlies_are_not_a_new_reversal():
    label,explanation=vortex_risk({'rows':[{'date':'2026-01-15','u10_ms':-10},{'date':'2026-01-16','u10_ms':-12}], 'complete':True})
    assert label=='Moderate'
    assert 'already present' in explanation
