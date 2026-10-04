import math

import numpy as np
import pytest
import torch
import torch.nn.functional as F

from hemlock_sentinel.reid.losses import (BatchHardTripletLoss, SubCenterArcFace, SupConLoss, build_loss,
                                          dynamic_margins)


def test_dynamic_margins_rare_classes_get_larger_margin():
    m = dynamic_margins([100, 10, 1], 0.2, 0.5)
    assert m[0] == pytest.approx(0.2) and m[2] == pytest.approx(0.5)
    assert m[0] < m[1] < m[2]


def test_dynamic_margins_equal_counts():
    # Regression: MiewID's formula divides 0/0 -> NaN when all counts are equal.
    m = dynamic_margins([5, 5, 5])
    assert np.all(np.isfinite(m)) and np.allclose(m, 0.5)


def test_dynamic_margins_rejects_bad_input():
    with pytest.raises(ValueError):
        dynamic_margins([0, 3])


def test_subcenter_takes_max_over_subcenters():
    loss = SubCenterArcFace(4, 2, k=3, margins=0.0)
    with torch.no_grad():
        loss.weight.zero_()
        loss.weight[1, 0] = 1.0  # class 0, sub-centre 1 points along e0
        loss.weight[3, 1] = 1.0  # class 1, sub-centre 0 along e1
    emb = torch.tensor([[1.0, 0, 0, 0]])
    cos = loss.cosine(emb).detach()
    assert cos[0, 0] == pytest.approx(1.0, abs=1e-5)
    assert cos[0, 1] == pytest.approx(0.0, abs=1e-5)


def test_arcface_target_logit_is_cos_theta_plus_m():
    m = 0.5
    loss = SubCenterArcFace(2, 2, k=1, s=1.0, margins=m)
    with torch.no_grad():
        loss.weight.copy_(torch.tensor([[1.0, 0.0], [0.0, 1.0]]))
    theta = 0.6
    emb = torch.tensor([[math.cos(theta), math.sin(theta)]])
    logits = loss.logits(emb, torch.tensor([0]))
    assert logits[0, 0].item() == pytest.approx(math.cos(theta + m), abs=1e-5)
    assert logits[0, 1].item() == pytest.approx(math.cos(math.pi / 2 - theta), abs=1e-5)


def test_arcface_fallback_when_theta_plus_m_exceeds_pi():
    m = 0.5
    loss = SubCenterArcFace(2, 2, k=1, s=1.0, margins=m)
    with torch.no_grad():
        loss.weight.copy_(torch.tensor([[1.0, 0.0], [0.0, 1.0]]))
    theta = math.pi - 0.2  # theta + m > pi
    emb = torch.tensor([[math.cos(theta), math.sin(theta)]])
    logit = loss.logits(emb, torch.tensor([0]))[0, 0].item()
    assert logit == pytest.approx(math.cos(theta) - math.sin(math.pi - m) * m, abs=1e-5)


def test_arcface_gradient_finite_at_cos_one():
    # Regression: sqrt(1 - cos^2) has an infinite derivative at cos = 1.
    loss = SubCenterArcFace(2, 2, k=1, margins=0.5)
    with torch.no_grad():
        loss.weight.copy_(torch.tensor([[1.0, 0.0], [0.0, 1.0]]))
    emb = torch.tensor([[1.0, 0.0]], requires_grad=True)
    loss(emb, torch.tensor([0])).backward()
    assert torch.isfinite(emb.grad).all()


def test_losses_decrease_when_training_separable_data():
    torch.manual_seed(0)
    centers = F.normalize(torch.randn(4, 8), dim=1)
    y = torch.arange(4).repeat_interleave(8)
    for name in ["subcenter_arcface", "arcface", "supcon", "triplet"]:
        x = (centers[y] + 0.3 * torch.randn(32, 8)).requires_grad_(False)
        proj = torch.nn.Linear(8, 8)
        lf = build_loss(name, 8, 4, class_counts=[8, 8, 8, 8])
        opt = torch.optim.Adam(list(proj.parameters()) + list(lf.parameters()), lr=1e-2)
        first = None
        for _ in range(60):
            l = lf(proj(x), y)
            first = first if first is not None else float(l.detach())
            opt.zero_grad()
            l.backward()
            opt.step()
        assert float(l.detach()) < first, name


def test_supcon_and_triplet_handle_no_positives():
    e = torch.randn(4, 8, requires_grad=True)
    y = torch.arange(4)
    assert float(SupConLoss()(e, y)) == 0.0
    assert float(BatchHardTripletLoss()(e, y)) == 0.0
