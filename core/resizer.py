from PIL import Image


def centered_aspect_rect(size, aspect: float):
    """이미지 크기(size=(w,h))에서 주어진 가로:세로 비율(aspect=w/h)의
    최대 영역을 중앙에 배치한 정규화 사각형 (nx, ny, nw, nh) 반환 (각 0~1)."""
    ow, oh = size
    if ow <= 0 or oh <= 0 or aspect <= 0:
        return (0.0, 0.0, 1.0, 1.0)
    src_ar = ow / oh
    if src_ar > aspect:
        # 원본이 더 넓음 → 가로를 줄임
        nw = aspect / src_ar
        return ((1.0 - nw) / 2.0, 0.0, nw, 1.0)
    else:
        nh = src_ar / aspect
        return (0.0, (1.0 - nh) / 2.0, 1.0, nh)


def crop_normalized(img: Image.Image, nx: float, ny: float, nw: float, nh: float,
                    tw: int = 0, th: int = 0) -> Image.Image:
    """
    정규화 좌표(0~1)로 지정한 영역을 잘라낸다. tw/th 가 주어지면 그 픽셀 크기로 리사이즈.
    - nx,ny: 좌상단 위치(이미지 비율), nw,nh: 너비·높이(이미지 비율)
    - 좌표는 이미지 경계 안으로 클램프된다.
    """
    ow, oh = img.size
    if ow <= 0 or oh <= 0:
        return img
    x = int(round(max(0.0, min(1.0, nx)) * ow))
    y = int(round(max(0.0, min(1.0, ny)) * oh))
    w = int(round(max(0.0, min(1.0, nw)) * ow))
    h = int(round(max(0.0, min(1.0, nh)) * oh))
    w = max(1, min(ow - x, w))
    h = max(1, min(oh - y, h))
    cropped = img.crop((x, y, x + w, y + h))
    if tw and th and tw > 0 and th > 0:
        cropped = cropped.resize((int(tw), int(th)), Image.LANCZOS)
    return cropped


def crop_to_size(img: Image.Image, tw: int, th: int, v_offset: float = 0.0) -> Image.Image:
    """
    사진 안에서 목표 비율(tw:th)로 중앙 크롭한 뒤 정확히 tw×th 픽셀로 리사이즈.

    - 왜곡 없음(비율 맞춰 가장자리만 잘라냄).
    - 세로로 잘릴 때(원본이 목표보다 세로로 긴 경우) v_offset 으로 크롭 위치 조절:
        v_offset = 0.0  → 가운데, -1.0 → 맨 위, +1.0 → 맨 아래.
      가로로 잘릴 때(원본이 더 넓은 경우)는 세로가 그대로라 v_offset 영향 없음(가로 중앙).
    """
    tw = max(1, int(tw)); th = max(1, int(th))
    ow, oh = img.size
    if ow <= 0 or oh <= 0:
        return img.resize((tw, th), Image.LANCZOS)

    target_ar = tw / th
    src_ar = ow / oh

    if src_ar > target_ar:
        # 원본이 더 넓음 → 가로를 잘라냄(세로 full, 가로 중앙)
        nw = max(1, int(round(oh * target_ar)))
        x = (ow - nw) // 2
        box = (x, 0, x + nw, oh)
    else:
        # 원본이 더 길거나 같음 → 세로를 잘라냄(v_offset 적용)
        nh = max(1, int(round(ow / target_ar)))
        max_y = max(0, oh - nh)
        center_y = max_y / 2.0
        v = max(-1.0, min(1.0, v_offset))
        y = int(round(center_y + v * center_y))
        y = max(0, min(max_y, y))
        box = (0, y, ow, y + nh)

    return img.crop(box).resize((tw, th), Image.LANCZOS)


PRESETS = {
    "original": 1.0,
    "75%": 0.75,
    "50%": 0.50,
    "25%": 0.25,
}


def resize_image(img: Image.Image, mode: str, custom_w: int = 0, custom_h: int = 0) -> Image.Image:
    if mode == "original":
        return img

    orig_w, orig_h = img.size

    if mode in PRESETS:
        scale = PRESETS[mode]
        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))
    elif isinstance(mode, str) and mode.endswith("%"):
        # 임의 퍼센트 스케일 (예: "10%", "30%") — 슬라이더 입력
        try:
            pct = float(mode[:-1])
        except ValueError:
            return img
        if pct <= 0 or pct >= 100:
            return img  # 0% 이하·100% 이상은 원본 유지
        scale = pct / 100.0
        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))
    elif mode == "custom":
        if custom_w > 0 and custom_h > 0:
            new_w, new_h = custom_w, custom_h
        elif custom_w > 0:
            scale = custom_w / orig_w
            new_w = custom_w
            new_h = max(1, int(orig_h * scale))
        elif custom_h > 0:
            scale = custom_h / orig_h
            new_h = custom_h
            new_w = max(1, int(orig_w * scale))
        else:
            return img
    else:
        return img

    return img.resize((new_w, new_h), Image.LANCZOS)
