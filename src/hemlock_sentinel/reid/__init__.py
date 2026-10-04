"""Individual re-identification: embedding model, losses, aggregation, matching.

Modules that need torch (backbone, gem, losses, multiview learned aggregators) are
imported lazily so that the numpy-only inference path (ONNX Runtime on the
handheld) does not pull in torch.
"""
