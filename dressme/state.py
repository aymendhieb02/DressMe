"""Local browser sessions, with no client-supplied identity or shared user state."""
import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager

from .config import STATE


class Sessions:
    def __init__(self):
        STATE.mkdir(parents=True, exist_ok=True)
        self.path = STATE / 'sessions.sqlite3'
        self.guard = threading.RLock()
        self.locks = {}
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, value TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        with sqlite3.connect(self.path, timeout=20) as db:
            yield db

    def get(self, sid):
        with self.connection() as db:
            row = db.execute('SELECT value FROM sessions WHERE id=?', (sid,)).fetchone()
        return json.loads(row[0]) if row else None

    def create(self, sid=None):
        sid = sid or secrets.token_urlsafe(32)
        self.save(sid, dict(preferences=[], wardrobe_ids=[], overrides={}, personal={},
                            conversation={}, history=[],recent_outfits=[]))
        return sid

    def save(self, sid, value):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (sid, json.dumps(value, ensure_ascii=False)))

    def lock(self, sid):
        with self.guard:
            return self.locks.setdefault(sid, threading.RLock())
