"""Browser sessions share caches and must not start competing refresh batches."""
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier, Event, Thread

import pytest

from data_sources import normals
from data_sources import refresh as refresh_module
from storage import bootstrap
from storage.database import Database, utcnow


def start_task(callback):
    """Capture a daemon worker's result so a broken lock fails with a timeout."""
    result = {}
    entered, done = Event(), Event()

    def run():
        entered.set()
        try:
            result['value'] = callback()
        except BaseException as error:
            result['error'] = error
        finally:
            done.set()

    thread = Thread(target=run, daemon=True)
    thread.start()
    assert entered.wait(2)
    return done, result


def finished(task):
    done, result = task
    assert done.wait(3), 'Refresh did not finish; its lock may be stuck.'
    if 'error' in result:
        raise result['error']
    return result['value']


def test_concurrent_startup_fetches_and_seeds_once(monkeypatch, tmp_path):
    first_db = Database(tmp_path / 'shared.sqlite3')
    second_db = Database(first_db.path)
    fetched, seeded = [], []
    fetch_started, finish_fetch = Event(), Event()
    seed_started, finish_seed = Event(), Event()

    def fetch(source, db):
        fetched.append(source)
        fetch_started.set()
        assert finish_fetch.wait(3)
        db.save(source, {'observed_at': utcnow().isoformat()})
        return {'source': source, 'success': True}

    def seed(db, progress=None):
        seeded.append(db.path)
        seed_started.set()
        assert finish_seed.wait(3)
        return [{'source': 'gfs archive 24h', 'success': True}]

    monkeypatch.setattr(refresh_module, 'fetch_source', fetch)
    monkeypatch.setattr(bootstrap, 'seed_recent_history', seed)
    first = start_task(lambda: refresh_module.refresh(first_db, sources=['gfs']))
    assert fetch_started.wait(2)
    second = start_task(lambda: refresh_module.refresh(second_db, sources=['gfs']))
    try:
        assert not second[0].wait(.1)
        finish_fetch.set()
        assert seed_started.wait(2)
        # Even after the latest GFS has been saved, initialization stays inside
        # the same batch until the comparison archive has finished importing.
        assert not second[0].wait(.1)
    finally:
        finish_fetch.set()
        finish_seed.set()
    assert finished(first) == [
        {'source': 'gfs', 'success': True},
        {'source': 'gfs archive 24h', 'success': True},
    ]
    assert finished(second) == []
    assert fetched == ['gfs']
    assert seeded == [first_db.path]
    assert len(first_db.history()) == 1


def test_forced_refresh_still_downloads_after_an_active_refresh(monkeypatch, tmp_path):
    db = Database(tmp_path / 'shared.sqlite3')
    fetched = []
    fetch_started, finish_fetch = Event(), Event()

    def fetch(source, db):
        fetched.append(source)
        fetch_started.set()
        assert finish_fetch.wait(3)
        db.save(source, {'observed_at': utcnow().isoformat()})
        return {'source': source, 'success': True}

    monkeypatch.setattr(refresh_module, 'fetch_source', fetch)
    first = start_task(lambda: refresh_module.refresh(db, sources=['snow']))
    assert fetch_started.wait(2)
    second = start_task(lambda: refresh_module.refresh(db, force=True, sources=['snow']))
    try:
        assert not second[0].wait(.1)
        assert fetched == ['snow']
    finally:
        finish_fetch.set()
    assert finished(first) == finished(second) == [{'source': 'snow', 'success': True}]
    assert fetched == ['snow', 'snow']
    assert len(db.history(source='snow')) == 2


@pytest.mark.parametrize('failure', ['worker', 'progress'])
def test_exception_releases_refresh_lock(monkeypatch, tmp_path, failure):
    db = Database(tmp_path / 'shared.sqlite3')

    def fetch(source, db):
        if failure == 'worker':
            raise RuntimeError('worker failed')
        db.save(source, {'observed_at': utcnow().isoformat()})
        return {'source': source, 'success': True}

    def progress(result):
        raise RuntimeError('progress failed')

    monkeypatch.setattr(refresh_module, 'fetch_source', fetch)
    first = start_task(lambda: refresh_module.refresh(db, sources=['snow'], progress=progress))
    with pytest.raises(RuntimeError, match=f'{failure} failed'):
        finished(first)

    def successful_fetch(source, db):
        db.save(source, {'observed_at': utcnow().isoformat()})
        return {'source': source, 'success': True}

    monkeypatch.setattr(refresh_module, 'fetch_source', successful_fetch)
    second = start_task(lambda: refresh_module.refresh(db, force=True, sources=['snow']))
    assert finished(second) == [{'source': 'snow', 'success': True}]


def test_simultaneous_station_cache_writes_use_separate_temporary_files(monkeypatch, tmp_path):
    days = {
        (date(2000, 1, 1) + timedelta(days=i)).strftime('%m-%d'):
        {'normal_temp_f': 65, 'normal_hdd': 0, 'normal_cdd': 0}
        for i in range(366)
    }
    download_barrier, write_barrier = Barrier(2), Barrier(2)

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def mount(self, *args):
            pass

        def get(self, *args, **kwargs):
            download_barrier.wait(timeout=3)
            return self

        def raise_for_status(self):
            pass

        text = 'test station normals'

    temporary_paths = []
    original_write = Path.write_text

    def simultaneous_write(path, *args, **kwargs):
        result = original_write(path, *args, **kwargs)
        if path.suffix == '.tmp':
            temporary_paths.append(path)
            # Both files are written before either can replace the final path.
            write_barrier.wait(timeout=3)
        return result

    monkeypatch.setattr(normals, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(normals.requests, 'Session', Session)
    monkeypatch.setattr(normals, 'parse_normals_csv', lambda text: days)
    monkeypatch.setattr(Path, 'write_text', simultaneous_write)
    first = start_task(lambda: normals.fetch_station_normals('USW00014739'))
    second = start_task(lambda: normals.fetch_station_normals('USW00014739'))
    assert finished(first)['days'] == finished(second)['days'] == days
    assert len(set(temporary_paths)) == 2
    assert list(tmp_path.glob('*.tmp')) == []
    # A later visitor reads the completed cache without another network call.
    assert normals.fetch_station_normals('USW00014739')['days'] == days
