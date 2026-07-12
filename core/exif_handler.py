import io
import piexif


def get_exif_bytes(src_path: str, remove_gps: bool = False):
    """
    Load EXIF from src_path and return piexif-dumped bytes.
    Returns None if EXIF cannot be loaded.
    """
    try:
        exif_dict = piexif.load(src_path)
    except Exception:
        return None

    if remove_gps:
        exif_dict['GPS'] = {}

    try:
        return piexif.dump(exif_dict)
    except Exception:
        return None


def embed_exif(jpeg_bytes: bytes, exif_bytes: bytes) -> bytes:
    """Insert exif_bytes into a JPEG byte string. Returns original on failure."""
    try:
        out = io.BytesIO()
        piexif.insert(exif_bytes, jpeg_bytes, out)
        return out.getvalue()
    except Exception:
        return jpeg_bytes


def force_dpi(jpeg_bytes: bytes, dpi: int) -> bytes:
    """JPEG의 EXIF 해상도(XResolution/YResolution)를 dpi로 설정. 실패 시 원본 반환.

    포토샵 등은 JFIF density보다 EXIF 해상도를 우선 읽는 경우가 많아, 인쇄 크기를
    정확히 맞추려면 EXIF 해상도도 함께 설정해야 한다.
    """
    if not dpi or dpi <= 0:
        return jpeg_bytes
    try:
        try:
            ex = piexif.load(jpeg_bytes)
        except Exception:
            ex = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        ex.setdefault("0th", {})
        ex["0th"][piexif.ImageIFD.XResolution]   = (int(dpi), 1)
        ex["0th"][piexif.ImageIFD.YResolution]   = (int(dpi), 1)
        ex["0th"][piexif.ImageIFD.ResolutionUnit] = 2  # 2 = inch
        out = io.BytesIO()
        piexif.insert(piexif.dump(ex), jpeg_bytes, out)
        return out.getvalue()
    except Exception:
        return jpeg_bytes


def copy_exif(src_path: str, img_bytes: bytes,
              remove_gps: bool = False, remove_all: bool = False) -> bytes:
    """High-level: copy EXIF from src_path into jpeg img_bytes."""
    if remove_all:
        return img_bytes

    exif_bytes = get_exif_bytes(src_path, remove_gps=remove_gps)
    if exif_bytes is None:
        return img_bytes

    return embed_exif(img_bytes, exif_bytes)
