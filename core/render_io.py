"""Explicit color/depth boundaries for linear-v1; legacy decoding stays unchanged."""
from __future__ import annotations

import io
from pathlib import Path
import struct
import zlib

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps

from core.image_io import RAW_EXTS
from core.render_engine import Frame, srgb_to_linear, to_pixels
from core.safe_output import write_output


def _orient(pixels: np.ndarray, orientation: int) -> np.ndarray:
    if orientation == 2:
        return np.fliplr(pixels)
    if orientation == 3:
        return pixels[::-1, ::-1]
    if orientation == 4:
        return np.flipud(pixels)
    if orientation == 5:
        return np.swapaxes(pixels, 0, 1)
    if orientation == 6:
        return np.rot90(pixels, -1)
    if orientation == 7:
        return np.swapaxes(pixels, 0, 1)[::-1, ::-1]
    if orientation == 8:
        return np.rot90(pixels, 1)
    return pixels


def _decoded_frame(pixels, alpha=None, linear=False, divisor=255):
    # Decode-owned buffers, validated by bounded integer input; avoid full-frame
    # float conversion temporaries and Frame's redundant defensive copy.
    h,w=pixels.shape[:2];rgb=np.empty((h,w,3),np.float32)
    for y in range(0,h,128):
        tile=pixels[y:y+128,:,:3]
        values=tile.astype(np.float32)/divisor
        rgb[y:y+128]=values if linear else srgb_to_linear(values)
    if alpha is not None:alpha=np.asarray(alpha,dtype=np.float32)
    return Frame._owned_render_result(rgb,alpha)


def decode_photo(path: str | Path, max_side=None, fast=False) -> Frame:
    if max_side is not None and (type(max_side) is not int or max_side<1):raise ValueError('미리보기 크기가 잘못되었습니다.')
    from core.render_engine import resize
    def finish(frame):return resize(frame,max_side) if max_side else frame
    path = Path(path)
    if path.suffix.lower() in RAW_EXTS:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            pixels = raw.postprocess(use_camera_wb=True, half_size=bool(fast and max_side and max(raw.sizes.width,raw.sizes.height)>=2*max_side),
                                     no_auto_bright=True, bright=1.0, gamma=(1, 1),
                                     output_bps=16, output_color=rawpy.ColorSpace.sRGB)
        if fast and max_side and max(pixels.shape[:2])>max_side:
            h,w=pixels.shape[:2];ratio=max_side/max(h,w)
            pixels=cv2.resize(pixels,(max(1,round(w*ratio)),max(1,round(h*ratio))),interpolation=cv2.INTER_AREA)
        return finish(_decoded_frame(pixels,linear=True,divisor=65535))
    with Image.open(path) as source:
        if fast and max_side and source.format=='JPEG':source.draft('RGB',(max_side,max_side))
        # Pillow's RGB PNG loader reduces 16-bit to 8-bit: bypass it explicitly.
        with path.open("rb") as stream:
            header = stream.read(26)
        if source.format == "PNG" and not source.info.get("icc_profile") and "srgb" not in source.info:
            gamma = source.info.get("gamma", .45455)
            chroma = source.info.get("chromaticity", (.3127, .329, .64, .33, .3, .6, .15, .06))
            if abs(gamma - .45455) > .0001 or not np.allclose(chroma, (.3127, .329, .64, .33, .3, .6, .15, .06), atol=.0001):
                raise ValueError("이 PNG의 gamma/색도는 지원하지 않습니다. sRGB로 변환하세요.")
        png16 = source.format == "PNG" and len(header) >= 25 and header[24] == 16
        if png16:
            if source.info.get("icc_profile") or ("srgb" not in source.info and "gamma" in source.info
                                                  and abs(source.info["gamma"] - 0.45455) > 0.0001):
                raise ValueError("16비트 PNG의 사용자 색상 프로파일은 아직 지원하지 않습니다.")
            pixels = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if pixels is None or pixels.dtype != np.uint16:
                raise ValueError("16비트 PNG를 읽을 수 없습니다.")
            if pixels.ndim == 2:
                pixels = np.repeat(pixels[..., None], 3, axis=2)
            else:
                pixels = pixels[..., [2, 1, 0, 3] if pixels.shape[2] == 4 else [2, 1, 0]]
            pixels = _orient(pixels, source.getexif().get(274, 1))
            return finish(_decoded_frame(pixels,pixels[...,3].astype(np.float32)/65535 if pixels.shape[2]==4 else None,divisor=65535))
        depths = source.tag_v2.get(258, (8,)) if source.format == "TIFF" else (8,)
        if source.mode in ("I", "F") or source.mode.startswith("I;16") or max(depths) > 8:
            raise ValueError("고정밀 TIFF 등의 입력은 아직 지원하지 않습니다. 16비트 PNG 또는 RAW를 사용하세요.")
        source.load()
        work = ImageOps.exif_transpose(source)
        if fast and max_side:work.thumbnail((max_side,max_side),Image.Resampling.LANCZOS)
        has_alpha = "A" in work.getbands() or "transparency" in work.info
        alpha = np.asarray(work.convert("RGBA"))[..., 3].astype(np.float32) / 255 if has_alpha else None
        profile = work.info.get("icc_profile")
        if profile:
            try:
                source_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile))
                color = work if work.mode in ("RGB", "L", "CMYK", "LAB") else work.convert("L" if work.mode == "LA" else "RGB")
                color = ImageCms.profileToProfile(color, source_profile, ImageCms.createProfile("sRGB"), outputMode="RGB")
            except Exception as error:
                raise ValueError("입력 ICC 프로파일을 sRGB로 변환하지 못했습니다.") from error
        else:
            if work.mode in ("CMYK", "LAB"):
                raise ValueError("이 색상 모드에는 ICC 프로파일이 필요합니다.")
            color = work.convert("RGB")
        return finish(_decoded_frame(np.asarray(color),alpha))


def encode_png(frame: Frame, bits: int = 16) -> bytes:
    pixels = to_pixels(frame, bits)
    pixels = pixels[..., [2, 1, 0, 3] if pixels.shape[2] == 4 else [2, 1, 0]]
    ok, encoded = cv2.imencode(".png", pixels)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    # Explicit standard-sRGB rendering intent; PNG's alpha is straight, linear coverage.
    tag = b"sRGB\x00"
    chunk = struct.pack(">I", 1) + tag + struct.pack(">I", zlib.crc32(tag))
    data = encoded.tobytes()
    return data[:33] + chunk + data[33:]


def export_png(frame: Frame, destination: str | Path, *, bits: int = 16,
               protected_inputs=(), mode: str = "rename") -> str | None:
    if Path(destination).suffix.lower() != ".png":
        raise ValueError("새 엔진 출력은 현재 PNG만 지원합니다.")
    return write_output(encode_png(frame, bits), destination, mode=mode, protected_inputs=protected_inputs)
