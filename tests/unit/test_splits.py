from hemlock_sentinel.evaluation.splits import (ImageRecord, gallery_query_split, make_observations,
                                                split_identities)


def _recs():
    out = []
    for t in range(10):
        for cap in range(2 if t < 3 else 1):
            for v in range(8):
                out.append(ImageRecord(f"p{t}_{cap}_{v}.jpg", f"PRU-{t}", "tsuga_canadensis", "20170101",
                                       f"PRU-{t}@{cap}", "Nexus 5", 100.0, v))
    return out


def test_identity_split_is_disjoint_and_deterministic():
    ids = [f"T{i}" for i in range(40)]
    a = split_identities(ids, (0.5, 0.2, 0.3), seed=1)
    b = split_identities(ids, (0.5, 0.2, 0.3), seed=1)
    assert a == b
    tr, va, te = map(set, a)
    assert not (tr & va) and not (tr & te) and not (va & te)
    assert len(tr | va | te) == 40


def test_observations_never_mix_captures_or_trees():
    obs = make_observations(_recs(), 4, seed=0)
    for o in obs:
        assert len(o.paths) == 4
        caps = {p.split("_")[1] for p in o.paths}
        trees = {p.split("_")[0] for p in o.paths}
        assert len(caps) == 1 and len(trees) == 1
    paths = [p for o in obs for p in o.paths]
    assert len(paths) == len(set(paths))  # no image reused


def test_gallery_query_open_set():
    obs = make_observations(_recs(), 4, seed=0)
    g, kq, nq = gallery_query_split(obs, 0.5, seed=0)
    gal_trees = {o.tree_id for o in g}
    assert all(o.tree_id in gal_trees for o in kq)
    assert all(o.tree_id not in gal_trees for o in nq)
    gal_paths = {p for o in g for p in o.paths}
    assert not gal_paths & {p for o in kq + nq for p in o.paths}
    # trees with two captures: queries come from the other capture
    for o in kq:
        gal = next(x for x in g if x.tree_id == o.tree_id)
        if o.tree_id in {"PRU-0", "PRU-1", "PRU-2"}:
            assert gal.obs_id.split("#")[0] != o.obs_id.split("#")[0]
