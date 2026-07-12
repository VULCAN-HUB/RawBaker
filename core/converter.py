"""
converter.py — 파일 입출력 + 파이프라인 실행을 담당하는 진입점.

처리 흐름:
    열기(RAW/일반) → ImagePipeline.run() → EXIF 처리 → 저장

보정 기능(Phase 2) 추가 시:
    pipeline.insert_before(ColorModeStep, BrightnessStep(factor))
    처럼 파이프라인에 단계만 끼워 넣으면 됩니다.
"""
import io
import os
import threading
import uuid
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from core.exif_handler import copy_exif, force_dpi
from core.image_io import (
    open_raw, open_raw_full, open_normal,
    RAW_EXTS as _IO_RAW_EXTS, AUTO_BRIGHT_FACTOR,
)
from core.pipeline import build_pipeline, ImagePipeline

RAW_EXTENSIONS    = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf"}
NORMAL_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".bmp"}

FORMAT_EXT = {
    "JPEG": ".jpg",
    "PNG":  ".png",
    "TIFF": ".tif",
    "WEBP": ".webp",
    "BMP":  ".bmp",
}

FORMAT_SAVE_KWARGS = {
    "JPEG": lambda q: {"format": "JPEG", "quality": q, "subsampling": 0},
    "PNG":  lambda q: {"format": "PNG",  "compress_level": 6},
    "TIFF": lambda q: {"format": "TIFF"},
    "WEBP": lambda q: {"format": "WEBP", "quality": q, "method": 2},
    "BMP":  lambda q: {"format": "BMP"},
}

_MAX_PATH       = 260
_collision_lock = threading.Lock()


# ─────────────────────────────────────────────────────────
# 공개 예외
# ─────────────────────────────────────────────────────────

class ConvertError(Exception):
    """사용자에게 보여줄 변환 오류."""


# ─────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────

def is_raw(path: str) -> bool:
    return Path(path).suffix.lower() in RAW_EXTENSIONS


