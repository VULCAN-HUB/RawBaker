"""Inspector for group compositing and non-destructive adjustment layers."""
from ui.editor_i18n import localize
from copy import deepcopy
from PyQt5.QtWidgets import QWidget,QFormLayout,QComboBox,QDoubleSpinBox,QPushButton,QLabel,QScrollArea,QVBoxLayout
from core.layer_groups import members
from core.layer_masks import paint_stroke,selection_mask,paint_mask
from ui.editor_groups import PREFIX


class EditorAdvanced:
    def create_advanced_controls(self):
        widget=QWidget();layout=QVBoxLayout(widget);layout.setContentsMargins(10,8,10,8);layout.setSpacing(6)
        self.advanced_loading=False
        self.advanced_title=QLabel();layout.addWidget(self.advanced_title)
        self.group_section=QWidget();form=QFormLayout(self.group_section);form.setContentsMargins(0,0,0,0);form.setSpacing(6)
        layout.addWidget(self.group_section)
        self.group_mode=QComboBox()
        for text,mode in [(localize('통과', self),'pass'),(localize('표준 · 격리', self),'normal'),(localize('곱하기', self),'multiply'),(localize('스크린', self),'screen'),(localize('오버레이', self),'overlay'),(localize('어둡게', self),'darken'),(localize('밝게', self),'lighten'),(localize('차이', self),'difference'),(localize('제외', self),'exclusion')]:self.group_mode.addItem(text,mode)
        form.addRow(localize('그룹 합성', self),self.group_mode)
        self.group_opacity=QDoubleSpinBox();self.group_opacity.setRange(0,1);self.group_opacity.setSingleStep(.05);self.group_opacity.setKeyboardTracking(False);form.addRow(localize('불투명도', self),self.group_opacity)
        self.group_mode.currentIndexChanged.connect(self.change_group_mode);self.group_opacity.valueChanged.connect(self.change_group_opacity)
        self.group_mask_label=QLabel();form.addRow(self.group_mask_label)
        for text,callback in [(localize('선택으로 그룹 마스크', self),self.mask_from_selection),(localize('그룹 마스크 브러시', self),lambda:self.activate_tool('mask_brush')),(localize('그룹 마스크 반전', self),self.invert_layer_mask),(localize('그룹 마스크 제거', self),lambda:self.apply_group_mask(None))]:
            button=QPushButton(text);button.clicked.connect(callback);form.addRow(button)
        self.adjustment_section=QWidget();form=QFormLayout(self.adjustment_section);form.setContentsMargins(0,0,0,0);form.setSpacing(6)
        layout.addWidget(self.adjustment_section);layout.addStretch(1)
        self.adjustment_fields={}
        for key,title,low,high,step,default in [('exposure',localize('노출', self),-10,10,.1,0),('contrast',localize('대비', self),0,3,.05,1),('saturation',localize('채도', self),0,3,.05,1),('temperature',localize('색온도', self),-100,100,1,0),('tint',localize('틴트', self),-100,100,1,0)]:
            spin=QDoubleSpinBox();spin.setRange(low,high);spin.setSingleStep(step);spin.setValue(default);spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda value,k=key:self.change_adjustment(k,value));form.addRow(title,spin);self.adjustment_fields[key]=spin
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(widget);scroll.setMinimumHeight(100)
        dock=self._dock('advanced',localize('그룹 · 조정', self),scroll);self.tabifyDockWidget(self.docks['properties'],dock);dock.hide()

    def active_group_header(self):
        item=self.layers.currentItem();key=item.data(256) if item else None
        return key[len(PREFIX):] if isinstance(key,str) and key.startswith(PREFIX) else None

    def load_advanced_controls(self):
        if not hasattr(self,'advanced_title'):return
        group_id=self.active_group_header();layer=self.current_layer();doc=self.project.state['documents'].get(self.document_id,{})
        group=doc.get('groups',{}).get(group_id);adjustment=bool(layer and layer['kind']=='adjustment' and not group)
        self.advanced_loading=True
        self.advanced_title.setText(group['name'] if group else (localize('조정 레이어', self) if adjustment else localize('그룹 또는 조정 레이어를 선택하세요.', self)))
        self.group_mode.setEnabled(bool(group));self.group_opacity.setEnabled(bool(group))
        self.group_section.setVisible(bool(group));self.adjustment_section.setVisible(adjustment)
        if group:
            self.group_mode.setCurrentIndex(self.group_mode.findData(group.get('blend_mode','pass')));self.group_opacity.setValue(group.get('opacity',1))
        self.group_mask_label.setText(localize('그룹 마스크 있음', self) if group and group.get('mask') else localize('그룹 마스크 없음', self))
        for key,spin in self.adjustment_fields.items():
            spin.setEnabled(adjustment)
            if adjustment:spin.setValue(layer['data']['adjustments'].get(key,1 if key in ('contrast','saturation') else 0))
        self.advanced_loading=False
        if (group or adjustment) and self.tabs.currentIndex()==2:self.show_dock('advanced')
        elif self.docks['advanced'].isVisible():
            self.docks['advanced'].hide()
            if self.tabs.currentIndex()==2:self.show_dock('properties')
        for name in ('x','y'):
            self.layer_spins[name].setEnabled(bool(layer) and not adjustment)
        if adjustment:
            for spin in self.layer_spins.values():spin.setEnabled(spin==self.layer_spins['opacity'])
            for button in self.swatch_buttons:button.setEnabled(False)

    def change_group_mode(self,index):
        key=self.active_group_header()
        if key and index>=0 and not self.advanced_loading:self.update_group(key,{'blend_mode':self.group_mode.itemData(index)})

    def change_group_opacity(self,value):
        key=self.active_group_header()
        if key and not self.advanced_loading:
            group=self.project.state['documents'][self.document_id]['groups'][key]
            self.update_group(key,{'opacity':value,'blend_mode':'normal' if group.get('blend_mode','pass')=='pass' else group['blend_mode']})

    def apply_group_mask(self,mask):
        key=self.active_group_header()
        if key:
            group=self.project.state['documents'][self.document_id]['groups'][key]
            self.update_group(key,{'mask':mask,'blend_mode':'normal' if group.get('blend_mode','pass')=='pass' else group['blend_mode']})

    def group_mask_target(self):
        key=self.active_group_header()
        if not key:return None
        doc=self.project.state['documents'][self.document_id]
        return doc,dict(x=0,y=0,width=doc['width'],height=doc['height'],rotation=0),doc['groups'][key].get('mask')

    def add_adjustment_layer(self):
        from core.project import Project
        from core.studio_commands import add_layer
        if not self.document_id:self.document_id=self.project.add_document(1920,1080,[])
        group=self.current_group()
        from core.layer_groups import group_locked
        if group and group_locked(self.project.state['documents'][self.document_id],{'group_id':group}):
            self.error(ValueError(localize('잠긴 그룹에는 조정 레이어를 추가할 수 없습니다.', self)));return
        staged=Project(self.project.root,self.project.state);key=add_layer(staged,self.document_id,'adjustment')
        if group:
            doc=staged.state['documents'][self.document_id];layer=doc['layers'].pop();layer['group_id']=group
            index=max(i for i,l in enumerate(doc['layers']) if l in members(doc,group));doc['layers'].insert(index+1,layer)
        self.project._change(staged.state);self.layer_id=key;self.pending_layer_selection=[key];self.refresh();self.tabs.setCurrentIndex(2)

    def change_adjustment(self,key,value):
        layer=self.current_layer()
        if self.advanced_loading or not layer or layer['kind']!='adjustment':return
        data=deepcopy(layer['data']);data['adjustments'][key]=value;self.layer_update({'data':data})

    def import_psd_dialog(self):
        from PyQt5.QtWidgets import QFileDialog,QInputDialog,QMessageBox
        from core.psd_io import import_psd,NOTICE
        from core.project import Project
        path,_=QFileDialog.getOpenFileName(self,localize('PSD 가져오기', self),'','Photoshop (*.psd)')
        if not path:return
        mode,ok=QInputDialog.getItem(self,localize('PSD 가져오기', self),localize('지원 범위: RGB 8비트. 레이어 구조는 기본 픽셀·그룹만 지원합니다.\n마스크·효과·텍스트 등이 있으면 합쳐진 화면을 선택하세요.', self), [localize('합쳐진 화면', self),localize('픽셀 레이어 구조', self)],0,False)
        if not ok:return
        staged=Project(self.project.root,self.project.state)
        def run(cancelled,progress):
            key=import_psd(staged,path,layered=mode==localize('픽셀 레이어 구조', self),cancelled=cancelled)
            return staged.state,key
        def done(result):
            self.project._change(result[0]);self.document_id=result[1];self.layer_id=None
            self.input_paths.add(path);self.refresh();self.tabs.setCurrentIndex(2)
            QMessageBox.information(self,localize('PSD 가져오기 완료', self),NOTICE)
        self.run_io(localize('PSD 읽는 중', self),run,done)

    def export_psd_dialog(self):
        from PyQt5.QtWidgets import QFileDialog,QInputDialog,QMessageBox
        from core.psd_io import export_psd,NOTICE
        from core.project import Project
        if not self.document_id:return
        mode,ok=QInputDialog.getItem(self,localize('PSD 내보내기', self),NOTICE+localize('\n조정 레이어·그룹 마스크가 있으면 합쳐진 화면을 선택하세요.', self), [localize('합쳐진 화면', self),localize('픽셀 레이어 구조', self)],0,False)
        if not ok:return
        path,_=QFileDialog.getSaveFileName(self,localize('PSD 내보내기', self),'design.psd','Photoshop (*.psd)')
        if not path:return
        if not path.lower().endswith('.psd'):path+='.psd'
        staged=Project(self.project.root,self.project.state);key=self.document_id;protected=self.protected()
        def run(cancelled,progress):return export_psd(staged,key,path,layered=mode==localize('픽셀 레이어 구조', self),protected_inputs=protected,cancelled=cancelled)
        self.run_io(localize('PSD 저장 중', self),run,lambda saved:QMessageBox.information(self,localize('PSD 내보내기 완료', self),str(saved)+'\n\n'+NOTICE))
