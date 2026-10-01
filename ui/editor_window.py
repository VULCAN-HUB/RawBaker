"""Document-first editor. Reuses tested project commands, never Studio's layout builder."""

from ui.editor_i18n import localize
from copy import deepcopy

from uuid import uuid4

from PyQt5.QtCore import Qt, QSize, QTimer, QSettings, QItemSelectionModel

from PyQt5.QtGui import QIcon, QPixmap, QPainter, QImage, QColor, QPainterPath, QPen

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,

    QLabel, QPushButton, QToolBar, QDockWidget, QStackedWidget, QTabWidget, QListWidget,

    QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit, QTextEdit, QCheckBox, QScrollArea,

    QSlider, QGroupBox, QAction, QActionGroup, QSizePolicy, QAbstractSpinBox, QMessageBox, QFileDialog)

from ui.studio_window import StudioWindow

from ui.studio_canvas import StudioCanvas, CurveEditor

from ui.studio_navigator import Navigator

from ui.editor_canvas import EditorCanvas

from ui.studio_style import tool_icon, slider_row

from ui.editor_style import STYLE

from core.render_engine import Adjustments

from core.edit_spec import BANDS

from ui.editor_groups import EditorGroups,PREFIX

from core.layer_groups import ancestors,members,group_locked

from ui.editor_advanced import EditorAdvanced

from ui.layer_list import LayerList





class WorkspaceStack(QStackedWidget):

    def addTab(self, widget, title):

        return self.addWidget(widget)





