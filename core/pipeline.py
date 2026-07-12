"""
ImagePipeline — 이미지 처리 단계를 조합 가능한 파이프라인 구조.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Optional

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from core.resizer import resize_image


# ─────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────

class ImageStep(ABC):
    @abstractmethod
    def apply(self, img: Image.Image) -> Image.Image: ...
    def __repr__(self): return self.__class__.__name__


def _to_rgb_f32(img: Image.Image) -> tuple[np.ndarray, str]:
    """RGB float32 배열과 원본 모드 반환."""
    return np.array(img.convert("RGB"), dtype=np.float32), img.mode


def _from_f32(arr: np.ndarray, mode: str) -> Image.Image:
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return out if mode == "RGB" else out.convert(mode)


def _apply_lut(img: Image.Image, lut: np.ndarray) -> Image.Image:
    """256-entry uint8 LUT를 각 채널에 적용."""
    arr = np.array(img.convert("RGB"), dtype=np.uint8)
    return _from_f32(lut[arr].astype(np.float32), img.mode)


# ─────────────────────────────────────────────────────────
# Built-in (변환)
# ─────────────────────────────────────────────────────────

class ResizeStep(ImageStep):
    def __init__(self, mode, custom_w=0, custom_h=0):
        self.mode=mode; self.custom_w=custom_w; self.custom_h=custom_h
    def apply(self, img): return resize_image(img, self.mode, self.custom_w, self.custom_h)


class ColorModeStep(ImageStep):
    def __init__(self, fmt): self.fmt = fmt.upper()
    def apply(self, img):
        if self.fmt == "JPEG" and img.mode in ("RGBA","P","LA"):
            bg = Image.new("RGB", img.size, (255,255,255))
            a = img.convert("RGBA"); bg.paste(a, mask=a.split()[3]); return bg
        if self.fmt in ("JPEG","BMP") and img.mode == "L": return img.convert("RGB")
        if self.fmt == "BMP" and img.mode == "RGBA": return img.convert("RGB")
        return img


# ─────────────────────────────────────────────────────────
# 빛 (Light)
# ─────────────────────────────────────────────────────────

class ExposureStep(ImageStep):
    """노출 보정 (EV 단위). 전체 밝기를 2^ev 배율로 조정."""
    def __init__(self, ev=0.0): self.ev = ev
    def apply(self, img):
        if self.ev == 0.0: return img
        arr, mode = _to_rgb_f32(img)
        return _from_f32(arr * (2.0 ** self.ev), mode)


class BrightnessStep(ImageStep):
    """밝기 (PIL Enhance). factor=1.0 원본."""
    def __init__(self, factor=1.0): self.factor = factor
    def apply(self, img):
        if self.factor == 1.0: return img
        return ImageEnhance.Brightness(img).enhance(max(0.0, self.factor))


class ContrastStep(ImageStep):
    """대비 (PIL Enhance). factor=1.0 원본."""
    def __init__(self, factor=1.0): self.factor = factor
    def apply(self, img):
        if self.factor == 1.0: return img
        return ImageEnhance.Contrast(img).enhance(max(0.0, self.factor))


class GammaStep(ImageStep):
    """감마 / 중간 톤 조정. amount > 0 밝게, < 0 어둡게. LUT 기반 고속."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount == 0.0: return img
        t = self.amount / 100.0           # -1 ~ +1
        # +100 → gamma≈0.45 (밝음), -100 → gamma≈2.0 (어둠)
        gamma = max(0.1, 1.0 - t * 0.55)
        x = np.arange(256, dtype=np.float32) / 255.0
        lut = np.clip(x ** gamma * 255.0, 0, 255).astype(np.uint8)
        return _apply_lut(img, lut)


class WhitesStep(ImageStep):
    """흰점 조정. 밝기 70% 이상 영역에만 집중 적용."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount == 0.0: return img
        arr, mode = _to_rgb_f32(img)
        w = np.clip((arr / 255.0 - 0.7) / 0.3, 0, 1) ** 2
        return _from_f32(arr + self.amount * 0.8 * w, mode)


class BlacksStep(ImageStep):
    """검은점 조정. 밝기 30% 이하 영역에만 집중 적용."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount == 0.0: return img
        arr, mode = _to_rgb_f32(img)
        w = np.clip((0.3 - arr / 255.0) / 0.3, 0, 1) ** 2
        return _from_f32(arr + self.amount * 0.8 * w, mode)


