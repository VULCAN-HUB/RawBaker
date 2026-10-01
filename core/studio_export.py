"""Color-managed photo/document export with normalized EXIF and protected inputs."""
from __future__ import annotations
import io
from pathlib import Path
import struct
import zlib
import piexif
import numpy as np
from PIL import Image, ImageCms

from core.render_engine import Frame, resize, to_pixels
from core.render_io import encode_png
from core.safe_output import write_output


def _chunk(kind, data):
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def encode_export(frame, *, format="PNG", quality=95, bits=16, dpi=300, metadata="remove_all", source=None):
    format = format.upper()
    if format not in ("PNG", "JPEG", "TIFF", "WEBP") or metadata not in ("keep", "remove_gps", "remove_all"):
        raise ValueError("출력 설정이 잘못되었습니다.")
    if not 1 <= quality <= 100 or not 1 <= dpi <= 9600 or bits not in (8, 16):
        raise ValueError("품질/DPI/비트 설정이 잘못되었습니다.")
    exif = None
    if source and metadata != "remove_all":
        try:
            ex = piexif.load(str(source))
        except (ValueError, OSError, piexif.InvalidImageDataError):
            try:
                with Image.open(source) as original:
                    exif_bytes = original.info.get("exif") or original.getexif().tobytes()
                ex = piexif.load(exif_bytes) if exif_bytes else None
            except (ValueError, OSError, piexif.InvalidImageDataError):
                ex = None
        if ex:
            ex["0th"][piexif.ImageIFD.Orientation] = 1
            for key in (piexif.ImageIFD.ImageWidth, piexif.ImageIFD.ImageLength):
                ex["0th"].pop(key, None)
            ex["Exif"][piexif.ExifIFD.PixelXDimension] = frame.rgb.shape[1]
            ex["Exif"][piexif.ExifIFD.PixelYDimension] = frame.rgb.shape[0]
            ex["Exif"][piexif.ExifIFD.ColorSpace] = 1
            ex["0th"][piexif.ImageIFD.XResolution] = (dpi, 1)
            ex["0th"][piexif.ImageIFD.YResolution] = (dpi, 1)
            ex["0th"][piexif.ImageIFD.ResolutionUnit] = 2
            ex["1st"], ex["thumbnail"] = {}, None
            if metadata == "remove_gps":
                ex["GPS"] = {}
            exif = piexif.dump(ex)
    if format == "PNG":
        data = encode_png(frame, bits)
        density = round(dpi/0.0254)
        extra = _chunk(b"pHYs", struct.pack(">IIB", density, density, 1))
        if exif:
            extra += _chunk(b"eXIf", exif[6:])
        return data[:33] + extra + data[33:]
    if format == "JPEG" and frame.alpha is not None:
        frame = Frame(frame.rgb*frame.alpha[..., None] + (1-frame.alpha[..., None]))
    image = Image.fromarray(to_pixels(frame, 8))
    options = dict(icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    if format in ("JPEG", "WEBP"):
        options["quality"] = quality
    if format in ("JPEG", "TIFF"):
        options["dpi"] = (dpi, dpi)
    if exif:
        options["exif"] = exif
    output = io.BytesIO()
    image.save(output, format=format, **options)
    return output.getvalue()


def export_image(frame, destination, *, protected_inputs=(), protected_hashes=(), collision="rename", max_side=None, **options):
    if max_side:
        frame = resize(frame, max_side)
    return write_output(encode_export(frame, **options), destination, protected_inputs=protected_inputs, protected_hashes=protected_hashes, mode=collision)
