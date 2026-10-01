"""Serializable editing contract shared by the studio, project validator and renderer."""
from __future__ import annotations
from copy import deepcopy
import math

from core.render_engine import Adjustments

BANDS = ("red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta")
GLOBAL_KEYS = set(Adjustments.__dataclass_fields__)
EXTRA_KEYS = {"colors", "masks", "retouch", "crop", "rotation"}


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("편집 값의 범위가 잘못되었습니다.")


def point(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("좌표가 잘못되었습니다.")
    for v in value:
        number(v, 0, 1)


def validate_mask(mask):
    if not isinstance(mask, dict) or set(mask) != {"kind", "points", "radius", "feather", "invert"}:
        raise ValueError("마스크 형식이 잘못되었습니다.")
    if mask["kind"] not in ("brush", "linear", "radial") or type(mask["invert"]) is not bool:
        raise ValueError("마스크 종류가 잘못되었습니다.")
    if not isinstance(mask["points"], list) or not 1 <= len(mask["points"]) <= 20000:
        raise ValueError("마스크 좌표 수가 잘못되었습니다.")
    if mask["kind"] != "brush" and len(mask["points"]) != 2:
        raise ValueError("선형/원형 마스크는 두 좌표가 필요합니다.")
    for p in mask["points"]:
        point(p)
    number(mask["radius"], .001, 1)
    number(mask["feather"], .001, 1)


def validate_edit(edit):
    if not isinstance(edit, dict) or set(edit) - GLOBAL_KEYS - EXTRA_KEYS:
        raise ValueError("지원하지 않는 보정 항목입니다.")
    Adjustments(**{k: v for k, v in edit.items() if k in GLOBAL_KEYS})
    colors = edit.get("colors", {})
    if not isinstance(colors, dict) or set(colors) - set(BANDS):
        raise ValueError("색상별 보정이 잘못되었습니다.")
    for value in colors.values():
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError("색조/채도/밝기가 필요합니다.")
        for v in value:
            number(v, -100, 100)
    masks = edit.get("masks", [])
    if not isinstance(masks, list) or len(masks) > 100:
        raise ValueError("부분 보정 수가 너무 많습니다.")
    for item in masks:
        if set(item) != {"mask", "adjustments"}:
            raise ValueError("부분 보정 형식이 잘못되었습니다.")
        validate_mask(item["mask"])
        Adjustments(**item["adjustments"])
    retouch = edit.get("retouch", [])
    if not isinstance(retouch, list) or len(retouch) > 1000:
        raise ValueError("리터칭 수가 너무 많습니다.")
    for item in retouch:
        if set(item) != {"kind", "source", "target", "radius"} or item["kind"] not in ("clone", "heal"):
            raise ValueError("리터칭 형식이 잘못되었습니다.")
        point(item["source"])
        point(item["target"])
        number(item["radius"], .001, .5)
    crop = edit.get("crop", [0, 0, 1, 1])
    if not isinstance(crop, (list, tuple)) or len(crop) != 4:
        raise ValueError("자르기 좌표가 잘못되었습니다.")
    for v in crop:
        number(v, 0, 1)
    x, y, w, h = crop
    if min(w, h) <= 0 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError("자르기 범위가 사진을 벗어났습니다.")
    if edit.get("rotation", 0) not in (0, 90, 180, 270):
        raise ValueError("회전은 90도 단위입니다.")


def globals_only(edit):
    return {k: deepcopy(v) for k, v in edit.items() if k in GLOBAL_KEYS or k == "colors"}


def validate_layer(layer, photos):
    if set(layer) == {"photo_id"}:  # Original project documents remain readable.
        if layer["photo_id"] not in photos:
            raise ValueError("레이어 사진이 없습니다.")
        return
    required = {"id", "kind", "name", "x", "y", "width", "height", "rotation", "opacity", "visible", "locked", "mask", "data"}
    if not required <= set(layer) or set(layer)-required-{'blend_mode','group_id','clipped','content_size','flip_x','flip_y','warp'} or layer["kind"] not in ("photo", "text", "rectangle", "ellipse", "adjustment"):
        raise ValueError("레이어 형식이 잘못되었습니다.")
    if 'warp' in layer:
        from core.layer_geometry import validate_warp
        validate_warp(layer)
    for key in ('flip_x','flip_y'):
        if key in layer and type(layer[key]) is not bool:raise ValueError('뒤집기 상태가 잘못되었습니다.')
    if 'content_size' in layer:
        if layer['kind'] not in ('photo','text') or type(layer['content_size']) is not list or len(layer['content_size'])!=2:raise ValueError('원본 배치 크기가 잘못되었습니다.')
        for value in layer['content_size']:number(value,.1,100000)
    if layer['kind']=='adjustment' and (layer.get('flip_x') or layer.get('flip_y')):raise ValueError('조정 레이어는 뒤집을 수 없습니다.')
    if 'group_id' in layer and (type(layer['group_id']) is not str or not layer['group_id']):raise ValueError('그룹 ID가 잘못되었습니다.')
    if 'clipped' in layer and type(layer['clipped']) is not bool:raise ValueError('클리핑 상태가 잘못되었습니다.')
    from core.layer_blend import BLEND_MODES
    if layer.get('blend_mode','normal') not in BLEND_MODES:
        raise ValueError('지원하지 않는 혼합 모드입니다.')
    if not isinstance(layer["id"], str) or not layer["id"] or not isinstance(layer["name"], str):
        raise ValueError("레이어 이름이 잘못되었습니다.")
    for key in ("x", "y"):
        number(layer[key], -100000, 100000)
    for key in ("width", "height"):
        number(layer[key], .1, 100000)
    number(layer["rotation"], -360, 360)
    number(layer["opacity"], 0, 1)
    if any(type(layer[k]) is not bool for k in ("visible", "locked")):
        raise ValueError("레이어 상태가 잘못되었습니다.")
    if layer["mask"] is not None:
        from core.layer_masks import validate_layer_mask
        validate_layer_mask(layer["mask"])
    data = layer["data"]
    if layer['kind']=='adjustment':
        if set(data)!={'adjustments'}:raise ValueError('조정 레이어 형식이 잘못되었습니다.')
        validate_edit(data['adjustments'])
        if set(data['adjustments'])-GLOBAL_KEYS-{'colors'}:raise ValueError('조정 레이어는 색/톤 조정만 지원합니다.')
        if layer.get('clipped') or layer.get('blend_mode','normal')!='normal' or layer['rotation']!=0:raise ValueError('조정 레이어는 표준 모드·회전 없음·클리핑 없음만 지원합니다.')
    elif layer["kind"] == "photo":
        if set(data) != {"photo_id"} or data["photo_id"] not in photos:
            raise ValueError("레이어 사진이 없습니다.")
    elif layer["kind"] == "text":
        if set(data) != {"text", "font", "size", "color"} or not isinstance(data["text"], str) or len(data["text"]) > 20000 or not isinstance(data["font"], str):
            raise ValueError("텍스트 형식이 잘못되었습니다.")
        number(data["size"], 1, 10000)
        color(data["color"])
    else:
        if set(data) != {"color"}:
            raise ValueError("도형 형식이 잘못되었습니다.")
        color(data["color"])


def color(value):
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        raise ValueError("색상은 #RRGGBB 형식이어야 합니다.")
    int(value[1:], 16)
