"""How much does an animated (TGS/Lottie) emoji actually move?

Some packs ship "animated" stickers whose animation never changes a single property; they
look frozen. We score motion from the keyframes: every keyframed property whose values
change counts, numeric transforms (position, scale, rotation, opacity) add their range,
shape morphs add a fixed amount. 0 means frozen.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

# Below this the emoji looks frozen or barely twitches.
ALIVE_THRESHOLD = 30.0
_WEIGHTS = {"r": 1.0, "p": 1.0, "s": 1.0, "o": 0.5}


def _numbers(value: Any) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list):
        return [float(v) for v in value if isinstance(v, (int, float))]
    return []


def motion_score(lottie: dict[str, Any]) -> float:
    total = 0.0

    def walk(node: Any, key: str | None = None) -> None:
        nonlocal total
        if isinstance(node, dict):
            frames = node.get("k")
            if isinstance(frames, list) and frames and all(
                    isinstance(f, dict) and "t" in f for f in frames):
                starts = [f.get("s") for f in frames if "s" in f]
                if len({json.dumps(s, sort_keys=True) for s in starts}) > 1:
                    values = [v for v in (_numbers(s) for s in starts) if v]
                    if len(values) >= 2:
                        dims = min(len(v) for v in values)
                        delta = max(max(v[i] for v in values) - min(v[i] for v in values)
                                    for i in range(dims))
                        total += min(delta, 200.0) * _WEIGHTS.get(key or "", 0.3)
                    else:
                        total += 20.0  # shape morph
            for child_key, child in node.items():
                walk(child, child_key)
        elif isinstance(node, list):
            for child in node:
                walk(child, key)

    walk(lottie.get("layers", []))
    walk(lottie.get("assets", []))
    return round(total, 1)


def tgs_motion(data: bytes) -> float:
    """Score a .tgs file (gzipped Lottie JSON)."""
    return motion_score(json.loads(gzip.decompress(data)))
