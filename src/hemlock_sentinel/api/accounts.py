"""Accounts and forests (demo-grade sign-in).

* users sign in with email + password (scrypt-hashed) and get a bearer token
  (stored as a SHA-256 hash, 30-day expiry);
* each user owns forests; each forest has its OWN tree database and photo store,
  so trees, IDs (H-001...) and matching never mix between forests or users;
* the models (delta, gamma: runtime + calibration) are loaded once and shared by all forests; each forest
  has one pipeline per model over the same tree database. When a visit is stored with one model, the other
  models fingerprint its photos in the background, so any model can recognise any tree later.

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
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..acquisition.interfaces import ModelRuntime
from ..acquisition.mocks import LocalFileStorage
from ..database.repository import TreeRepository
from ..pipeline.inference import HemlockSentinel, PipelineConfig
from ..pipeline.registry import DEFAULT_MODEL, ModelSpec, spec
from ..reid.calibration import Calibration
from . import field, health, sections

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
    def __init__(self, root: str | Path, runtime: ModelRuntime | None = None, calibration: Calibration | None = None,
                 config_factory=PipelineConfig, models: dict[str, ModelSpec] | None = None):
        """Pass ``models`` (delta, gamma...), or a single runtime + calibration (registered as delta)."""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.models = models or {DEFAULT_MODEL: spec(DEFAULT_MODEL, runtime, calibration)}
        self.default_model = DEFAULT_MODEL if DEFAULT_MODEL in self.models else next(iter(self.models))
        d = self.models[self.default_model]
        self.runtime, self.cal, self.config_factory = d.runtime, d.cal, config_factory
        self._stores: dict[int, tuple[TreeRepository, LocalFileStorage]] = {}
        self._model_locks: dict[tuple[int, str], threading.RLock] = {}
        self._bg = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cross-embed")
        self._bg_errors: list[str] = []
        self._db = sqlite3.connect(self.root / "accounts.sqlite", check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._pipes: dict[tuple[int, str], HemlockSentinel] = {}

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

    def delete_forest(self, user_id: int, forest_id: int) -> bool:
        """Remove a forest and its tree database."""
        import shutil

        with self._lock:
            if self.forest(user_id, forest_id) is None:
                return False
            for k in [k for k in self._pipes if k[0] == forest_id]:
                self._pipes.pop(k)
            st = self._stores.pop(forest_id, None)
            if st is not None:
                st[0].close()
            self._db.execute("DELETE FROM forests WHERE forest_id=?", (forest_id,))
            shutil.rmtree(self.root / "forests" / str(forest_id), ignore_errors=True)
            return True

    def _store(self, forest: Forest) -> tuple[TreeRepository, LocalFileStorage]:
        st = self._stores.get(forest.forest_id)
        if st is None:
            d = self.root / "forests" / str(forest.forest_id)
            repo = TreeRepository(d / "trees.sqlite")
            health.ensure_schema(repo)
            field.ensure_schema(repo)
            sections.ensure_schema(repo)
            st = self._stores[forest.forest_id] = (repo, LocalFileStorage(d / "blobs"))
        return st

    def model(self, key: str | None) -> ModelSpec:
        """The model ``key`` (None: the default). KeyError for an unknown key."""
        return self.models[key or self.default_model]

    def pipeline(self, forest: Forest, model: str | None = None) -> HemlockSentinel:
        """The pipeline of one model in one forest (all models share the forest's tree database)."""
        key = model or self.default_model
        m = self.models[key]
        with self._lock:
            p = self._pipes.get((forest.forest_id, key))
            if p is None:
                repo, storage = self._store(forest)
                p = HemlockSentinel(m.runtime, repo, storage, m.cal, self.config_factory(), model_key=key)
                self._pipes[(forest.forest_id, key)] = p
            return p

    def pipelines(self, forest: Forest) -> dict[str, HemlockSentinel]:
        return {k: self.pipeline(forest, k) for k in self.models}

    def _model_lock(self, forest: Forest, key: str) -> threading.RLock:
        with self._lock:
            return self._model_locks.setdefault((forest.forest_id, key), threading.RLock())

    def sync(self, forest: Forest, model: str | None = None) -> int:
        """Bring one model's fingerprints of this forest up to date: adopt embeddings stored before per-model
        storage existed (default model only) and embed stored photos it has not seen. Returns how many
        observations were added."""
        key = model or self.default_model
        p = self.pipeline(forest, key)
        with self._model_lock(forest, key):
            n = 0
            if key == self.default_model:
                others = [k for k in self.models if k != key]
                n = p.repo.adopt_legacy_embeddings(key, p.runtime.embedding_dim,
                                                   exclude_version_prefix=others[0] if len(others) == 1 else None)
                if n:
                    p.index.invalidate()
            return n + p.backfill_embeddings()

    @contextmanager
    def ready(self, forest: Forest, model: str | None = None):
        """Hold this model's lock with its fingerprints up to date (identify inside this block)."""
        key = model or self.default_model
        with self._model_lock(forest, key):
            self.sync(forest, key)
            yield self.pipeline(forest, key)

    def after_commit(self, forest: Forest, model: str | None) -> None:
        """A visit was stored with ``model``: the other models fingerprint its photos in the background."""
        key = model or self.default_model
        for other in [k for k in self.models if k != key]:
            self._bg.submit(self._bg_sync, forest, other)

    def _bg_sync(self, forest: Forest, key: str) -> None:
        try:
            if self.forest(forest.user_id, forest.forest_id) is not None:
                self.sync(forest, key)
        except Exception as e:  # noqa: BLE001  (never kill the worker; identify syncs again anyway)
            self._bg_errors.append(f"{key} forest {forest.forest_id}: {e}")

    def warm_up(self) -> int:
        """At start-up: queue every model's catch-up for every forest (trees stored before a model was added).
        Returns how many jobs were queued; scans still catch up synchronously if a job has not run yet."""
        with self._lock:
            forests = [Forest(**dict(r)) for r in self._db.execute("SELECT * FROM forests").fetchall()]
        for f in forests:
            for k in self.models:
                self._bg.submit(self._bg_sync, f, k)
        return len(forests) * len(self.models)

    def wait_background(self, timeout: float = 120.0) -> None:
        """Tests and shutdown: wait until queued background fingerprinting has finished."""
        self._bg.submit(lambda: None).result(timeout)
