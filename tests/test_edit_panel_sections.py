"""EditPanel 이 핵심 5종만 노출하는지 검증.

EditPanel(QWidget) 인스턴스화는 QApplication 이 필요해 headless 환경에서 막힌다.
하지만 패널의 슬라이더 행(self._rows)은 모듈 수준 _ALL_SECTIONS 에서 1:1로 생성되므로,
위젯을 만들지 않고 _ALL_SECTIONS · _KEY_CONV 데이터만 검사해 동일한 계약을 검증한다.
(실제 위젯 생성 검증은 실기기 GUI 테스트에서 수행)
"""
import ui.edit_panel as edit_panel


EXPECTED_KEYS = {"exposure", "contrast", "white_balance", "saturation", "sharpness"}


def _section_keys():
    """_ALL_SECTIONS 의 모든 항목 key 집합 — EditPanel._rows 키와 동일하게 생성됨."""
    return {item[0] for _title, params in edit_panel._ALL_SECTIONS for item in params}


def test_sections_yield_five_keys():
    # _build_ui 는 각 섹션 항목마다 _SliderRow 를 만들어 self._rows[key] 에 넣으므로,
    # 섹션이 내놓는 key 집합이 곧 패널이 노출하는 슬라이더다.
    assert _section_keys() == EXPECTED_KEYS


def test_effects_section_removed():
    titles = [t for t, _ in edit_panel._ALL_SECTIONS]
    assert "효과" not in titles


def test_key_conv_matches_rows():
    assert set(edit_panel._KEY_CONV.keys()) == EXPECTED_KEYS
