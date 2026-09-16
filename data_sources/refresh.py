"""Independent source failures preserve last good data; successful pulls append."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import import_module
from threading import Lock
from config import REFRESH_HOURS, STALE_HOURS
from storage.database import Database, utcnow, parse_time
from models.hdd import regional_frame
from data_sources.cache_merge import merge_cached_subproducts
from data_sources.noaa_dates import previous_noaa_date

CONNECTORS = {'gfs':('gfs','fetch_gfs'), 'cpc':('cpc','fetch_cpc'),
              'noaa_maps':('noaa_maps','fetch'),
              'snow':('rutgers_snow','fetch_snow'), 'ice':('nsidc','fetch_ice'), 'eia':('eia','fetch_eia')}
_REFRESH_LOCK = Lock()

def fetch_source(name, db):
    try:
        module,func=CONNECTORS[name]
        payload=getattr(import_module('data_sources.'+module),func)()
        if not isinstance(payload,dict) or not payload:
            raise ValueError('Source returned no structured data')
        if name=='gfs':
            regional=regional_frame(payload.get('rows',[]))
            if regional.empty or regional.date.nunique()<1:
                raise ValueError('No complete daily forecast')
            if not payload.get('model_run'):
                raise ValueError('GFS model initialization not identified')
        previous=db.latest(name)
        payload=merge_cached_subproducts(name,payload,previous['payload'] if previous else {})
        db.save(name,payload)
        return {'source':name,'success':True}
    except Exception as exc:
        db.failure(name,f'{type(exc).__name__}: {exc}')
        return {'source':name,'success':False,'error':f'{type(exc).__name__}: {exc}'}

def refresh(db=None, force=False, sources=None, progress=None):
    """Serialize session refreshes, then recheck the shared cache's freshness.

    A second visitor reuses the first visitor's successful downloads and archive
    import. Explicit forced refreshes still fetch after any active refresh ends.
    The context manager releases the lock even if a callback or worker raises.
    """
    with _REFRESH_LOCK:
        return _refresh_locked(db, force, sources, progress)


def _refresh_locked(db=None, force=False, sources=None, progress=None):
    db=db or Database()
    first_forecast=db.latest('gfs') is None
    names=[]
    for name in sources or CONNECTORS:
        last=db.latest(name)
        calendar_changed = name == 'noaa_maps' and last is not None and last['payload'].get('requested_previous_date') != previous_noaa_date()
        if force or last is None or calendar_changed or (utcnow()-parse_time(last['fetched_at'])).total_seconds()>REFRESH_HOURS[name]*3600:
            names.append(name)
    results=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(fetch_source,name,db):name for name in names}
        for future in as_completed(futures):
            result=future.result();results.append(result)
            if progress:
                progress(result)
    if first_forecast and db.latest('gfs'):
        from storage.bootstrap import seed_recent_history
        try:
            results.extend(seed_recent_history(db,progress=progress))
        except Exception as exc:
            result={'source':'gfs archive import','success':False,'error':str(exc)}
            results.append(result)
            if progress: progress(result)
    return results

def source_status(name,snapshot):
    if snapshot is None:
        return 'Unavailable'
    if name == 'noaa_maps' and snapshot['payload'].get('requested_previous_date') != previous_noaa_date():
        return 'Stale'
    observed=snapshot.get('observed_at')
    if not observed:
        return 'Age unknown'
    try:
        age=(utcnow()-parse_time(observed)).total_seconds()/3600
        return 'Stale' if age>STALE_HOURS[name] else 'Current'
    except ValueError:
        return 'Age unknown'

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--force',action='store_true')
    p.add_argument('--sources',nargs='+',choices=list(CONNECTORS))
    args=p.parse_args()
    refresh(force=args.force,sources=args.sources,progress=lambda r: print(r,flush=True))
