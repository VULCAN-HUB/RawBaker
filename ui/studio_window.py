"""RawBaker Studio: shared project, three workspaces and cancellable background work."""

from __future__ import annotations
from ui.editor_i18n import localize

from copy import deepcopy

from pathlib import Path

import json

import shutil

import threading

from uuid import uuid4



from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QStandardPaths, QLockFile, QSize, QSettings

from PyQt5.QtGui import QIcon, QPixmap

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,

    QLabel, QListWidget, QListWidgetItem, QTabWidget, QScrollArea, QFormLayout, QDoubleSpinBox,

    QSpinBox, QComboBox, QCheckBox, QLineEdit, QTextEdit, QGroupBox, QFileDialog, QMessageBox,

    QInputDialog, QProgressDialog, QDialog, QDialogButtonBox, QAction, QMenu, QAbstractSpinBox, QToolButton, QButtonGroup, QSizePolicy, QGridLayout, QSlider)

from core.project import Project, encode, digest

from core.project_store import save_project, load_project

from core.edit_spec import GLOBAL_KEYS, BANDS, globals_only

from core.render_engine import Adjustments, RenderCancelled

from core.studio_render import PhotoRenderer, render_document, normalized_layer

from core.studio_commands import edit_photos, linear_copy, add_layer, change_layer

from core.studio_export import export_image

from ui.studio_canvas import StudioCanvas, CurveEditor

from ui.studio_navigator import Navigator

from ui.studio_style import STYLE, slider_row, tool_icon





class StudioJob(QThread):

    result = pyqtSignal(object)

    failed = pyqtSignal(str)

    progress = pyqtSignal(int, str)



    def __init__(self, function, parent=None):

        super().__init__(parent)

        self.function = function

        self.cancel = threading.Event()



    def run(self):

        try:

            self.result.emit(self.function(self.cancel.is_set, self.progress.emit))

        except RenderCancelled:

            pass

        except Exception as error:

            self.failed.emit(str(error))