class HighlightsStep(ImageStep):
    """하이라이트. 밝은 픽셀 가중 조정 (제곱 비례)."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount == 0.0: return img
        arr, mode = _to_rgb_f32(img)
        w = (arr / 255.0) ** 2
        return _from_f32(arr + self.amount * 0.8 * w, mode)


class ShadowsStep(ImageStep):
    """쉐도우. 어두운 픽셀 가중 조정 (제곱 비례)."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount == 0.0: return img
        arr, mode = _to_rgb_f32(img)
        w = (1.0 - arr / 255.0) ** 2
        return _from_f32(arr + self.amount * 0.8 * w, mode)


# ─────────────────────────────────────────────────────────
# 색상 (Color)
# ─────────────────────────────────────────────────────────

class WhiteBalanceStep(ImageStep):
    """색온도. > 0 따뜻하게(R↑B↓), < 0 차갑게(R↓B↑)."""
    def __init__(self, temperature=0): self.temperature = temperature
    def apply(self, img):
        if self.temperature == 0: return img
        arr, mode = _to_rgb_f32(img)
        t = self.temperature / 50.0
        arr[:,:,0] *= (1.0 + 0.25 * t)
        arr[:,:,2] *= (1.0 - 0.25 * t)
        return _from_f32(arr, mode)


class TintStep(ImageStep):
    """색조(Tint). > 0 마젠타, < 0 녹색 (녹색-마젠타 축 이동)."""
    def __init__(self, amount=0): self.amount = amount
    def apply(self, img):
        if self.amount == 0: return img
        arr, mode = _to_rgb_f32(img)
        t = self.amount / 50.0              # -1 ~ +1
        # 마젠타: G 감소 / 녹색: G 증가
        arr[:,:,1] *= max(0.1, 1.0 - 0.20 * t)
        return _from_f32(arr, mode)


class VibranceStep(ImageStep):
    """활기(Vibrance). 채도 낮은 색을 우선 강화, 이미 채도 높은 색은 덜 변화."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount == 0.0: return img
        arr, mode = _to_rgb_f32(img)
        f = arr / 255.0
        maxc = np.max(f, axis=2, keepdims=True)
        minc = np.min(f, axis=2, keepdims=True)
        # maxc==0(순흑색)에서 0/0 nan 방지: 해당 위치만 0으로 두고 분모>0 에서만 계산
        sat  = np.divide(maxc - minc, maxc, out=np.zeros_like(maxc), where=maxc > 0)
        # 낮은 채도 → 강한 부스트 / 높은 채도 → 약한 부스트
        boost = 1.0 + (self.amount / 100.0) * (1.0 - sat)
        mean  = f.mean(axis=2, keepdims=True)
        out   = mean + (f - mean) * boost
        return _from_f32(out * 255.0, mode)


class SaturationStep(ImageStep):
    """채도 (PIL Enhance). factor=0 흑백, 1.0 원본."""
    def __init__(self, factor=1.0): self.factor = factor
    def apply(self, img):
        if self.factor == 1.0: return img
        return ImageEnhance.Color(img).enhance(max(0.0, self.factor))


class HueStep(ImageStep):
    """색상 회전 (-180°~+180°). RGB 공간 Gray 축 회전 행렬."""
    def __init__(self, degrees=0.0): self.degrees = degrees
    def apply(self, img):
        if self.degrees == 0.0: return img
        arr, mode = _to_rgb_f32(img)
        a = np.radians(self.degrees)
        c, s = np.cos(a), np.sin(a)
        k, q = (1.0-c)/3.0, s/np.sqrt(3.0)
        m = np.array([[c+k, k-q, k+q],
                      [k+q, c+k, k-q],
                      [k-q, k+q, c+k]], dtype=np.float32)
        out = arr.reshape(-1, 3) @ m.T
        return _from_f32(out.reshape(arr.shape), mode)


# ─────────────────────────────────────────────────────────
# 디테일 (Detail)
# ─────────────────────────────────────────────────────────

class ClarityStep(ImageStep):
    """명료도. 큰 반경 언샤프 마스크로 중간 대역 대비 강화. < 0 소프트."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount == 0.0: return img
        radius = 10 + abs(self.amount) / 10.0   # 10~20 px
        if self.amount > 0:
            pct = int(self.amount * 1.5)
            return img.filter(ImageFilter.UnsharpMask(radius=radius, percent=pct, threshold=0))
        else:
            blurred = img.filter(ImageFilter.GaussianBlur(radius=radius / 5.0))
            return Image.blend(img, blurred, abs(self.amount) / 200.0)


