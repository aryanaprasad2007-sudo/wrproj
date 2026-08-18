"""Backend lookup. The single place that knows every video backend by name.

Imports are deferred into `build()` so that a broken or unavailable backend
(missing model, diffusers version without that pipeline class) cannot stop the
other three from working, and so `--dry-run` costs nothing.
"""
from __future__ import annotations

BACKENDS = ("ltx", "wan", "svd", "animatediff")


def build(name: str, cfg, hw):
    key = (name or "ltx").lower()
    if key == "ltx":
        from .ltx import LTXBackend
        return LTXBackend(cfg, hw)
    if key == "wan":
        from .wan import WanBackend
        return WanBackend(cfg, hw)
    if key == "svd":
        from .svd import SVDBackend
        return SVDBackend(cfg, hw)
    if key == "animatediff":
        from .animatediff import AnimateDiffBackend
        return AnimateDiffBackend(cfg, hw)
    raise ValueError(f"unknown video backend '{name}' (have: {', '.join(BACKENDS)})")
