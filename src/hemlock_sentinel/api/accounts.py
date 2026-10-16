"""Accounts and forests (demo-grade sign-in).

* users sign in with email + password (scrypt-hashed) and get a bearer token
  (stored as a SHA-256 hash, 30-day expiry);
* each user owns forests; each forest has its OWN tree database and photo store,
  so trees, IDs (H-001...) and matching never mix between forests or users;
* the model (runtime) and calibration are loaded once and shared by all forests.

This is enough for a demo. Before real deployment add HTTPS, rate limiting,
password reset and account deletion.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..acquisition.interfaces import ModelRuntime
from ..acquisition.mocks import LocalFileStorage
from ..database.repository import TreeRepository
from ..pipeline.inference import HemlockSentinel, PipelineConfig
from ..reid.calibration import Calibration
from . import health

TOKEN_TTL_S = 30 * 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    pw_salt BLOB NOT NULL,
    pw_hash BLOB NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS forests (
    forest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    name TEXT NOT NULL,
    lat REAL, lon REAL,
    created_at REAL NOT NULL,
    UNIQUE(user_id, name)
);
"""


@dataclass
class User:
    user_id: int
    email: str
    name: str


@dataclass
class Forest:
    forest_id: int
    user_id: int
    name: str
    lat: float | None
    lon: float | None
    created_at: float


def _hash_pw(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Accounts:
    def __init__(self, root: str | Path, runtime: ModelRuntime, calibration: Calibration,
                 config_factory=PipelineConfig):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runtime, self.cal, self.config_factory = runtime, calibration, config_factory
        self._db = sqlite3.connect(self.root / "accounts.sqlite", check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._pipes: dict[int, HemlockSentinel] = {}

    # ----------------------------------------------------------------- users
    def register(self, email: str, password: str, name: str) -> User:
        salt = secrets.token_bytes(16)
        with self._lock:
            try:
                cur = self._db.execute("INSERT INTO users(email, name, pw_salt, pw_hash, created_at) VALUES(?,?,?,?,?)",
                                       (email.strip(), name.strip(), salt, _hash_pw(password, salt), time.time()))
            except sqlite3.IntegrityError as e:
                raise ValueError("an account with this email already exists") from e
        return User(cur.lastrowid, email.strip(), name.strip())

    def login(self, email: str, password: str) -> tuple[str, User] | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM users WHERE email=?", (email.strip(),)).fetchone()
        if r is None:
            _hash_pw(password, b"0" * 16)  # same work either way: no account-existence timing signal
            return None
        if not hmac.compare_digest(_hash_pw(password, r["pw_salt"]), r["pw_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute("DELETE FROM tokens WHERE expires_at < ?", (time.time(),))
            self._db.execute("INSERT INTO tokens(token_hash, user_id, expires_at) VALUES(?,?,?)",
                             (_hash_token(token), r["user_id"], time.time() + TOKEN_TTL_S))
        return token, User(r["user_id"], r["email"], r["name"])

    def user_for_token(self, token: str) -> User | None:
        with self._lock:
            r = self._db.execute("SELECT u.* FROM tokens t JOIN users u ON u.user_id=t.user_id "
                                 "WHERE t.token_hash=? AND t.expires_at > ?", (_hash_token(token), time.time())).fetchone()
        return None if r is None else User(r["user_id"], r["email"], r["name"])

    def logout(self, token: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM tokens WHERE token_hash=?", (_hash_token(token),))

    def find_user(self, email: str) -> User | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return None if r is None else User(r["user_id"], r["email"], r["name"])

    # --------------------------------------------------------------- forests
    def create_forest(self, user_id: int, name: str, lat: float | None = None, lon: float | None = None) -> Forest:
        with self._lock:
            try:
                cur = self._db.execute("INSERT INTO forests(user_id, name, lat, lon, created_at) VALUES(?,?,?,?,?)",
                                       (user_id, name.strip(), lat, lon, time.time()))
            except sqlite3.IntegrityError as e:
                raise ValueError(f"you already have a forest called {name!r}") from e
        return self.forest(user_id, cur.lastrowid)

    def forests(self, user_id: int) -> list[Forest]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM forests WHERE user_id=? ORDER BY name", (user_id,)).fetchall()
        return [Forest(**dict(r)) for r in rows]

    def forest(self, user_id: int, forest_id: int) -> Forest | None:
        """None unless the forest exists AND belongs to this user."""
        with self._lock:
            r = self._db.execute("SELECT * FROM forests WHERE forest_id=? AND user_id=?", (forest_id, user_id)).fetchone()
        return None if r is None else Forest(**dict(r))

    def pipeline(self, forest: Forest) -> HemlockSentinel:
        with self._lock:
            p = self._pipes.get(forest.forest_id)
            if p is None:
                d = self.root / "forests" / str(forest.forest_id)
                repo = TreeRepository(d / "trees.sqlite")
                health.ensure_schema(repo)
                p = HemlockSentinel(self.runtime, repo, LocalFileStorage(d / "blobs"), self.cal, self.config_factory())
                self._pipes[forest.forest_id] = p
            return p