class SharpnessStep(ImageStep):
    """선명도 (UnsharpMask). amount 0~100."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount <= 0.0: return img
        r = 1.0 + self.amount / 100.0
        return img.filter(ImageFilter.UnsharpMask(radius=r, percent=int(self.amount*3), threshold=3))


class DenoiseStep(ImageStep):
    """노이즈 제거. 가우시안 블러 기반 (amount 0~100)."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount <= 0.0: return img
        radius = self.amount / 100.0 * 2.5   # 0 ~ 2.5 px
        return img.filter(ImageFilter.GaussianBlur(radius=radius))


# ─────────────────────────────────────────────────────────
# 효과 (Effects)
# ─────────────────────────────────────────────────────────

class VignetteStep(ImageStep):
    """비네팅. > 0 가장자리 어둡게, < 0 밝게."""
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount == 0.0: return img
        arr, mode = _to_rgb_f32(img)
        h, w = arr.shape[:2]
        cy, cx = h / 2.0, w / 2.0
        y, x = np.ogrid[:h, :w]
        dist = np.sqrt(((x-cx)/cx)**2 + ((y-cy)/cy)**2)
        mask = np.clip(1.0 - dist**2 * (self.amount/100.0) * 0.7, 0.1, 2.0)
        return _from_f32(arr * mask[:,:,np.newaxis], mode)


class GrainStep(ImageStep):
    """필름 그레인. amount 0~100. 고정 시드로 미리보기 깜박임 방지."""
    _SEED = 42
    def __init__(self, amount=0.0): self.amount = amount
    def apply(self, img):
        if self.amount <= 0.0: return img
        arr, mode = _to_rgb_f32(img)
        sigma = self.amount * 0.3
        rng   = np.random.default_rng(self._SEED)
        noise = rng.normal(0, sigma, arr.shape).astype(np.float32)
        return _from_f32(arr + noise, mode)


# ─────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────

class ImagePipeline:
    def __init__(self): self._steps: List[ImageStep] = []

    def add_step(self, step):
        self._steps.append(step); return self

    def insert_before(self, target_type, step):
        for i, s in enumerate(self._steps):
            if isinstance(s, target_type):
                self._steps.insert(i, step); return self
        self._steps.append(step); return self

    def run(self, img, progress_cb=None):
        n = len(self._steps)
        for i, step in enumerate(self._steps):
            img = step.apply(img)
            if progress_cb: progress_cb(int(30 + (i+1)/n*50))
        return img

    def __repr__(self):
        return f"ImagePipeline({' → '.join(repr(s) for s in self._steps)})"


# ─────────────────────────────────────────────────────────
# 보정 순서 정의 (key, Step, default, threshold)
# 순서: 빛 → 색상 → 디테일 → 효과
# ─────────────────────────────────────────────────────────

_ADJ_STEPS = [
    # 빛
    ("exposure",      ExposureStep,    0.0, 0.0),
    ("gamma",         GammaStep,       0.0, 0.0),
    ("whites",        WhitesStep,      0.0, 0.0),
    ("blacks",        BlacksStep,      0.0, 0.0),
    ("highlights",    HighlightsStep,  0.0, 0.0),
    ("shadows",       ShadowsStep,     0.0, 0.0),
    ("brightness",    BrightnessStep,  1.0, 1.0),
    ("contrast",      ContrastStep,    1.0, 1.0),
    # 색상
    ("white_balance", WhiteBalanceStep, 0,  0),
    ("tint",          TintStep,         0,  0),
    ("vibrance",      VibranceStep,    0.0, 0.0),
    ("saturation",    SaturationStep,  1.0, 1.0),
    ("hue",           HueStep,         0.0, 0.0),
    # 디테일
    ("clarity",       ClarityStep,     0.0, 0.0),
    ("sharpness",     SharpnessStep,   0.0, 0.0),
    ("denoise",       DenoiseStep,     0.0, 0.0),
    # 효과
    ("vignette",      VignetteStep,    0.0, 0.0),
    ("grain",         GrainStep,       0.0, 0.0),
]


def apply_adjustments(img: Image.Image, adjustments: dict) -> Image.Image:
    """보정 단계만 적용. 미리보기 + 변환 공용."""
    for key, StepCls, default, threshold in _ADJ_STEPS:
        val = adjustments.get(key, default)
        if val != threshold:
            img = StepCls(val).apply(img)
    return img


def build_pipeline(
    target_format: str,
    resize_mode: str = "original",
    custom_w: int = 0,
    custom_h: int = 0,
    adjustments: Optional[dict] = None,
) -> ImagePipeline:
    p = ImagePipeline()
    if adjustments:
        for key, StepCls, default, threshold in _ADJ_STEPS:
            val = adjustments.get(key, default)
            if val != threshold:
                p.add_step(StepCls(val))
    p.add_step(ResizeStep(resize_mode, custom_w, custom_h))
    p.add_step(ColorModeStep(target_format))
    return p
