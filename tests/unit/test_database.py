import numpy as np
import pytest

from hemlock_sentinel.database.models import ObservationRecord, ViewRecord, from_blob, to_blob
from hemlock_sentinel.database.repository import TreeRepository


def _obs(tid, emb, t, views=1):
    return ObservationRecord("", tid, t, "existing" if tid else "uncertain", "tsuga_canadensis", 0.97, 0.9,
                             emb, views=[ViewRecord(i, "trunk_north", f"k{i}", emb) for i in range(views)])


def test_ids_are_persistent_sequential_and_not_row_positions(tmp_path):
    db = tmp_path / "t.db"
    r = TreeRepository(db)
    assert r.create_tree("tsuga_canadensis", "H") == "H-001"
    assert r.create_tree("tsuga_canadensis", "H") == "H-002"
    assert r.create_tree("pinus_strobus", "P") == "P-001"
    r.merge_trees("H-001", "H-002")
    r.close()
    r = TreeRepository(db)  # new session
    assert r.create_tree("tsuga_canadensis", "H") == "H-003"  # H-002 retired, not reused
    assert [t.tree_id for t in r.list_trees("tsuga_canadensis")] == ["H-001", "H-003"]


def test_observation_roundtrip_and_ordering(tmp_path):
    r = TreeRepository(tmp_path / "t.db")
    tid = r.create_tree("tsuga_canadensis", "H", now=0)
    e1, e2 = np.eye(4)[0], np.eye(4)[1]
    r.add_observation(_obs(tid, e2, t=200.0, views=3))
    r.add_observation(_obs(tid, e1, t=100.0))
    obs = r.get_observations(tid)
    assert [o.timestamp for o in obs] == [100.0, 200.0]
    assert len(obs[1].views) == 3 and np.allclose(obs[1].views[0].embedding, e2)
    t = r.get_tree(tid)
    assert t.observation_count == 2 and t.last_seen_at == 200.0
    assert np.linalg.norm(t.canonical_embedding) == pytest.approx(1.0, abs=1e-3)
    tids, oids, emb = r.gallery("tsuga_canadensis")
    assert tids == [tid, tid] and emb.shape == (2, 4)


def test_uncertain_observation_then_assign(tmp_path):
    r = TreeRepository(tmp_path / "t.db")
    tid = r.create_tree("tsuga_canadensis", "H")
    oid = r.add_observation(_obs(None, np.ones(4), t=1.0))
    assert r.get_tree(tid).observation_count == 0
    r.assign_observation(oid, tid)
    assert r.get_tree(tid).observation_count == 1
    assert r.get_observation(oid).decision == "confirmed"


def test_blob_fp16_roundtrip_precision():
    v = np.random.default_rng(0).normal(size=2152).astype(np.float32)
    v /= np.linalg.norm(v)
    w = from_blob(to_blob(v))
    assert w.dtype == np.float32 and float(v @ w) > 0.9999
    assert len(to_blob(v)) == 2152 * 2


def test_failed_transaction_rolls_back(tmp_path):
    r = TreeRepository(tmp_path / "t.db")
    with pytest.raises(RuntimeError):
        with r.tx() as c:
            c.execute("INSERT INTO trees(tree_id, species, created_at, last_seen_at) VALUES('X-1','s',0,0)")
            raise RuntimeError
    assert r.get_tree("X-1") is None
