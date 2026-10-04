"""Numerical properties of embeddings and similarity."""

import numpy as np
import pytest
import torch

from hemlock_sentinel.database.models import from_blob, to_blob
from hemlock_sentinel.reid.multiview import aggregate_mean, l2_normalize
from hemlock_sentinel.reid.retrieval import EmbeddingIndex, cosine_similarity


@pytest.fixture(scope="module")
def tiny_net():
    from hemlock_sentinel.reid.embedding import ReIDConfig, ReIDNet

    # Small timm backbone with random weights: tests the wiring, not accuracy.
    return ReIDNet(ReIDConfig(backbone="efficientnet_b0", pretrained=False, image_size=64, n_species=3)).eval()


def test_embedding_dimensionality(tiny_net):
    with torch.no_grad():
        emb, logits = tiny_net(torch.rand(2, 3, 64, 64))
    assert emb.shape == (2, tiny_net.backbone.num_features) and logits.shape == (2, 3)


def test_primary_backbone_dimension_matches_miewid():
    import timm

    m = timm.create_model("efficientnetv2_rw_m", pretrained=False, num_classes=0)
    assert m.num_features == 2152  # MiewID embedding width (backbone width, no FC)


def test_normalised_embeddings_have_unit_norm():
    x = np.random.default_rng(0).normal(size=(10, 2152)) * 37
    assert np.allclose(np.linalg.norm(l2_normalize(x), axis=1), 1.0, atol=1e-5)


def test_cosine_range_and_identity():
    rng = np.random.default_rng(1)
    a, b = rng.normal(size=(20, 64)), rng.normal(size=(30, 64))
    s = cosine_similarity(a, b)
    assert s.min() >= -1 and s.max() <= 1
    assert np.allclose(np.diag(cosine_similarity(a, a)), 1.0, atol=1e-5)


def test_known_cases():
    e = np.eye(3)
    assert cosine_similarity(e[0], e[1])[0, 0] == pytest.approx(0.0, abs=1e-7)
    assert cosine_similarity(e[0], -e[0])[0, 0] == pytest.approx(-1.0)
    assert cosine_similarity(e[0], 5 * e[0])[0, 0] == pytest.approx(1.0)
    assert cosine_similarity([1, 1, 0], [1, 0, 0])[0, 0] == pytest.approx(2 ** -0.5)


def test_zero_vector_is_safe():
    assert np.all(np.isfinite(l2_normalize(np.zeros((1, 4)))))


def test_fp16_storage_changes_cosine_by_less_than_1e3():
    rng = np.random.default_rng(2)
    a, b = l2_normalize(rng.normal(size=2152)), l2_normalize(rng.normal(size=2152))
    a16, b16 = from_blob(to_blob(a)), from_blob(to_blob(b))
    assert abs(float(a @ b) - float(l2_normalize(a16) @ l2_normalize(b16))) < 1e-3
    idx = EmbeddingIndex(2152)
    idx.add("T", a)
    assert idx.tree_scores(a)[0, 0] == pytest.approx(1.0, abs=1e-3)


def test_mean_aggregation_of_identical_views_is_the_view():
    v = l2_normalize(np.random.default_rng(3).normal(size=128))
    assert np.allclose(aggregate_mean(np.stack([v, v, v])), v, atol=1e-6)


def test_eval_mode_embedding_is_deterministic(tiny_net):
    x = torch.rand(1, 3, 64, 64)
    with torch.no_grad():
        assert torch.equal(tiny_net(x)[0], tiny_net(x)[0])


def test_learned_aggregators_shapes_and_masks():
    from hemlock_sentinel.reid.multiview import AttentionPool, MultiViewTransformer

    torch.manual_seed(0)
    views = torch.randn(2, 5, 32)
    mask = torch.tensor([[1, 1, 1, 0, 0], [1, 1, 1, 1, 1]], dtype=torch.bool)
    for m in (AttentionPool(32), MultiViewTransformer(32, 16, 1, 2)):
        m.eval()
        with torch.no_grad():
            out = m(views, mask)
            assert out.shape == (2, 32)
            assert torch.allclose(out.norm(dim=1), torch.ones(2), atol=1e-5)
            # padded views must not change the output
            v2 = views.clone()
            v2[0, 3:] = torch.randn(2, 32) * 100
            assert torch.allclose(m(v2, mask)[0], out[0], atol=1e-5)


@pytest.mark.parametrize("name,kw,size", [("efficientnetv2_rw_t", {}, 64),
                                          ("vit_small_patch14_dinov2", {"img_size": 56}, 56)])
def test_trunk_tail_split_equals_full_backbone(name, kw, size):
    from hemlock_sentinel.reid.backbone import Backbone, trunk_tail

    torch.manual_seed(0)
    trunk, tail, dim, _ = trunk_tail(name, pretrained=False, **kw)
    full = Backbone(name, pretrained=False, **kw)
    full.model.load_state_dict(trunk_tail_state(trunk, tail, full))
    trunk.eval(), tail.eval(), full.eval()
    x = torch.rand(2, 3, size, size)
    with torch.no_grad():
        assert torch.allclose(tail(trunk(x)), full(x), atol=1e-5)


def trunk_tail_state(trunk, tail, full):
    """The split modules share the same underlying timm parameters; copy them to the full model."""
    sd = {}
    src = getattr(trunk, "vit", None)
    if src is not None:
        return src.state_dict()
    # efficientnet: trunk = Sequential(conv_stem, bn1, *blocks[:k]); tail = Sequential(blocks[k:], conv_head, bn2)
    ref = full.model.state_dict()
    t_sd = trunk.state_dict()
    names = ["conv_stem", "bn1"]
    for key, v in t_sd.items():
        i, rest = key.split(".", 1)
        i = int(i)
        sd[(names[i] + "." + rest) if i < 2 else f"blocks.{i - 2}.{rest}"] = v
    for key, v in tail.state_dict().items():
        i, rest = key.split(".", 1)
        sd[{"0": "blocks", "1": "conv_head", "2": "bn2"}[i] + "." + rest] = v
    assert set(sd) == set(ref), set(ref) ^ set(sd)
    return sd


@pytest.mark.parametrize("name,kw,size", [("efficientnetv2_rw_m", {}, 64),
                                          ("vit_small_patch14_dinov2", {"img_size": 56}, 56)])
def test_last_block_split_composes_to_tail(name, kw, size):
    from hemlock_sentinel.reid.backbone import last_block_split, trunk_tail

    torch.manual_seed(0)
    trunk, tail, _, _ = trunk_tail(name, pretrained=False, **kw)
    prefix, last, _ = last_block_split(name, pretrained=False, **kw)
    # copy the tail's weights into prefix/last (all randomly initialised separately)
    if name.startswith("efficientnetv2"):
        stage = tail[0][0]  # blocks[5]
        prefix.load_state_dict(torch.nn.Sequential(*stage[:-1]).state_dict())
        last[0].load_state_dict(stage[-1:].state_dict())
        last[1].load_state_dict(tail[1].state_dict())
        last[2].load_state_dict(tail[2].state_dict())
    else:
        prefix.load_state_dict(torch.nn.Sequential(*tail.blocks[:-1]).state_dict())
        last.blocks.load_state_dict(tail.blocks[-1:].state_dict())
        last.norm.load_state_dict(tail.norm.state_dict())
    for m in (trunk, tail, prefix, last):
        m.eval()
    with torch.no_grad():
        h = trunk(torch.rand(2, 3, size, size))
        assert torch.allclose(last(prefix(h)), tail(h), atol=1e-4)
