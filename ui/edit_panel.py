"""
EditPanel — 파일별 보정 슬라이더 패널 (18개 항목 / 4섹션).
- 더블클릭으로 슬라이더 0 초기화
- 값 클릭 → 숫자 직접 입력
- load/get_adjustments API
"""
import re
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QScrollArea, QLineEdit, QComboBox,
    QInputDialog, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

from core import preset_manager


# ─────────────────────────────────────────────────────────
# 숫자 파싱
# ─────────────────────────────────────────────────────────

def _pnum(s):
    m = re.search(r'[-+]?\d+\.?\d*', str(s))
    return m.group() if m else "0"

_ev_disp  = lambda v: f"{v/10:+.1f} EV"
_ev_parse = lambda s: round(float(_pnum(s)) * 10)
_int_disp = lambda v: f"{v:+d}"
_int_parse= lambda s: int(float(_pnum(s)))
_pos_disp = lambda v: str(v)
_pos_parse= lambda s: int(float(_pnum(s)))
_wb_disp  = lambda v: ("따뜻 +" + str(v) if v > 0 else ("차갑 " + str(v) if v < 0 else "0"))
_wb_parse = lambda s: int(float(_pnum(s)))


# ─────────────────────────────────────────────────────────
# 섹션별 파라미터
# ─────────────────────────────────────────────────────────
# (key, 라벨, min, max, default, display_fn, parse_fn, tooltip)

_LIGHT = [
    ("exposure",   "노출",    -30,  30,   0, _ev_disp,  _ev_parse,
        "사진 전체 밝기를 빛의 양(EV)으로 곱셈 조정.\n"
        "+1 EV = 밝기 2배, -1 EV = 절반. 가장 자연스러운 전체 밝기 조절."),
    ("contrast",   "대비",   -100, 100,   0, _int_disp, _int_parse,
        "밝은 곳은 더 밝게, 어두운 곳은 더 어둡게 — 명암 차이를 키움(+)/줄임(-)."),
]

_COLOR = [
    ("white_balance","색온도", -50,  50,  0, _wb_disp,  _wb_parse,
        "색온도: 차갑게(파랑, -) ←  → 따뜻하게(주황, +). 빛의 색을 보정."),
    ("saturation",  "채도",  -100, 100,  0, _int_disp, _int_parse,
        "모든 색의 채도를 조정. -100은 흑백."),
]

_DETAIL = [
    ("sharpness", "선명도",     0, 100,  0, _pos_disp, _pos_parse,
        "엣지 선명화(UnsharpMask). 윤곽을 또렷하게."),
]

_ALL_SECTIONS = [
    ("빛",     _LIGHT),
    ("색상",   _COLOR),
    ("디테일", _DETAIL),
]

# key → (default, scale_to_adj, scale_from_adj)
# scale_to_adj:   raw int → adj value
# scale_from_adj: adj value → raw int
_KEY_CONV = {
    "exposure":      (0,   lambda r: r/10.0,          lambda v: round(v*10)),
    "contrast":      (0,   lambda r: 1.0+r/100.0,     lambda v: round((v-1.0)*100)),
    "white_balance": (0,   lambda r: int(r),           lambda v: int(v)),
    "saturation":    (0,   lambda r: 1.0+r/100.0,     lambda v: round((v-1.0)*100)),
    "sharpness":     (0,   lambda r: float(r),         lambda v: int(v)),
}


# ─────────────────────────────────────────────────────────
# 더블클릭 리셋 슬라이더
# ─────────────────────────────────────────────────────────

class _AdjSlider(QSlider):
    def __init__(self, orient, default=0, parent=None):
        super().__init__(orient, parent)
        self._default = default
    def mouseDoubleClickEvent(self, e):
        self.setValue(self._default)
        super().mouseDoubleClickEvent(e)


# ─────────────────────────────────────────────────────────
# 클릭 편집 QLineEdit
# ─────────────────────────────────────────────────────────

