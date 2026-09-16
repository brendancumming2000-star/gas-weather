"""Calendar rollover and archive-cache integrity are essential to 'yesterday'."""
from copy import deepcopy
from datetime import datetime, timezone

from data_sources.noaa_dates import previous_noaa_date
from data_sources.cache_merge import merge_cached_subproducts
from data_sources import refresh as refresh_module
from storage.database import Database


def test_noaa_day_follows_eastern_calendar_in_summer_and_winter():
    assert previous_noaa_date(datetime(2026,9,15,3,59,tzinfo=timezone.utc)) == '2026-09-13'
    assert previous_noaa_date(datetime(2026,9,15,4,0,tzinfo=timezone.utc)) == '2026-09-14'
    assert previous_noaa_date(datetime(2026,1,15,4,59,tzinfo=timezone.utc)) == '2026-01-13'
    assert previous_noaa_date(datetime(2026,1,15,5,0,tzinfo=timezone.utc)) == '2026-01-14'


def _payload(day):
    return {'requested_previous_date':day,'requested_season':'NDJ 2026–27',
            'previous_outlooks':[{'name':'6–10 day','observed_at':day,'image_base64':'saved'}],
            'seasonal':{'observed_at':'2026-08-20','image_base64':'seasonal'},'warnings':[]}


def test_missing_archive_is_retained_only_for_same_requested_day():
    previous=_payload('2026-09-14')
    current=_payload('2026-09-14');current['previous_outlooks']=[];current['seasonal']={}
    before=deepcopy((previous,current))
    same=merge_cached_subproducts('noaa_maps',current,previous)
    assert same['previous_outlooks'][0]['observed_at']=='2026-09-14'
    assert same['previous_outlooks'][0]['retained_from_cache']
    assert same['seasonal']['retained_from_cache']
    assert (previous,current)==before
    current['requested_previous_date']='2026-09-15'
    next_day=merge_cached_subproducts('noaa_maps',current,previous)
    assert next_day['previous_outlooks']==[]
    assert next_day['seasonal']['observed_at']=='2026-08-20'
    current['requested_season']='NDJ 2027–28'
    assert merge_cached_subproducts('noaa_maps',current,previous)['seasonal']=={}


def test_calendar_rollover_refreshes_maps_inside_normal_ttl(monkeypatch,tmp_path):
    now=datetime(2026,9,15,4,1,tzinfo=timezone.utc)
    monkeypatch.setattr(refresh_module,'utcnow',lambda:now)
    monkeypatch.setattr(refresh_module,'previous_noaa_date',lambda:'2026-09-14')
    db=Database(tmp_path/'test.sqlite3')
    db.save('gfs',{'observed_at':now.isoformat()})
    old=_payload('2026-09-13');old['observed_at']='2026-09-13'
    db.save('noaa_maps',old,fetched_at='2026-09-15T03:59:00+00:00')
    called=[]
    def fetch(name,db):
        called.append(name)
        return {'source':name,'success':True}
    monkeypatch.setattr(refresh_module,'fetch_source',fetch)
    refresh_module.refresh(db,sources=['noaa_maps'])
    assert called==['noaa_maps']
    assert refresh_module.source_status('noaa_maps',db.latest('noaa_maps'))=='Stale'


def test_same_day_fresh_map_bundle_is_not_refetched(monkeypatch,tmp_path):
    now=datetime(2026,9,15,5,0,tzinfo=timezone.utc)
    monkeypatch.setattr(refresh_module,'utcnow',lambda:now)
    monkeypatch.setattr(refresh_module,'previous_noaa_date',lambda:'2026-09-14')
    db=Database(tmp_path/'test.sqlite3')
    db.save('gfs',{'observed_at':now.isoformat()})
    payload=_payload('2026-09-14');payload['observed_at']='2026-09-14'
    db.save('noaa_maps',payload,fetched_at=now.isoformat())
    def unexpected(*args):
        raise AssertionError('Fresh bundle must not cause a network call')
    monkeypatch.setattr(refresh_module,'fetch_source',unexpected)
    assert refresh_module.refresh(db,sources=['noaa_maps'])==[]
