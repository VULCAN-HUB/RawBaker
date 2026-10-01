"""Bounded preview of selection edges using the production mask renderer."""
from ui.editor_i18n import localize
from copy import deepcopy
import numpy as np
from PyQt5.QtCore import Qt,QTimer
from PyQt5.QtGui import QImage,QPixmap
from PyQt5.QtWidgets import QDialog,QHBoxLayout,QVBoxLayout,QFormLayout,QLabel,QSpinBox,QComboBox,QCheckBox,QDialogButtonBox,QSizePolicy
from ui.selection_geometry import refine_selection
from core.layer_masks import selection_mask,layer_mask_pixels


class RefineSelectionDialog(QDialog):
    def __init__(self,document,selection,inverted,feather,image,parent=None):
        super().__init__(parent);self.setWindowTitle(localize('선택 경계 다듬기', self));self.resize(920,620)
        self.document=deepcopy(document);self.original=deepcopy(selection);self.inverted=inverted
        self.result_selection=None;self.source=image.scaled(1024,1024,Qt.KeepAspectRatio,Qt.SmoothTransformation) if max(image.width(),image.height())>1024 else image.copy()
        self.preview=QLabel();self.preview.setAlignment(Qt.AlignCenter);self.preview.setMinimumSize(360,280)
        self.preview.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored)
        self.preview.setStyleSheet('background:#151517;')
        layout=QHBoxLayout(self);layout.addWidget(self.preview,1);panel=QVBoxLayout();layout.addLayout(panel)
        form=QFormLayout();panel.addLayout(form)
        self.smooth=QSpinBox();self.smooth.setRange(0,100);self.smooth.setSuffix(' px')
        self.shift=QSpinBox();self.shift.setRange(-500,500);self.shift.setSuffix(' px')
        self.feather=QSpinBox();self.feather.setRange(0,500);self.feather.setValue(feather);self.feather.setSuffix(' px')
        for text,widget in [(localize('경계 매끄럽게', self),self.smooth),(localize('확장 / 축소', self),self.shift),(localize('페더', self),self.feather)]:form.addRow(text,widget)
        self.view=QComboBox();self.view.addItems([localize('빨간 오버레이', self),localize('흑백 마스크', self)]);form.addRow(localize('보기', self),self.view)
        self.before=QCheckBox(localize('보정 전 윤곽', self));panel.addWidget(self.before)
        hint=QLabel(localize('문서 픽셀 기준\n빨강: 선택 밖 · 흰색: 선택 안\n작은 세부 영역은 사라질 수 있음\n페더는 다음 마스크 생성에 적용\n미리보기는 최대 1024px 근사', self));hint.setWordWrap(True);panel.addWidget(hint)
        self.message=QLabel();self.message.setWordWrap(True);self.message.setMaximumWidth(220);panel.addWidget(self.message);panel.addStretch()
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);self.buttons.button(QDialogButtonBox.Ok).setText(localize('선택에 적용', self));self.buttons.button(QDialogButtonBox.Cancel).setText(localize('취소', self));panel.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(120);self.timer.timeout.connect(self.update_preview)
        for widget in (self.smooth,self.shift,self.feather):widget.valueChanged.connect(self.schedule)
        self.view.currentIndexChanged.connect(self.schedule);self.before.toggled.connect(self.schedule)
        self.update_preview()

    def schedule(self,*args):
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False);self.timer.start()

    def update_preview(self):
        self.timer.stop();self.result_selection=None
        try:
            doc=self.document
            result=refine_selection(self.original,self.inverted,doc['width'],doc['height'],self.smooth.value(),self.shift.value())
            layer=dict(x=0,y=0,width=doc['width'],height=doc['height'],rotation=0)
            points=self.original if self.before.isChecked() else result
            mask=selection_mask(layer,doc,points,self.inverted if self.before.isChecked() else False,0 if self.before.isChecked() else self.feather.value())
            width=self.source.width() or 640;height=self.source.height() or max(1,round(width*doc['height']/doc['width']))
            width=min(width,1024);height=min(height,1024)
            alpha=layer_mask_pixels(mask,width,height,layer,(0,0,1,1),None)
            if self.view.currentIndex()==1:rgb=np.repeat((alpha[:,:,None]*255).astype(np.uint8),3,axis=2)
            else:
                src=self.source.convertToFormat(QImage.Format_RGBA8888)
                if src.isNull():rgb=np.full((height,width,3),80,np.float32)
                else:
                    ptr=src.bits();ptr.setsize(src.byteCount());data=np.frombuffer(ptr,np.uint8).reshape(height,src.bytesPerLine())[:,:width*4].reshape(height,width,4).astype(np.float32)
                    rgb=data[:,:,:3]*(data[:,:,3:4]/255)+48*(1-data[:,:,3:4]/255)
                weight=(1-alpha[:,:,None])*.55;rgb=np.clip(rgb*(1-weight)+np.array([230,45,60])*weight,0,255).astype(np.uint8)
            rgb=np.ascontiguousarray(rgb);self.preview_image=QImage(rgb.data,width,height,rgb.strides[0],QImage.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(self.preview_image).scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
            self.result_selection=result;self.message.setText(localize('선택 영역 비어 있음', self) if not result['rings'] else localize('확인 후 선택에 적용하세요.', self))
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        except (ValueError,MemoryError) as error:
            self.preview.clear();self.message.setText(str(error));self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)

    def accept(self):
        self.update_preview()
        if self.result_selection is not None:super().accept()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'preview_image'):self.preview.setPixmap(QPixmap.fromImage(self.preview_image).scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
