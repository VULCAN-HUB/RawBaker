from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QCheckBox, QLineEdit, QPushButton, QSlider,
    QGroupBox, QRadioButton, QButtonGroup, QFileDialog, QScrollArea,
)
from PyQt5.QtCore import Qt, pyqtSignal


FORMATS = ["JPEG", "PNG", "TIFF", "WebP", "BMP"]


def _ratio_target_size(ratio, orig_w, orig_h):
    """크롭 출력 픽셀 크기 (tw, th) 계산 — 순수 함수(위젯 비의존, 테스트 가능).

    ratio: None(자유) | "src"(원본 비율) | (rw, rh)(고정 비율)
    자유/원본비율 → 원본 크기 그대로. 고정 비율 → 원본 안에 맞는 최대 정수 크기(업스케일 회피).
    원본 크기를 모르면(0 이하) (0, 0)을 반환 — 호출측이 현재 값을 유지하도록 한다
    (0,0 으로 깎아 1×1 로 붕괴되는 것을 방지)."""
    ow = int(orig_w); oh = int(orig_h)
    if ow <= 0 or oh <= 0:
        return (0, 0)
    if ratio is None or ratio == "src":
        return (ow, oh)
    rw, rh = ratio
    if rw <= 0 or rh <= 0:
        return (ow, oh)
    if ow >= oh:
        tw = ow
        th = max(1, round(ow * rh / rw))
        if th > oh:
            th = oh; tw = max(1, round(oh * rw / rh))
    else:
        th = oh
        tw = max(1, round(oh * rw / rh))
        if tw > ow:
            tw = ow; th = max(1, round(ow * rh / rw))
    return (int(tw), int(th))


