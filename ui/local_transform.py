"""Explicit per-layer local-axis resize/flip controls."""
from ui.editor_i18n import localize
from PyQt5.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QDoubleSpinBox,QCheckBox,QLabel,QDialogButtonBox


class LocalTransformDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle(localize('레이어별 크기 · 뒤집기', self));self.setMinimumWidth(340)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.scale_x=QDoubleSpinBox();self.scale_y=QDoubleSpinBox()
        for spin in (self.scale_x,self.scale_y):spin.setRange(1,10000);spin.setValue(100);spin.setDecimals(2);spin.setSuffix(' %');spin.setKeyboardTracking(False)
        form.addRow(localize('가로 배율', self),self.scale_x);form.addRow(localize('세로 배율', self),self.scale_y)
        self.link=QCheckBox(localize('비율 유지', self));self.link.setChecked(True);box.addWidget(self.link)
        self.flip_x=QCheckBox(localize('가로 뒤집기', self));self.flip_y=QCheckBox(localize('세로 뒤집기', self));box.addWidget(self.flip_x);box.addWidget(self.flip_y)
        self.scale_x.valueChanged.connect(lambda v:self.sync(self.scale_y,v));self.scale_y.valueChanged.connect(lambda v:self.sync(self.scale_x,v))
        self.link.toggled.connect(lambda value:self.sync(self.scale_y,self.scale_x.value()) if value else None)
        hint=QLabel(localize('각 레이어의 중심과 회전된 축을 기준으로 적용합니다.\n비율 유지를 끄면 사진·텍스트·마스크가 함께 늘어납니다.\n여러 레이어의 중심 간격은 유지합니다.', self));hint.setWordWrap(True);box.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Ok).setText(localize('적용', self));buttons.button(QDialogButtonBox.Cancel).setText(localize('취소', self));buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);box.addWidget(buttons)

    def sync(self,spin,value):
        if self.link.isChecked():spin.blockSignals(True);spin.setValue(value);spin.blockSignals(False)