def validate_output_dir(out_dir: str) -> None:
    """출력 폴더 유효성 검사. 문제 있으면 ConvertError raise."""
    if not out_dir:
        return

    if len(out_dir) > _MAX_PATH - 20:
        raise ConvertError(
            f"폴더 경로가 너무 깁니다 ({len(out_dir)}자). 더 짧은 경로를 선택해 주세요."
        )

    if not os.path.exists(out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            raise ConvertError(f"폴더를 만들 수 없습니다: {e}") from e

    # 쓰기 권한 확인 (스레드 안전: uuid 파일명)
    test_file = os.path.join(out_dir, f".rawbaker_wt_{uuid.uuid4().hex[:8]}")
    try:
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
    except (OSError, PermissionError):
        raise ConvertError("이 폴더에는 저장할 수 없습니다. 다른 폴더를 선택해 주세요.")

    if not os.access(out_dir, os.W_OK):
        raise ConvertError("이 폴더에는 저장할 수 없습니다. 다른 폴더를 선택해 주세요.")


def _open_raw(path: str, auto_bright: bool = True) -> Image.Image:
    """
    RAW 센서 풀 해상도 디코딩 — 변환 출력 전용.
    썸네일을 우회하고 rawpy.postprocess()로 직접 디코딩하여
    원본 해상도와 색공간을 보존한다.
    auto_bright=True 면 기본 밝기 부스트(AUTO_BRIGHT_FACTOR)를 적용한다.
    """
    bright = AUTO_BRIGHT_FACTOR if auto_bright else 1.0
    try:
        return open_raw_full(path, bright=bright)
    except Exception as e:
        raise ConvertError(f"RAW 파일을 열 수 없습니다: {e}") from e


def _open_normal(path: str) -> Image.Image:
    """ICC 보정 포함. 미리보기와 동일한 베이스."""
    try:
        return open_normal(path)
    except Exception as e:
        raise ConvertError(f"이미지 파일을 열 수 없습니다: {e}") from e


def _sanitize_suffix(suffix: str) -> str:
    """충돌 시 붙일 사용자 단어에서 파일명 불가 문자를 제거."""
    if not suffix:
        return ""
    cleaned = "".join(c for c in suffix if c not in r'\/:*?"<>|').strip()
    return cleaned


def _ensure_no_collision(out_path: str, ext: str) -> str:
    """같은 이름 파일이 있으면 _1, _2 … 접미사 추가 (스레드 안전)."""
    with _collision_lock:
        if not os.path.exists(out_path):
            open(out_path, 'wb').close()   # 슬롯 예약
            return out_path
        base = str(Path(out_path).with_suffix(""))
        counter = 1
        while True:
            candidate = f"{base}_{counter}{ext}"
            if not os.path.exists(candidate):
                open(candidate, 'wb').close()
                return candidate
            counter += 1


# ─────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────

def convert_file(
    src_path: str,
    out_dir: str,
    out_format: str,
    jpeg_quality: int = 100,
    resize_mode: str = "original",
    custom_w: int = 0,
    custom_h: int = 0,
    exif_mode: str = "keep",
    adjustments: Optional[dict] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
    pipeline: Optional[ImagePipeline] = None,
    on_collision: str = "rename",
    rename_suffix: str = "",
    crop_enabled: bool = False,
    crop_landscape: tuple = (2400, 1600),
    crop_portrait: tuple = (1066, 1600),
    crop_rect_landscape=None,   # (nx,ny,nw,nh) 정규화. None이면 중앙 비율맞춤
    crop_rect_portrait=None,
    dpi: int = 0,
    auto_bright: bool = True,
) -> Optional[str]:
    """
    단일 파일을 변환합니다. 성공 시 출력 경로 반환.
    on_collision == 'skip' 이고 대상 파일이 이미 있으면 None 반환(건너뜀).

    adjustments: build_pipeline에 전달되는 보정 딕셔너리
    pipeline: 전달하면 기본 파이프라인 대신 사용됩니다.
    exif_mode: 'keep' | 'remove_gps' | 'remove_all'
    on_collision: 'rename'(번호 붙이기) | 'overwrite'(덮어쓰기) | 'skip'(건너뛰기)
    rename_suffix: 모든 출력 파일 이름 뒤에 항상 붙일 사용자 단어
                   (예: '_복사' → a.cr2 → a_복사.jpg). 충돌과 무관하게 항상 적용되며,
                   그 이름마저 이미 있으면 on_collision 규칙(번호/덮어쓰기/건너뛰기)이 적용된다.
    """
    src = Path(src_path)
    ext = src.suffix.lower()

    # --- 출력 폴더 ---
    resolved_out_dir = out_dir if out_dir else str(src.parent)
    validate_output_dir(resolved_out_dir)

    # --- 대상 경로 미리 계산 (skip 모드는 디코딩 전에 건너뛰기 판단) ---
    # 사용자 단어(rename_suffix)는 충돌과 무관하게 항상 파일명 뒤에 붙인다.
    target_format = out_format.upper()
    out_ext   = FORMAT_EXT[target_format]
    suffix    = _sanitize_suffix(rename_suffix)
    base_stem = src.stem + suffix
    candidate = os.path.join(resolved_out_dir, base_stem + out_ext)
    if os.path.abspath(candidate) == os.path.abspath(src_path):
        candidate = os.path.join(resolved_out_dir, base_stem + "_converted" + out_ext)

    if on_collision == "skip" and os.path.exists(candidate):
        return None  # 이미 존재 → 디코딩 없이 건너뜀

    if progress_cb:
        progress_cb(10)

    # --- 열기 ---
    if ext in RAW_EXTENSIONS:
        img = _open_raw(src_path, auto_bright=auto_bright)
        has_exif_src = False
    elif ext in NORMAL_EXTENSIONS:
        img = _open_normal(src_path)
        has_exif_src = ext in {".jpg", ".jpeg", ".tiff", ".tif"}
    else:
        raise ConvertError(f"지원하지 않는 형식: {ext}")

    # --- 크롭 (켜져 있으면 방향 자동 판별 → 정규화 영역 잘라 출력 크기로) ---
    effective_resize = resize_mode
    if crop_enabled:
        from core.resizer import crop_normalized, centered_aspect_rect
        if img.width >= img.height:
            tw, th = crop_landscape; rect = crop_rect_landscape
        else:
            tw, th = crop_portrait;  rect = crop_rect_portrait
        if not rect:
            rect = centered_aspect_rect(img.size, (tw / th) if th else 1.0)
        img = crop_normalized(img, rect[0], rect[1], rect[2], rect[3], tw, th)
        effective_resize = "original"   # 크롭이 최종 크기를 정하므로 리사이즈 생략

    if progress_cb:
        progress_cb(25)

    # --- 파이프라인 실행 ---
    active_pipeline = pipeline or build_pipeline(
        target_format, effective_resize, custom_w, custom_h, adjustments
    )

    img = active_pipeline.run(img, progress_cb=progress_cb)

    if progress_cb:
        progress_cb(80)

    # --- 저장 ---
    save_kwargs = FORMAT_SAVE_KWARGS[target_format](jpeg_quality)
    if dpi and dpi > 0 and target_format in ("JPEG", "PNG", "TIFF"):
        save_kwargs["dpi"] = (int(dpi), int(dpi))   # 인쇄 해상도 메타데이터
    buf = io.BytesIO()
    try:
        img.save(buf, **save_kwargs)
    except Exception as e:
        raise ConvertError(f"저장 실패: {e}") from e
    img_bytes = buf.getvalue()

    # --- EXIF ---
    if target_format == "JPEG" and has_exif_src and exif_mode != "remove_all":
        remove_gps = exif_mode == "remove_gps"
        img_bytes = copy_exif(src_path, img_bytes,
                              remove_gps=remove_gps, remove_all=False)

    # --- DPI(인쇄 해상도) EXIF 보정 ---
    # JPEG은 뷰어가 EXIF 해상도를 우선 읽는 경우가 많아 EXIF에도 DPI를 박아준다.
    # (EXIF 전체 제거 모드에서는 JFIF density만 사용 — EXIF를 추가하지 않음)
    if target_format == "JPEG" and dpi and dpi > 0 and exif_mode != "remove_all":
        img_bytes = force_dpi(img_bytes, dpi)

    # --- 출력 경로 (충돌 처리 모드 적용) ---
    if on_collision == "overwrite":
        out_path = candidate            # 기존 파일 덮어쓰기
    elif on_collision == "skip":
        out_path = candidate            # 사전 검사에서 없음을 확인함
    else:                               # rename: 충돌 시 번호 붙이기 (스레드 안전 슬롯 예약)
        out_path = _ensure_no_collision(candidate, out_ext)

    if len(out_path) > _MAX_PATH:
        raise ConvertError(f"출력 경로가 너무 깁니다 ({len(out_path)}자).")

    try:
        with open(out_path, "wb") as f:
            f.write(img_bytes)
    except OSError as e:
        raise ConvertError(f"파일 저장 실패: {e}") from e

    if progress_cb:
        progress_cb(100)

    return out_path
