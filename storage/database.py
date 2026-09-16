"""Append-only successful pulls and separate attempt audit; all clocks UTC."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
from config import DB_PATH

def utcnow():
    return datetime.now(timezone.utc)

def parse_time(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

class Database:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL, fetched_at TEXT NOT NULL,
                observed_at TEXT, model_run TEXT, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS snapshot_source ON snapshots(source, id);
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                attempted_at TEXT NOT NULL, success INTEGER NOT NULL, error TEXT);
            ''')

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def save(self, source, payload, fetched_at=None):
        # Serialize before transaction; invalid/non-finite data cannot corrupt history.
        body = json.dumps(payload, allow_nan=False)
        stamp = parse_time(fetched_at).isoformat() if fetched_at else utcnow().isoformat()
        model_run = payload.get('model_run')
        if model_run:
            model_run = parse_time(model_run).isoformat()
        with self.connect() as con:
            cur = con.execute('INSERT INTO snapshots(source,fetched_at,observed_at,model_run,payload) VALUES(?,?,?,?,?)',
                              (source,stamp,payload.get('observed_at'),model_run,body))
            con.execute('INSERT INTO attempts(source,attempted_at,success) VALUES(?,?,1)', (source,stamp))
            return cur.lastrowid

    def save_batch(self, source, payloads):
        """Atomically append an archive batch followed by the current snapshot."""
        records=[]
        for payload in payloads:
            body=json.dumps(payload,allow_nan=False)
            stamp=parse_time(payload['retrieved_at']).isoformat() if payload.get('retrieved_at') else utcnow().isoformat()
            run=parse_time(payload['model_run']).isoformat() if payload.get('model_run') else None
            records.append((source,stamp,payload.get('observed_at'),run,body))
        with self.connect() as con:
            for record in records:
                con.execute('INSERT INTO snapshots(source,fetched_at,observed_at,model_run,payload) VALUES(?,?,?,?,?)',record)
                con.execute('INSERT INTO attempts(source,attempted_at,success) VALUES(?,?,1)',(source,record[1]))

    def failure(self, source, error):
        with self.connect() as con:
            con.execute('INSERT INTO attempts(source,attempted_at,success,error) VALUES(?,?,0,?)',
                        (source,utcnow().isoformat(),str(error)[:2000]))

    @staticmethod
    def unpack(row):
        if row is None:
            return None
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        return result

    def latest(self, source):
        with self.connect() as con:
            return self.unpack(con.execute('SELECT * FROM snapshots WHERE source=? ORDER BY id DESC LIMIT 1',(source,)).fetchone())

    def attempts(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute('SELECT * FROM attempts WHERE id IN (SELECT max(id) FROM attempts GROUP BY source)')]

    def history(self, source='gfs', limit=200):
        with self.connect() as con:
            return [dict(r) for r in con.execute('SELECT id,source,fetched_at,observed_at,model_run,json_extract(payload, \"$.retrieval_mode\") AS retrieval_mode FROM snapshots WHERE source=? ORDER BY id DESC LIMIT ?', (source,limit))]

    def snapshot(self, snapshot_id):
        with self.connect() as con:
            return self.unpack(con.execute('SELECT * FROM snapshots WHERE id=?', (snapshot_id,)).fetchone())

    def comparison(self, current, hours=None):
        """Previous distinct cycle, or latest cycle <= target with max 6h gap.

        A repeated fetch of the same model initialization is never a prior run.
        24/48h labels reference model initialization, not retrieval timestamps.
        """
        run = parse_time(current['model_run'])
        with self.connect() as con:
            rows = con.execute('SELECT * FROM snapshots WHERE source=? AND id<? AND model_run IS NOT NULL ORDER BY model_run DESC,id DESC',
                               ('gfs',current['id'])).fetchall()
        for row in rows:
            when = parse_time(row['model_run'])
            if when >= run:
                continue
            if hours is None:
                return self.unpack(row)
            target = run - timedelta(hours=hours)
            if target - timedelta(hours=6) <= when <= target:
                return self.unpack(row)
        return None