class StudioWindow(QMainWindow):

    def __init__(self, lang=None, lang_key="ko", *, storage_root=None, offer_recovery=True):

        super().__init__()

        self.lang, self.lang_key = lang or {}, lang_key

        self.base = Path(storage_root or (Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))/"studio-sessions"))

        self.base.mkdir(parents=True, exist_ok=True)

        self.project = Project(self.base/str(uuid4()))

        self.leases, self.retired = [], []

        self._lease(self.project.root)

        self.path, self.token = None, None

        self.saved = encode(self.project.state)

        self.checkpoint_revision = -1

        self.checkpoint_job = None

        self.photo_id = self.document_id = self.layer_id = None

        self.source_point = None

        self.thumb_icons = {}

        self.input_paths = set()

        self.renderer = PhotoRenderer()

        self.jobs = []

        self.preview_job = None

        self.preview_request = None

        self.preview_max = 1024

        self.generation = 0

        self.io_busy = False

        self.loading_controls = False

        self.legacy_windows = []

        self.resize(1366, 860)

        self._build()

        self.debounce = QTimer(self)

        self.debounce.setSingleShot(True)

        self.debounce.timeout.connect(self.request_preview)

        self.autosave = QTimer(self)

        self.autosave.setInterval(3000)

        self.autosave.timeout.connect(self.checkpoint)

        self.autosave.start()

        self.refresh()

        if offer_recovery:

            QTimer.singleShot(0, self.offer_recovery)



    def _lease(self, root):

        lock = QLockFile(str(root/"active.lock"))

        lock.setStaleLockTime(0)

        if not lock.tryLock():

            raise ValueError(localize('다른 창에서 사용하는 작업입니다.', self))

        self.leases.append((root, lock))



    def tr_text(self, ko, en):

        return en if self.lang_key == "en" else ko



    def button(self, text, callback, layout):

        widget = QPushButton(text)

        widget.setMinimumHeight(20)

        widget.clicked.connect(callback)

        layout.addWidget(widget)

        return widget



    def _build(self):

        self.setStyleSheet(STYLE)

        root = QWidget(); self.setCentralWidget(root)

        outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        top = QHBoxLayout(); top.setContentsMargins(8, 3, 8, 3); top.setSpacing(6)

        title = QLabel("RawBaker")

        title.setStyleSheet("font-size:12px;font-weight:600;color:#dbd9e0;")

        top.addWidget(title)

        label = QLabel("STUDIO"); label.setStyleSheet("color:#8e8174;font-size:10px;letter-spacing:2px;")

        label.hide()

        menu_button = self.button(self.tr_text("파일", "File"), lambda: None, top)

        menu_button.setProperty("quiet", True)

        menu = QMenu(menu_button)

        for text, callback in [(self.tr_text("새 작업", "New"), self.new_project),

                               (self.tr_text("열기…", "Open…"), self.open_dialog),

                               (self.tr_text("다른 이름으로 저장…", "Save as…"), lambda: self.save(as_new=True)),

                               ("한국어 / English", self.change_language)]:

            menu.addAction(text, callback)

        menu_button.setMenu(menu)

        self.library_toggle = self.button(self.tr_text("사진 목록", "Photos"), lambda: self.library.setVisible(not self.library.isVisible()), top)

        self.library_toggle.setProperty("quiet", True)

        top.addStretch()

        self.workspace_choice = QComboBox()

        self.workspace_choice.addItems([self.tr_text("일괄 변환", "Batch"), self.tr_text("사진 보정", "Photo"), self.tr_text("디자인", "Design")])

        self.workspace_choice.setFixedWidth(108)

        top.addWidget(self.workspace_choice)

        self.button(self.tr_text("사진 추가", "Add photos"), self.import_dialog, top)

        self.button(self.tr_text("저장", "Save"), self.save, top)

        export = self.button(self.tr_text("내보내기", "Export"), self.export_current, top)

        export.setProperty("primary", True)

        outer.addLayout(top)

        split = QSplitter(); outer.addWidget(split, 1)

        self.library = QWidget(); left = QVBoxLayout(self.library)

        left.setContentsMargins(12, 16, 12, 12); left.setSpacing(10)

        library_title = QLabel(self.tr_text("프로젝트 사진", "PROJECT PHOTOS"))

        library_title.setStyleSheet("color:#aaa;font-weight:600;padding:4px;")

        left.addWidget(library_title)

        self.photos = QListWidget(); self.photos.setIconSize(QSize(40, 32))

        self.photos.setSelectionMode(QListWidget.ExtendedSelection)

        self.photos.currentItemChanged.connect(self.select_photo)

        left.addWidget(self.photos, 1)

        self.button(self.tr_text("보정 동기화", "Sync adjustments"), self.sync, left)

        row = QHBoxLayout()

        self.button(self.tr_text("보정본 복제", "Duplicate"), self.duplicate, row)

        self.button(self.tr_text("제거", "Remove"), self.remove_photos, row)

        left.addLayout(row)

        credit = QLabel("Unknown · @unknown8563"); credit.setStyleSheet("font-size:10px;color:#777;padding-top:8px;")

        left.addWidget(credit)

        split.addWidget(self.library)

        self.tabs = QTabWidget(); split.addWidget(self.tabs)

        split.setSizes([210, 1156]); self.library.setMinimumWidth(180)

        self._batch_tab(); self._adjust_tab(); self._design_tab()

        self.tabs.tabBar().hide()

        self.workspace_choice.currentIndexChanged.connect(self.tabs.setCurrentIndex)

        self.tabs.currentChanged.connect(self.workspace_choice.setCurrentIndex)

        self.tabs.currentChanged.connect(self.workspace_changed)

        for shortcut, callback in [("Ctrl+S", self.save), ("Ctrl+Shift+S", lambda: self.save(as_new=True)),

                                   ("Ctrl+O", self.open_dialog), ("Ctrl+Z", self.undo), ("Ctrl+Shift+Z", self.redo)]:

            action = QAction(self)

            action.setShortcut(shortcut)

            action.triggered.connect(callback)

            self.addAction(action)

        history = QHBoxLayout(); history.setContentsMargins(6, 1, 6, 1)

        self.button(self.tr_text("실행 취소", "Undo"), self.undo, history)

        self.button(self.tr_text("다시 실행", "Redo"), self.redo, history)

        self.status = QLabel()

        self.status.setWordWrap(False)

        history.addWidget(self.status, 1)

        outer.addLayout(history)

        self.tabs.setCurrentIndex(1)



    def export_current(self):

        if self.tabs.currentIndex() == 2:

            self.export_document()

        else:

            self.tabs.setCurrentIndex(0)



    def workspace_changed(self, index):

        self.library.setVisible(index == 0)

        if hasattr(self, "debounce"):

            self.request_preview()



    def _batch_tab(self):

        page = QWidget()

        shell = QHBoxLayout(page); shell.setContentsMargins(40, 24, 40, 24)

        card = QWidget(); card.setMaximumWidth(620)

        layout = QVBoxLayout(card); layout.setSpacing(14)

        shell.addStretch(); shell.addWidget(card, 1); shell.addStretch()

        heading = QLabel(self.tr_text("선택 사진을 보정 그대로 내보내기", "Export selected photos with their edits"))

        heading.setStyleSheet("font-size:22px;font-weight:600;padding:8px 0 18px 0")

        layout.addWidget(heading)

        self.export_form = QFormLayout(); self.export_form.setVerticalSpacing(14)

        self.format = QComboBox(); self.format.addItems(["PNG", "JPEG", "TIFF", "WEBP"])

        self.quality = QSpinBox(); self.quality.setRange(1, 100); self.quality.setValue(95)

        self.bits = QComboBox(); self.bits.addItems(["16", "8"])

        self.long_side = QSpinBox(); self.long_side.setRange(0, 30000); self.long_side.setSpecialValueText(self.tr_text("원본 크기", "Original size"))

        self.dpi = QSpinBox(); self.dpi.setRange(1, 9600); self.dpi.setValue(300)

        self.metadata = QComboBox()

        for text, value in [(self.tr_text("모두 제거", "Remove all"), "remove_all"), (self.tr_text("GPS 제거", "Remove GPS"), "remove_gps"), (self.tr_text("유지", "Keep"), "keep")]:

            self.metadata.addItem(text, value)

        self.suffix = QLineEdit("_edited")

        self.collision = QComboBox()

        for text, value in [(self.tr_text("새 번호", "Rename"), "rename"), (self.tr_text("건너뛰기", "Skip"), "skip"), (self.tr_text("출력 덮어쓰기", "Replace output"), "overwrite")]:

            self.collision.addItem(text, value)

        for widget in (self.format, self.bits, self.metadata, self.collision): widget.currentIndexChanged.connect(self.export_settings_changed)

        for widget in (self.quality, self.long_side, self.dpi):

            widget.setKeyboardTracking(False); widget.valueChanged.connect(self.export_settings_changed)

        self.suffix.editingFinished.connect(self.export_settings_changed)

        for label, widget in [(self.tr_text("파일 형식", "Format"), self.format), (self.tr_text("품질", "Quality"), self.quality), (self.tr_text("PNG 비트 깊이", "PNG bits"), self.bits),

                              (self.tr_text("긴 변", "Long side"), self.long_side), ("DPI", self.dpi),

                              ("EXIF", self.metadata), (self.tr_text("이름 뒤에 붙이기", "Name suffix"), self.suffix),

                              (self.tr_text("이름 충돌", "Name collision"), self.collision)]:

            self.export_form.addRow(label, widget)

        layout.addLayout(self.export_form)

        self.button(self.tr_text("선택 사진 내보내기", "Export selected photos"), self.export_photos, layout).setProperty("primary", True)

        self.button(self.tr_text("프로젝트 없이 파일만 일괄 변환", "Batch files without a project"), self.legacy_batch, layout)

        layout.addWidget(QLabel(self.tr_text("PNG는 8/16비트, 다른 형식은 8비트 sRGB로 저장합니다. JPEG 투명 영역은 흰색입니다.", "PNG: 8/16-bit; other formats: 8-bit sRGB. JPEG transparency is flattened onto white.")))

        layout.addStretch()

        self.tabs.addTab(page, self.tr_text("일괄 변환", "Batch"))



    def _adjust_tab(self):

        page = QWidget(); layout = QHBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(1)

        center = QVBoxLayout(); center.setSpacing(0)

        toolbar = QHBoxLayout(); toolbar.setContentsMargins(6, 2, 6, 2)

        self.before = QCheckBox(self.tr_text("보정 전", "Before")); self.before.toggled.connect(lambda _: self.request_preview())

        toolbar.addWidget(self.before)

        self.tool = QComboBox()

        for ko, en, value in [(localize('보기', self), "View", "view"), (localize('자르기', self), "Crop", "crop"), (localize('브러시', self), "Brush", "brush"), (localize('선형 마스크', self), "Linear mask", "linear"), (localize('원형 마스크', self), "Radial mask", "radial"), (localize('복제 도장', self), "Clone", "clone"), (localize('잡티 제거', self), "Heal", "heal")]:

            self.tool.addItem(self.tr_text(ko, en), value)

        self.tool.currentIndexChanged.connect(self.tool_changed)

        self.tool.setVisible(False)

        rail = QVBoxLayout(); rail.setContentsMargins(3, 4, 3, 4); rail.setSpacing(2)

        tool_group = QButtonGroup(self); tool_group.setExclusive(True)

        for index in range(self.tool.count()):

            button = QToolButton(); button.setCheckable(True); button.setFixedSize(27, 26)

            button.setIcon(tool_icon(self.tool.itemData(index))); button.setIconSize(QSize(17, 17))

            button.setToolTip(self.tool.itemText(index)); button.setAccessibleName(self.tool.itemText(index))

            tool_group.addButton(button, index); rail.addWidget(button)

        tool_group.button(0).setChecked(True)

        tool_group.idClicked.connect(self.tool.setCurrentIndex)

        self.tool.currentIndexChanged.connect(lambda index: tool_group.button(index).setChecked(True))

        rail.addStretch(); layout.addLayout(rail)

        self.active_tool_label = QLabel(self.tool.currentText())

        self.tool.currentTextChanged.connect(self.active_tool_label.setText)

        toolbar.addSpacing(16); toolbar.addWidget(self.active_tool_label); toolbar.addStretch()

        self.canvas = StudioCanvas()

        self.button(self.tr_text("맞춤", "Fit"), self.fit_preview, toolbar)

        self.button("100%", self.full_preview, toolbar)

        self.button("↻ 90°", self.rotate, toolbar)

        center.addLayout(toolbar)

        center.addWidget(self.canvas, 1)

        self.filmstrip = QListWidget(); self.filmstrip.setFlow(QListWidget.LeftToRight)

        self.filmstrip.setViewMode(QListWidget.IconMode); self.filmstrip.setWrapping(False)

        self.filmstrip.setFixedHeight(72); self.filmstrip.setIconSize(QSize(64, 44)); self.filmstrip.setGridSize(QSize(105, 66))

        self.filmstrip.setMovement(QListWidget.Static)

        self.filmstrip.currentItemChanged.connect(self.film_selected)

        center.addWidget(self.filmstrip)

        self.canvas.gesture.connect(self.gesture)

        hint = QLabel(self.tr_text("마스크·자르기는 원본 위에서 드래그합니다. 복제/잡티 제거: Alt+클릭으로 원본점, 클릭으로 적용.", "Draw masks/crop on the original. Clone/heal: Alt-click source, then click destination."))

        hint.setWordWrap(True); self.canvas.setToolTip(hint.text()); hint.hide()

        layout.addLayout(center, 1)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFixedWidth(286)

        panel = QWidget(); controls = QVBoxLayout(panel); controls.setContentsMargins(8, 5, 8, 8); controls.setSpacing(5)

        panel_title = QLabel(self.tr_text("사진 보정", "Edit photo")); panel_title.setProperty("panelHeader", True); controls.addWidget(panel_title)

        self.photo_navigator = Navigator(self.canvas)

        controls.addWidget(self.photo_navigator)

        self.edit_widgets = {}

        basic = QGroupBox(self.tr_text("기본 보정", "Basic adjustments")); form = QFormLayout(basic); form.setVerticalSpacing(4)

        advanced = QGroupBox(self.tr_text("고급 보정", "Advanced")); advanced.setCheckable(True); advanced.setChecked(False)

        advanced.setMaximumHeight(40)

        advanced.toggled.connect(lambda checked: advanced.setMaximumHeight(16777215 if checked else 40))

        advanced_form = QFormLayout(advanced)

        names = [("exposure", localize('노출', self), -10, 10, .1), ("contrast", localize('대비', self), 0, 3, .05),

                 ("temperature", localize('색온도', self), -100, 100, 1), ("saturation", localize('채도', self), 0, 3, .05),

                 ("sharpness", localize('선명도', self), 0, 100, 1), ("highlights", localize('하이라이트', self), -100, 100, 1),

                 ("shadows", localize('그림자', self), -100, 100, 1), ("whites", localize('흰색', self), -100, 100, 1),

                 ("blacks", localize('검정', self), -100, 100, 1), ("tint", localize('틴트', self), -100, 100, 1)]

        for index, (key, ko, low, high, step) in enumerate(names):

            spin = QDoubleSpinBox(); spin.setRange(low, high); spin.setSingleStep(step); spin.setDecimals(2 if step < 1 else 0)

            spin.setKeyboardTracking(False)

            spin.setValue(getattr(Adjustments(), key))

            spin.valueChanged.connect(lambda _, k=key: self.adjust_changed(k))

            self.edit_widgets[key] = spin

            (form if index < 5 else advanced_form).addRow(slider_row(self.tr_text(ko, key.title()), spin))

        self.curve = QLineEdit("0:0, 0.5:0.5, 1:1")

        self.curve.editingFinished.connect(self.curve_changed)

        self.curve.setVisible(False)  # Text parser retained for backwards-compatible scripted controls.

        self.curve_graph = CurveEditor(); self.curve_graph.edited.connect(self.graph_curve_changed)

        advanced_form.addRow(self.tr_text("톤 커브", "Tone curve"), self.curve_graph)

        self.band = QComboBox(); self.band.addItems(list(BANDS)); self.band.currentIndexChanged.connect(self.load_band)

        advanced_form.addRow(self.tr_text("색상별 조정", "Color adjustments"), self.band)

        self.band_spins = []

        for label in (self.tr_text("색조", "Hue"), self.tr_text("채도", "Saturation"), self.tr_text("밝기", "Lightness")):

            spin = QSpinBox(); spin.setRange(-100, 100); spin.setKeyboardTracking(False)

            spin.valueChanged.connect(self.color_changed); self.band_spins.append(spin); advanced_form.addRow(label, spin)

        controls.addWidget(basic); controls.addWidget(advanced)

        # Collapse advanced widgets instead of leaving disabled space.

        for i in range(advanced_form.count()):

            advanced_form.itemAt(i).widget().setVisible(False)

        advanced.toggled.connect(lambda visible: [advanced_form.itemAt(i).widget().setVisible(visible) for i in range(advanced_form.count())])

        local = QGroupBox(self.tr_text("부분 보정·리터칭", "Local edits")); lf = QFormLayout(local)

        self.radius = QDoubleSpinBox(); self.radius.setRange(.01, .5); self.radius.setSingleStep(.01); self.radius.setValue(.06)

        self.local_ev = QDoubleSpinBox(); self.local_ev.setRange(-5, 5); self.local_ev.setSingleStep(.1); self.local_ev.setValue(.5)

        self.feather = QDoubleSpinBox(); self.feather.setRange(.01, 1); self.feather.setValue(.5); self.feather.setSingleStep(.1)

        lf.addRow(self.tr_text("반경", "Radius"), self.radius); lf.addRow("EV", self.local_ev); lf.addRow(self.tr_text("부드러움", "Feather"), self.feather)

        controls.addWidget(local)

        local.setVisible(False)

        self.tool.currentIndexChanged.connect(lambda _: local.setVisible(self.tool.currentData() in ("brush", "linear", "radial", "clone", "heal")))

        remove_local = self.button(self.tr_text("부분 작업 삭제", "Remove local edit"), self.remove_local, controls)

        remove_local.setVisible(False)

        self.tool.currentIndexChanged.connect(lambda _: remove_local.setVisible(self.tool.currentData() in ("brush", "linear", "radial", "clone", "heal")))

        self.button(self.tr_text("보정 초기화", "Reset adjustments"), self.reset_edit, controls)

        presets = QHBoxLayout()

        self.button(self.tr_text("프리셋 저장", "Save preset"), self.save_preset, presets)

        self.button(self.tr_text("불러오기", "Load preset"), self.load_preset, presets)

        controls.addLayout(presets)

        self.button(self.tr_text("디자인에 배치", "Place in design"), self.place_photo, controls).setProperty("primary", True)

        controls.addStretch(); scroll.setWidget(panel); layout.addWidget(scroll)

        self.tabs.addTab(page, self.tr_text("보정", "Adjust"))



    def icon_button(self, kind, label, callback, layout):

        button = QToolButton(); button.setFixedSize(27, 26)

        button.setIcon(tool_icon(kind)); button.setIconSize(QSize(17, 17))

        button.setToolTip(label); button.setAccessibleName(label)

        button.clicked.connect(callback); layout.addWidget(button)

        return button



    def panel_heading(self, title):

        label = QLabel(title); label.setProperty("panelHeader", True)

        return label



    def _design_tab(self):

        page = QWidget(); layout = QHBoxLayout(page)

        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        rail = QVBoxLayout(); rail.setContentsMargins(3, 3, 3, 3); rail.setSpacing(2)

        self.icon_button("move", self.tr_text("레이어 이동", "Move layer"), lambda: setattr(self.design_canvas, "tool", "move"), rail)

        for kind, label in [("photo", localize('사진 배치', self)), ("text", localize('텍스트', self)), ("rectangle", localize('사각형', self)), ("ellipse", localize('타원', self))]:

            self.icon_button(kind, self.tr_text(label, kind.title()), lambda _, k=kind: self.design_add(k), rail)

        rail.addSpacing(8)

        self.icon_button("view", self.tr_text("화면 이동", "Pan canvas"), lambda: setattr(self.design_canvas, "tool", "view"), rail)

        self.icon_button("fit", self.tr_text("화면에 맞춤", "Fit canvas"), lambda: self.design_canvas.fit(), rail)

        rail.addStretch(); layout.addLayout(rail)

        center = QVBoxLayout(); center.setSpacing(0)

        bar = QHBoxLayout(); bar.setContentsMargins(6, 2, 6, 2); bar.setSpacing(4)

        self.button(self.tr_text("새 문서", "New document"), self.new_document, bar)

        bar.addSpacing(8); bar.addWidget(QLabel(self.tr_text("캔버스 정렬", "Align to canvas")))

        for kind, label in [("left", localize('왼쪽', self)), ("center", localize('가로 중앙', self)), ("right", localize('오른쪽', self)), ("top", localize('위쪽', self)), ("middle", localize('세로 중앙', self)), ("bottom", localize('아래쪽', self))]:

            self.icon_button(kind, self.tr_text(label, kind.title()), lambda _, k=kind: self.align_layer(k), bar)

        bar.addStretch()

        self.button(self.tr_text("보정 열기", "Edit photo"), self.edit_linked, bar)

        center.addLayout(bar)

        self.documents = QTabWidget(); self.documents.setObjectName("documents")

        self.documents.setTabsClosable(True); self.documents.tabCloseRequested.connect(self.remove_document)

        self.documents.currentChanged.connect(self.select_document); self.documents.setFixedHeight(26)

        center.addWidget(self.documents)

        self.design_canvas = StudioCanvas(); self.design_canvas.tool = "move"

        self.design_canvas.gesture.connect(self.move_layer)

        center.addWidget(self.design_canvas, 1); layout.addLayout(center, 1)

        inspector = QWidget(); inspector.setObjectName("inspector"); inspector.setFixedWidth(280)

        right = QVBoxLayout(inspector); right.setContentsMargins(7, 5, 7, 5); right.setSpacing(5)

        right.addWidget(self.panel_heading(self.tr_text("내비게이터", "Navigator")))

        self.navigator = Navigator(self.design_canvas); right.addWidget(self.navigator)

        zoom_bar = QHBoxLayout(); zoom_bar.setSpacing(6)

        self.zoom_label = QLabel("100%"); self.zoom_label.setFixedWidth(44); zoom_bar.addWidget(self.zoom_label)

        self.zoom_slider = QSlider(Qt.Horizontal); self.zoom_slider.setRange(5, 400); self.zoom_slider.setValue(100)

        self.zoom_slider.setAccessibleName(self.tr_text("화면 확대율", "Canvas zoom"))

        self.zoom_slider.valueChanged.connect(self.set_design_zoom); zoom_bar.addWidget(self.zoom_slider, 1)

        self.icon_button("fit", self.tr_text("맞춤", "Fit"), self.design_canvas.fit, zoom_bar)

        self.design_canvas.viewChanged.connect(self.update_design_zoom); right.addLayout(zoom_bar)

        right.addWidget(self.panel_heading(self.tr_text("색상 견본", "Swatches")))

        swatches = QGridLayout(); swatches.setSpacing(2)

        colors = ["#111111","#333333","#555555","#777777","#999999","#bbbbbb","#dddddd","#ffffff","#f6d3ce","#efb89e","#e8d6a4","#e1e9bd",

                  "#c4e9dd","#a8d5e8","#b4c2ec","#c1b4e5","#e6b7dc","#ed9db5","#e56b6f","#e99957","#e6ca5e","#9abe69","#55a58b","#519ba9",

                  "#4268ae","#6355a9","#98559f","#be547d","#823a40","#79523a","#777343","#3f6747","#2b6668","#304c68","#453854","#624557"]

        self.swatch_buttons = []

        for index, color in enumerate(colors):

            button = QPushButton(); button.setFixedSize(19, 16); button.setToolTip(color); button.setAccessibleName(color)

            button.setStyleSheet("QPushButton{background:"+color+";border:1px solid #38383c;border-radius:3px;padding:0;}QPushButton:hover{border:1px solid white;}")

            button.clicked.connect(lambda _, c=color: self.apply_swatch(c)); swatches.addWidget(button, index//12, index%12); self.swatch_buttons.append(button)

        right.addLayout(swatches)

        self.inspector_tabs = QTabWidget(); right.addWidget(self.inspector_tabs, 1)

        layers_page = QWidget(); layers_box = QVBoxLayout(layers_page); layers_box.setContentsMargins(0, 5, 0, 0); layers_box.setSpacing(4)

        self.layers = QListWidget(); self.layers.setObjectName("layers"); self.layers.setMinimumSize(0, 100); self.layers.setIconSize(QSize(28, 28))

        self.layers.currentItemChanged.connect(self.select_layer); self.layers.itemChanged.connect(self.layer_item_changed)

        layers_box.addWidget(self.layers, 1)

        layer_actions = QHBoxLayout(); layer_actions.setSpacing(2)

        self.icon_button("plus", self.tr_text("사진 레이어 추가", "Add photo layer"), lambda: self.design_add("photo"), layer_actions)

        self.icon_button("up", self.tr_text("레이어 위로", "Raise layer"), lambda: self.reorder_layer(1), layer_actions)

        self.icon_button("down", self.tr_text("레이어 아래로", "Lower layer"), lambda: self.reorder_layer(-1), layer_actions)

        self.icon_button("trash", self.tr_text("레이어 삭제", "Delete layer"), self.delete_layer, layer_actions)

        layer_actions.addStretch(); layers_box.addLayout(layer_actions)

        self.inspector_tabs.addTab(layers_page, self.tr_text("레이어", "Layers"))

        scroll = QScrollArea(); scroll.setWidgetResizable(True)

        panel = QWidget(); props = QVBoxLayout(panel); props.setContentsMargins(7, 7, 7, 7); props.setSpacing(6)

        form = QFormLayout(); self.layer_spins = {}

        for key in ("x", "y", "width", "height", "rotation", "opacity"):

            spin = QDoubleSpinBox(); spin.setDecimals(2); spin.setKeyboardTracking(False)

            spin.setRange(-100000, 100000) if key in ("x", "y") else spin.setRange(.1, 100000)

            if key == "rotation": spin.setRange(-360, 360)

            if key == "opacity": spin.setRange(0, 1); spin.setSingleStep(.05)

            spin.valueChanged.connect(lambda _, k=key: self.layer_property(k))

            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

            self.layer_spins[key] = spin; form.addRow(self.tr_text({"x":"가로 위치", "y":"세로 위치", "width":"너비", "height":"높이", "rotation":"회전", "opacity":"불투명도"}[key], key.title()), spin)

        self.layer_visible = QCheckBox(self.tr_text("표시", "Visible")); self.layer_visible.toggled.connect(lambda v: self.layer_update({"visible": v}))

        self.layer_locked = QCheckBox(self.tr_text("잠금", "Locked")); self.layer_locked.toggled.connect(lambda v: self.layer_update({"locked": v}))

        form.addRow(self.layer_visible, self.layer_locked)

        self.text_content = QTextEdit(); self.text_content.setMinimumWidth(0); self.text_content.setMaximumHeight(90)

        form.addRow(self.tr_text("텍스트", "Text"), self.text_content)

        self.font_size = QSpinBox(); self.font_size.setRange(1, 10000); self.font_size.setValue(64)

        form.addRow(self.tr_text("글자 크기", "Font size"), self.font_size)

        self.layer_color = QLineEdit("#ffffff"); form.addRow(self.tr_text("색상", "Color"), self.layer_color)

        props.addLayout(form)

        self.button(self.tr_text("텍스트·색상 적용", "Apply text / color"), self.apply_layer_data, props)

        self.button(self.tr_text("캔버스 중앙 정렬", "Center on canvas"), self.center_layer, props)

        self.button(self.tr_text("사진 보정으로 이동", "Adjust linked photo"), self.edit_linked, props)

        mask_bar = QHBoxLayout()

        self.button(self.tr_text("원형", "Radial"), lambda: self.layer_mask("radial"), mask_bar)

        self.button(self.tr_text("마스크 해제", "Clear"), lambda: self.layer_update({"mask": None}), mask_bar)

        props.addLayout(mask_bar)

        self.button(self.tr_text("선형 마스크", "Linear mask"), lambda: self.layer_mask("linear"), props)

        props.addStretch()

        for widget in [w for w in panel.findChildren(QWidget) if isinstance(w, (QPushButton, QDoubleSpinBox, QSpinBox, QLineEdit, QTextEdit, QListWidget))]:

            widget.setMinimumWidth(0); widget.setSizePolicy(QSizePolicy.Ignored, widget.sizePolicy().verticalPolicy())

        scroll.setWidget(panel); self.inspector_tabs.addTab(scroll, self.tr_text("속성", "Properties"))

        layout.addWidget(inspector); self.tabs.addTab(page, self.tr_text("디자인", "Design"))



    def design_add(self, kind):

        self.add_design_layer(kind)

        self.design_canvas.tool = "move"

        if kind == "text": self.inspector_tabs.setCurrentIndex(1)



    def apply_swatch(self, color):

        layer = self.current_layer()

        if layer and layer["kind"] != "photo":

            self.layer_color.setText(color); self.apply_layer_data()



    def layer_item_changed(self, item):

        if self.loading_controls: return

        key = item.data(Qt.UserRole)

        try:

            change_layer(self.project, self.document_id, key, {"visible": item.checkState() == Qt.Checked})

            self.refresh()

        except Exception as error:

            self.error(error); self.refresh_layers()



    def set_design_zoom(self, percent):

        canvas = self.design_canvas; canvas.auto_fit = False

        doc = self.project.state["documents"].get(self.document_id)

        ratio = doc["width"]/canvas.image_size[0] if doc else 1

        canvas.resetTransform(); canvas.scale(percent/100*ratio, percent/100*ratio); canvas.viewChanged.emit()



    def update_design_zoom(self):

        doc = self.project.state["documents"].get(self.document_id)

        ratio = self.design_canvas.image_size[0]/doc["width"] if doc else 1

        percent = round(self.design_canvas.transform().m11()*ratio*100)

        self.zoom_label.setText(str(percent)+"%")

        self.zoom_slider.blockSignals(True); self.zoom_slider.setValue(percent); self.zoom_slider.blockSignals(False)



    def align_layer(self, alignment):

        import math

        layer = self.current_layer()

        if not layer: return

        doc = self.project.state["documents"][self.document_id]

        angle = math.radians(layer["rotation"]); c, sn = math.cos(angle), math.sin(angle)

        xs = [c*x-sn*y for x,y in [(0,0),(layer["width"],0),(layer["width"],layer["height"]),(0,layer["height"])]]

        ys = [sn*x+c*y for x,y in [(0,0),(layer["width"],0),(layer["width"],layer["height"]),(0,layer["height"])]]

        values = {"left": {"x": -min(xs)}, "center": {"x": (doc["width"]-min(xs)-max(xs))/2}, "right": {"x": doc["width"]-max(xs)},

                  "top": {"y": -min(ys)}, "middle": {"y": (doc["height"]-min(ys)-max(ys))/2}, "bottom": {"y": doc["height"]-max(ys)}}

        self.layer_update(values[alignment])



    def error(self, error):

        self.status.setText(localize(str(error), self))

        QMessageBox.warning(self, "RawBaker", localize(str(error), self))



    def selected(self):

        return [i.data(Qt.UserRole) for i in self.photos.selectedItems()]



    def refresh(self):

        self.loading_controls = True

        if self.photo_id not in self.project.state["photos"]:

            self.photo_id = next(iter(self.project.state["photos"]), None)

        selected = set(self.selected()) if hasattr(self, "photos") else set()

        self.photos.blockSignals(True); self.photos.clear()

        self.filmstrip.blockSignals(True); self.filmstrip.clear()

        for key in self.project.state["ui"]["photo_order"]:

            photo = self.project.state["photos"][key]

            name = self.project.state["ui"].get("photo_names", {}).get(key, self.project.state["assets"][photo["asset_id"]]["name"])

            item = QListWidgetItem(name + (" · legacy" if photo["engine_version"] == "legacy-v1" else "")); item.setData(Qt.UserRole, key)

            self.photos.addItem(item)

            film = QListWidgetItem(name); film.setData(Qt.UserRole, key); self.filmstrip.addItem(film)

            if key in self.thumb_icons:

                item.setIcon(self.thumb_icons[key]); film.setIcon(self.thumb_icons[key])

            if key == self.photo_id: self.photos.setCurrentItem(item)

            if key == self.photo_id: self.filmstrip.setCurrentItem(film)

            item.setSelected(key in selected or key == self.photo_id)

        self.photos.blockSignals(False)

        self.filmstrip.blockSignals(False)

        self.documents.blockSignals(True)
        # QTabWidget.clear() removes tabs but retains their QWidget pages.
        # These pages only label documents; dispose them when rebuilding tabs.
        old_pages = [self.documents.widget(i) for i in range(self.documents.count())]
        self.documents.clear()
        for page in old_pages:
            page.deleteLater()
        for index, key in enumerate(self.project.state["documents"]):

            self.documents.addTab(QWidget(), self.tr_text("문서 ", "Document ")+str(index+1))

            self.documents.tabBar().setTabData(index, key)

            if key == self.document_id: self.documents.setCurrentIndex(index)

        self.documents.blockSignals(False)

        if self.document_id not in self.project.state["documents"]:

            self.document_id = next(iter(self.project.state["documents"]), None)

        options = self.project.state["ui"]["options"].get("studio_export", {"format": "PNG"})

        if options:

            self.format.setCurrentText(options.get("format", "PNG")); self.bits.setCurrentText(str(options.get("bits", 16)))

            self.quality.setValue(options.get("quality", 95)); self.dpi.setValue(options.get("dpi", 300)); self.long_side.setValue(options.get("max_side") or 0)

            self.metadata.setCurrentIndex(max(0, self.metadata.findData(options.get("metadata", "remove_all"))))

            self.collision.setCurrentIndex(max(0, self.collision.findData(options.get("collision", "rename"))))

            self.suffix.setText(options.get("suffix", "_edited"))

        self.loading_controls = False

        self.load_controls(); self.refresh_layers(); self.update_title(); self.request_preview()



    def update_title(self):

        dirty = encode(self.project.state) != self.saved

        self.setWindowTitle("RawBaker Studio — " + (self.path.name if self.path else self.tr_text("새 작업", "Untitled")) + (" *" if dirty else ""))



    def select_photo(self, current, previous=None):

        self.photo_id = current.data(Qt.UserRole) if current else None

        self.preview_max = 1024

        self.canvas.auto_fit = True

        self.source_point = None

        self.filmstrip.blockSignals(True)

        for index in range(self.filmstrip.count()):

            if self.filmstrip.item(index).data(Qt.UserRole) == self.photo_id: self.filmstrip.setCurrentRow(index)

        self.filmstrip.blockSignals(False)

        self.load_controls(); self.request_preview()



    def film_selected(self, current, previous=None):

        if current:

            key = current.data(Qt.UserRole)

            for index in range(self.photos.count()):

                if self.photos.item(index).data(Qt.UserRole) == key: self.photos.setCurrentRow(index); break



    def remove_photos(self):

        keys = set(self.selected())

        if not keys: return

        for doc in self.project.state["documents"].values():

            if any(layer.get("photo_id", layer.get("data", {}).get("photo_id")) in keys for layer in doc["layers"]):

                self.error(self.tr_text("디자인에서 사용 중입니다. 연결된 사진 레이어를 먼저 제거하세요.", "Remove linked design layers before removing these photos.")); return

        state = deepcopy(self.project.state)

        for key in keys:

            state["photos"].pop(key); state["ui"].get("photo_names", {}).pop(key, None)

        state["ui"]["photo_order"] = [key for key in state["ui"]["photo_order"] if key not in keys]

        used = {photo["asset_id"] for photo in state["photos"].values()}

        state["assets"] = {key: value for key, value in state["assets"].items() if key in used}

        self.project._change(state); self.photo_id = next(iter(state["photos"]), None); self.refresh()



    def photo_edit(self):

        if self.photo_id not in self.project.state["photos"]:

            return None

        photo = self.project.state["photos"][self.photo_id]

        if photo["engine_version"] != "linear-v1":

            self.status.setText(self.tr_text("기존 보정이 유지됩니다. '별도 보정본'으로 새 엔진에서 시작하세요.", "Legacy edits are preserved. Make an independent copy to use the new engine."))

            return None

        return deepcopy(photo["adjustments"])



    def load_controls(self):

        edit = self.photo_edit()

        self.loading_controls = True

        for key, spin in self.edit_widgets.items():

            spin.setEnabled(edit is not None); spin.setValue((edit or {}).get(key, getattr(Adjustments(), key)))

        self.curve.setText(", ".join(f"{x:g}:{y:g}" for x, y in (edit or {}).get("curve", ((0, 0), (.5, .5), (1, 1)))))

        self.curve_graph.set_curve((edit or {}).get("curve", ((0, 0), (.5, .5), (1, 1))))

        self.loading_controls = False

        self.load_band()



    def load_band(self):

        edit = self.photo_edit() or {}

        self.loading_controls = True

        for spin, value in zip(self.band_spins, edit.get("colors", {}).get(self.band.currentText(), [0, 0, 0])):

            spin.setValue(value)

        self.loading_controls = False



    def commit_edit(self, edit):

        try:

            edit_photos(self.project, [self.photo_id], edit)

            self.update_title(); self.debounce.start(80)

        except Exception as error:

            self.error(error); self.load_controls()



    def adjust_changed(self, key):

        if self.loading_controls: return

        edit = self.photo_edit()

        if edit is not None:

            edit[key] = self.edit_widgets[key].value(); self.commit_edit(edit)



    def curve_changed(self):

        if self.loading_controls: return

        edit = self.photo_edit()

        if edit is not None:

            try:

                edit["curve"] = [[float(v) for v in pair.strip().split(":")] for pair in self.curve.text().split(",")]

                self.commit_edit(edit)

            except ValueError as error: self.error(error)



    def graph_curve_changed(self, points):

        if self.loading_controls: return

        edit = self.photo_edit()

        if edit is not None:

            edit["curve"] = deepcopy(points); self.commit_edit(edit)



    def color_changed(self):

        if self.loading_controls: return

        edit = self.photo_edit()

        if edit is not None:

            edit.setdefault("colors", {})[self.band.currentText()] = [s.value() for s in self.band_spins]

            self.commit_edit(edit)



    def tool_changed(self):

        self.canvas.tool = self.tool.currentData()

        self.request_preview()



    def gesture(self, points, alt):

        edit = self.photo_edit()

        if edit is None: return

        kind = self.tool.currentData()

        if kind in ("clone", "heal"):

            if alt:

                self.source_point = points[-1]; self.status.setText(self.tr_text("원본점 선택됨. 적용할 위치를 클릭하세요.", "Source selected. Click the destination.")); return

            if self.source_point is None:

                self.status.setText(self.tr_text("먼저 Alt+클릭으로 원본점을 선택하세요.", "Alt-click a source first.")); return

            radius = self.radius.value()

            selected = [points[0]]

            import math

            for p in points[1:]:

                if math.dist(p, selected[-1]) >= radius*.25: selected.append(p)

            for p in selected:

                source = [max(0, min(1, self.source_point[i]+p[i]-points[0][i])) for i in range(2)]

                edit.setdefault("retouch", []).append(dict(kind=kind, source=source, target=p, radius=radius))

        elif kind == "crop":

            a, b = points[0], points[-1]

            w, h = abs(a[0]-b[0]), abs(a[1]-b[1])

            if min(w, h) < .001: return

            edit["crop"] = [min(a[0], b[0]), min(a[1], b[1]), w, h]

        elif kind in ("brush", "linear", "radial"):

            spec = dict(kind=kind, points=points if kind == "brush" else [points[0], points[-1]], radius=self.radius.value(), feather=self.feather.value(), invert=False)

            edit.setdefault("masks", []).append(dict(mask=spec, adjustments={"exposure": self.local_ev.value()}))

        else: return

        self.commit_edit(edit); self.tool.setCurrentIndex(0)



    def remove_local(self):

        edit = self.photo_edit()

        if edit is None: return

        choices = [(group, index, f"{group} {index+1}: " + (item["mask"]["kind"] if group == "masks" else item["kind"]))

                   for group in ("masks", "retouch") for index, item in enumerate(edit.get(group, []))]

        if choices:

            selected, ok = QInputDialog.getItem(self, "RawBaker", self.tr_text("삭제할 작업", "Edit to remove"), [value[2] for value in choices], editable=False)

            if ok:

                group, index, _ = next(value for value in choices if value[2] == selected)

                edit[group].pop(index); self.commit_edit(edit)



    def rotate(self):

        edit = self.photo_edit()

        if edit is not None:

            edit["rotation"] = (edit.get("rotation", 0)+90) % 360; self.commit_edit(edit)



    def reset_edit(self):

        if self.photo_edit() is not None:

            self.commit_edit({}); self.load_controls()



    def duplicate(self):

        if not self.photo_id: return

        photo = self.project.state["photos"][self.photo_id]

        self.photo_id = self.project.duplicate_photo(self.photo_id) if photo["engine_version"] == "linear-v1" else linear_copy(self.project, self.photo_id)

        self.refresh()



    def sync(self):

        edit = self.photo_edit()

        if edit is None: return

        try:

            edit_photos(self.project, self.selected(), edit, synchronize=True); self.refresh()

        except Exception as error: self.error(error)



    def save_preset(self):

        edit = self.photo_edit()

        if edit is None: return

        path, _ = QFileDialog.getSaveFileName(self, self.tr_text("보정 프리셋", "Adjustment preset"), "", "RawBaker preset (*.rbpreset)")

        if path:

            from core.safe_output import write_output

            try:

                self.external_destination(path)

                write_output(encode(dict(engine_version="linear-v1", adjustments=globals_only(edit))), path, mode="overwrite", protected_inputs=self.protected(), protected_hashes=self.project.state["assets"])

            except Exception as error: self.error(error)



    def load_preset(self):

        if self.photo_edit() is None: return

        path, _ = QFileDialog.getOpenFileName(self, self.tr_text("보정 프리셋", "Adjustment preset"), "", "RawBaker preset (*.rbpreset)")

        if not path: return

        try:

            if Path(path).stat().st_size > 1024*1024: raise ValueError(self.tr_text("프리셋은 1 MB 이하여야 합니다.", "Preset must be 1 MB or smaller."))

            preset = json.loads(Path(path).read_text(encoding="utf-8"))

            if preset["engine_version"] != "linear-v1": raise ValueError(self.tr_text("지원하지 않는 프리셋 버전입니다.", "This preset version is not supported."))

            edit_photos(self.project, [self.photo_id], preset["adjustments"], synchronize=True); self.refresh()

        except Exception as error: self.error(error)



    def undo(self):

        if self.project.undo(): self.refresh()



    def redo(self):

        if self.project.redo(): self.refresh()



    def request_preview(self, max_side="current"):

        if not hasattr(self, "debounce"): return

        if max_side == "current": max_side = self.preview_max

        else: self.preview_max = max_side

        if getattr(self,'brush_preview_state',None) is not None:max_side=1024

        self.generation += 1

        self.preview_request = (self.generation, Project(self.project.root, getattr(self,'brush_preview_state',None) or self.project.state), self.tabs.currentIndex(), self.photo_id, self.document_id,

                                self.before.isChecked() or self.tool.currentData() != "view", max_side)

        if self.preview_job:

            self.preview_job.cancel.set()

        else: self._launch_preview()



    def _launch_preview(self):

        request, self.preview_request = self.preview_request, None

        if not request: return

        generation, project, mode, photo, document, before, max_side = request

        if (mode != 2 and photo not in project.state["photos"]) or (mode == 2 and document not in project.state["documents"]):

            canvas = self.design_canvas if mode == 2 else self.canvas

            canvas.image_item.setPixmap(QPixmap()); canvas.outline(None); return

        def run(cancelled, progress):
            if mode==2 and max_side is None:
                from core.disk_composite import document_pixels
                frame=document_pixels(project,document,cancelled=cancelled)
            else:frame = render_document(project, document, self.renderer, max_side, cancelled) if mode == 2 else self.renderer.photo(project, photo, max_side, cancelled, before)
            return generation, mode, frame, max_side

        job = StudioJob(run, self); self.preview_job = job; self.jobs.append(job)

        def display(result):

            if result[0] != self.generation: return

            canvas=self.design_canvas if result[1]==2 else self.canvas
            if result[1]==2 and result[3] is None:canvas.set_pixels(result[2])
            else:canvas.set_frame(result[2])
            (self.navigator if result[1] == 2 else self.photo_navigator).update()

            if result[1] != 2:

                icon = QIcon(self.canvas.image_item.pixmap().scaled(96, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))

                self.thumb_icons[photo] = icon

                for listing in (self.photos, self.filmstrip):

                    for index in range(listing.count()):

                        if listing.item(index).data(Qt.UserRole) == photo: listing.item(index).setIcon(icon)

            if result[1] == 2:

                self.update_outline(); self.update_design_zoom()

            quality = self.tr_text("빠른 미리보기", "Quick preview") if result[3] == 1024 else self.tr_text("원본 해상도 미리보기", "Full-resolution preview")

            document = self.project.state["documents"].get(self.document_id) if result[1] == 2 else None

            dimensions = f"{document['width']} × {document['height']} px  ·  " if document else ""

            if getattr(self,'brush_preview_state',None) is not None:quality=localize('브러시 미리보기 · 놓으면 적용 · Esc 취소', self)

            self.status.setText(dimensions + "sRGB  ·  " + quality)

        def finished():

            self.preview_job = None; self.jobs.remove(job); job.deleteLater()

            if self.preview_request: self._launch_preview()

        job.result.connect(display); job.failed.connect(lambda message: self.status.setText(localize(message, self)) if generation == self.generation else None)

        job.finished.connect(finished); job.start()



    def full_preview(self):
        (self.design_canvas if self.tabs.currentIndex()==2 else self.canvas).one_to_one(); self.request_preview(None)


    def fit_preview(self):
        (self.design_canvas if self.tabs.currentIndex()==2 else self.canvas).fit(); self.request_preview(1024)


    def run_io(self, label, function, done, cancellable=True, on_finish=None):

        if self.io_busy: return

        self.io_busy = True

        self.centralWidget().setEnabled(False)

        for action in self.actions(): action.setEnabled(False)

        progress = QProgressDialog(label, self.tr_text("취소", "Cancel") if cancellable else "", 0, 0, self)

        progress.setWindowModality(Qt.ApplicationModal); progress.setMinimumDuration(0); progress.setAutoClose(False)

        if not cancellable: progress.setCancelButton(None)

        job = StudioJob(function, self); self.jobs.append(job)

        progress.canceled.connect(job.cancel.set)

        job.progress.connect(lambda value, message: progress.setLabelText(message))

        result_box = []

        job.result.connect(result_box.append); job.failed.connect(self.error)

        def finished():

            self.io_busy = False; progress.close(); progress.deleteLater(); self.jobs.remove(job); job.deleteLater()

            self.centralWidget().setEnabled(True)

            for action in self.actions(): action.setEnabled(True)

            if result_box:

                try: done(result_box[0])

                except Exception as error: self.error(error)

            if on_finish: on_finish()

            self.update_title()

        job.finished.connect(finished); job.start()



    def import_dialog(self):

        paths, _ = QFileDialog.getOpenFileNames(self, self.tr_text("사진 추가", "Add photos"), "", "Images (*.jpg *.jpeg *.png *.tif *.tiff *.webp *.bmp *.cr2 *.cr3 *.nef *.arw *.dng *.orf *.rw2 *.raf)")

        if paths: self.import_paths(paths)



    def import_paths(self, paths):

        staged = Project(self.project.root, self.project.state)

        def run(cancelled, progress):

            ids = []

            for i, path in enumerate(paths):

                if cancelled(): raise RenderCancelled()

                progress(i, str(path)); ids.append(staged.import_photo(path, engine_version="linear-v1")); staged._undo.clear()

                staged.state["ui"].setdefault("photo_names", {})[ids[-1]] = Path(path).name

            return staged.state, ids

        def done(result):

            self.input_paths.update(map(str, paths))

            self.project._change(result[0]); self.photo_id = result[1][-1]; self.refresh()

        self.run_io(self.tr_text("원본 가져오는 중", "Importing originals"), run, done)



    def save(self, checked=False, *, as_new=False, on_saved=None):

        if self.io_busy: return False

        path = self.path

        if path is None or as_new:

            name, _ = QFileDialog.getSaveFileName(self, "RawBaker", str(path or ""), "RawBaker (*.rbproj)")

            if not name: return False

            path = Path(name if name.lower().endswith(".rbproj") else name+".rbproj")

            expected = digest(path) if path.exists() else None

        else: expected = self.token

        from core.safe_output import is_protected

        if is_protected(path, self.protected(include_project=False)) or (path.is_file() and digest(path) in self.project.state["assets"]):

            self.error(localize('프로젝트가 원본을 덮어쓸 수 없습니다.', self)); return False

        try: self.external_destination(path)

        except ValueError as error: self.error(error); return False

        snapshot = Project(self.project.root, self.project.state)

        def done(token):

            self.path, self.token, self.saved = path, token, encode(snapshot.state)

            self.status.setText(self.tr_text("저장 완료", "Saved"))

            if on_saved: QTimer.singleShot(0, on_saved)

        self.run_io(self.tr_text("프로젝트 저장 중", "Saving project"), lambda cancel, progress: save_project(snapshot, path, expected_token=expected, cancelled=cancel), done)

        return True



    def leave(self, callback):

        if self.io_busy: return

        if encode(self.project.state) == self.saved: callback(); return

        choice = QMessageBox.question(self, "RawBaker", self.tr_text("변경 내용을 저장할까요?", "Save changes?"), QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)

        if choice == QMessageBox.Save: self.save(on_saved=callback)

        elif choice == QMessageBox.Discard: callback()



    def switch(self, project, path=None, token=None, recovered=False, lease=None):

        if lease is None: self._lease(project.root)

        else: self.leases.append((project.root, lease))

        self.retired.append(self.project.root)

        self.project = project

        self.path, self.token = path, token

        self.saved = b"" if recovered else encode(project.state)

        if any("kind" not in layer for doc in project.state["documents"].values() for layer in doc["layers"]):

            state = deepcopy(project.state)

            for document in state["documents"].values():

                document["layers"] = [dict(normalized_layer(layer, document), id=str(uuid4())) if "kind" not in layer else layer for layer in document["layers"]]

            project._change(state)

        self.photo_id = next(iter(project.state["photos"]), None); self.document_id = None; self.layer_id = None

        self.thumb_icons.clear()

        self.checkpoint_revision = -1; self.refresh()



    def new_project(self):

        self.leave(lambda: self.switch(Project(self.base/str(uuid4()))))



    def open_dialog(self):

        def open_selected():

            name, _ = QFileDialog.getOpenFileName(self, "RawBaker", "", "RawBaker (*.rbproj)")

            if name: self.open_path(name)

        self.leave(open_selected)



    def open_path(self, path):

        destination = self.base/str(uuid4())

        self.run_io(self.tr_text("프로젝트 여는 중", "Opening project"), lambda cancel, progress: load_project(path, destination),

                    lambda result: self.switch(result[0], Path(path), result[1]), cancellable=False)



    def checkpoint(self):

        if self.io_busy or self.checkpoint_job or self.checkpoint_revision == self.project.state["revision"] or encode(self.project.state) == self.saved: return

        snapshot = Project(self.project.root, self.project.state)

        job = StudioJob(lambda cancel, progress: snapshot.checkpoint(verify_assets=False), self)

        self.jobs.append(job); self.checkpoint_job = job

        def success(_):

            if self.project.root == snapshot.root: self.checkpoint_revision = snapshot.state["revision"]

        def finished():

            self.checkpoint_job = None; self.jobs.remove(job); job.deleteLater()

        job.result.connect(success)

        job.failed.connect(lambda message: self.status.setText(localize(message, self)))

        job.finished.connect(finished); job.start()



    def offer_recovery(self):

        for folder in self.base.iterdir():

            if folder == self.project.root or folder.is_symlink() or not (folder/"recovery.json").is_file(): continue

            try: uuid4_type = __import__("uuid").UUID(folder.name)

            except ValueError: continue

            lock = QLockFile(str(folder/"active.lock"))

            lock.setStaleLockTime(0)

            if not lock.tryLock(): continue

            if QMessageBox.question(self, "RawBaker", self.tr_text("이전 작업을 복구할까요?", "Recover the previous session?")) == QMessageBox.Yes:

                transferred = [False]

                def recovered(project, held=lock):

                    self.switch(project, recovered=True, lease=held); transferred[0] = True

                def release(held=lock):

                    if not transferred[0]: held.unlock()

                self.run_io(self.tr_text("작업 복구 중", "Recovering session"), lambda cancel, progress, root=folder: Project.recover(root), recovered, cancellable=False, on_finish=release)

                return

            lock.unlock()



    def protected(self, include_project=True):

        values = [self.project.root/"assets"/key for key in self.project.state["assets"]] + list(self.input_paths)

        values.extend((self.project.root/"decoded-inputs").glob("*"))

        if self.path and include_project: values.append(self.path)

        return values



    def external_destination(self, path):

        target = Path(path).resolve()

        if target == self.base.resolve() or self.base.resolve() in target.parents:

            raise ValueError(self.tr_text("임시 작업 폴더 밖에 저장하세요.", "Save outside the temporary working folder."))



    def export_options(self):

        return dict(format=self.format.currentText(), quality=self.quality.value(), bits=int(self.bits.currentText()),

                    dpi=self.dpi.value(), metadata=self.metadata.currentData(), max_side=self.long_side.value() or None,

                    collision=self.collision.currentData())



    def export_settings_changed(self, *args):

        if self.loading_controls or not hasattr(self, "status"): return

        state = deepcopy(self.project.state)

        state["ui"]["options"]["studio_export"] = {**self.export_options(), "suffix": self.suffix.text()}

        if state != self.project.state:

            self.project._change(state); self.update_title()



    def export_photos(self):

        keys = self.selected()

        if not keys: return

        folder = QFileDialog.getExistingDirectory(self, self.tr_text("출력 폴더", "Output folder"))

        if not folder: return

        snapshot = Project(self.project.root, self.project.state); options = self.export_options(); suffix = self.suffix.text()

        if any(c in suffix for c in '\\/:*?"<>|'): self.error(localize('잘못된 이름 접미사입니다.', self)); return

        destination = Path(folder).resolve()

        if self.base.resolve() in destination.parents or destination == self.base.resolve(): self.error(localize('작업 폴더 밖으로 출력하세요.', self)); return

        protected = self.protected()

        def run(cancelled, progress):

            renderer = PhotoRenderer(); successes = 0; skipped = 0; failures = []

            for i, key in enumerate(keys):

                if cancelled(): break

                photo = snapshot.state["photos"][key]; asset = photo["asset_id"]

                name = snapshot.state["ui"].get("photo_names", {}).get(key, snapshot.state["assets"][asset]["name"])

                progress(i, f"{i+1}/{len(keys)} · {name}")

                try:

                    frame = renderer.photo(snapshot, key, cancelled=cancelled)

                    if cancelled(): break

                    ext = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tif", "WEBP": ".webp"}[options["format"]]

                    source = snapshot.root/"decoded-inputs"/(asset+Path(snapshot.state["assets"][asset]["name"]).suffix.lower())

                    saved = export_image(frame, destination/(Path(name).stem+suffix+ext), source=source, protected_inputs=protected, protected_hashes=snapshot.state["assets"], **options)

                    successes += saved is not None; skipped += saved is None

                except RenderCancelled: break

                except Exception as error: failures.append((key, f"{name}: {localize(str(error), self)}"))

            return (successes, skipped, len(failures), cancelled()), failures

        def done(result):

            counts, failures = result

            summary = self.export_summary(*counts)

            self.status.setText(summary + ("\n"+"\n".join(message for _, message in failures[:2]) if failures else ""))

            if failures:

                failed = dict(failures)

                for index in range(self.photos.count()):

                    item = self.photos.item(index); key = item.data(Qt.UserRole)

                    item.setSelected(key in failed)

                    if key in failed:

                        item.setText("⚠ " + item.text()); item.setToolTip(failed[key])

        self.run_io(self.tr_text("내보내는 중", "Exporting"), run, done)



    def export_summary(self, successes, skipped, errors, cancelled):
        template = self.tr_text("완료 {0} · 건너뜀 {1} · 오류 {2}", "Completed {0} · Skipped {1} · Errors {2}")
        return template.format(successes, skipped, errors) + (self.tr_text(" · 취소됨", " · Cancelled") if cancelled else "")

    def new_document(self):

        dialog = QDialog(self); dialog.setWindowTitle(self.tr_text("새 문서", "New document")); form = QFormLayout(dialog)

        width, height = QSpinBox(), QSpinBox()

        for spin, value in [(width, 1920), (height, 1080)]: spin.setRange(1, 30000); spin.setValue(value)

        form.addRow(self.tr_text("너비", "Width"), width); form.addRow(self.tr_text("높이", "Height"), height)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.button(QDialogButtonBox.Ok).setText(self.tr_text("확인", "OK")); buttons.button(QDialogButtonBox.Cancel).setText(self.tr_text("취소", "Cancel")); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)

        if dialog.exec_():

            self.document_id = self.project.add_document(width.value(), height.value(), []); self.refresh(); self.tabs.setCurrentIndex(2)



    def select_document(self, index):

        if self.loading_controls: return

        self.document_id = self.documents.tabBar().tabData(index) if index >= 0 else None

        self.layer_id = None; self.refresh_layers(); self.request_preview()



    def remove_document(self, index):

        key = self.documents.tabBar().tabData(index)

        if key:

            state = deepcopy(self.project.state); del state["documents"][key]; self.project._change(state); self.refresh()



    def place_photo(self):

        if not self.photo_id: return

        if not self.document_id:

            self.document_id = self.project.add_document(1920, 1080, [])

        self.add_design_layer("photo"); self.tabs.setCurrentIndex(2)



    def add_design_layer(self, kind):

        if not self.document_id:

            self.document_id = self.project.add_document(1920, 1080, [])

        if kind == "photo" and not self.photo_id: return

        self.layer_id = add_layer(self.project, self.document_id, kind, self.photo_id)

        self.refresh()



    def refresh_layers(self):

        self.layers.blockSignals(True); self.layers.clear()

        document = self.project.state["documents"].get(self.document_id)

        if document:

            for raw_layer in reversed(document["layers"]):

                layer = normalized_layer(raw_layer, document)

                item = QListWidgetItem(layer["name"]); item.setIcon(self.thumb_icons.get(layer["data"].get("photo_id"), tool_icon(layer["kind"]))); item.setCheckState(Qt.Checked if layer["visible"] else Qt.Unchecked); item.setToolTip(layer["name"]); item.setData(Qt.UserRole, layer["id"]); self.layers.addItem(item)

                if layer["id"] == self.layer_id: self.layers.setCurrentItem(item)

        self.layers.blockSignals(False); self.select_layer(self.layers.currentItem())



    def current_layer(self):

        doc = self.project.state["documents"].get(self.document_id, {})

        return next((layer for layer in doc.get("layers", []) if layer.get("id") == self.layer_id), None)



    def select_layer(self, current, previous=None):

        self.layer_id = current.data(Qt.UserRole) if current else None

        layer = self.current_layer()

        self.loading_controls = True

        if layer:

            for key, spin in self.layer_spins.items(): spin.setValue(layer[key])

            self.layer_visible.setChecked(layer["visible"]); self.layer_locked.setChecked(layer["locked"])

            self.text_content.setPlainText(layer["data"].get("text", "")); self.font_size.setValue(int(layer["data"].get("size", 64)))

            self.layer_color.setText(layer["data"].get("color", "#ffffff"))

        for button in self.swatch_buttons: button.setEnabled(bool(layer and layer["kind"] != "photo" and not layer["locked"]))

        self.loading_controls = False

        self.update_outline()



    def update_outline(self):

        import math

        layer = self.current_layer()

        if layer is None:

            self.design_canvas.outline(None); return

        document = self.project.state["documents"][self.document_id]

        angle = math.radians(layer["rotation"]); c, s = math.cos(angle), math.sin(angle)

        points = [((layer["x"]+c*x-s*y)/document["width"], (layer["y"]+s*x+c*y)/document["height"])

                  for x,y in [(0,0), (layer["width"],0), (layer["width"],layer["height"]), (0,layer["height"])]]

        self.design_canvas.outline(points)



    def layer_property(self, key):

        if not self.loading_controls: self.layer_update({key: self.layer_spins[key].value()})



    def layer_update(self, values):

        if self.loading_controls or not self.current_layer(): return

        try:

            change_layer(self.project, self.document_id, self.layer_id, values); self.refresh()

        except Exception as error: self.error(error)



    def apply_layer_data(self):

        layer = self.current_layer()

        if not layer or layer["kind"] == "photo": return

        data = deepcopy(layer["data"]); data["color"] = self.layer_color.text()

        if layer["kind"] == "text": data.update(text=self.text_content.toPlainText(), size=self.font_size.value())

        self.layer_update({"data": data, "name": data.get("text", layer["name"])[:80]})



    def move_layer(self, points, alt):

        layer = self.current_layer()

        if not layer: return

        doc = self.project.state["documents"][self.document_id]

        self.layer_update({"x": layer["x"]+(points[-1][0]-points[0][0])*doc["width"], "y": layer["y"]+(points[-1][1]-points[0][1])*doc["height"]})



    def center_layer(self):

        layer = self.current_layer()

        if layer:

            doc = self.project.state["documents"][self.document_id]

            self.layer_update({"x": (doc["width"]-layer["width"])/2, "y": (doc["height"]-layer["height"])/2})



    def reorder_layer(self, offset):

        layer = self.current_layer()

        if not layer or layer["locked"]: return

        state = deepcopy(self.project.state); layers = state["documents"][self.document_id]["layers"]

        index = next(i for i, value in enumerate(layers) if value.get("id") == self.layer_id)

        target = max(0, min(len(layers)-1, index+offset))

        layers.insert(target, layers.pop(index)); self.project._change(state); self.refresh()



    def delete_layer(self):

        layer = self.current_layer()

        if not layer or layer["locked"]: return

        state = deepcopy(self.project.state)

        state["documents"][self.document_id]["layers"] = [l for l in state["documents"][self.document_id]["layers"] if l.get("id") != self.layer_id]

        self.project._change(state); self.layer_id = None; self.refresh()



    def edit_linked(self):

        layer = self.current_layer()

        if layer and layer["kind"] == "photo":

            self.photo_id = layer["data"]["photo_id"]; self.refresh(); self.tabs.setCurrentIndex(1)



    def layer_mask(self, kind):

        self.layer_update({"mask": dict(kind=kind, points=[[.5, .5], [1., 1.]] if kind == "radial" else [[0., .5], [1., .5]], radius=.1, feather=.5, invert=False)})



    def export_document(self):

        if not self.document_id: return

        path, selected = QFileDialog.getSaveFileName(self, self.tr_text("문서 출력", "Export document"), "design.png", "PNG (*.png);;JPEG (*.jpg *.jpeg)")
        if not path: return

        if Path(path).suffix.lower() not in ('.png','.jpg','.jpeg'):path += '.jpg' if selected.startswith('JPEG') else '.png'
        try: self.external_destination(path)

        except ValueError as error: self.error(error); return

        snapshot = Project(self.project.root, self.project.state); key = self.document_id; protected = self.protected(); dpi = self.dpi.value()

        def run(cancelled, progress):

            from core.tiled_export import export_document_png

            if Path(path).suffix.lower() in ('.jpg','.jpeg'):
                from core.disk_composite import export_document_jpeg
                return export_document_jpeg(snapshot,key,path,dpi=dpi,protected_inputs=protected,cancelled=cancelled)
            return export_document_png(snapshot,key,path,bits=16,dpi=dpi,protected_inputs=protected,protected_hashes=snapshot.state['assets'],collision='overwrite',cancelled=cancelled,progress=lambda value:progress(value,localize('문서 PNG 저장 중…', self)))
        self.run_io(self.tr_text("문서 출력 중", "Exporting document"), run, lambda result: self.status.setText(str(result)))



    def legacy_batch(self):

        from ui.main_window import MainWindow

        window = MainWindow(self.lang, self.lang_key)

        self.legacy_windows.append(window); window.show()



    def change_language(self):

        selected = "en" if self.lang_key == "ko" else "ko"

        QSettings("RawBaker", "RawBaker").setValue("language", selected)

        self.status.setText(self.tr_text("언어를 저장했습니다. 다시 시작하면 적용됩니다.", "Language saved. Restart RawBaker to apply."))



    def closeEvent(self, event):

        if self.io_busy:

            event.ignore(); return

        if not getattr(self, "closing_approved", False) and encode(self.project.state) != self.saved:

            event.ignore()

            def close_approved(): self.closing_approved = True; self.close()

            self.leave(close_approved); return

        self.autosave.stop(); self.debounce.stop(); self.preview_request = None

        for window in self.legacy_windows:

            if window.isVisible() and not window.close():

                event.ignore(); self.autosave.start(); return

        for job in list(self.jobs): job.cancel.set()

        for job in list(self.jobs):

            if not job.wait(10000):

                self.status.setText(self.tr_text("작업을 종료하고 있습니다. 잠시 후 다시 닫아주세요.", "Finishing background work. Please close again shortly."))

                self.closing_approved = False; self.autosave.start(); event.ignore(); return

        for root, lock in self.leases:

            lock.unlock()

            if root.parent.resolve() == self.base.resolve() and not root.is_symlink(): shutil.rmtree(root, ignore_errors=True)

        event.accept()