class _ValueEdit(QLineEdit):
    value_entered = pyqtSignal(str)
    cancelled     = pyqtSignal()
    step_requested = pyqtSignal(int)   # 위/아래 방향키 → +1 / -1 (최소 단위)
    text_live      = pyqtSignal(str)   # 입력 중 즉시 적용용

    _S_DISP = ("QLineEdit{color:#CCCCCC;font-size:11px;font-family:monospace;"
               "background:transparent;border:none;selection-background-color:#D35400;}")
    _S_EDIT = ("QLineEdit{color:#FFF;font-size:11px;font-family:monospace;"
               "background:#252525;border:1px solid #D35400;border-radius:2px;"
               "padding:0 3px;selection-background-color:#D35400;}")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setFrame(False)
        self.setStyleSheet(self._S_DISP)
        self.setCursor(Qt.IBeamCursor)

    def mousePressEvent(self, e):
        if self.isReadOnly():
            self.setReadOnly(False)
            self.setStyleSheet(self._S_EDIT)
            self.selectAll()
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter): self._confirm()
        elif e.key() == Qt.Key_Escape: self._cancel()
        elif e.key() == Qt.Key_Up:   self.step_requested.emit(1)
        elif e.key() == Qt.Key_Down: self.step_requested.emit(-1)
        else:
            super().keyPressEvent(e)
            # 편집 중 입력이 바뀌면 즉시 적용 (엔터/포커스아웃 없이)
            if not self.isReadOnly():
                self.text_live.emit(self.text())

    def focusOutEvent(self, e):
        if not self.isReadOnly(): self._confirm()
        super().focusOutEvent(e)

    def _confirm(self):
        t = self.text()
        self.setReadOnly(True); self.setStyleSheet(self._S_DISP); self.clearFocus()
        self.value_entered.emit(t)

    def _cancel(self):
        self.setReadOnly(True); self.setStyleSheet(self._S_DISP); self.clearFocus()
        self.cancelled.emit()

    def set_display(self, text):
        if self.isReadOnly(): self.setText(text)


# ─────────────────────────────────────────────────────────
# 슬라이더 행
# ─────────────────────────────────────────────────────────

_SL_STYLE = """
    QSlider::groove:horizontal{height:4px;background:#2A2A2A;border-radius:2px;}
    QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;
        background:#D35400;border-radius:6px;}
    QSlider::sub-page:horizontal{background:#D35400;border-radius:2px;}
"""


class _SliderRow(QWidget):
    changed = pyqtSignal()

    def __init__(self, key, label, mn, mx, default, disp_fn, parse_fn, tip="", parent=None):
        super().__init__(parent)
        self.key=key; self.default=default; self.display_fn=disp_fn
        self._parse_fn=parse_fn; self._mn=mn; self._mx=mx

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(6)

        name = QLabel(label)
        name.setFixedWidth(72)
        name.setStyleSheet("color:#999;font-size:11px;")
        if tip: name.setToolTip(tip)

        self.slider = _AdjSlider(Qt.Horizontal, default)
        self.slider.setRange(mn, mx)
        self.slider.setValue(default)
        self.slider.setStyleSheet(_SL_STYLE)
        self.slider.setToolTip("더블클릭 → 0 초기화" + (f"\n{tip}" if tip else ""))

        self.val_edit = _ValueEdit()
        self.val_edit.setFixedWidth(70)
        self.val_edit.setText(disp_fn(default))
        self.val_edit.setToolTip("클릭하여 숫자 직접 입력\n위/아래 방향키 → 한 칸씩 조절 (즉시 적용)")

        lay.addWidget(name)
        lay.addWidget(self.slider, stretch=1)
        lay.addWidget(self.val_edit)

        self.slider.valueChanged.connect(self._on_slide)
        self.val_edit.value_entered.connect(self._on_text)
        self.val_edit.cancelled.connect(self._restore)
        self.val_edit.text_live.connect(self._on_text_live)      # 입력 중 즉시 적용
        self.val_edit.step_requested.connect(self._on_step)      # 방향키 ±1

    def _on_slide(self, v):
        self.val_edit.set_display(self.display_fn(v))
        self.changed.emit()

    def _on_text(self, text):
        try:
            raw = max(self._mn, min(self._mx, self._parse_fn(text)))
            self.slider.setValue(raw)
        except Exception:
            self._restore()

    def _on_text_live(self, text):
        """편집 중 유효한 숫자가 들어오면 즉시 슬라이더에 반영(텍스트는 그대로 둠)."""
        try:
            raw = max(self._mn, min(self._mx, self._parse_fn(text)))
        except Exception:
            return
        self.slider.setValue(raw)   # valueChanged → _on_slide → changed.emit (라이브 미리보기)

    def _on_step(self, delta: int):
        """위/아래 방향키 → 최소 단위(슬라이더 1칸)씩 이동하고 즉시 적용."""
        step = max(1, self.slider.singleStep())
        new = max(self._mn, min(self._mx, self.slider.value() + delta * step))
        self.slider.setValue(new)
        # 편집 중(읽기전용 아님)이면 set_display가 막히므로 텍스트도 직접 갱신
        self.val_edit.setText(self.display_fn(new))

    def _restore(self):
        self.val_edit.set_display(self.display_fn(self.slider.value()))

    def reset(self): self.slider.setValue(self.default)
    def set_raw(self, v): self.slider.setValue(int(v))
    def value(self): return self.slider.value()
    def is_default(self): return self.slider.value() == self.default


