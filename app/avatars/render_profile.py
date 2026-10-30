"""Versioned browser-render profile and strict image validation."""

from __future__ import annotations

import math
from io import BytesIO

from PIL import Image, UnidentifiedImageError

PROFILE_ID = "fashn-full-body-frontal"
PROFILE_VERSION = 1
RENDERER_VERSION = "google-model-viewer@4.3.1"
OUTPUT_WIDTH = 576
OUTPUT_HEIGHT = 768
MAX_RENDER_BYTES = 5 * 1024 * 1024
BACKGROUND = "#F4F3EE"
CAMERA_FOV_DEGREES = 30.0
CAMERA_AZIMUTH_DEGREES = 0.0
CAMERA_POLAR_DEGREES = 75.0
CAMERA_MARGIN_FACTOR = 1.12


def expected_camera_radius(bounds: dict[str, float]) -> float:
    """Return the fixed-perspective bounding-sphere distance used by the browser."""
    diagonal = math.sqrt(sum(bounds[axis] ** 2 for axis in ("x", "y", "z")))
    return (diagonal / 2.0) / math.sin(math.radians(CAMERA_FOV_DEGREES / 2.0)) * CAMERA_MARGIN_FACTOR


def validate_camera_settings(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"bounds_m", "azimuth_degrees", "polar_degrees", "fov_degrees", "radius_m"}:
        raise ValueError("The camera settings are invalid.")
    bounds = value.get("bounds_m")
    if not isinstance(bounds, dict) or set(bounds) != {"x", "y", "z"}:
        raise ValueError("The avatar bounds are invalid.")
    dimensions: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        dimension = bounds.get(axis)
        if isinstance(dimension, bool) or not isinstance(dimension, (float, int)) or not math.isfinite(dimension) or not 0 < dimension <= 100:
            raise ValueError("The avatar bounds are invalid.")
        dimensions[axis] = float(dimension)
    expected = expected_camera_radius(dimensions)
    radius = value.get("radius_m")
    if isinstance(radius, bool) or not isinstance(radius, (float, int)) or not math.isfinite(radius):
        raise ValueError("The camera distance is invalid.")
    if abs(float(radius) - expected) > max(0.0001, expected * 0.001):
        raise ValueError("The camera distance does not match the selected render profile.")
    if value.get("azimuth_degrees") != CAMERA_AZIMUTH_DEGREES or value.get("polar_degrees") != CAMERA_POLAR_DEGREES or value.get("fov_degrees") != CAMERA_FOV_DEGREES:
        raise ValueError("The camera does not match the selected render profile.")
    return {
        "bounds_m": dimensions,
        "framing": "bounding-sphere-margin-v1",
        "azimuth_degrees": CAMERA_AZIMUTH_DEGREES,
        "polar_degrees": CAMERA_POLAR_DEGREES,
        "fov_degrees": CAMERA_FOV_DEGREES,
        "radius_m": float(radius),
        "target": "auto-bounds-center",
    }


def validate_render_png(data: bytes) -> tuple[int, int]:
    if not data or len(data) > MAX_RENDER_BYTES:
        raise ValueError("The rendered PNG is empty or exceeds the 5 MiB limit.")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (OUTPUT_WIDTH, OUTPUT_HEIGHT):
                raise ValueError("The render must be a 576×768 PNG.")
            if image.mode not in {"RGB", "RGBA"}:
                raise ValueError("The render must use RGB or opaque RGBA pixels.")
            image.load()
            if image.mode == "RGBA" and image.getchannel("A").getextrema() != (255, 255):
                raise ValueError("The render background must be opaque.")
            return image.width, image.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("The upload is not a valid PNG image.") from None


def profile_settings(camera: dict) -> dict:
    return {
        "pose": "source-glb-default; animations-disabled",
        "camera": camera,
        "background": {"color": BACKGROUND, "opacity": 1.0},
        "lighting": {"environment": "model-viewer-default-neutral", "exposure": 1.0, "shadow_intensity": 0.8},
        "color_space": "sRGB",
        "output": {"format": "image/png", "width": OUTPUT_WIDTH, "height": OUTPUT_HEIGHT, "fit": "contain"},
    }
