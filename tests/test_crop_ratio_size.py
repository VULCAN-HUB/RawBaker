"""_ratio_target_size 순수 함수 검증 (Qt 위젯 비의존 — headless 안전)."""
from ui.options_panel import _ratio_target_size


def test_src_and_free_return_original():
    assert _ratio_target_size(None, 6000, 4000) == (6000, 4000)
    assert _ratio_target_size("src", 6000, 4000) == (6000, 4000)


def test_unknown_size_returns_zero():
    # 원본 크기를 모르면 (0,0) — 호출측이 현재 값을 유지해 1×1 붕괴를 막는다
    assert _ratio_target_size("src", 0, 0) == (0, 0)
    assert _ratio_target_size((3, 2), 0, 0) == (0, 0)
    assert _ratio_target_size((1, 1), -5, 100) == (0, 0)


def test_square_fits_inside_landscape():
    tw, th = _ratio_target_size((1, 1), 6000, 4000)
    assert tw == th
    assert tw <= 6000 and th <= 4000


def test_3_2_on_landscape_source():
    # 3:2 비율, 가로 원본 → 가로 폭 유지
    assert _ratio_target_size((3, 2), 6000, 4000) == (6000, 4000)


def test_16_9_fits_inside():
    tw, th = _ratio_target_size((16, 9), 6000, 4000)
    assert abs(tw / th - 16 / 9) < 0.01
    assert tw <= 6000 and th <= 4000


def test_portrait_source():
    tw, th = _ratio_target_size((16, 9), 4000, 6000)
    assert tw <= 4000 and th <= 6000
    assert abs(tw / th - 16 / 9) < 0.01
