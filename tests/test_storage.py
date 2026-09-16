from storage.database import Database
import pytest

def payload(run,value=10):
    return {'model_run':run,'observed_at':run,'rows':[{'value':value}]}

def test_append_only_and_distinct_run_selection(tmp_path):
    db=Database(tmp_path/'cache.sqlite3')
    first=db.save('gfs',payload('2026-01-01T00:00:00Z'))
    db.save('gfs',payload('2026-01-02T00:00:00Z',20))
    last=db.save('gfs',payload('2026-01-02T00:00:00Z',21))
    current=db.latest('gfs')
    assert current['id']==last
    assert db.comparison(current)['id']==first
    assert db.comparison(current,24)['id']==first
    assert db.comparison(current,48) is None
    assert db.snapshot(first)['payload']['rows'][0]['value']==10
    assert len(db.history())==3

def test_errors_and_nan_do_not_replace_success(tmp_path):
    db=Database(tmp_path/'cache.sqlite3')
    first=db.save('gfs',payload('2026-01-01T00:00:00Z'))
    db.failure('gfs','Timeout')
    with pytest.raises(ValueError): db.save('gfs',{'value':float('nan')})
    assert db.latest('gfs')['id']==first
    assert len(db.history())==1
    assert db.attempts()[0]['success']==0

def test_24hour_match_does_not_use_wrong_cycle(tmp_path):
    db=Database(tmp_path/'cache.sqlite3')
    db.save('gfs',payload('2026-01-01T06:00:00Z'))
    db.save('gfs',payload('2026-01-02T00:00:00Z'))
    assert db.comparison(db.latest('gfs'),24) is None

def test_archive_batch_preserves_current_and_actual_retrieval(tmp_path):
    db=Database(tmp_path/'archive.sqlite3')
    current=payload('2026-01-03T00:00:00Z',30)
    current['retrieved_at']='2026-01-03T05:00:00Z'
    original=db.save('gfs',current)
    old=payload('2026-01-02T00:00:00Z',20)
    old['retrieved_at']='2026-01-03T05:01:00Z'
    old['retrieval_mode']='archive'
    db.save_batch('gfs',[old,current])
    latest=db.latest('gfs')
    assert latest['model_run']=='2026-01-03T00:00:00+00:00'
    prior=db.comparison(latest,24)
    assert prior['payload']['retrieval_mode']=='archive'
    assert prior['fetched_at']=='2026-01-03T05:01:00+00:00'
    assert db.snapshot(original)['payload']==current


def test_archive_batch_rejects_invalid_payload_atomically(tmp_path):
    db=Database(tmp_path/'archive.sqlite3')
    db.save('gfs',payload('2026-01-03T00:00:00Z'))
    with pytest.raises(ValueError):
        db.save_batch('gfs',[payload('2026-01-02T00:00:00Z'),{'value':float('nan')}])
    assert len(db.history())==1
