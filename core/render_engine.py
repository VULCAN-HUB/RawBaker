"""Versioned, Qt-independent linear-sRGB renderer. No 8-bit intermediate steps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

ENGINE_VERSION = "linear-v1"
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


class RenderCancelled(RuntimeError):
    pass


def srgb_to_linear(value: np.ndarray) -> np.ndarray:
    value = np.asarray(value, dtype=np.float32)
    return np.where(value <= 0.04045, value / 12.92,
                    np.power(np.maximum((value + 0.055) / 1.055, 0), 2.4)).astype(np.float32)


def linear_to_srgb(value: np.ndarray) -> np.ndarray:
    value = np.asarray(value, dtype=np.float32)
    return np.where(value <= 0.0031308, value * 12.92,
                    1.055 * np.power(np.maximum(value, 0), 1 / 2.4) - 0.055).astype(np.float32)


@dataclass(frozen=True)
class Frame:
    """Owned read-only float32 pixels, straight alpha; RGB may exceed display range."""
    rgb: np.ndarray
    alpha: np.ndarray | None = None

    def __post_init__(self):
        rgb = np.array(self.rgb, dtype=np.float32, copy=True, order="C")
        if rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 1 or not np.isfinite(rgb).all():
            raise ValueError("RGB must be finite H×W×3 pixels")
        rgb.setflags(write=False)
        object.__setattr__(self, "rgb", rgb)
        if self.alpha is not None:
            alpha = np.array(self.alpha, dtype=np.float32, copy=True, order="C")
            if alpha.shape != rgb.shape[:2] or not np.isfinite(alpha).all() or np.any((alpha < 0) | (alpha > 1)):
                raise ValueError("Alpha must be H×W within [0, 1]")
            alpha.setflags(write=False)
            object.__setattr__(self, "alpha", alpha)

    @classmethod
    def _owned_render_result(cls, rgb: np.ndarray, alpha: np.ndarray | None) -> Frame:
        # Only renderer-created buffers whose tiles were validated may use this.
        # Sharing the already read-only source alpha avoids a full-frame extra copy.
        result = object.__new__(cls)
        rgb.setflags(write=False)
        object.__setattr__(result, "rgb", rgb)
        object.__setattr__(result, "alpha", alpha)
        return result


@dataclass(frozen=True)
class Adjustments:
    exposure: float = 0.0             # EV
    contrast: float = 1.0             # slope around 18% linear gray
    temperature: float = 0.0          # -100 .. 100, relative RGB balance
    tint: float = 0.0                 # -100 .. 100
    saturation: float = 1.0
    highlights: float = 0.0           # -100 .. 100, weighted +/- 2 EV
    shadows: float = 0.0
    whites: float = 0.0
    blacks: float = 0.0
    sharpness: float = 0.0            # 0 .. 100, 1px source-space Gaussian
    curve: tuple[tuple[float, float], ...] = field(default_factory=lambda: ((0., 0.), (1., 1.)))

    def __post_init__(self):
        bounds = {"exposure": (-10, 10), "contrast": (0, 3), "saturation": (0, 3),
                  "sharpness": (0, 100)}
        for name in ("temperature", "tint", "highlights", "shadows", "whites", "blacks"):
            bounds[name] = (-100, 100)
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if type(value) not in (int, float) or not np.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Invalid adjustment: {name}")
        curve = np.asarray(self.curve, dtype=np.float64)
        if (curve.ndim != 2 or curve.shape[1] != 2 or not 2 <= len(curve) <= 32
                or not np.isfinite(curve).all() or np.any((curve < 0) | (curve > 1))
                or curve[0, 0] != 0 or curve[-1, 0] != 1 or np.any(np.diff(curve[:, 0]) <= 0)):
            raise ValueError("Curve needs 2–32 ordered points spanning [0, 1]")
        object.__setattr__(self, "curve", tuple(map(tuple, curve)))


def _point_adjust(rgb: np.ndarray, settings: Adjustments) -> np.ndarray:
    gains = np.array([2 ** (settings.temperature / 200), 2 ** (-settings.tint / 200),
                      2 ** (-settings.temperature / 200)], dtype=np.float32) * np.float32(2 ** settings.exposure)
    rgb = cv2.transform(rgb, np.diag(gains))
    if any((settings.highlights, settings.shadows, settings.whites, settings.blacks)):
        y = np.clip(cv2.transform(rgb, LUMA[None, :]), 0, 1)
        high = y * y * (3 - 2 * y)
        stops = (settings.highlights * high + settings.shadows * (1 - high)
                 + settings.whites * y ** 4 + settings.blacks * (1 - y) ** 4) / 50
        rgb *= np.exp2(stops)[..., None]
    if settings.contrast != 1 or settings.saturation != 1:
        matrix = (np.eye(3, dtype=np.float32) * settings.saturation
                  + np.tile(LUMA, (3, 1)) * (1 - settings.saturation)) * settings.contrast
        affine = np.column_stack((matrix, np.full(3, .18 * (1 - settings.contrast), dtype=np.float32)))
        rgb = cv2.transform(rgb, affine)
    if settings.curve != ((0., 0.), (1., 1.)):
        # Display-encoded control points; preserve out-of-range values by end slopes.
        encoded = linear_to_srgb(rgb)
        xp, yp = np.asarray(settings.curve).T
        mapped = np.interp(encoded, xp, yp).astype(np.float32)
        mapped = np.where(encoded < 0, yp[0] + encoded * (yp[1] - yp[0]) / (xp[1] - xp[0]), mapped)
        mapped = np.where(encoded > 1, yp[-1] + (encoded - 1) * (yp[-1] - yp[-2]) / (xp[-1] - xp[-2]), mapped)
        rgb = srgb_to_linear(mapped)
    return rgb


def render(frame: Frame, settings: Adjustments = Adjustments(), *, tile_rows: int = 128,
           cancelled: Callable[[], bool] | None = None) -> Frame:
    """Identical source-pixel rendering for preview/export; bounded temporary row tiles."""
    if type(tile_rows) is not int or tile_rows < 1:
        raise ValueError("tile_rows must be a positive integer")
    height = frame.rgb.shape[0]
    result = np.empty_like(frame.rgb)
    halo = 3 if settings.sharpness else 0
    for start in range(0, height, tile_rows):
        if cancelled and cancelled():
            raise RenderCancelled("Rendering cancelled")
        end = min(start + tile_rows, height)
        lo, hi = max(0, start - halo), min(height, end + halo)
        rgb = _point_adjust(frame.rgb[lo:hi], settings)
        if settings.sharpness:
            if frame.alpha is None:
                blur = cv2.GaussianBlur(rgb, (7, 7), 1, borderType=cv2.BORDER_REFLECT_101)
            else:
                # Normalize premultiplied blur so invisible RGB cannot bleed into edges.
                alpha = frame.alpha[lo:hi, :, None]
                weight = cv2.GaussianBlur(alpha, (7, 7), 1, borderType=cv2.BORDER_REFLECT_101)[..., None]
                blur = cv2.GaussianBlur(rgb * alpha, (7, 7), 1, borderType=cv2.BORDER_REFLECT_101)
                np.divide(blur, weight, out=blur, where=weight > 1e-8)
            amount = settings.sharpness / 100
            rgb = cv2.addWeighted(rgb, 1 + amount, blur, -amount, 0)
        if not np.isfinite(rgb).all():
            raise ValueError("Rendered values exceed float32 range")
        result[start:end] = rgb[start-lo:end-lo]
    return Frame._owned_render_result(result, frame.alpha)


def resize(frame: Frame, max_side: int) -> Frame:
    """Area-reduce in linear light and premultiplied alpha, never enlarge."""
    if type(max_side) is not int or max_side < 1:
        raise ValueError("max_side must be a positive integer")
    h, w = frame.rgb.shape[:2]
    scale = min(1, max_side / max(h, w))
    if scale == 1:
        return frame
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    if frame.alpha is None:
        return Frame(cv2.resize(frame.rgb, size, interpolation=cv2.INTER_AREA))
    alpha = cv2.resize(frame.alpha, size, interpolation=cv2.INTER_AREA)
    rgb = cv2.resize(frame.rgb * frame.alpha[..., None], size, interpolation=cv2.INTER_AREA)
    np.divide(rgb, alpha[..., None], out=rgb, where=alpha[..., None] > 1e-8)
    rgb[alpha <= 1e-8] = 0
    return Frame(rgb, alpha)


def to_pixels(frame: Frame, bits: int = 8) -> np.ndarray:
    """Clip and quantize only at display/file boundary. Alpha is not gamma encoded."""
    if bits not in (8, 16):
        raise ValueError("Output depth must be 8 or 16 bits")
    maximum = (1 << bits) - 1
    h, w = frame.rgb.shape[:2]
    pixels = np.empty((h, w, 4 if frame.alpha is not None else 3), dtype=np.uint8 if bits == 8 else np.uint16)
    for start in range(0, h, 128):
        end = min(h, start + 128)
        rgb = np.clip(linear_to_srgb(frame.rgb[start:end]), 0, 1)
        pixels[start:end, :, :3] = np.rint(rgb * maximum)
        if frame.alpha is not None:
            pixels[start:end, :, 3] = np.rint(frame.alpha[start:end] * maximum)
    return pixels
