"""Offline UI tests use isolated test-only data, never production snapshots."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from config import REGIONS
from storage.database import Database
from data_sources.noaa_dates import previous_noaa_date


def run_app_script(tmp_path, script, warm=False, bad_previous=False, map_images=None):
    now=datetime.now(timezone.utc)
    run=now.replace(hour=(now.hour//6)*6,minute=0,second=0,microsecond=0)
    path=tmp_path/'test.sqlite3';db=Database(path)
    for age,temp in ([(48,70),(24,73),(6,74),(0,75)] if warm else [(48,40),(24,35),(6,31),(0,30)]):
        model_run=(run-timedelta(hours=age)).isoformat()
        rows=[{'date':(now.date()+timedelta(days=i)).isoformat(),'region':r['name'],
               'temp_f':temp,'normal_hdd':0 if warm else 20,'normal_cdd':5 if warm else 0}
              for i in range(1,16) for r in REGIONS]
        if bad_previous and age==24:rows=rows[1:]
        db.save('gfs',{'rows':rows,'model_run':model_run,'observed_at':model_run})
    for source in ['cpc','snow','ice','eia']:db.save(source,{'observed_at':now.isoformat()})
    maps={'observed_at':now.isoformat(),'requested_previous_date':previous_noaa_date(now),
          'previous_outlooks':[],'seasonal':{},'warnings':[]}
    if map_images:
        import base64
        from io import BytesIO
        from PIL import Image
        buffer=BytesIO();Image.new('RGB',(40,30),'white').save(buffer,format='PNG')
        fixture={'observed_at':previous_noaa_date(now),'valid_period':'Fixture forecast dates',
                 'image_base64':base64.b64encode(buffer.getvalue()).decode(),
                 'source_url':'https://example.invalid/source'}
        maps['previous_outlooks']=[dict(fixture,name=name) for name in ['6–10 day','8–14 day','Weeks 3–4']]
        maps['seasonal']=dict(fixture,name='November–December–January',valid_period='Nov–Dec–Jan 2026–27')
        if map_images=='corrupt':maps['previous_outlooks'][0]['image_base64']='not-an-image'
    db.save('noaa_maps',maps)
    env=os.environ.copy();env['WEATHER_DB_PATH']=str(path)
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr


def test_pages_controls_and_heating_revision(tmp_path):
    run_app_script(tmp_path, '''
from streamlit.testing.v1 import AppTest
at=AppTest.from_file('app.py').run(timeout=45)
assert not at.exception,[e.message for e in at.exception]
assert any(m.label=='Combined effect' and m.value=='+12.00 Bcf/day' for m in at.metric)
at.number_input(key='heating_coefficient').set_value(1.6).run(timeout=45)
assert any(m.label=='Combined effect' and m.value=='+24.00 Bcf/day' for m in at.metric)
at.radio(key='navigation').set_value('What changed').run(timeout=45)
assert not at.exception,[e.message for e in at.exception]
assert any(m.label=='Combined effect' and m.value=='+8.00 Bcf/day' for m in at.metric)
for page in ['Heating & cooling','Longer-range outlook','Cold-weather clues','Gas market','Data & assumptions','Overview']:
    at.radio(key='navigation').set_value(page).run(timeout=45)
    assert not at.exception,(page,[e.message for e in at.exception])
at.radio(key='navigation').set_value('Heating & cooling').run(timeout=45)
at.slider(key='temperature_example').set_value(55).run(timeout=45)
assert any(m.label=='Heating need' and m.value=='10 HDD' for m in at.metric)
assert any(m.label=='Cooling need' and m.value=='0 CDD' for m in at.metric)
''')


def test_cooling_changes_overview_and_revision(tmp_path):
    run_app_script(tmp_path, '''
from streamlit.testing.v1 import AppTest
at=AppTest.from_file('app.py').run(timeout=45)
assert not at.exception,[e.message for e in at.exception]
assert any(m.label=='Heating effect' and m.value=='+0.00 Bcf/day' for m in at.metric)
assert any(m.label=='Air-conditioning effect' and m.value=='+2.00 Bcf/day' for m in at.metric)
assert any(m.label=='Combined effect' and m.value=='+2.00 Bcf/day' for m in at.metric)
at.number_input(key='cooling_coefficient').set_value(0.8).run(timeout=45)
assert any(m.label=='Combined effect' and m.value=='+4.00 Bcf/day' for m in at.metric)
at.radio(key='navigation').set_value('What changed').run(timeout=45)
assert any(m.label=='Combined effect' and m.value=='+1.60 Bcf/day' for m in at.metric)
at.radio(key='navigation').set_value('Heating & cooling').run(timeout=45)
at.slider(key='temperature_example').set_value(75).run(timeout=45)
assert any(m.label=='Cooling need' and m.value=='10 CDD' for m in at.metric)
assert not at.exception,[e.message for e in at.exception]
''',warm=True)


def test_bad_earlier_forecast_does_not_clear_valid_current_forecast(tmp_path):
    run_app_script(tmp_path, """
from streamlit.testing.v1 import AppTest
at=AppTest.from_file('app.py').run(timeout=45)
assert not at.exception,[e.message for e in at.exception]
assert any(m.label=='Combined effect' and m.value=='+12.00 Bcf/day' for m in at.metric)
at.radio(key='navigation').set_value('What changed').run(timeout=45)
assert not at.exception,[e.message for e in at.exception]
assert any('could not be compared' in w.value for w in at.warning)
""",bad_previous=True)


def test_overview_starts_with_simple_read_then_four_maps_and_vortex(tmp_path):
    run_app_script(tmp_path, """
from streamlit.testing.v1 import AppTest
at=AppTest.from_file('app.py').run(timeout=45)
assert not at.exception,[e.message for e in at.exception]
assert not at.main.get('title')  # The removed question heading does not precede the hero.
text=' '.join(m.value for m in at.markdown)
assert text.index('THE SIMPLE READ') < text.index('NOAA temperature outlooks') < text.index('The gas-demand details')
assert 'Cold weather makes people turn up the heating.' not in text
assert len(at.get('image'))==4
assert any(s.value=='Could Arctic cold reach us?' for s in at.subheader)
assert any('Nov–Dec–Jan 2026–27' in c.value for c in at.caption)
assert any('weekly' in c.value for c in at.caption)
assert not any('Weather forecast issued' in c.value for c in at.caption)
""",map_images='complete')


def test_one_corrupt_map_preserves_other_maps_and_gas_estimate(tmp_path):
    run_app_script(tmp_path, """
from streamlit.testing.v1 import AppTest
at=AppTest.from_file('app.py').run(timeout=45)
assert not at.exception,[e.message for e in at.exception]
assert len(at.get('image'))==3
assert any('saved image could not be displayed' in m.value for m in at.info)
assert any(m.label=='Combined effect' and m.value=='+12.00 Bcf/day' for m in at.metric)
""",map_images='corrupt')