class EditorWindow(EditorAdvanced,EditorGroups,StudioWindow):

    def _build(self):

        self.setStyleSheet(STYLE)

        self.setDockNestingEnabled(True)

        self.docks = {}

        self.editor_ready = False

        self.tabs = WorkspaceStack()

        self.setCentralWidget(self.tabs)

        # Batch is a separate utility; the document/photo editor is built below.

        self._batch_tab()

        self.tabs.widget(0).layout().setContentsMargins(20,16,20,16)

        for label in self.tabs.widget(0).findChildren(QLabel):label.setWordWrap(True)

        self.canvas = StudioCanvas(); self.canvas.gesture.connect(self.gesture)

        self.design_canvas = EditorCanvas(); self.design_canvas.tool = 'move'

        self.design_canvas.colorPicked.connect(self.select_color_at);self.design_canvas.layerPicked.connect(self.pick_layer); self.design_canvas.cornerResized.connect(self.resize_corner)

        self.design_canvas.gesture.connect(self.move_layer)

        self.design_canvas.areaSelected.connect(self.set_selection)

        self.design_canvas.maskPainted.connect(self.paint_layer_mask)

        self.design_canvas.maskPreview.connect(self.preview_layer_mask)

        self.design_canvas.maskSizeStep.connect(lambda step:self.mask_size.setValue(self.mask_size.value()+step))

        self.brush_preview_state=None



        photo_page = QWidget(); photo_layout = QVBoxLayout(photo_page)

        photo_layout.setContentsMargins(0,0,0,0); photo_layout.setSpacing(0)

        self.photo_caption = QLabel(self.tr_text(' 사진 편집', ' Photo editor'))

        self.photo_caption.setFixedHeight(26); photo_layout.addWidget(self.photo_caption)

        photo_layout.addWidget(self.canvas,1)

        self.filmstrip = QListWidget(); self.filmstrip.setFlow(QListWidget.LeftToRight)

        self.filmstrip.setViewMode(QListWidget.IconMode); self.filmstrip.setWrapping(False)

        self.filmstrip.setMovement(QListWidget.Static); self.filmstrip.setFixedHeight(74)

        self.filmstrip.setIconSize(QSize(66,44)); self.filmstrip.setGridSize(QSize(110,68))

        self.filmstrip.currentItemChanged.connect(self.film_selected); photo_layout.addWidget(self.filmstrip)

        self.tabs.addWidget(photo_page)

        doc_page = QWidget(); doc_layout = QVBoxLayout(doc_page)

        doc_layout.setContentsMargins(0,0,0,0); doc_layout.setSpacing(0)

        self.documents = QTabWidget(); self.documents.setFixedHeight(27); self.documents.setTabsClosable(True)

        self.documents.currentChanged.connect(self.select_document); self.documents.tabCloseRequested.connect(self.remove_document)

        doc_layout.addWidget(self.documents); doc_layout.addWidget(self.design_canvas,1)

        self.tabs.addWidget(doc_page)

        self._create_controls()

        self._create_docks()

        self.create_advanced_controls()

        self._create_options()

        self._create_tools()

        self._create_menus()
        from ui.empty_canvas import EmptyCanvas
        self.empty_document = EmptyCanvas(self.design_canvas,
            self.tr_text('새 작업을 시작하세요', 'Start a new project'),
            self.tr_text('문서를 만들거나 사진을 가져와 편집하세요.', 'Create a document or import photos to begin editing.'),
            [(self.tr_text('새 문서', 'New document'), self.new_document),
             (self.tr_text('사진 가져오기', 'Import photos'), self.import_dialog)])
        self.empty_photo = EmptyCanvas(self.canvas,
            self.tr_text('사진을 가져오세요', 'Import a photo'),
            self.tr_text('가져온 사진을 선택하면 보정을 시작할 수 있습니다.', 'Select an imported photo to start adjusting it.'),
            [(self.tr_text('사진 가져오기', 'Import photos'), self.import_dialog)])

        self.status = QLabel(self.tr_text('문서를 만들거나 사진을 가져오세요.', 'Create a document or import a photo.'))

        self.statusBar().addWidget(self.status,1)

        self.statusBar().addPermanentWidget(QLabel('RawBaker  ·  Unknown / @unknown8563'))

        self.tabs.currentChanged.connect(self.workspace_changed)

        self.editor_ready = True

        self.tabs.setCurrentIndex(2)

        self.default_dock_state = self.saveState()

        self.workspace_changed(2)

        self.resize(1440,900)

        saved=QSettings('RawBaker','RawBaker').value('editor/workspace-v1')

        if saved is not None:self.restoreState(saved)

        self.tool.currentIndexChanged.connect(self.update_photo_options)
        self.photos.itemSelectionChanged.connect(self.update_readiness)



    def button(self, text, callback, layout):
        widget = super().button(text, callback, layout)
        if not hasattr(self, 'command_widgets'): self.command_widgets = {}
        self.command_widgets.setdefault(getattr(callback, '__name__', ''), []).append(widget)
        return widget

    def update_design_zoom(self):
        document = self.document_id in self.project.state['documents']
        self.zoom_slider.setEnabled(document)
        if document: super().update_design_zoom()
        else: self.zoom_label.setText('—')

    def _action(self, menu, title, callback, shortcut=None):

        action = QAction(title,self); action.triggered.connect(callback)
        if not hasattr(self, 'command_actions'): self.command_actions = {}
        self.command_actions.setdefault(getattr(callback, '__name__', ''), []).append(action)

        if shortcut: action.setShortcut(shortcut)

        self.addAction(action); menu.addAction(action)

        return action



    def _create_menus(self):

        mb = self.menuBar()

        file = mb.addMenu(self.tr_text('파일','File'))

        for title, callback, key in [(localize('새 문서', self),self.new_document,'Ctrl+N'),(localize('새 프로젝트', self),self.new_project,None),

                (localize('프로젝트 열기', self),self.open_dialog,'Ctrl+O'),(localize('사진 가져오기', self),self.import_dialog,'Ctrl+Shift+O'),

                (localize('저장', self),self.save,'Ctrl+S'),(localize('다른 이름으로 저장', self),lambda: self.save(as_new=True),'Ctrl+Shift+S'),

                (localize('이미지 내보내기', self),self.export_current,'Ctrl+Alt+S')]:

            self._action(file,title,callback,key)

        self._action(file,localize('PSD 가져오기', self),self.import_psd_dialog)

        self._action(file,localize('PSD 내보내기', self),self.export_psd_dialog)

        edit = mb.addMenu(self.tr_text('편집','Edit'))

        self._action(edit,localize('실행 취소', self),self.undo,'Ctrl+Z'); self._action(edit,localize('다시 실행', self),self.redo,'Ctrl+Shift+Z')

        layer = mb.addMenu(self.tr_text('레이어','Layer'))

        for kind,title in [('photo',localize('사진 배치', self)),('text',localize('텍스트', self)),('rectangle',localize('사각형', self)),('ellipse',localize('타원', self))]:

            self._action(layer,title,lambda _,k=kind:self.design_add(k))

        self._action(layer,localize('레이어별 크기 · 뒤집기', self),self.local_transform_dialog)

        self._action(layer,localize('공통 중심 · 기울이기 · 원근', self),self.world_transform_dialog)

        self._action(layer,localize('선택 함께 변형', self),self.multi_transform_dialog,'Ctrl+Shift+T')

        self._action(layer,localize('레이어 복제', self),self.duplicate_layer,'Ctrl+J')

        self._action(layer,localize('레이어 삭제', self),self.delete_layer)

        self._action(layer,localize('조정 레이어 추가', self),self.add_adjustment_layer)

        self._action(layer,localize('선택 레이어 그룹 만들기', self),self.create_layer_group,'Ctrl+G')

        self._action(layer,localize('그룹 해제', self),self.ungroup_layers,'Ctrl+Shift+G')

        self._action(layer,localize('그룹 이름 변경', self),self.rename_layer_group)

        self._action(layer,localize('그룹 잠금 / 해제', self),self.toggle_group_lock)

        self._action(layer,localize('클리핑 마스크 생성 / 해제', self),self.toggle_clipping,'Ctrl+Alt+G')

        self._action(layer,localize('사진 원본 보정', self),self.edit_linked)

        self._action(layer,localize('선택 영역으로 마스크 만들기', self),self.mask_from_selection)

        self._action(layer,localize('레이어 마스크 반전', self),self.invert_layer_mask)

        selection = mb.addMenu(localize('선택', self))

        self._action(selection,localize('사각형 선택', self),lambda:self.activate_tool('select_rect'),'M')

        self._action(selection,localize('올가미 선택', self),lambda:self.activate_tool('lasso'),'L')

        self._action(selection,localize('합성 색상 선택', self),lambda:self.activate_tool('color_select'),'W')

        self._action(selection,localize('선택 경계 다듬기', self),self.refine_selection_dialog)

        self._action(selection,localize('선택 확장 / 축소', self),self.offset_selection_dialog)

        self._action(selection,localize('선택 실행 취소', self),self.undo_selection,'Ctrl+Alt+Z')

        self._action(selection,localize('선택 다시 실행', self),self.redo_selection,'Ctrl+Alt+Shift+Z')

        self._action(selection,localize('전체 선택', self),self.select_all_area)

        self._action(selection,localize('선택 해제', self),self.clear_selection,'Ctrl+D')

        self._action(selection,localize('선택 반전', self),self.invert_selection,'Ctrl+Shift+I')

        image = mb.addMenu(self.tr_text('이미지','Image'))

        self._action(image,localize('사진 보정', self),lambda:self.tabs.setCurrentIndex(1))

        self._action(image,localize('보정 초기화', self),self.reset_edit)

        self._action(image,localize('90° 회전', self),self.rotate)

        view = mb.addMenu(self.tr_text('보기','View'))

        self._action(view,localize('화면 맞춤', self),self.fit_active,'Ctrl+0')
        self._action(view,localize('원본 크기 · 100%', self),self.full_preview,'Ctrl+1')
        self._action(view,localize('패널 배치 초기화', self),self.reset_workspace)

        windows = mb.addMenu(self.tr_text('창','Window'))

        for dock in self.docks.values(): windows.addAction(dock.toggleViewAction())

        help_menu = mb.addMenu(self.tr_text('도움말','Help'))

        self._action(help_menu,localize('RawBaker 정보', self),lambda:QMessageBox.information(self,'RawBaker',localize('RawBaker\nUnknown · @unknown8563\n문서 편집기 개발판', self)))

        self._action(help_menu,'한국어 / English',self.change_language)

        self.workspace_choice = QComboBox(); self.workspace_choice.addItems([localize('일괄 변환', self),localize('사진 보정', self),localize('문서 편집', self)])

        self.workspace_choice.setMinimumWidth(150); self.workspace_choice.setCurrentIndex(2)

        self.workspace_choice.currentIndexChanged.connect(self.tabs.setCurrentIndex)

        mb.setCornerWidget(self.workspace_choice,Qt.TopRightCorner)



    def _dock(self, key, title, widget, area=Qt.RightDockWidgetArea):

        dock = QDockWidget(title,self); dock.setObjectName('editor-'+key)

        dock.setWidget(widget); dock.setMinimumWidth(230)

        dock.setAllowedAreas(Qt.LeftDockWidgetArea|Qt.RightDockWidgetArea)

        self.addDockWidget(area,dock); self.docks[key]=dock

        return dock



    def _box(self):

        widget=QWidget(); layout=QVBoxLayout(widget); layout.setContentsMargins(8,6,8,6); layout.setSpacing(6)

        return widget,layout



    def _create_controls(self):

        # Inputs are the command adapter's public contract, independent of the old UI layout.

        self.before=QCheckBox(localize('보정 전', self)); self.before.toggled.connect(lambda _:self.request_preview())

        self.tool=QComboBox()

        for label,value in [(localize('보기', self),'view'),(localize('자르기', self),'crop'),(localize('브러시 마스크', self),'brush'),(localize('선형 마스크', self),'linear'),(localize('원형 마스크', self),'radial'),(localize('복제 도장', self),'clone'),(localize('잡티 제거', self),'heal')]: self.tool.addItem(label,value)

        self.tool.currentIndexChanged.connect(self.tool_changed); self.tool.hide()

        self.edit_widgets={}

        for key,lo,hi,step in [('exposure',-10,10,.1),('contrast',0,3,.05),('temperature',-100,100,1),('tint',-100,100,1),('highlights',-100,100,1),('shadows',-100,100,1),('whites',-100,100,1),('blacks',-100,100,1),('saturation',0,3,.05),('sharpness',0,100,1)]:

            spin=QDoubleSpinBox();spin.setRange(lo,hi);spin.setSingleStep(step);spin.setDecimals(2 if step<1 else 0)

            spin.setKeyboardTracking(False);spin.setValue(getattr(Adjustments(),key));spin.valueChanged.connect(lambda _,k=key:self.adjust_changed(k));self.edit_widgets[key]=spin

        self.curve=QLineEdit();self.curve.hide();self.curve.editingFinished.connect(self.curve_changed)

        self.curve_graph=CurveEditor();self.curve_graph.edited.connect(self.graph_curve_changed)

        self.band=QComboBox();self.band.addItems(list(BANDS));self.band.currentIndexChanged.connect(self.load_band)

        self.band_spins=[]

        for _ in range(3):

            spin=QSpinBox();spin.setRange(-100,100);spin.setKeyboardTracking(False);spin.valueChanged.connect(self.color_changed);self.band_spins.append(spin)

        self.radius=QDoubleSpinBox();self.radius.setRange(.01,.5);self.radius.setValue(.06);self.radius.setSingleStep(.01)

        self.local_ev=QDoubleSpinBox();self.local_ev.setRange(-5,5);self.local_ev.setValue(.5);self.local_ev.setSingleStep(.1)

        self.feather=QDoubleSpinBox();self.feather.setRange(.01,1);self.feather.setValue(.5);self.feather.setSingleStep(.1)

        for field in (self.radius,self.feather,self.local_ev):field.setFixedWidth(55)

        self.layer_spins={}

        for key in ('x','y','width','height','rotation','opacity'):

            spin=QDoubleSpinBox();spin.setDecimals(2);spin.setKeyboardTracking(False);spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

            spin.setRange(-100000,100000) if key in ('x','y') else spin.setRange(.1,100000)

            if key=='rotation':spin.setRange(-360,360)

            if key=='opacity':spin.setRange(0,1);spin.setSingleStep(.05)

            spin.valueChanged.connect(lambda _,k=key:self.layer_property(k));self.layer_spins[key]=spin

        self.layer_visible=QCheckBox(localize('표시', self));self.layer_visible.toggled.connect(lambda value:self.layer_update({'visible':value}))

        self.layer_locked=QCheckBox(localize('잠금', self));self.layer_locked.toggled.connect(lambda value:self.layer_update({'locked':value}))

        self.text_content=QTextEdit();self.text_content.setFixedHeight(72)

        self.font_size=QSpinBox();self.font_size.setRange(1,10000);self.font_size.setValue(64)

        self.layer_color=QLineEdit('#ffffff');self.layer_color.setMaximumWidth(90)



    def _create_docks(self):

        collection,box=self._box()

        self.photos=QListWidget();self.photos.setSelectionMode(QListWidget.ExtendedSelection);self.photos.setIconSize(QSize(48,36))

        self.photos.currentItemChanged.connect(self.select_photo);box.addWidget(self.photos,1)

        self.button(localize('사진 열기', self),self.import_dialog,box)

        self.button(localize('보정본 복제', self),self.duplicate,box);self.button(localize('선택 사진 보정 동기화', self),self.sync,box)

        self.library=self._dock('assets',localize('프로젝트 사진', self),collection,Qt.LeftDockWidgetArea)

        nav,box=self._box();self.nav_stack=QStackedWidget()

        self.photo_navigator=Navigator(self.canvas);self.navigator=Navigator(self.design_canvas)

        self.nav_stack.addWidget(self.photo_navigator);self.nav_stack.addWidget(self.navigator);box.addWidget(self.nav_stack)

        zoom=QHBoxLayout();self.zoom_label=QLabel('100%');self.zoom_label.setFixedWidth(44);zoom.addWidget(self.zoom_label)

        self.zoom_slider=QSlider(Qt.Horizontal);self.zoom_slider.setRange(5,400);self.zoom_slider.valueChanged.connect(self.set_design_zoom);zoom.addWidget(self.zoom_slider,1)

        self.icon_button('fit',localize('화면 맞춤', self),self.fit_active,zoom);box.addLayout(zoom)

        self.design_canvas.viewChanged.connect(self.update_design_zoom);self.canvas.viewChanged.connect(self.update_design_zoom)

        navdock=self._dock('navigator',localize('내비게이터', self),nav)

        props,box=self._box();form=QGridLayout()

        for i,(key,label) in enumerate([('x','X'),('y','Y'),('width','W'),('height','H'),('rotation',localize('회전', self))]):

            row,col=divmod(i,2);form.addWidget(QLabel(label),row,col*2);form.addWidget(self.layer_spins[key],row,col*2+1)

        box.addLayout(form);flags=QHBoxLayout();flags.addWidget(self.layer_visible);flags.addWidget(self.layer_locked);box.addLayout(flags)

        self.text_section=QWidget();textbox=QVBoxLayout(self.text_section);textbox.setContentsMargins(0,0,0,0)

        textbox.addWidget(QLabel(localize('텍스트', self)));textbox.addWidget(self.text_content)

        textrow=QHBoxLayout();textrow.addWidget(QLabel(localize('크기', self)));textrow.addWidget(self.font_size);textrow.addWidget(self.layer_color);textbox.addLayout(textrow)

        self.button(localize('텍스트 · 색상 적용', self),self.apply_layer_data,textbox);box.addWidget(self.text_section)

        maskgroup=QGroupBox(localize('레이어 마스크', self));self.mask_group=maskgroup;maskbox=QVBoxLayout(maskgroup)

        self.mask_info=QLabel(localize('마스크 없음', self));maskbox.addWidget(self.mask_info)

        self.mask_enabled=QCheckBox(localize('마스크 사용', self));self.mask_enabled.toggled.connect(self.toggle_layer_mask);maskbox.addWidget(self.mask_enabled)

        masks=QHBoxLayout();self.button(localize('선택으로 만들기', self),self.mask_from_selection,masks);self.button(localize('브러시', self),lambda:self.activate_tool('mask_brush'),masks);maskbox.addLayout(masks)

        masks=QHBoxLayout();self.button(localize('반전', self),self.invert_layer_mask,masks);self.button(localize('제거', self),lambda:self.layer_update({'mask':None}),masks);maskbox.addLayout(masks)

        masks=QHBoxLayout();self.button(localize('원형', self),lambda:self.layer_mask('radial'),masks);self.button(localize('선형', self),lambda:self.layer_mask('linear'),masks);maskbox.addLayout(masks)

        box.addWidget(maskgroup);box.addStretch()

        prop_scroll=QScrollArea();prop_scroll.setWidgetResizable(True);prop_scroll.setWidget(props)

        propdock=self._dock('properties',localize('속성', self),prop_scroll)

        colors,box=self._box();grid=QGridLayout();grid.setSpacing(3);self.swatch_buttons=[]

        for i,color in enumerate(['#ffffff','#dddddd','#bbbbbb','#999999','#777777','#555555','#333333','#111111','#ffc9bb','#f29b77','#e4796e','#bd5365','#edce77','#b6cd83','#62a99d','#5f99ba','#677dc0','#9583bb','#b888af','#614357','#41546d','#316461','#5b6945','#746347']):

            button=QPushButton();button.setFixedSize(23,20);button.setToolTip(color);button.setAccessibleName(color)

            button.setStyleSheet('background:'+color+';border:1px solid #555;border-radius:2px;padding:0;')

            button.clicked.connect(lambda _,c=color:self.apply_swatch(c));self.swatch_buttons.append(button);grid.addWidget(button,i//8,i%8)

        box.addLayout(grid);box.addStretch();colordock=self._dock('color',localize('색상 견본', self),colors)

        self.tabifyDockWidget(propdock,colordock);colordock.raise_()

        layers,box=self._box()

        self.blend_mode=QComboBox();self.blend_mode.setMinimumWidth(70);self.blend_mode.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);self.layer_spins['opacity'].setFixedWidth(48)

        self.blend_mode.setPlaceholderText(localize('서로 다른 혼합 모드', self))

        for label,mode in [(localize('표준', self),'normal'),(localize('곱하기', self),'multiply'),(localize('스크린', self),'screen'),(localize('오버레이', self),'overlay'),(localize('어둡게', self),'darken'),(localize('밝게', self),'lighten'),(localize('차이', self),'difference'),(localize('제외', self),'exclusion')]:self.blend_mode.addItem(label,mode)

        self.blend_mode.setToolTip(localize('선형 sRGB 혼합 · 선택 레이어에 적용', self));self.blend_mode.currentIndexChanged.connect(self.blend_changed)

        opacity=QHBoxLayout();opacity.addWidget(self.blend_mode,1);opacity.addWidget(QLabel(localize('불투명도', self)));opacity.addWidget(self.layer_spins['opacity']);box.addLayout(opacity)

        self.layer_selection_label=QLabel(localize('레이어 선택', self));box.addWidget(self.layer_selection_label)

        self.layer_search=QLineEdit();self.layer_search.setPlaceholderText(localize('레이어 이름 검색', self));self.layer_search.textChanged.connect(self.filter_layers);box.addWidget(self.layer_search)

        self.layers=LayerList();self.layers.relocateRequested.connect(self.relocate_layer);self.layers.dragHint.connect(lambda text:self.status.setText(text));self.layers.setObjectName('layers');self.layers.setIconSize(QSize(48,24));self.layers.currentItemChanged.connect(self.select_layer);self.layers.itemChanged.connect(self.layer_item_changed);box.addWidget(self.layers,1)

        self.layers.setSelectionMode(QListWidget.ExtendedSelection);self.layers.itemSelectionChanged.connect(self.layer_selection_changed)

        self.layers.itemDoubleClicked.connect(self.layer_double_clicked)

        actions=QHBoxLayout()

        for kind,label,callback in [('plus',localize('사진 레이어', self),lambda:self.design_add('photo')),('folder',localize('그룹 만들기', self),self.create_layer_group),('clip',localize('클리핑 마스크', self),self.toggle_clipping),('up',localize('위로', self),lambda:self.reorder_layer(1)),('down',localize('아래로', self),lambda:self.reorder_layer(-1)),('trash',localize('삭제', self),self.delete_layer)]:self.icon_button(kind,label,callback,actions)

        actions.addStretch();box.addLayout(actions);layerdock=self._dock('layers',localize('레이어', self),layers)

        self.splitDockWidget(navdock,propdock,Qt.Vertical);self.splitDockWidget(propdock,layerdock,Qt.Vertical)

        self.tabifyDockWidget(propdock,colordock);colordock.raise_()

        edits,box=self._box();names=[localize('노출', self),localize('대비', self),localize('색온도', self),localize('틴트', self),localize('하이라이트', self),localize('그림자', self),localize('흰색', self),localize('검정', self),localize('채도', self),localize('선명도', self)]

        for (key,spin),name in zip(self.edit_widgets.items(),names):box.addWidget(slider_row(name,spin))

        group=QGroupBox(localize('톤 커브', self));g=QVBoxLayout(group);g.addWidget(self.curve_graph);box.addWidget(group)

        form=QFormLayout();form.addRow(localize('색상별 조정', self),self.band)

        for label,spin in zip([localize('색조', self),localize('채도', self),localize('밝기', self)],self.band_spins):form.addRow(label,spin)

        box.addLayout(form);self.button(localize('프리셋 저장', self),self.save_preset,box);self.button(localize('프리셋 불러오기', self),self.load_preset,box);self.button(localize('보정 초기화', self),self.reset_edit,box);box.addStretch()

        sc=QScrollArea();sc.setWidgetResizable(True);sc.setWidget(edits);self._dock('adjustments',localize('사진 보정', self),sc)

        for dock in self.docks.values():

            for field in dock.findChildren((QWidget)):

                if isinstance(field,(QLineEdit,QTextEdit,QSpinBox,QDoubleSpinBox)):

                    if field in self.edit_widgets.values():

                        field.setFixedWidth(48);field.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed)

                    else:

                        field.setMinimumWidth(0);field.setSizePolicy(QSizePolicy.Ignored,field.sizePolicy().verticalPolicy())

        self.layer_spins['opacity'].setFixedWidth(48);self.layer_spins['opacity'].setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed)

        self.resizeDocks([navdock,propdock,layerdock],[170,190,340],Qt.Vertical)

        self.resizeDocks([navdock],[296],Qt.Horizontal)



    def _create_options(self):

        self.options_bar=QToolBar(localize('도구 옵션', self),self);self.options_bar.setObjectName('editor-options');self.options_bar.setMovable(False)

        self.addToolBar(Qt.TopToolBarArea,self.options_bar)

        self.option_pages=QStackedWidget();self.option_pages.setFixedHeight(30);self.option_pages.setMinimumWidth(0);self.option_pages.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);self.options_bar.addWidget(self.option_pages)

        move=QWidget();row=QHBoxLayout(move);row.setContentsMargins(4,0,4,0);row.setSpacing(5)

        row.addWidget(QLabel(localize('이동  ·  캔버스 정렬', self)))

        for kind in ('left','center','right','top','middle','bottom'):self.icon_button(kind,kind,lambda _,k=kind:self.align_layer(k),row)

        self.perspective_corners=QCheckBox(localize('원근 모서리', self));self.perspective_corners.setToolTip(localize('선택한 레이어 전체의 네 모서리를 드래그합니다. 단일 원근 레이어에는 자동 적용됩니다.', self));self.perspective_corners.toggled.connect(lambda _:self.activate_tool('transform'));row.addWidget(self.perspective_corners)

        self.button(localize('레이어 복제', self),self.duplicate_layer,row);row.addStretch();self.option_pages.addWidget(move)

        photo=QWidget();row=QHBoxLayout(photo);row.setContentsMargins(4,0,4,0)

        row.addWidget(self.before);row.addWidget(QLabel(localize('반경', self)));row.addWidget(self.radius);row.addWidget(QLabel(localize('부드러움', self)));row.addWidget(self.feather);row.addWidget(QLabel('EV'));row.addWidget(self.local_ev)

        self.photo_option_layout=row

        self.button(localize('부분 작업 삭제', self),self.remove_local,row);self.button('100%',self.full_preview,row);self.button(localize('맞춤', self),self.fit_preview,row);row.addStretch();self.option_pages.addWidget(photo)

        text=QWidget();row=QHBoxLayout(text);row.setContentsMargins(4,0,4,0);row.addWidget(QLabel(localize('텍스트 · 도형의 색상과 크기', self)))

        self.button(localize('속성 열기', self),lambda:self.show_dock('properties'),row);self.button(localize('적용', self),self.apply_layer_data,row);row.addStretch();self.option_pages.addWidget(text)

        selection=QWidget();row=QHBoxLayout(selection);row.setContentsMargins(4,0,4,0)

        self.selection_mode=QComboBox()

        for label,mode in [(localize('새 선택', self),'replace'),(localize('선택 더하기', self),'add'),(localize('선택 빼기', self),'subtract'),(localize('교차 영역', self),'intersect')]:self.selection_mode.addItem(label,mode)

        row.addWidget(self.selection_mode)

        self.selection_feather=QSpinBox();self.selection_feather.setRange(0,500);self.selection_feather.setSuffix(' px');self.selection_feather.setFixedWidth(85)

        row.addWidget(QLabel(localize('페더', self)));row.addWidget(self.selection_feather)

        self.selection_info=QLabel(localize('드래그하여 선택', self));row.addWidget(self.selection_info)

        self.button(localize('마스크 만들기', self),self.mask_from_selection,row);self.button(localize('반전', self),self.invert_selection,row);self.button(localize('해제', self),self.clear_selection,row);row.addStretch();self.option_pages.addWidget(selection)

        mask=QWidget();row=QHBoxLayout(mask);row.setContentsMargins(4,0,4,0)

        self.mask_mode=QComboBox();self.mask_mode.addItems([localize('숨기기 · 검정', self),localize('복원 · 흰색', self)]);row.addWidget(self.mask_mode)

        self.mask_size=QSpinBox();self.mask_size.setRange(1,2000);self.mask_size.setValue(80);self.mask_size.setSuffix(' px');self.mask_size.setToolTip(localize('브러시 지름 · [ 줄이기 / ] 늘리기', self));self.mask_size.setFixedWidth(85)

        self.mask_size.valueChanged.connect(lambda value:self.design_canvas.set_mask_radius(value/2));self.design_canvas.mask_radius=40

        row.addWidget(QLabel(localize('크기', self)));row.addWidget(self.mask_size)

        self.mask_softness=QSpinBox();self.mask_softness.setRange(0,100);self.mask_softness.setValue(50);self.mask_softness.setSuffix('%');self.mask_softness.setFixedWidth(65)

        row.addWidget(QLabel(localize('부드러움', self)));row.addWidget(self.mask_softness);self.button(localize('흑백 교환', self),self.swap_mask_paint,row);row.addStretch();self.option_pages.addWidget(mask)

        color=QWidget();row=QHBoxLayout(color);row.setContentsMargins(4,0,4,0)

        row.addWidget(QLabel(localize('합성 색상 · 클릭하여 선택', self)))

        self.color_tolerance=QSpinBox();self.color_tolerance.setRange(0,100);self.color_tolerance.setValue(20);self.color_tolerance.setFixedWidth(65)

        row.addWidget(QLabel(localize('허용 범위', self)));row.addWidget(self.color_tolerance)

        self.color_contiguous=QCheckBox(localize('연속 영역', self));self.color_contiguous.setChecked(True);row.addWidget(self.color_contiguous)

        self.color_resolution=QComboBox();self.color_resolution.addItem(localize('빠른 선택 · 1024px', self),1024);self.color_resolution.addItem(localize('원본 해상도', self),None);row.addWidget(self.color_resolution)

        row.addWidget(QLabel(localize('선택 연산/페더는 선택 도구 설정 사용', self)));row.addStretch();self.option_pages.addWidget(color)



    def _create_tools(self):

        self.tools_bar=QToolBar(localize('도구', self),self);self.tools_bar.setObjectName('editor-tools');self.tools_bar.setIconSize(QSize(18,18));self.tools_bar.setMovable(True);self.tools_bar.setToolButtonStyle(Qt.ToolButtonIconOnly)

        self.addToolBar(Qt.LeftToolBarArea,self.tools_bar)

        self.tool_actions={};group=QActionGroup(self);group.setExclusive(True)

        for kind,label,key in [('move',localize('이동', self),'V'),('transform',localize('자유 변형', self),'Ctrl+T'),('select_rect',localize('사각형 선택 · M', self),None),('lasso',localize('올가미 선택 · L', self),None),('color_select',localize('합성 색상 선택 · W', self),None),('mask_brush',localize('레이어 마스크 브러시', self),'K'),('view',localize('화면 이동', self),'H'),('crop',localize('자르기', self),'C'),('brush',localize('사진 부분 보정 브러시', self),'B'),('linear',localize('선형 마스크', self),None),('radial',localize('원형 마스크', self),None),('clone',localize('복제 도장', self),'S'),('heal',localize('잡티 제거', self),'J'),('text',localize('텍스트', self),'T'),('rectangle',localize('사각형', self),'U'),('ellipse',localize('타원', self),None),('photo',localize('사진 배치', self),None)]:

            if kind in ('select_rect','view','brush','text'):self.tools_bar.addSeparator()

            action=QAction(tool_icon(kind),label,self);action.setCheckable(True)

            if key:action.setShortcut(key)

            action.triggered.connect(lambda _,k=kind:self.activate_tool(k));group.addAction(action);self.tools_bar.addAction(action);self.tool_actions[kind]=action

        self.tool_actions['move'].setChecked(True)

        swap=QAction(self);swap.setShortcut('X');swap.triggered.connect(self.swap_mask_paint);self.addAction(swap)

        self.tools_bar.addSeparator();action=self.tools_bar.addAction(tool_icon('fit'),localize('화면 맞춤', self));action.triggered.connect(self.fit_active)



    def activate_tool(self,kind):

        self.design_canvas.cancel_gesture()

        self.tool_actions[kind].setChecked(True)

        focus=self.focusWidget()

        if isinstance(focus,(QLineEdit,QTextEdit,QSpinBox,QDoubleSpinBox)): focus.clearFocus()

        if kind in ('photo','text','rectangle','ellipse'):

            self.tabs.setCurrentIndex(2);self.design_add(kind);self.option_pages.setCurrentIndex(2);return

        if kind in ('move','transform'):self.tabs.setCurrentIndex(2);self.design_canvas.tool=kind;self.option_pages.setCurrentIndex(0);self.update_outline();return

        if kind in ('select_rect','lasso','color_select','mask_brush'):

            self.tabs.setCurrentIndex(2);self.design_canvas.tool=kind

            self.option_pages.setCurrentIndex(4 if kind=='mask_brush' else (5 if kind=='color_select' else 3))

            self.update_outline()

            if kind=='mask_brush':

                self.show_dock('properties')

                QTimer.singleShot(0,lambda:self.docks['properties'].widget().ensureWidgetVisible(self.mask_group))

            return

        if kind=='view':

            if self.tabs.currentIndex()==1:self.tool.setCurrentIndex(self.tool.findData('view'))

            else:self.design_canvas.tool='view'

            return

        layer=self.current_layer()

        if layer and layer['kind']=='photo':self.photo_id=layer['data']['photo_id'];self.refresh()

        self.tabs.setCurrentIndex(1);self.tool.setCurrentIndex(self.tool.findData(kind));self.option_pages.setCurrentIndex(1)



    def workspace_changed(self,index):

        self.design_canvas.cancel_gesture()

        if not self.editor_ready:return

        self.workspace_choice.blockSignals(True);self.workspace_choice.setCurrentIndex(index);self.workspace_choice.blockSignals(False)

        self.library.setVisible(index==0)

        for key in ('navigator','properties','color','layers'):self.docks[key].setVisible(index==2)

        self.docks['adjustments'].setVisible(index==1)

        if 'advanced' in self.docks:self.docks['advanced'].setVisible(False)

        self.tools_bar.setVisible(index!=0);self.options_bar.setVisible(index!=0)

        self.update_photo_options()

        page={'select_rect':3,'lasso':3,'color_select':5,'mask_brush':4}.get(self.design_canvas.tool,0)

        self.option_pages.setCurrentIndex(1 if index==1 else page);self.nav_stack.setCurrentIndex(0 if index==1 else 1)

        if index==2 and self.design_canvas.tool in self.tool_actions:self.tool_actions[self.design_canvas.tool].setChecked(True)

        if index==2:self.docks['color'].raise_()

        self.update_readiness()
        if hasattr(self,'debounce'):self.request_preview()



    def show_dock(self,key):

        self.docks[key].show();self.docks[key].raise_()



    def reset_workspace(self):

        self.restoreState(self.default_dock_state);self.workspace_changed(self.tabs.currentIndex())



    def design_add(self,kind):

        self.add_design_layer(kind);self.design_canvas.tool='move'

        if kind in ('text','rectangle','ellipse'):self.show_dock('properties')



    def filter_layers(self,text):

        self.filter_group_rows(text)



    def refresh_layers(self):

        context=(str(self.project.root),self.document_id)

        selected_headers=[item.data(Qt.UserRole)[len(PREFIX):] for item in self.layers.selectedItems() if isinstance(item.data(Qt.UserRole),str) and item.data(Qt.UserRole).startswith(PREFIX)]

        chosen=self.selected_layer_ids() if getattr(self,'layers_context',None)==context else []

        if self.layer_id not in chosen:chosen=[self.layer_id] if self.layer_id else []

        pending=getattr(self,'pending_layer_selection',None);self.pending_layer_selection=None

        if pending is not None:chosen=pending

        self.layers_context=context

        super().refresh_layers()

        self.layers.blockSignals(True)

        for i in range(self.layers.count()):self.layers.item(i).setSelected(self.layers.item(i).data(Qt.UserRole) in chosen)

        self.layers.blockSignals(False)

        if hasattr(self,'layer_search'):self.filter_layers(self.layer_search.text())

        doc=self.project.state['documents'].get(self.document_id)

        self.design_canvas.document_layers=deepcopy(doc['layers']) if doc else []

        for layer in self.design_canvas.document_layers:

            chain=ancestors(doc,layer.get('group_id'))

            layer['visible']=layer.get('visible',True) and all(doc['groups'][g]['visible'] for g in chain)

            layer['locked']=layer.get('locked',False) or group_locked(doc,layer)

        self.design_canvas.document_size=(doc['width'],doc['height']) if doc else (1,1)

        if doc:

            from core.layer_masks import layer_mask_pixels

            from core.studio_render import mask_pixels

            self.layers.blockSignals(True)

            for i in range(self.layers.count()):

                item=self.layers.item(i);layer=next((v for v in doc['layers'] if v.get('id')==item.data(Qt.UserRole)),None)

                if not layer or not layer['mask']:continue

                mask=deepcopy(layer['mask'])

                enabled=mask.get('enabled',True)

                if mask.get('kind')=='paint':mask['enabled']=True

                pixels=(layer_mask_pixels(mask,28,28,layer,(0,0,1,1),mask_pixels)*255).astype('uint8')

                img=QImage(pixels.data,28,28,pixels.strides[0],QImage.Format_Grayscale8).copy()

                thumb=QPixmap(60,28);thumb.fill(Qt.transparent);painter=QPainter(thumb)

                painter.drawPixmap(0,0,item.icon().pixmap(28,28));painter.drawImage(32,0,img)

                painter.setPen(QColor('#999999'));painter.drawRect(32,0,27,27)

                if not enabled:painter.setPen(QColor('#ef7979'));painter.drawLine(32,0,59,27)

                painter.end();item.setIcon(QIcon(thumb));item.setToolTip(layer['name']+localize(' · 마스크', self)+(localize(' 사용', self) if enabled else localize(' 해제', self))+localize(' · 두 번 클릭하여 마스크 편집', self))

            self.layers.blockSignals(False)

        selected_headers=[key for key in selected_headers if doc and {l['id'] for l in members(doc,key)}<=set(chosen)]

        self.group_rows(selected_headers if context==getattr(self,'selection_context',None) else ())

        self.select_layer(self.layers.currentItem())

        context=(str(self.project.root),self.document_id)

        if getattr(self,'selection_context',None)!=context:

            self.selection_context=context;self.clear_selection(reset_history=True);self.design_canvas.cancel_gesture()

        self.layer_selection_changed()



    def selected_layer_ids(self):

        doc=self.project.state['documents'].get(self.document_id,{})

        valid={layer.get('id') for layer in doc.get('layers',[])}

        result=set()

        for item in self.layers.selectedItems():

            key=item.data(Qt.UserRole)

            if key in valid:result.add(key)

            elif isinstance(key,str) and key.startswith(PREFIX):

                result.update(l['id'] for l in members(doc,key[len(PREFIX):]))

        return [l['id'] for l in doc.get('layers',[]) if l.get('id') in result]



    def layer_selection_changed(self):

        if not hasattr(self,'blend_mode'):return

        ids=self.selected_layer_ids();doc=self.project.state['documents'].get(self.document_id,{})

        selected=[layer for layer in doc.get('layers',[]) if layer.get('id') in ids]

        modes={layer.get('blend_mode','normal') for layer in selected}

        self.blend_mode.blockSignals(True);self.blend_mode.setCurrentIndex(self.blend_mode.findData(next(iter(modes))) if len(modes)==1 else -1);self.blend_mode.blockSignals(False)

        self.blend_mode.setEnabled(bool(selected))

        self.layer_selection_label.setText(str(len(ids))+localize('개 선택 · Ctrl/Shift로 추가', self) if ids else localize('레이어 선택', self))

        for key in ('width','height','rotation'):self.layer_spins[key].setEnabled(len(ids)==1)

        self.update_outline()



        self.load_advanced_controls()

        group=self.active_group_header()

        title=(localize('그룹 · ', self)+doc['groups'][group]['name']+' · '+str(len(ids))+localize('개', self)) if group else (localize('레이어 · ', self)+selected[0]['name'] if len(selected)==1 else str(len(ids))+localize('개 레이어 선택', self))

        from PyQt5.QtGui import QFontMetrics

        self.layer_selection_label.setToolTip(title)

        self.layer_selection_label.setText(QFontMetrics(self.layer_selection_label.font()).elidedText(title,Qt.ElideRight,260))

        self.text_section.setVisible(not group and len(selected)==1 and selected[0]['kind']=='text')

        self.blend_mode.setEnabled(bool(selected) and not group)

        self.layer_spins['opacity'].setEnabled(bool(selected) and not group)

        self.layer_visible.setEnabled(bool(selected) and not group);self.layer_locked.setEnabled(bool(selected) and not group)

        self.mask_group.setVisible(bool(selected) and not group)

        if any('warp' in layer for layer in selected):

            for key in ('width','height','rotation'):self.layer_spins[key].setEnabled(False)

        if group:

            for spin in self.layer_spins.values():spin.setEnabled(False)

        self.update_readiness()



    def update_readiness(self):
        if not hasattr(self, 'empty_document'): return
        document = self.document_id in self.project.state['documents']
        photo = self.photo_id in self.project.state['photos']
        design = document and self.tabs.currentIndex() == 2
        selected = bool(self.selected_layer_ids()) and design
        self.empty_document.setVisible(not document)
        self.empty_photo.setVisible(not photo)
        self.empty_document.setEnabled(not self.io_busy)
        self.empty_photo.setEnabled(not self.io_busy)
        ready = {
            'export_current': design if self.tabs.currentIndex()==2 else photo,
            'export_psd_dialog': design,
            'duplicate_layer': selected, 'delete_layer': selected,
            'local_transform_dialog': selected, 'world_transform_dialog': selected,
            'multi_transform_dialog': selected, 'create_layer_group': selected,
            'edit_linked': design and bool(self.current_layer() and self.current_layer()['kind']=='photo'),
            'reset_edit': photo, 'rotate': photo,
            'export_photos': bool(self.selected()), 'sync_photos': photo,
            'save_preset': photo, 'load_preset': photo,
            'undo': bool(self.project._undo), 'redo': bool(self.project._redo),
        }
        for command, enabled in ready.items():
            for action in self.command_actions.get(command, []): action.setEnabled(enabled)
            for widget in self.command_widgets.get(command, []): widget.setEnabled(enabled)
        self.update_design_zoom()

    def batch_layer_action(self,operation,values=None):

        from core.studio_commands import edit_layers

        ids=self.selected_layer_ids()

        if not ids:return

        try:

            result=edit_layers(self.project,self.document_id,ids,operation,values)

            self.pending_layer_selection=result

            if self.layer_id not in result:self.layer_id=result[-1] if result else None

            self.refresh()

        except ValueError as error:self.error(error)



    def blend_changed(self,index):

        if index>=0 and not self.loading_controls:self.batch_layer_action('update',{'blend_mode':self.blend_mode.itemData(index)})



    def layer_property(self,key):

        if self.loading_controls:return

        layer=self.current_layer();ids=self.selected_layer_ids()

        if len(ids)>1 and layer:

            if key=='opacity':self.batch_layer_action('update',{'opacity':self.layer_spins[key].value()})

            elif key in ('x','y'):

                delta=self.layer_spins[key].value()-layer[key]

                self.batch_layer_action('move',{'dx':delta if key=='x' else 0.,'dy':delta if key=='y' else 0.})

        else:super().layer_property(key)



    def move_layer(self,points,alt):

        doc=self.project.state['documents'].get(self.document_id)

        if doc and any(l['kind']=='adjustment' for l in doc['layers'] if l.get('id') in self.selected_layer_ids()):

            self.status.setText(localize('조정 레이어를 제외하고 이동하세요.', self));return

        if doc:self.batch_layer_action('move',{'dx':(points[-1][0]-points[0][0])*doc['width'],'dy':(points[-1][1]-points[0][1])*doc['height']})



    def delete_layer(self):

        self.batch_layer_action('delete')



    def reorder_layer(self,offset):

        from core.layer_groups import reorder_block

        group=self.active_group_header();layer=self.current_layer()

        if not group and len(self.selected_layer_ids())!=1:

            self.status.setText(localize('레이어 하나 또는 그룹 행을 선택하세요.', self));return

        if not group and not layer:return

        try:

            reorder_block(self.project,self.document_id,group or layer['id'],offset,group=bool(group))

            self.refresh()

            if group:self.select_group_header(group)

        except ValueError as error:self.error(error)



    def align_layer(self,kind):

        if len(self.selected_layer_ids())>1:

            self.status.setText(localize('정렬할 레이어 하나를 선택하세요.', self));return

        layer=self.current_layer()

        if layer and 'warp' in layer:

            from core.layer_transform import selection_bounds

            doc=self.project.state['documents'][self.document_id];x0,y0,x1,y1=selection_bounds(doc,[layer['id']])

            delta={'left':(-x0,0),'center':((doc['width']-x0-x1)/2,0),'right':(doc['width']-x1,0),'top':(0,-y0),'middle':(0,(doc['height']-y0-y1)/2),'bottom':(0,doc['height']-y1)}.get(kind)

            if delta:self.batch_layer_action('move',{'dx':delta[0],'dy':delta[1]})

            return

        super().align_layer(kind)



    def update_outline(self):

        super().update_outline()

        canvas=self.design_canvas

        old=getattr(self,'multi_outline',None)

        if old is not None:canvas.scene().removeItem(old);self.multi_outline=None

        if not hasattr(self,'layers'):return

        ids=self.selected_layer_ids()

        layer=self.current_layer()

        canvas.projective_handles=bool(ids) and ((len(ids)==1 and bool(layer) and bool(layer.get('warp'))) or (hasattr(self,'perspective_corners') and self.perspective_corners.isChecked()))

        if hasattr(self,'perspective_corners'):self.perspective_corners.setEnabled(bool(ids))

        if len(ids)<2:

            layer=self.current_layer();doc=self.project.state['documents'].get(self.document_id)

            if layer and doc and 'warp' in layer:

                from core.layer_geometry import layer_corners

                canvas.outline([[x/doc['width'],y/doc['height']] for x,y in layer_corners(layer)])

            return

        canvas.outline(None)

        if canvas.tool not in ('move','transform'):return

        if canvas.tool=='transform':

            from core.layer_transform import selection_bounds

            doc=self.project.state['documents'][self.document_id];x0,y0,x1,y1=selection_bounds(doc,ids)

            canvas.outline([[x/doc['width'],y/doc['height']] for x,y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]])

        import math

        doc=self.project.state['documents'][self.document_id];w,h=canvas.image_size;path=QPainterPath()

        for layer in doc['layers']:

            if layer.get('id') not in ids:continue

            from core.layer_geometry import layer_corners

            for i,(x,y) in enumerate(layer_corners(layer)):

                px=x*w/doc['width'];py=y*h/doc['height']

                path.moveTo(px,py) if i==0 else path.lineTo(px,py)

            path.closeSubpath()

        pen=QPen(QColor('#ccccdd'),1,Qt.DashLine);pen.setCosmetic(True)

        self.multi_outline=canvas.scene().addPath(path,pen);self.multi_outline.setZValue(101)



    def select_layer(self,current,previous=None):

        self.design_canvas.cancel_gesture()

        key=current.data(Qt.UserRole) if current else None

        if isinstance(key,str) and key.startswith(PREFIX):

            doc=self.project.state['documents'].get(self.document_id,{})

            member_ids={l['id'] for l in members(doc,key[len(PREFIX):])}

            current=next((self.layers.item(i) for i in range(self.layers.count()) if self.layers.item(i).data(Qt.UserRole) in member_ids),None)

        super().select_layer(current,previous)

        if not hasattr(self,'mask_info'):return

        layer=self.current_layer();mask=layer['mask'] if layer else None

        self.mask_info.setText((localize('브러시 · ', self)+str(len(mask['strokes']))+localize('회', self) if mask.get('kind')=='paint' else localize('기본 ', self)+mask['kind']) if mask else localize('마스크 없음', self))

        self.mask_enabled.blockSignals(True);self.mask_enabled.setChecked(bool(mask and mask.get('enabled',True)))

        self.mask_enabled.setEnabled(bool(mask and not layer['locked']));self.mask_enabled.blockSignals(False)

        self.load_advanced_controls()



    def layer_item_changed(self,item):

        key=item.data(Qt.UserRole)

        if isinstance(key,str) and key.startswith(PREFIX):

            self.update_group(key[len(PREFIX):],{'visible':item.checkState()==Qt.Checked});return

        super().layer_item_changed(item)



    def set_selection(self,points,mode=None):

        if not self.document_id:return

        from ui.selection_geometry import combine_selection

        try:

            result=combine_selection(getattr(self.design_canvas,'area_points',None),getattr(self.design_canvas,'area_inverted',False),points,mode or self.selection_mode.currentData())

            self.set_selection_state(result)

        except ValueError as error:self.error(error)



    def select_color_at(self,point):

        if not self.document_id or self.io_busy:return

        from core.project import Project

        from core.studio_render import render_document

        from core.color_selection import color_selection,check_color_budget

        snapshot=Project(self.project.root,self.project.state);key=self.document_id

        tolerance=self.color_tolerance.value();contiguous=self.color_contiguous.isChecked();mode=self.selection_mode.currentData();max_side=self.color_resolution.currentData()

        def run(cancelled,progress):

            doc=snapshot.state['documents'][key]

            if max_side is None:check_color_budget(doc['width'],doc['height'])

            frame=render_document(snapshot,key,max_side=max_side,cancelled=cancelled)

            return color_selection(frame,point,tolerance,contiguous,cancelled)

        self.run_io(localize('합성 색상 선택 계산 중', self),run,lambda result:self.set_selection(result,mode=mode))



    def offset_selection_dialog(self):

        from PyQt5.QtWidgets import QInputDialog

        from ui.selection_geometry import offset_selection

        selection=getattr(self.design_canvas,'area_points',None)

        if not selection or not self.document_id:return

        pixels,ok=QInputDialog.getInt(self,localize('선택 확장 / 축소', self),localize('문서 px · 양수: 확장 / 음수: 축소', self),5,-500,500)

        if ok:

            doc=self.project.state['documents'][self.document_id]

            try:self.set_selection(offset_selection(selection,self.design_canvas.area_inverted,doc['width'],doc['height'],pixels),mode='replace')

            except ValueError as error:self.error(error)



    def refine_selection_dialog(self):

        from ui.refine_selection import RefineSelectionDialog

        from PyQt5.QtWidgets import QDialog

        points=getattr(self.design_canvas,'area_points',None)

        if points is None or not self.document_id or self.io_busy:

            self.status.setText(localize('선택 영역을 먼저 지정하세요.', self));return

        if self.jobs or self.debounce.isActive():

            self.status.setText(localize('화면 갱신이 끝난 뒤 경계 다듬기를 여세요.', self));return

        dialog=RefineSelectionDialog(self.project.state['documents'][self.document_id],points,self.design_canvas.area_inverted,self.selection_feather.value(),self.design_canvas.image_item.pixmap().toImage(),self)

        if dialog.exec_()==QDialog.Accepted:

            self.set_selection_state(dialog.result_selection)

            self.selection_feather.setValue(dialog.feather.value())



    def selection_history(self):

        from core.selection_history import SelectionHistory

        if not hasattr(self,'_selection_history'):self._selection_history=SelectionHistory()

        return self._selection_history



    def show_selection_state(self):

        points,inverted=self.selection_history().current

        self.design_canvas.set_area(deepcopy(points),inverted)

        if hasattr(self,'selection_info'):

            self.selection_info.setText(localize('드래그하여 선택', self) if points is None else (localize('선택 영역 반전', self) if inverted else (localize('선택 영역 비어 있음', self) if isinstance(points,dict) and not points['rings'] else localize('선택 영역 활성', self))))



    def set_selection_state(self,points=None,inverted=False):

        self.selection_history().change(points,inverted);self.show_selection_state()



    def clear_selection(self,reset_history=False):

        if reset_history:self.selection_history().reset();self.show_selection_state()

        else:self.set_selection_state()



    def undo_selection(self):

        self.design_canvas.cancel_gesture()

        if self.selection_history().undo():self.show_selection_state()



    def redo_selection(self):

        self.design_canvas.cancel_gesture()

        if self.selection_history().redo():self.show_selection_state()



    def select_all_area(self):

        self.set_selection([[0.,0.],[1.,0.],[1.,1.],[0.,1.]],mode="replace")



    def invert_selection(self):

        points=getattr(self.design_canvas,'area_points',None)

        if points:

            inverted=not self.design_canvas.area_inverted;self.set_selection_state(points,inverted)



    def mask_from_selection(self):

        from core.layer_masks import selection_mask

        target=self.group_mask_target()

        if target:

            points=getattr(self.design_canvas,'area_points',None)

            if points:self.apply_group_mask(selection_mask(target[1],target[0],points,self.design_canvas.area_inverted,self.selection_feather.value()));self.clear_selection()

            return

        layer=self.current_layer();points=getattr(self.design_canvas,'area_points',None)

        if not layer or not points:

            self.status.setText(localize('레이어와 선택 영역을 먼저 지정하세요.', self));return

        if layer['locked']:self.status.setText(localize('잠긴 레이어입니다.', self));return

        try:mask=selection_mask(layer,self.project.state['documents'][self.document_id],points,self.design_canvas.area_inverted,self.selection_feather.value())

        except ValueError as error:self.error(error);return

        self.layer_update({'mask':mask});self.clear_selection();self.show_dock('properties')



    def refresh(self):

        if hasattr(self,'design_canvas'):self.design_canvas.cancel_gesture()

        super().refresh()
        self.update_readiness()



    def preview_layer_mask(self,points):

        if points is None:

            if self.brush_preview_state is not None:

                self.brush_preview_state=None;self.debounce.stop();self.request_preview()

            return

        from core.layer_masks import paint_stroke

        layer=self.current_layer();target=self.group_mask_target()

        if not target and (not layer or layer['locked']):return

        doc=self.project.state['documents'].get(self.document_id)

        if not doc:return

        if layer and group_locked(doc,layer):return

        try:

            existing,geometry=(target[2],target[1]) if target else (layer['mask'],layer)

            mask=paint_stroke(existing,geometry,doc,points,self.mask_size.value()/2,self.mask_softness.value()/100,

                              self.mask_mode.currentIndex()==1,getattr(self.design_canvas,'area_points',None),

                              getattr(self.design_canvas,'area_inverted',False),self.selection_feather.value())

            state=deepcopy(self.project.state);document=state['documents'][self.document_id]

            if target:

                group=document['groups'][self.active_group_header()]

                if group.get('locked'):return

                group['mask']=mask

                if group.get('blend_mode','pass')=='pass':group['blend_mode']='normal'

            else:next(l for l in document['layers'] if l['id']==layer['id'])['mask']=mask

            self.brush_preview_state=state

            # Throttle without restarting on every move so continuous strokes render.

            if not self.debounce.isActive():self.debounce.start(90)

        except ValueError as error:self.status.setText(localize(str(error), self))



    def paint_layer_mask(self,points):

        from core.layer_masks import paint_stroke

        target=self.group_mask_target()

        if target:

            try:self.apply_group_mask(paint_stroke(target[2],target[1],target[0],points,self.mask_size.value()/2,self.mask_softness.value()/100,self.mask_mode.currentIndex()==1,getattr(self.design_canvas,'area_points',None),getattr(self.design_canvas,'area_inverted',False),self.selection_feather.value()))

            except ValueError as error:self.error(error)

            return

        layer=self.current_layer()

        if not layer or layer['locked']:

            self.status.setText(localize('잠기지 않은 레이어를 선택하세요.', self));return

        try:

            mask=paint_stroke(layer['mask'],layer,self.project.state['documents'][self.document_id],points,

                              self.mask_size.value()/2,self.mask_softness.value()/100,self.mask_mode.currentIndex()==1,

                              getattr(self.design_canvas,'area_points',None),getattr(self.design_canvas,'area_inverted',False),self.selection_feather.value())

            self.layer_update({'mask':mask})

        except ValueError as error:self.error(error)



    def swap_mask_paint(self):

        if self.design_canvas.tool=='mask_brush':self.mask_mode.setCurrentIndex(1-self.mask_mode.currentIndex())



    def invert_layer_mask(self):

        from core.layer_masks import paint_mask

        target=self.group_mask_target()

        if target:

            mask=paint_mask(target[2]);mask['invert']=not mask['invert'];self.apply_group_mask(mask);return

        layer=self.current_layer()

        if layer and layer['mask']:

            mask=paint_mask(layer['mask']);mask['invert']=not mask['invert'];self.layer_update({'mask':mask})



    def toggle_layer_mask(self,enabled):

        from core.layer_masks import paint_mask

        layer=self.current_layer()

        if layer and layer['mask']:

            mask=paint_mask(layer['mask']);mask['enabled']=enabled;self.layer_update({'mask':mask})



    def duplicate_layer(self):

        self.batch_layer_action('duplicate')



    def fit_active(self):

        if self.tabs.currentIndex()==1:self.fit_preview()

        else:self.design_canvas.fit()



    def export_current(self):

        if self.tabs.currentIndex()==2:self.export_document()

        else:self.tabs.setCurrentIndex(0)



    def run_io(self,label,function,done,cancellable=True,on_finish=None):

        if self.io_busy:return

        def restore():

            for dock in self.docks.values():dock.setEnabled(True)

            self.tools_bar.setEnabled(True);self.options_bar.setEnabled(True);self.menuBar().setEnabled(True)

            self.update_readiness()
            if on_finish:on_finish()

        for dock in self.docks.values():dock.setEnabled(False)

        self.tools_bar.setEnabled(False);self.options_bar.setEnabled(False);self.menuBar().setEnabled(False)

        self.empty_document.setEnabled(False); self.empty_photo.setEnabled(False)
        super().run_io(label,function,done,cancellable,restore)



    def pick_layer(self,key):

        for i in range(self.layers.count()):

            if self.layers.item(i).data(Qt.UserRole)==key:

                if key in self.selected_layer_ids():

                    self.layers.setCurrentItem(self.layers.item(i),QItemSelectionModel.NoUpdate);return

                self.layers.setCurrentRow(i);return

        self.layers.setCurrentRow(-1)



    def apply_multi_transform(self,scale,angle,pivot=None):

        from core.layer_transform import transform_layers

        ids=self.selected_layer_ids()

        if not ids:return

        try:

            transform_layers(self.project,self.document_id,ids,scale,angle,pivot)

            self.pending_layer_selection=ids;self.refresh()

        except ValueError as error:self.error(error)



    def apply_local_transform(self,scale_x=1,scale_y=1,flip_x=False,flip_y=False):

        from core.layer_transform import transform_local_layers

        ids=self.selected_layer_ids()

        if not ids:return

        try:

            transform_local_layers(self.project,self.document_id,ids,scale_x,scale_y,flip_x,flip_y)

            self.pending_layer_selection=ids;self.refresh()

        except ValueError as error:self.error(error)



    def local_transform_dialog(self):

        from ui.local_transform import LocalTransformDialog

        from PyQt5.QtWidgets import QDialog

        if not self.selected_layer_ids():return

        dialog=LocalTransformDialog(self)

        if dialog.exec_()==QDialog.Accepted:self.apply_local_transform(dialog.scale_x.value()/100,dialog.scale_y.value()/100,dialog.flip_x.isChecked(),dialog.flip_y.isChecked())



    def apply_world_transform(self,scale_x=1,scale_y=1,shear_x=0,shear_y=0,offsets=None):

        from core.layer_transform import selection_bounds,world_transform_matrix,transform_world_layers

        ids=self.selected_layer_ids()

        if not ids:return

        try:

            bounds=selection_bounds(self.project.state['documents'][self.document_id],ids)

            matrix=world_transform_matrix(bounds,scale_x,scale_y,shear_x,shear_y,offsets)

            transform_world_layers(self.project,self.document_id,ids,matrix)

            self.pending_layer_selection=ids;self.refresh()

        except ValueError as error:self.error(error)



    def world_transform_dialog(self):

        from ui.world_transform import WorldTransformDialog

        from PyQt5.QtWidgets import QDialog

        if not self.selected_layer_ids():return

        dialog=WorldTransformDialog(self)

        if dialog.exec_()==QDialog.Accepted:self.apply_world_transform(*dialog.values())



    def multi_transform_dialog(self):

        from PyQt5.QtWidgets import QInputDialog

        if not self.selected_layer_ids():return

        scale,ok=QInputDialog.getDouble(self,localize('선택 함께 변형', self),localize('비율 유지 배율 (%)', self),100,1,10000,2)

        if not ok:return

        angle,ok=QInputDialog.getDouble(self,localize('선택 함께 변형', self),localize('공통 중심 회전 (도)', self),0,-360,360,2)

        if ok:self.apply_multi_transform(scale/100,angle)



    def resize_corner(self,corner,point):

        import math

        if len(self.selected_layer_ids())>1:

            if self.perspective_corners.isChecked():

                from core.layer_transform import move_selection_corner

                ids=self.selected_layer_ids();doc=self.project.state['documents'][self.document_id]

                try:

                    move_selection_corner(self.project,self.document_id,ids,corner,[point[0]*doc['width'],point[1]*doc['height']])

                    self.pending_layer_selection=ids;self.refresh()

                except ValueError as error:self.status.setText(localize(str(error), self))

                return

            from core.layer_transform import selection_bounds

            doc=self.project.state['documents'][self.document_id];x0,y0,x1,y1=selection_bounds(doc,self.selected_layer_ids())

            corners=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)];ax,ay=corners[(corner+2)%4];cx,cy=corners[corner]

            dx,dy=cx-ax,cy-ay;tx,ty=point[0]*doc['width']-ax,point[1]*doc['height']-ay

            scale=max(.01,min(100,(tx*dx+ty*dy)/max(dx*dx+dy*dy,1e-8)))

            self.apply_multi_transform(scale,0,(ax,ay));return

        layer=self.current_layer()

        if not layer or layer['locked']:return

        doc=self.project.state['documents'][self.document_id]

        if 'warp' in layer or self.perspective_corners.isChecked():

            from core.layer_transform import move_projective_corner

            try:

                move_projective_corner(self.project,self.document_id,layer['id'],corner,[point[0]*doc['width'],point[1]*doc['height']])

                self.pending_layer_selection=[layer['id']];self.refresh()

            except ValueError as error:self.status.setText(localize(str(error), self))

            return

        c,s=math.cos(math.radians(layer['rotation'])),math.sin(math.radians(layer['rotation']))

        anchors=[(layer['width'],layer['height']),(0,layer['height']),(0,0),(layer['width'],0)]

        ax,ay=anchors[corner];anchor_x=layer['x']+c*ax-s*ay;anchor_y=layer['y']+s*ax+c*ay

        dx,dy=point[0]*doc['width']-anchor_x,point[1]*doc['height']-anchor_y

        lx,ly=c*dx+s*dy,-s*dx+c*dy

        w=max(1.,min(100000.,lx*(-1 if corner in (0,3) else 1)))

        h=max(1.,min(100000.,ly*(-1 if corner in (0,1) else 1)))

        anchors=[(w,h),(0,h),(0,0),(w,0)];ax,ay=anchors[corner]

        self.layer_update({'x':anchor_x-c*ax+s*ay,'y':anchor_y-s*ax-c*ay,'width':w,'height':h})



    def update_photo_options(self):

        if not hasattr(self,'photo_option_layout'):return

        kind=self.tool.currentData()

        if hasattr(self,'tool_actions') and self.tabs.currentIndex()==1:self.tool_actions[kind].setChecked(True)

        local=kind in ('brush','linear','radial','clone','heal')

        for index in range(1,7):

            widget=self.photo_option_layout.itemAt(index).widget()

            if widget:widget.setVisible(local and (index not in (5,6) or kind in ('brush','linear','radial')))



    def closeEvent(self,event):

        state=self.saveState()

        super().closeEvent(event)

        if event.isAccepted():QSettings('RawBaker','RawBaker').setValue('editor/workspace-v1',state)



    def update_title(self):

        super().update_title()

        self.setWindowTitle(self.windowTitle().replace('RawBaker Studio','RawBaker Editor'))



    def import_dialog(self):

        paths,_=QFileDialog.getOpenFileNames(self,localize('사진 열기', self),'','Images (*.jpg *.jpeg *.png *.tif *.tiff *.webp *.bmp *.cr2 *.cr3 *.nef *.arw *.dng *.orf *.rw2 *.raf)')

        if paths:

            self.tabs.setCurrentIndex(1);self.import_paths(paths)



    def apply_layer_data(self):

        if self.current_layer() and self.current_layer()['kind']=='adjustment':return

        super().apply_layer_data()

