"""Simulated Lightroom renders for plugin and position-check tests.

A photo is stored pixels plus a develop crop and an orientation code. Lightroom
shows the develop crop of the stored pixels, rotated or flipped for display.
"""

import cv2
import numpy as np

from src.crop_calculator import CropRegion
from src.lrc_bridge import _orientation_frame


def textured_image(width: int, height: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.random((height, width)).astype(np.float32)
    blurred = cv2.GaussianBlur(noise, (0, 0), 6)
    blurred = (blurred - blurred.min()) / (blurred.max() - blurred.min())
    gray = (blurred * 255).astype(np.uint8)
    return cv2.merge([gray, 255 - gray, gray])


def orient(stored: np.ndarray, orientation: str) -> np.ndarray:
    """Display the stored pixels the way Lightroom would for an orientation code."""
    origin, u_axis, v_axis = _orientation_frame(orientation)
    height, width = stored.shape[:2]
    display_w, display_h = (width, height) if u_axis[0] != 0 else (height, width)
    xs, ys = np.meshgrid(
        (np.arange(display_w) + 0.5) / display_w,
        (np.arange(display_h) + 0.5) / display_h,
    )
    map_x = (origin[0] + xs * u_axis[0] + ys * v_axis[0]) * width - 0.5
    map_y = (origin[1] + xs * u_axis[1] + ys * v_axis[1]) * height - 0.5
    return cv2.remap(stored, map_x.astype(np.float32), map_y.astype(np.float32), cv2.INTER_LINEAR)


def render(stored: np.ndarray, develop_crop: CropRegion, orientation: str, long_edge: int) -> np.ndarray:
    """What Lightroom exports: the develop crop of the stored pixels, oriented, resized, JPEG'd."""
    height, width = stored.shape[:2]
    cropped = stored[
        round(develop_crop.top * height):round(develop_crop.bottom * height),
        round(develop_crop.left * width):round(develop_crop.right * width),
    ]
    shown = orient(cropped, orientation)
    scale = long_edge / max(shown.shape[:2])
    size = (max(1, round(shown.shape[1] * scale)), max(1, round(shown.shape[0] * scale)))
    resized = cv2.resize(shown, size, interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)
