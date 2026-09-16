"""Opt-in live integration verification; makes real source pulls and saves snapshots."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import base64
import json
import requests
from config import REGIONS
from data_sources.refresh import refresh, CONNECTORS
from storage.database import Database, utcnow, parse_time
from models.hdd import regional_frame, national_daily

def digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot['payload'],sort_keys=True).encode()).hexdigest()

def main():
    db=Database()
    first=refresh(db,force=True,progress=lambda r: print(r,flush=True))
    assert all(r['success'] for r in first),first
    before={name:db.latest(name) for name in CONNECTORS}
    hashes={name:digest(snap) for name,snap in before.items()}
    second=refresh(db,force=True,progress=lambda r: print(r,flush=True))
    assert all(r['success'] for r in second),second
    for name,old in before.items():
        assert digest(db.snapshot(old['id']))==hashes[name],f'{name}: historical snapshot changed'
        assert db.latest(name)['id']>old['id'],f'{name}: second pull did not append'
    gfs=db.latest('gfs')['payload']
    regional=regional_frame(gfs['rows']);daily=national_daily(regional)
    assert len(regional)==15*len(REGIONS) and len(daily)==15
    assert daily.normal_hdd.notna().all() and daily.normal_cdd.notna().all()
    assert daily.cdd.ge(0).all()
    assert parse_time(gfs['observed_at'])==parse_time(gfs['model_run'])
    assert daily.date.min()>utcnow().date().isoformat()
    assert regional.hdd.ge(0).all()
    assert abs(sum(r['weight'] for r in REGIONS)-1)<1e-9
    cpc=db.latest('cpc')['payload']
    assert len(cpc['outlooks'])==3
    assert cpc['nao']['history'] and cpc['nao']['forecast']
    assert len(cpc['nao']['forecast'])>=15
    for name in ['snow','ice']:
        assert db.latest(name)['payload']['current_extent_million_km2']>=0
    assert db.latest('eia')['payload']['price_rows'] and db.latest('eia')['payload']['storage_rows']
    for outlook in cpc['outlooks']:
        assert base64.b64decode(outlook['image_base64']).startswith((b'GIF8',b'\x89PNG'))
        response=requests.get(outlook['image_url'],timeout=30)
        response.raise_for_status()
        assert response.headers.get('content-type','').startswith('image/')
    sources={n:{'observed_at':db.latest(n)['observed_at'],'fetched_at':db.latest(n)['fetched_at'],'source_url':db.latest(n)['payload']['source_url'],'warnings':db.latest(n)['payload'].get('warnings',[])} for n in CONNECTORS}
    report={'verified_at':utcnow().isoformat(),'sources':sources,'gfs_model_run':gfs['model_run'],
            'regions':len(REGIONS),'days':len(daily),'first_valid':daily.date.min(),'last_valid':daily.date.max(),
            'weighted_hdd':float(daily.hdd.sum()),'normal_hdd':float(daily.normal_hdd.sum()),
            'weighted_cdd':float(daily.cdd.sum()),'normal_cdd':float(daily.normal_cdd.sum()),
            'all_normals_available':True,'second_refresh_preserved_all_prior_snapshots':True,
            'cpc_images_verified':True, 'cpc_image_snapshots_verified':True,
            'nao_observed_date':cpc['nao']['observed_at'],
            'nao_ensemble_initialization':cpc['nao']['forecast_initialized_at']}
    output=Path(__file__).resolve().parents[1]/'docs'/'live_validation.json'
    output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
