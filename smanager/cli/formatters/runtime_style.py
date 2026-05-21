"""Runtime type styling helpers for CLI tables."""

from __future__ import annotations

import hashlib
import colorsys
from functools import lru_cache

from ...service_managers import list_service_managers


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _runtime_hsl(runtime_type: str) -> tuple[float, float, float]:
    digest = hashlib.sha256(runtime_type.encode("utf-8")).digest()

    hue_raw = int.from_bytes(digest[0:2], "big")
    sat_raw = digest[2]
    light_raw = digest[3]

    h = (hue_raw % 360) / 360.0
    s = 0.58 + (sat_raw / 255.0) * 0.32
    l = 0.42 + (light_raw / 255.0) * 0.24

    return h, _clamp(s, 0.58, 0.90), _clamp(l, 0.42, 0.66)


def _runtime_hex_color(runtime_type: str) -> str:
    h, s, l = _runtime_hsl(runtime_type)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


@lru_cache(maxsize=256)
def runtime_style(runtime_type: str) -> str:
    """Return a deterministic style for a runtime type."""
    normalized = runtime_type.strip().lower() if runtime_type else "unknown"
    return _runtime_hex_color(normalized)


def runtime_style_map() -> dict[str, str]:
    """Return deterministic styles for all currently registered runtimes."""
    return {
        runtime_type: runtime_style(runtime_type)
        for runtime_type in list_service_managers()
    }
