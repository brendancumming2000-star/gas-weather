"""Import real recent NOAA archive cycles, preserving actual retrieval times.

Archive rows are not fabricated local history. Only valid dates supported by
that older model's original horizon enter comparisons.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
import copy
from storage.database import Database, parse_time
from models.hdd import regional_frame


def seed_recent_history(db=None, progress=None):
    from data_sources.gfs import fetch_archived_gfs
    db=db or Database()
    current=db.latest('gfs')
    if current is None:
        raise ValueError('Fetch the current GFS forecast before importing archived cycles.')
    dates=sorted({r['date'] for r in current['payload']['rows']})
    run=parse_time(current['model_run'])
    known={r['model_run'] for r in db.history(limit=10000)}
    targets=[(hours,run-timedelta(hours=hours)) for hours in (6,24,48)
             if (run-timedelta(hours=hours)).isoformat() not in known]
    results=[];payloads=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(fetch_archived_gfs,model_run=target,comparison_dates=dates):(hours,target) for hours,target in targets}
        for future in as_completed(jobs):
            hours,target=jobs[future]
            try:
                payload=future.result()
                regional_frame(payload['rows'])
                payloads.append(payload)
                result={'source':f'gfs archive {hours}h','success':True,'model_run':payload['model_run'],'days':len({r['date'] for r in payload['rows']})}
            except Exception as exc:
                result={'source':f'gfs archive {hours}h','success':False,'error':str(exc)}
            results.append(result)
            if progress: progress(result)
    if payloads:
        # One transaction makes the current run remain latest to concurrent readers.
        ordered=sorted(payloads,key=lambda p:p['model_run'])
        original=copy.deepcopy(current['payload'])
        original['history_import_note']='Recent archived model cycles retrieved now; original model initialization and retrieval times remain distinct.'
        db.save_batch('gfs',ordered+[original])
    return results


if __name__=='__main__':
    import json
    results=seed_recent_history(progress=lambda r:print(json.dumps(r),flush=True))
    if not results: print('Recent comparison cycles are already saved.')
