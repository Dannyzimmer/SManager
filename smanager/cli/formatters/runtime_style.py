"""Runtime type styling helpers for CLI tables."""

from __future__ import annotations

import hashlib
import colorsys
from functools import lru_cache

from ...service_managers import list_service_managers


# Fine-tuning constants for inactive runtime styles.
# - Lower saturation factor => more muted runtime type colors.
# - Higher lightness boost => lighter inactive type colors.
INACTIVE_SATURATION_FACTOR = 0.32
INACTIVE_LIGHTNESS_BOOST = 0.07


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


def _hex_to_rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    r = int(value[0:2], 16) / 255.0
    g = int(value[2:4], 16) / 255.0
    b = int(value[4:6], 16) / 255.0
    return r, g, b


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return f"#{int(_clamp(r, 0.0, 1.0) * 255):02x}{int(_clamp(g, 0.0, 1.0) * 255):02x}{int(_clamp(b, 0.0, 1.0) * 255):02x}"


def _desaturate_hex_color(color: str) -> str:
    r, g, b = _hex_to_rgb(color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    desaturated_s = _clamp(s * INACTIVE_SATURATION_FACTOR, 0.0, 1.0)
    softened_l = _clamp(l + INACTIVE_LIGHTNESS_BOOST, 0.0, 1.0)
    r2, g2, b2 = colorsys.hls_to_rgb(h, softened_l, desaturated_s)
    return _rgb_to_hex(r2, g2, b2)


@lru_cache(maxsize=256)
def runtime_style(runtime_type: str) -> str:
    """Return a deterministic style for a runtime type."""
    normalized = runtime_type.strip().lower() if runtime_type else "unknown"
    return _runtime_hex_color(normalized)


def runtime_style_for_activity(
    runtime_type: str,
    active: bool,
    *,
    base_style: str | None = None,
) -> str:
    """Return deterministic runtime style, desaturated when service is inactive."""
    resolved_base_style = base_style or runtime_style(runtime_type)
    if active:
        return resolved_base_style
    return _desaturate_hex_color(resolved_base_style)


def runtime_style_map() -> dict[str, str]:
    """Return deterministic styles for all currently registered runtimes."""
    return {
        runtime_type: runtime_style(runtime_type)
        for runtime_type in list_service_managers()
    }
