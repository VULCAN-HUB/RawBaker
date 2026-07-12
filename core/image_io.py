"""
image_io.py — 이미지 로드 공통 유틸.

미리보기와 변환 출력이 동일한 베이스 이미지를 사용하도록
한 곳에서 관리한다.

RAW 로드 우선순위:
  1) RAW 내 임베딩 JPEG  — 카메라 색보정·픽처스타일 적용 상태
                           Windows 사진 앱과 동일한 색감
  2) rawpy postprocess   — 임베딩 없을 때 폴백
"""
from __future__ import annotations

import io as _io
from pathlib import Path
from typing import Optional

from PIL import Image

RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf"}

# 자동 밝기 보정 계수 — RAW 직접 디코딩은 카메라 JPEG보다 평탄/어둡게 보이므로
# 기본적으로 약간 밝게 끌어올린다(라이트룸의 베이스 톤업과 유사). 1.0 = 부스트 없음.
AUTO_BRIGHT_FACTOR = 1.15


# ─────────────────────────────────────────────────────────
# ICC → sRGB 변환
# ─────────────────────────────────────────────────────────

def icc_to_srgb(img: Image.Image) -> Image.Image:
    """
    ICC 프로파일이 내장된 이미지를 sRGB로 변환.
    프로파일 없거나 변환 실패 시 원본 반환.
    """
    from PIL import ImageCms
    icc_bytes = img.info.get('icc_profile')
    if not icc_bytes:
        return img
    try:
        src = ImageCms.ImageCmsProfile(_io.BytesIO(icc_bytes))
        dst = ImageCms.createProfile('sRGB')
        if img.mode == 'RGBA':
            rgb = img.convert('RGB')
            out = ImageCms.profileToProfile(rgb, src, dst)
            out.putalpha(img.split()[3])
            return out
        work = img if img.mode in ('RGB', 'L') else img.convert('RGB')
        return ImageCms.profileToProfile(work, src, dst)
    except Exception:
        return img


# ─────────────────────────────────────────────────────────
# 임베딩 JPEG 추출
# ─────────────────────────────────────────────────────────

def _extract_embedded_jpeg(path: str) -> Optional[Image.Image]:
    """
    RAW 파일에서 임베딩 JPEG를 추출한다.
    없거나 실패하면 None 반환.
    """
    import rawpy
    try:
        with rawpy.imread(path) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                img = Image.open(_io.BytesIO(thumb.data))
                img.load()
                return icc_to_srgb(img).convert("RGB")
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────
# RAW 로드 (미리보기·변환 공용)
# ─────────────────────────────────────────────────────────

def open_raw(path: str, half_size: bool = False) -> Image.Image:
    """
    RAW 파일을 RGB PIL.Image로 반환.

    half_size=False: 변환 출력용 (풀 해상도)
    half_size=True : rawpy 폴백 시 미리보기 속도 개선용
                     (임베딩 JPEG는 half_size 무관하게 원본 크기)

    ※ 이 함수는 자동 밝기 부스트(AUTO_BRIGHT_FACTOR)를 적용하지 않는다.
      현재 변환/미리보기 경로는 open_raw_full()/open_raw_preview()를 쓰며,
      이 함수는 임베딩 JPEG 우선 레거시 경로다.
    """
    # 1순위: 임베딩 JPEG
    img = _extract_embedded_jpeg(path)
    if img is not None:
        return img

    # 2순위: rawpy 디코딩
    import rawpy
    try:
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=half_size,
                no_auto_bright=False,
                output_bps=8,
                output_color=rawpy.ColorSpace.sRGB,
            )
        return Image.fromarray(rgb, "RGB")
    except Exception as e:
        raise RuntimeError(f"RAW 파일을 열 수 없습니다: {e}") from e


# ─────────────────────────────────────────────────────────
# RAW 로드 — 변환 출력 전용 (풀 센서 해상도)
# ─────────────────────────────────────────────────────────

def open_raw_full(path: str, bright: float = AUTO_BRIGHT_FACTOR) -> Image.Image:
    """
    RAW 파일을 풀 센서 해상도 RGB PIL.Image로 반환.
    ※ 변환 출력 전용 — 썸네일을 우회하고 rawpy.postprocess() 직접 디코딩.

    open_raw()와의 차이:
      open_raw()      : 임베딩 JPEG 썸네일 우선 (빠름, 미리보기용)
      open_raw_full() : rawpy 풀 디코딩만 수행  (느림, 출력 품질 최우선)

    보장:
      - 카메라 센서의 원본 해상도 그대로 출력
      - use_camera_wb=True 로 화이트밸런스 보존
      - output_color=sRGB 로 ICC 변환 없이 색공간 통일
      - bright(기본 AUTO_BRIGHT_FACTOR)로 밝기 보정. 1.0이면 부스트 없음.
    """
    import rawpy
    try:
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=False,
                no_auto_bright=False,
                bright=bright,
                output_bps=8,
                output_color=rawpy.ColorSpace.sRGB,
            )
        return Image.fromarray(rgb, "RGB")
    except Exception as e:
        raise RuntimeError(
            f"RAW 파일 풀 해상도 디코딩 실패: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# RAW 로드 — 미리보기 전용 (출력과 색 일치 보장)
# ─────────────────────────────────────────────────────────

def open_raw_preview(path: str, bright: float = AUTO_BRIGHT_FACTOR) -> Image.Image:
    """
    RAW 파일을 미리보기용으로 로드 — **출력(open_raw_full)과 동일한 색**.

    라이트룸·캡처원 같은 전문 프로그램과 동일한 원리:
      임베딩 JPEG(카메라 색감)이 아니라 RAW 엔진(rawpy)으로 직접 디모자이킹한
      결과를 보여준다. 따라서 화면에서 본 색 = 변환 출력 색 (WYSIWYG).

    open_raw_full() 과 색 파라미터(use_camera_wb·no_auto_bright·sRGB·bright)는 완전히
    동일하고, 속도를 위해 half_size=True 로 절반 해상도만 디코딩한다.
    절반 해상도는 화면 표시·보정 미리보기에 충분하며 색은 풀 디코딩과 같다.
    bright(기본 AUTO_BRIGHT_FACTOR)로 밝기 보정 — 출력과 같은 값을 써야 색이 일치한다.
    """
    import rawpy
    try:
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=True,          # 미리보기 속도용 — 색은 풀 디코딩과 동일
                no_auto_bright=False,
                bright=bright,
                output_bps=8,
                output_color=rawpy.ColorSpace.sRGB,
            )
        return Image.fromarray(rgb, "RGB")
    except Exception as e:
        raise RuntimeError(f"RAW 미리보기 디코딩 실패: {e}") from e


# ─────────────────────────────────────────────────────────
# 일반 이미지 로드
# ─────────────────────────────────────────────────────────

def open_normal(path: str) -> Image.Image:
    """
    일반 이미지를 ICC 보정 후 반환.
    변환 파이프라인·미리보기 양쪽에서 사용.
    """
    img = Image.open(path)
    img.load()
    img = icc_to_srgb(img)
    if img.mode not in ("RGB", "RGBA", "L", "P", "LA"):
        img = img.convert("RGB")
    return img
