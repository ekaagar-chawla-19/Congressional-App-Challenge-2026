import torch

from hemlock_sentinel.reid.gem import GeM


def test_gem_p1_is_average_pool():
    x = torch.rand(2, 5, 4, 4) + 0.1
    g = GeM(p=1.0, learnable=False)
    assert torch.allclose(g(x), x.mean(dim=(-2, -1)), atol=1e-6)


def test_gem_large_p_approaches_max():
    x = torch.rand(2, 5, 4, 4) + 0.1
    g = GeM(p=60.0, learnable=False)
    assert torch.allclose(g(x), x.amax(dim=(-2, -1)), rtol=0.05)


def test_gem_p_is_learnable_and_gets_gradient():
    g = GeM(p=3.0)
    x = torch.rand(2, 3, 4, 4, requires_grad=True)
    g(x).sum().backward()
    assert g.p.grad is not None and torch.isfinite(g.p.grad).all()


def test_gem_handles_negative_and_zero_inputs():
    g = GeM()
    x = torch.zeros(1, 2, 3, 3)
    x[0, 0] = -5
    y = g(x)
    assert torch.isfinite(y).all() and (y >= 0).all()


def test_embedding_head_shapes_and_bn():
    from hemlock_sentinel.reid.embedding import EmbeddingHead

    h = EmbeddingHead(16)
    h.train()
    y = h(torch.rand(8, 16, 5, 5))
    assert y.shape == (8, 16)
    # train-mode BN output is standardised per dimension
    assert torch.allclose(y.mean(0), torch.zeros(16), atol=1e-4)