# ─────────────────────────────────────────────────────────
# 섹션 헤더
# ─────────────────────────────────────────────────────────

def _section_hdr(title):
    w = QWidget()
    lay = QHBoxLayout(w); lay.setContentsMargins(0, 8, 0, 2)
    lbl = QLabel(title)
    lbl.setStyleSheet("color:#D35400;font-size:10px;font-weight:bold;letter-spacing:1px;")
    line = QWidget(); line.setFixedHeight(1); line.setStyleSheet("background:#2A2A2A;")
    lay.addWidget(lbl); lay.addWidget(line, stretch=1)
    return w


# ─────────────────────────────────────────────────────────
# EditPanel
# ─────────────────────────────────────────────────────────

class EditPanel(QWidget):
    adjustments_changed = pyqtSignal()
    back_requested      = pyqtSignal()
    preview_compare     = pyqtSignal(bool)   # True=원본, False=보정 후
    apply_to_all        = pyqtSignal(dict)   # 전체 파일에 보정값 일괄 적용

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[str, _SliderRow] = {}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)

        # 상단 바
        top = QWidget(); top.setFixedHeight(36)
        top.setStyleSheet("background:#161616;border-bottom:1px solid #222;")
        tl = QHBoxLayout(top); tl.setContentsMargins(6,0,8,0); tl.setSpacing(6)
        back = QPushButton("← 옵션"); back.setFixedHeight(24)
        back.setStyleSheet("""QPushButton{background:transparent;color:#777;
            border:1px solid #333;border-radius:3px;font-size:11px;padding:0 8px;}
            QPushButton:hover{color:#D35400;border-color:#D35400;}""")
        back.clicked.connect(self.back_requested)

        # 보정 전/후 비교 버튼
        self._compare_btn = QPushButton("◐  원본 보기")
        self._compare_btn.setCheckable(True)
        self._compare_btn.setFixedHeight(24)
        self._compare_btn.setStyleSheet("""
            QPushButton {
                background:transparent; color:#555;
                border:1px solid #2E2E2E; border-radius:3px;
                font-size:10px; padding:0 7px;
            }
            QPushButton:hover { color:#CCCCCC; border-color:#555; }
            QPushButton:checked {
                background:#1C1C1C; color:#D35400;
                border:1px solid #D35400; font-weight:bold;
            }
        """)
        self._compare_btn.setToolTip("클릭: 보정 전 원본 보기 (토글)")
        self._compare_btn.toggled.connect(self._on_compare_toggled)

        self._fname = QLabel("")
        self._fname.setStyleSheet("color:#D35400;font-size:11px;font-weight:bold;")
        self._fname.setMaximumWidth(160)

        tl.addWidget(back)
        tl.addSpacing(4)
        tl.addWidget(self._compare_btn)
        tl.addStretch()
        tl.addWidget(self._fname)
        outer.addWidget(top)

        # ── 프리셋 바 ────────────────────────────────────────
        preset_bar = QWidget(); preset_bar.setFixedHeight(32)
        preset_bar.setStyleSheet("background:#141414;border-bottom:1px solid #1E1E1E;")
        pb_lay = QHBoxLayout(preset_bar)
        pb_lay.setContentsMargins(6, 3, 6, 3); pb_lay.setSpacing(4)

        lbl_p = QLabel("프리셋")
        lbl_p.setStyleSheet("color:#555;font-size:10px;"); lbl_p.setFixedWidth(34)
        pb_lay.addWidget(lbl_p)

        self._preset_combo = QComboBox()
        self._preset_combo.setFixedHeight(22)
        self._preset_combo.setStyleSheet("""
            QComboBox{background:#1C1C1C;color:#AAA;border:1px solid #333;
                border-radius:3px;font-size:10px;padding:0 4px;}
            QComboBox::drop-down{border:none;width:14px;}
            QComboBox QAbstractItemView{background:#1C1C1C;color:#AAA;
                selection-background-color:#D35400;}
        """)
        self._preset_combo.setToolTip("저장된 프리셋 선택 → 슬라이더 자동 적용")
        self._preset_combo.activated.connect(self._on_preset_selected)
        pb_lay.addWidget(self._preset_combo, stretch=1)

        _pb_btn_style = """QPushButton{background:#1A1A1A;color:#888;
            border:1px solid #2E2E2E;border-radius:3px;font-size:10px;padding:0 6px;}
            QPushButton:hover{color:#D35400;border-color:#D35400;}"""

        save_p_btn = QPushButton("저장")
        save_p_btn.setFixedSize(36, 22)
        save_p_btn.setStyleSheet(_pb_btn_style)
        save_p_btn.setToolTip("현재 보정값을 프리셋으로 저장")
        save_p_btn.clicked.connect(self._save_preset)
        pb_lay.addWidget(save_p_btn)

        del_p_btn = QPushButton("삭제")
        del_p_btn.setFixedSize(36, 22)
        del_p_btn.setStyleSheet(_pb_btn_style)
        del_p_btn.setToolTip("선택한 프리셋 삭제")
        del_p_btn.clicked.connect(self._delete_preset)
        pb_lay.addWidget(del_p_btn)

        apply_all_btn = QPushButton("전체 적용")
        apply_all_btn.setFixedSize(58, 22)
        apply_all_btn.setStyleSheet("""QPushButton{background:#1A1A1A;color:#D35400;
            border:1px solid #3A1500;border-radius:3px;font-size:10px;padding:0 4px;}
            QPushButton:hover{background:#2A0D00;border-color:#D35400;}""")
        apply_all_btn.setToolTip("현재 보정값을 목록의 모든 파일에 적용")
        apply_all_btn.clicked.connect(self._emit_apply_to_all)
        pb_lay.addWidget(apply_all_btn)

        outer.addWidget(preset_bar)
        self._refresh_presets()

        # 스크롤
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""QScrollArea{border:none;background:#111;}
            QScrollBar:vertical{background:#111;width:6px;border-radius:3px;}
            QScrollBar::handle:vertical{background:#333;border-radius:3px;min-height:20px;}
            QScrollBar::handle:vertical:hover{background:#D35400;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}""")

        content = QWidget(); content.setStyleSheet("background:#111;")
        inner = QVBoxLayout(content); inner.setContentsMargins(10,4,10,10); inner.setSpacing(1)

        hint = QLabel("슬라이더 더블클릭 → 0 초기화  |  값 클릭 → 직접 입력")
        hint.setStyleSheet("color:#333;font-size:10px;"); inner.addWidget(hint)

        for sec_title, params in _ALL_SECTIONS:
            inner.addWidget(_section_hdr(sec_title))
            for key, label, mn, mx, default, dfn, pfn, tip in params:
                row = _SliderRow(key, label, mn, mx, default, dfn, pfn, tip)
                row.changed.connect(self.adjustments_changed)
                self._rows[key] = row
                inner.addWidget(row)

        inner.addSpacing(8)
        sep = QWidget(); sep.setFixedHeight(1); sep.setStyleSheet("background:#1E1E1E;")
        inner.addWidget(sep); inner.addSpacing(4)

        rst = QPushButton("모두 초기화"); rst.setFixedHeight(26)
        rst.setStyleSheet("""QPushButton{background:transparent;color:#444;
            border:1px solid #2A2A2A;border-radius:3px;font-size:11px;}
            QPushButton:hover{color:#D35400;border-color:#D35400;}""")
        rst.clicked.connect(self.reset_all)
        inner.addWidget(rst); inner.addStretch()

        scroll.setWidget(content); outer.addWidget(scroll)

    # ── 공개 API ─────────────────────────────────────────

    def _on_compare_toggled(self, checked: bool):
        if checked:
            self._compare_btn.setText("◑  보정 후 보기")
        else:
            self._compare_btn.setText("◐  원본 보기")
        self.preview_compare.emit(checked)

    def reset_compare(self):
        """compare 버튼을 기본 상태(보정 후)로 초기화."""
        self._compare_btn.blockSignals(True)
        self._compare_btn.setChecked(False)
        self._compare_btn.setText("◐  원본 보기")
        self._compare_btn.blockSignals(False)

    def load(self, path: str, adj: dict):
        name = Path(path).name
        if len(name) > 26: name = name[:23] + "…"
        self._fname.setText(name)
        self.reset_compare()                    # 파일 전환 시 compare 상태 초기화
        for row in self._rows.values():
            row.slider.blockSignals(True)
        self._load_values(adj)
        for row in self._rows.values():
            row.slider.blockSignals(False)
            row.val_edit.set_display(row.display_fn(row.slider.value()))

    def _load_values(self, adj: dict):
        for key, (raw_default, _, from_adj) in _KEY_CONV.items():
            if key not in self._rows:
                continue
            if key in adj:
                # adj 값을 raw 슬라이더 값으로 역변환
                try:
                    self._rows[key].set_raw(from_adj(adj[key]))
                except Exception:
                    self._rows[key].set_raw(raw_default)
            else:
                # adj에 없으면 기본값(슬라이더 0)으로 설정
                self._rows[key].set_raw(raw_default)

    def get_adjustments(self) -> dict:
        if self.is_default():
            return {}
        result = {}
        for key, (default, to_adj, _) in _KEY_CONV.items():
            if key in self._rows:
                raw = self._rows[key].value()
                val = to_adj(raw)
                # only include non-default values
                adj_default = to_adj(default)
                if val != adj_default:
                    result[key] = val
        return result

    def is_default(self) -> bool:
        return all(r.is_default() for r in self._rows.values())

    def reset_all(self):
        self.reset_compare()                    # 초기화 시 compare도 해제
        for r in self._rows.values(): r.slider.blockSignals(True)
        for r in self._rows.values(): r.reset()
        for r in self._rows.values():
            r.slider.blockSignals(False)
            r.val_edit.set_display(r.display_fn(r.default))
        self.adjustments_changed.emit()

    # ── 프리셋 ───────────────────────────────────────────────

    def _refresh_presets(self):
        """저장된 프리셋 목록으로 콤보박스 갱신."""
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        names = preset_manager.list_presets()
        if names:
            self._preset_combo.addItems(names)
        else:
            self._preset_combo.addItem("(저장된 프리셋 없음)")
        self._preset_combo.blockSignals(False)

    def _on_preset_selected(self, index: int):
        """콤보 선택 → 프리셋 슬라이더 자동 적용."""
        name = self._preset_combo.itemText(index)
        if not name or name.startswith("("):
            return
        try:
            adj = preset_manager.load_preset(name)
            self._apply_preset_values(adj)
        except Exception as e:
            QMessageBox.warning(self, "프리셋 오류", f"프리셋을 불러오지 못했습니다:\n{e}")

    def _apply_preset_values(self, adj: dict):
        """adj 딕셔너리를 슬라이더에 반영 + adjustments_changed 발생."""
        for row in self._rows.values():
            row.slider.blockSignals(True)
        self._load_values(adj)
        for row in self._rows.values():
            row.slider.blockSignals(False)
            row.val_edit.set_display(row.display_fn(row.slider.value()))
        self.adjustments_changed.emit()

    def _save_preset(self):
        """현재 보정값을 이름 지정해 프리셋으로 저장."""
        adj = self.get_adjustments()
        if not adj:
            QMessageBox.information(self, "프리셋 저장",
                "모든 보정값이 기본값입니다.\n값을 조정한 뒤 저장하세요.")
            return
        # 현재 콤보 선택명을 기본값으로 제안
        current = self._preset_combo.currentText()
        default_name = "" if current.startswith("(") else current

        name, ok = QInputDialog.getText(
            self, "프리셋 저장", "프리셋 이름을 입력하세요:", text=default_name
        )
        if not ok or not name.strip():
            return
        try:
            preset_manager.save_preset(name.strip(), adj)
            self._refresh_presets()
            # 방금 저장한 프리셋 선택
            idx = self._preset_combo.findText(name.strip())
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)
        except Exception as e:
            QMessageBox.warning(self, "저장 실패", str(e))

    def _delete_preset(self):
        """콤보에서 선택된 프리셋 삭제."""
        name = self._preset_combo.currentText()
        if not name or name.startswith("("):
            return
        reply = QMessageBox.question(
            self, "프리셋 삭제", f"'{name}' 프리셋을 삭제하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            preset_manager.delete_preset(name)
            self._refresh_presets()

    def _emit_apply_to_all(self):
        """현재 보정값을 모든 파일에 적용 시그널 발생."""
        self.apply_to_all.emit(self.get_adjustments())
