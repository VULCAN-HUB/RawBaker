"""제거된 키(예: vignette, hue)가 없는 보정 dict 로도 파이프라인이 동작하는지,
그리고 5종 키만 있는 dict 가 정상 적용되는지 검증.

보정 슬라이더는 18종 → 5종(exposure/contrast/white_balance/saturation/sharpness)으로
줄었지만, apply_adjustments/build_pipeline 은 adjustments.get(key, default) 로
누락 키를 안전 처리하므로 부분 dict 로도 KeyError 없이 동작해야 한다.
"""
from PIL import Image

from core.pipeline import apply_adjustments, build_pipeline


def _img():
    return Image.new("RGB", (32, 24), (120, 120, 120))


def test_apply_with_five_keys_only():
    adj = {"exposure": 1.0, "contrast": 20, "white_balance": 10,
           "saturation": 15, "sharpness": 30}
    out = apply_adjustments(_img(), adj)
    assert out.size == (32, 24)
    assert out.mode == "RGB"


def test_apply_with_empty_dict():
    out = apply_adjustments(_img(), {})
    assert out.size == (32, 24)


def test_build_pipeline_runs_with_five_keys():
    adj = {"exposure": 0.5, "contrast": -10, "white_balance": -5,
           "saturation": 8, "sharpness": 12}
    p = build_pipeline("JPEG", "original", 0, 0, adj)
    out = p.run(_img())
    assert out.size == (32, 24)