class OptionsPanel(QWidget):
    output_folder_changed = pyqtSignal(str)
    crop_dims_changed     = pyqtSignal()   # 가로/세로 W·H(비율) 변경 시

    def __init__(self, lang: dict, parent=None):
        super().__init__(parent)
        self._lang = lang
        self._init_ui()

    def _init_ui(self):
        # 창이 작아도 그룹이 세로로 눌리지 않도록 전체를 스크롤 영역에 담는다.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 배경을 명시적으로 다크(#111111)로 — transparent로 두면 라이트 모드 PC에서
        # 스크롤 뷰포트 기본 흰색이 비쳐 설정 패널이 흰색으로 보인다(보정 패널과 동일 패턴).
        self._scroll.setStyleSheet(
            "QScrollArea{border:none;background:#111111;}"
            "QScrollBar:vertical{background:#111111;width:7px;border-radius:3px;}"
            "QScrollBar::handle:vertical{background:#333;border-radius:3px;min-height:24px;}"
            "QScrollBar::handle:vertical:hover{background:#D35400;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        self._scroll.viewport().setStyleSheet("background:#111111;")
        _content = QWidget()
        _content.setObjectName("optContent")
        _content.setStyleSheet("#optContent{background:#111111;}")
        root = QVBoxLayout(_content)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # ── 출력 포맷 ──────────────────────────────
        fmt_group = self._group(self._lang["output_format"])
        fmt_inner = QVBoxLayout(fmt_group)
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(FORMATS)
        self.fmt_combo.setCurrentText("JPEG")
        self._style_combo(self.fmt_combo)
        fmt_inner.addWidget(self.fmt_combo)

        # ── 자동 밝기 보정 ─────────────────────────
        bright_group = self._group("자동 밝기 보정")
        bg = QVBoxLayout(bright_group)
        self.auto_bright_cb = QCheckBox("자동 밝기 보정 (RAW가 어둡게 나올 때 권장)")
        self.auto_bright_cb.setChecked(True)
        self.auto_bright_cb.setStyleSheet("color:#CCCCCC; font-size:12px;")
        self.auto_bright_cb.setToolTip(
            "RAW를 단순 변환하면 카메라 화면보다 어둡게 보일 수 있습니다.\n"
            "켜면 눈으로 본 밝기에 가깝게 자동 보정합니다. (RAW 전용, 일반 이미지엔 영향 없음)"
        )
        bg.addWidget(self.auto_bright_cb)
        bright_hint = QLabel("RAW 변환 결과가 어두우면 켜 두세요")
        bright_hint.setStyleSheet("color:#555; font-size:10px;")
        bg.addWidget(bright_hint)

        # ── 리사이즈 (가로 슬라이더: 10%~100%, 100=원본) ──
        resize_group = self._group(self._lang["resize"])
        r_inner = QVBoxLayout(resize_group)

        # 현재 선택값 표시
        self.resize_value_lbl = QLabel("원본 (100%)")
        self.resize_value_lbl.setStyleSheet("color:#D35400; font-size:12px; font-weight:bold;")
        r_inner.addWidget(self.resize_value_lbl)

        # 슬라이더 값 1~10 = 10%~100% (10단위 스냅). 기본 10(원본).
        self.resize_slider = QSlider(Qt.Horizontal)
        self.resize_slider.setRange(1, 10)
        self.resize_slider.setValue(10)
        self.resize_slider.setSingleStep(1)
        self.resize_slider.setPageStep(1)
        self.resize_slider.setTickPosition(QSlider.TicksBelow)
        self.resize_slider.setTickInterval(1)
        self.resize_slider.setStyleSheet("""
            QSlider::groove:horizontal{height:4px;background:#2A2A2A;border-radius:2px;}
            QSlider::handle:horizontal{width:14px;height:14px;margin:-5px 0;
                background:#D35400;border-radius:7px;}
            QSlider::sub-page:horizontal{background:#D35400;border-radius:2px;}
        """)
        self.resize_slider.valueChanged.connect(self._on_resize_slider)
        r_inner.addWidget(self.resize_slider)

        # 눈금 라벨 (10% … 100%원본)
        ticks = QHBoxLayout(); ticks.setContentsMargins(2, 0, 2, 0); ticks.setSpacing(0)
        for t in ["10%", "50%", "원본"]:
            tl = QLabel(t); tl.setStyleSheet("color:#777; font-size:9px;")
            ticks.addWidget(tl, 1, Qt.AlignCenter)
        r_inner.addLayout(ticks)

        # ── 크롭 ────────────────────────────────────
        crop_group = self._group("크롭")
        cr = QVBoxLayout(crop_group)

        self.crop_cb = QCheckBox("크롭 사용")
        self.crop_cb.setChecked(False)
        self.crop_cb.setStyleSheet("color:#CCCCCC; font-size:12px;")
        self.crop_cb.setToolTip("켜면 중앙 미리보기에 크롭 박스가 나타납니다.\n"
                                "박스를 드래그해 위치·크기를 조절하세요.")
        self.crop_cb.toggled.connect(self._on_crop_toggle)
        cr.addWidget(self.crop_cb)

        # 내부 상태
        self._crop_rect = None
        self._orig_w = 0
        self._orig_h = 0

        # 비율 드롭다운 (자유 / 1:1 / 4:3 / 3:2 / 16:9 / 원본 비율)
        ratio_row = QHBoxLayout(); ratio_row.setSpacing(4)
        ratio_lbl = QLabel("비율"); ratio_lbl.setStyleSheet("color:#888;font-size:11px;")
        ratio_lbl.setFixedWidth(28)
        self.crop_ratio_combo = QComboBox()
        # (표시, 값) — None=자유, "src"=원본 비율, (rw,rh)=고정 비율
        self._crop_ratios = [
            ("자유",      None),
            ("1 : 1",     (1, 1)),
            ("4 : 3",     (4, 3)),
            ("3 : 2",     (3, 2)),
            ("16 : 9",    (16, 9)),
            ("원본 비율", "src"),
        ]
        for _label, _v in self._crop_ratios:
            self.crop_ratio_combo.addItem(_label)
        self.crop_ratio_combo.setCurrentIndex(5)   # 기본: 원본 비율
        self._style_combo(self.crop_ratio_combo)
        self.crop_ratio_combo.setToolTip(
            "크롭 박스의 가로:세로 비율.\n'자유'는 비율 고정 없이 변을 드래그할 수 있습니다.")
        self.crop_ratio_combo.activated.connect(self._on_crop_ratio_changed)
        ratio_row.addWidget(ratio_lbl)
        ratio_row.addWidget(self.crop_ratio_combo, stretch=1)
        cr.addLayout(ratio_row)

        crop_hint = QLabel("[크기 조절] 탭 중앙에서 박스를 드래그해 영역을 조절하세요")
        crop_hint.setStyleSheet("color:#555; font-size:10px;"); crop_hint.setWordWrap(True)
        cr.addWidget(crop_hint)

        # ── 접이식 정밀(픽셀) 옵션 ──────────────────
        self.crop_precise_toggle = QPushButton("정밀 크기 지정 (픽셀)  ▼")
        self.crop_precise_toggle.setCheckable(True)
        self.crop_precise_toggle.setFixedHeight(22)
        self.crop_precise_toggle.setStyleSheet(
            "QPushButton{background:transparent;color:#777;border:none;"
            "font-size:10px;text-align:left;} QPushButton:hover{color:#D35400;}")
        self.crop_precise_toggle.toggled.connect(self._on_crop_precise_toggle)
        cr.addWidget(self.crop_precise_toggle)

        self._crop_precise = QWidget(); self._crop_precise.setVisible(False)
        cp = QVBoxLayout(self._crop_precise)
        cp.setContentsMargins(0, 0, 0, 0); cp.setSpacing(3)
        size_row = QHBoxLayout(); size_row.setSpacing(4)
        self.crop_w = QSpinBox(); self.crop_h = QSpinBox()
        for sp, dv in ((self.crop_w, 2400), (self.crop_h, 1600)):
            sp.setRange(1, 99999); sp.setValue(dv)
            sp.setStyleSheet(self._spin_style())
        x_lbl = QLabel("×"); x_lbl.setStyleSheet("color:#666;font-size:12px;")
        self.crop_reset_btn = QPushButton("원본으로")
        self.crop_reset_btn.setFixedHeight(24)
        self.crop_reset_btn.setToolTip("선택한 이미지의 원본 해상도로 출력 크기 되돌리기")
        self.crop_reset_btn.setStyleSheet(
            "QPushButton{background:#1E1E1E;color:#AAAAAA;font-size:10px;"
            "border:1px solid #333;border-radius:3px;padding:0 6px;}"
            "QPushButton:hover{background:#2A2A2A;color:#DDD;}")
        self.crop_reset_btn.clicked.connect(self._on_reset_to_original)
        size_row.addWidget(self.crop_w); size_row.addWidget(x_lbl)
        size_row.addWidget(self.crop_h); size_row.addWidget(self.crop_reset_btn)
        cp.addLayout(size_row)
        self._px_ratio_lbl = QLabel("비율  —")
        self._px_ratio_lbl.setStyleSheet("color:#555;font-size:10px;")
        cp.addWidget(self._px_ratio_lbl)
        for sp in (self.crop_w, self.crop_h):
            sp.valueChanged.connect(self._on_size_changed)
        cr.addWidget(self._crop_precise)

        # ── 출력 해상도 (DPI) ─────────────────────────
        dpi_group = self._group("출력 해상도 (DPI)")
        dg = QVBoxLayout(dpi_group)
        dpi_row = QHBoxLayout(); dpi_row.setSpacing(4)
        self.dpi_cb = QCheckBox("DPI 지정")
        self.dpi_cb.setChecked(False)
        self.dpi_cb.setStyleSheet("color:#CCCCCC; font-size:12px;")
        self.dpi_cb.setToolTip("출력 파일에 인쇄 해상도(DPI)를 기록합니다.\n"
                               "픽셀 수는 그대로이고 인쇄 크기 정보만 바뀝니다 (웹 업로드엔 영향 없음).\n"
                               "JPEG/PNG/TIFF 지원. 일반 인쇄 300, 웹 72.")
        self.dpi_cb.toggled.connect(self._on_dpi_toggle)
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(1, 2400); self.dpi_spin.setValue(300)
        self.dpi_spin.setEnabled(False)
        self.dpi_spin.setStyleSheet(self._spin_style())
        unit = QLabel("dpi"); unit.setStyleSheet("color:#888; font-size:11px;")
        dpi_row.addWidget(self.dpi_cb); dpi_row.addWidget(self.dpi_spin); dpi_row.addWidget(unit)
        dpi_row.addStretch()
        dg.addLayout(dpi_row)

        # ── EXIF ──────────────────────────────────
        exif_group = self._group(self._lang["exif_options"])
        e_inner = QVBoxLayout(exif_group)
        self.exif_btn_group  = QButtonGroup(self)
        self.exif_keep       = QRadioButton(self._lang["exif_keep"])
        self.exif_remove_gps = QRadioButton(self._lang["exif_remove_gps"])
        self.exif_remove_all = QRadioButton(self._lang["exif_remove_all"])
        self.exif_keep.setChecked(True)
        for rb in (self.exif_keep, self.exif_remove_gps, self.exif_remove_all):
            rb.setStyleSheet("color:#CCCCCC; font-size:12px;")
            self.exif_btn_group.addButton(rb)
            e_inner.addWidget(rb)

        # ── 출력 폴더 ──────────────────────────────
        out_group = self._group(self._lang["output_folder"])
        o_inner = QVBoxLayout(out_group)
        self.same_src_cb = QCheckBox(self._lang["same_as_source"])
        self.same_src_cb.setChecked(True)
        self.same_src_cb.setStyleSheet("color:#CCCCCC; font-size:12px;")
        self.same_src_cb.toggled.connect(self._on_same_src_toggle)
        o_inner.addWidget(self.same_src_cb)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(self._lang["same_as_source"])
        self.folder_edit.setEnabled(False)
        self.folder_edit.setStyleSheet(self._line_edit_style())
        self.browse_btn = QPushButton(self._lang["browse"])
        self.browse_btn.setEnabled(False)
        self.browse_btn.setFixedWidth(64)
        self.browse_btn.setStyleSheet(self._small_btn_style())
        self.browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(self.browse_btn)
        o_inner.addLayout(folder_row)

        # ── 파일 이름 뒤에 붙일 단어 (항상 적용) ──────
        name_group = self._group("파일 이름 뒤에 붙일 단어")
        n_inner = QVBoxLayout(name_group)
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("예: _복사  (비우면 원래 이름)")
        self.suffix_edit.setStyleSheet(self._line_edit_style())
        self.suffix_edit.setToolTip(
            "모든 출력 파일 이름 뒤에 항상 이 단어를 붙입니다.\n"
            "예: ‘_복사’ → a.cr2 → a_복사.jpg  (비우면 원래 이름 그대로)"
        )
        n_inner.addWidget(self.suffix_edit)

        # ── 파일 충돌 처리 ─────────────────────────
        col_group = self._group("같은 이름 파일이 있을 때")
        c_inner = QVBoxLayout(col_group)
        self.collision_combo = QComboBox()
        # (표시 텍스트, 모드값)
        self._collision_modes = [
            ("번호 붙이기 (예: a_1.jpg)", "rename"),
            ("덮어쓰기",                 "overwrite"),
            ("건너뛰기",                 "skip"),
        ]
        for label, _ in self._collision_modes:
            self.collision_combo.addItem(label)
        self._style_combo(self.collision_combo)
        self.collision_combo.setToolTip("출력 폴더에 같은 이름 파일이 이미 있을 때의 처리 방식")
        c_inner.addWidget(self.collision_combo)

        # ── 변환 후 처리 ───────────────────────────
        post_group = self._group("변환 후 처리")
        p_inner = QVBoxLayout(post_group)
        self.delete_src_cb = QCheckBox("변환 후 원본 파일 삭제")
        self.delete_src_cb.setChecked(False)
        self.delete_src_cb.setStyleSheet("color:#CCCCCC; font-size:12px;")
        self.delete_src_cb.setToolTip(
            "변환에 성공한 파일의 원본을 삭제합니다.\n"
            "⚠ 삭제된 원본은 복구할 수 없습니다 (휴지통 아님). 신중히 사용하세요."
        )
        p_inner.addWidget(self.delete_src_cb)
        warn = QLabel("⚠ 원본은 복구 불가하게 삭제됩니다")
        warn.setStyleSheet("color:#B85C00; font-size:10px;")
        warn.setWordWrap(True)
        p_inner.addWidget(warn)

        # ── 언어 ──────────────────────────────────
        lang_group = self._group(self._lang["language"])
        l_inner = QHBoxLayout(lang_group)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["한국어", "English"])
        self._style_combo(self.lang_combo)
        l_inner.addWidget(self.lang_combo)

        for w in (fmt_group, bright_group, resize_group, crop_group, dpi_group,
                  exif_group, out_group, name_group, col_group, post_group, lang_group):
            root.addWidget(w)
        root.addStretch()

        # 모드별 표시 그룹 — 출력 설정 / 크기 조절 버튼으로 전환(패널 길어짐 방지)
        self._size_groups   = [resize_group, crop_group, dpi_group]
        self._output_groups = [fmt_group, bright_group, exif_group, out_group,
                               name_group, col_group, post_group, lang_group]
        self.set_mode("output")

        self._scroll.setWidget(_content)
        outer.addWidget(self._scroll)

    def set_mode(self, mode: str):
        """'output' 또는 'size' — 해당 그룹만 표시."""
        for g in self._size_groups:
            g.setVisible(mode == "size")
        for g in self._output_groups:
            g.setVisible(mode != "size")

    # ── Accessors ─────────────────────────────────

    def get_format(self) -> str:
        return self.fmt_combo.currentText()

    def get_quality(self) -> int:
        return 100  # 최대 품질 고정

    def get_resize_mode(self) -> str:
        pct = self.resize_slider.value() * 10   # 10 ~ 100
        return "original" if pct >= 100 else f"{pct}%"

    def get_custom_size(self):
        # 직접 입력(W/H) 기능 제거 — 슬라이더 퍼센트만 사용
        return 0, 0

    def get_exif_mode(self) -> str:
        if self.exif_remove_all.isChecked():
            return "remove_all"
        if self.exif_remove_gps.isChecked():
            return "remove_gps"
        return "keep"

    def get_output_folder(self) -> str:
        if self.same_src_cb.isChecked():
            return ""
        return self.folder_edit.text().strip()

    def get_delete_source(self) -> bool:
        return self.delete_src_cb.isChecked()

    def get_collision_mode(self) -> str:
        idx = self.collision_combo.currentIndex()
        if 0 <= idx < len(self._collision_modes):
            return self._collision_modes[idx][1]
        return "rename"

    def get_rename_suffix(self) -> str:
        return self.suffix_edit.text().strip()

    def get_auto_bright(self) -> bool:
        return self.auto_bright_cb.isChecked()

    def set_auto_bright(self, on: bool):
        self.auto_bright_cb.setChecked(bool(on))

    # ── 크롭 ─────────────────────────────────────
    def get_crop_enabled(self) -> bool:
        return self.crop_cb.isChecked()

    def _current_ratio(self):
        idx = self.crop_ratio_combo.currentIndex()
        if 0 <= idx < len(self._crop_ratios):
            return self._crop_ratios[idx][1]
        return "src"

    def set_original_size(self, w: int, h: int):
        """현재 선택 이미지 원본 해상도 기억 + 현재 비율로 출력 크기 재계산.
        ※ crop_dims_changed 를 emit 하면 main_window._refresh_crop_editor 와 무한 루프가
          생기므로 여기서는 emit 하지 않고 위젯 값/라벨만 직접 갱신한다."""
        w, h = max(1, int(w)), max(1, int(h))
        if (w, h) == (self._orig_w, self._orig_h):
            return
        self._orig_w, self._orig_h = w, h
        tw, th = _ratio_target_size(self._current_ratio(), w, h)
        if tw > 0 and th > 0:
            self.crop_w.blockSignals(True); self.crop_h.blockSignals(True)
            self.crop_w.setValue(tw); self.crop_h.setValue(th)
            self.crop_w.blockSignals(False); self.crop_h.blockSignals(False)
        self._update_ratio_label()

    def _update_ratio_label(self):
        w, h = self.crop_w.value(), self.crop_h.value()
        if w > 0 and h > 0:
            from math import gcd
            g = gcd(w, h); rw, rh = w // g, h // g
            if rw > 99 or rh > 99:
                self._px_ratio_lbl.setText(f"비율  {w/h:.2f} : 1")
            else:
                self._px_ratio_lbl.setText(f"비율  {rw} : {rh}")

    def get_crop_size(self):
        """출력 크기(px) — 정밀 입력(crop_w/h)을 그대로 사용."""
        return (self.crop_w.value(), self.crop_h.value())

    # 하위 호환 (converter.py가 landscape/portrait 키를 사용)
    def get_crop_landscape(self):
        return (self.crop_w.value(), self.crop_h.value())

    def get_crop_portrait(self):
        return (self.crop_w.value(), self.crop_h.value())

    def get_crop_rect(self):
        return self._crop_rect

    def set_crop_rect(self, rect):
        self._crop_rect = tuple(rect) if rect else None

    # 하위 호환
    def get_crop_rect_landscape(self):
        return self._crop_rect

    def get_crop_rect_portrait(self):
        return self._crop_rect

    def set_crop_rect_landscape(self, rect):
        self._crop_rect = tuple(rect) if rect else None

    def set_crop_rect_portrait(self, rect):
        self._crop_rect = tuple(rect) if rect else None

    def get_dpi(self) -> int:
        return self.dpi_spin.value() if self.dpi_cb.isChecked() else 0

    # ── 설정 저장/복원 (마지막 사용 옵션 기억) ──────────

    def get_settings(self) -> dict:
        # ※ delete_source(원본 삭제)는 파괴적 옵션이라 세션 간에 기억하지 않는다
        #   (재실행 시 항상 꺼진 상태로 시작 — 사용자가 잊고 원본을 지우는 사고 방지)
        return {
            "format":        self.get_format(),
            "resize":        self.get_resize_mode(),
            "exif":          self.get_exif_mode(),
            "collision":     self.get_collision_mode(),
            "rename_suffix": self.get_rename_suffix(),
            "crop_enabled":  self.crop_cb.isChecked(),
            "crop_ratio_idx": self.crop_ratio_combo.currentIndex(),
            "crop_w": self.crop_w.value(), "crop_h": self.crop_h.value(),
            "crop_rect": list(self._crop_rect) if self._crop_rect else None,
            "dpi_enabled": self.dpi_cb.isChecked(), "dpi": self.dpi_spin.value(),
        }

    def apply_settings(self, s: dict):
        """저장된 설정을 위젯에 복원 (값이 없거나 잘못돼도 안전하게 무시)."""
        try:
            if s.get("format") in FORMATS:
                self.fmt_combo.setCurrentText(s["format"])
            rk = s.get("resize")
            if rk == "original":
                self.resize_slider.setValue(10)
            elif isinstance(rk, str) and rk.endswith("%"):
                try:
                    self.resize_slider.setValue(max(1, min(10, round(int(rk[:-1]) / 10))))
                except Exception:
                    pass
            exif = s.get("exif")
            if exif == "remove_all":
                self.exif_remove_all.setChecked(True)
            elif exif == "remove_gps":
                self.exif_remove_gps.setChecked(True)
            elif exif == "keep":
                self.exif_keep.setChecked(True)
            if "delete_source" in s:
                self.delete_src_cb.setChecked(bool(s["delete_source"]))
            mode = s.get("collision")
            for i, (_, m) in enumerate(self._collision_modes):
                if m == mode:
                    self.collision_combo.setCurrentIndex(i)
                    break
            if isinstance(s.get("rename_suffix"), str):
                self.suffix_edit.setText(s["rename_suffix"])
            # 크롭 설정 복원
            ci = s.get("crop_ratio_idx")
            if isinstance(ci, int) and 0 <= ci < self.crop_ratio_combo.count():
                self.crop_ratio_combo.setCurrentIndex(ci)
            # 과거 버그로 저장된 1×1 같은 퇴화 값은 무시(선택 사진에서 다시 잡힘)
            if isinstance(s.get("crop_w"), int) and s["crop_w"] > 1:
                self.crop_w.setValue(s["crop_w"])
            if isinstance(s.get("crop_h"), int) and s["crop_h"] > 1:
                self.crop_h.setValue(s["crop_h"])
            rect = s.get("crop_rect")
            if isinstance(rect, (list, tuple)) and len(rect) == 4:
                self._crop_rect = tuple(float(v) for v in rect)
            if "crop_enabled" in s:
                self.crop_cb.setChecked(bool(s["crop_enabled"]))
            if isinstance(s.get("dpi"), int) and s["dpi"] > 0:
                self.dpi_spin.setValue(s["dpi"])
            if "dpi_enabled" in s:
                self.dpi_cb.setChecked(bool(s["dpi_enabled"]))
            self._on_resize_slider(self.resize_slider.value())  # 라벨 동기화
            self._on_crop_toggle(self.crop_cb.isChecked())       # 크롭 입력 활성 동기화
            self._on_dpi_toggle(self.dpi_cb.isChecked())
        except Exception:
            pass

    # ── Slots ─────────────────────────────────────

    def _on_resize_slider(self, v: int):
        """슬라이더 이동 → 현재 퍼센트 라벨 갱신."""
        pct = v * 10
        self.resize_value_lbl.setText("원본 (100%)" if pct >= 100 else f"{pct}% 로 축소")

    def _on_crop_toggle(self, checked: bool):
        # 크롭 사용 시 리사이즈 슬라이더 비활성(크롭이 최종 크기를 정함)
        self.resize_slider.setEnabled(not checked)
        self.resize_value_lbl.setStyleSheet(
            "color:#555; font-size:12px;" if checked
            else "color:#D35400; font-size:12px; font-weight:bold;")
        self.crop_dims_changed.emit()

    def _on_crop_ratio_changed(self, _idx: int):
        # 비율 변경 → 출력 크기 재계산 + 저장된 박스 초기화
        tw, th = _ratio_target_size(self._current_ratio(), self._orig_w, self._orig_h)
        if tw > 0 and th > 0:
            self.crop_w.blockSignals(True); self.crop_h.blockSignals(True)
            self.crop_w.setValue(tw); self.crop_h.setValue(th)
            self.crop_w.blockSignals(False); self.crop_h.blockSignals(False)
            self._update_ratio_label()
        self._crop_rect = None
        self.crop_dims_changed.emit()

    def _on_size_changed(self):
        self._update_ratio_label()
        self._crop_rect = None
        self.crop_dims_changed.emit()

    def _on_crop_precise_toggle(self, checked: bool):
        self._crop_precise.setVisible(checked)
        self.crop_precise_toggle.setText(
            "정밀 크기 지정 (픽셀)  ▲" if checked else "정밀 크기 지정 (픽셀)  ▼")

    def _on_reset_to_original(self):
        """현재 비율 기준으로 '현재 사진'의 원본 해상도에 맞춘 출력 크기로 되돌리기."""
        tw, th = _ratio_target_size(self._current_ratio(), self._orig_w, self._orig_h)
        if tw > 0 and th > 0:
            self.crop_w.blockSignals(True); self.crop_h.blockSignals(True)
            self.crop_w.setValue(tw); self.crop_h.setValue(th)
            self.crop_w.blockSignals(False); self.crop_h.blockSignals(False)
            self._crop_rect = None
            self._update_ratio_label()
            self.crop_dims_changed.emit()

    def _on_dpi_toggle(self, checked: bool):
        self.dpi_spin.setEnabled(checked)

    def _on_same_src_toggle(self, checked: bool):
        self.folder_edit.setEnabled(not checked)
        self.browse_btn.setEnabled(not checked)
        if checked:
            self.output_folder_changed.emit("")

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self._lang["select_output"])
        if folder:
            self.folder_edit.setText(folder)
            self.output_folder_changed.emit(folder)

    def update_lang(self, lang: dict):
        self._lang = lang
        self.same_src_cb.setText(lang["same_as_source"])
        self.browse_btn.setText(lang["browse"])
        self.exif_keep.setText(lang["exif_keep"])
        self.exif_remove_gps.setText(lang["exif_remove_gps"])
        self.exif_remove_all.setText(lang["exif_remove_all"])

    # ── Style ──────────────────────────────────────

    def _group(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        g.setStyleSheet("""
            QGroupBox {
                color: #D35400; font-size: 12px; font-weight: bold;
                border: 1px solid #2A2A2A; border-radius: 4px;
                margin-top: 8px; padding-top: 6px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; }
        """)
        return g

    def _style_combo(self, combo: QComboBox):
        combo.setStyleSheet("""
            QComboBox {
                background: #222222; color: #CCCCCC;
                border: 1px solid #333333; border-radius: 3px;
                padding: 4px 8px; font-size: 12px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #222222; color: #CCCCCC;
                selection-background-color: #D35400;
            }
        """)

    def _spin_style(self) -> str:
        return ("QSpinBox { background:#222222; color:#CCCCCC; border:1px solid #333333;"
                " border-radius:3px; padding:2px 4px; font-size:12px; }")

    def _line_edit_style(self) -> str:
        return ("QLineEdit { background:#222222; color:#CCCCCC; border:1px solid #333333;"
                " border-radius:3px; padding:3px 6px; font-size:11px; }")

    def _small_btn_style(self) -> str:
        return ("QPushButton { background:#2A2A2A; color:#CCCCCC; border:1px solid #444444;"
                " border-radius:3px; padding:4px; font-size:11px; }"
                "QPushButton:hover { background:#333333; }"
                "QPushButton:disabled { color:#555555; }")
