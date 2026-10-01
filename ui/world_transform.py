from PyQt5.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QDoubleSpinBox,QLabel,QDialogButtonBox,QHBoxLayout,QWidget
from ui.editor_i18n import localize


class WorldTransformDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle(localize('공통 중심 · 기울이기 · 원근', self));self.setMinimumWidth(420)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form);self.fields=[]
        for name,low,high,value,suffix in [(localize('가로 배율', self),1,10000,100,' %'),(localize('세로 배율', self),1,10000,100,' %'),(localize('가로 기울기', self),-75,75,0,' °'),(localize('세로 기울기', self),-75,75,0,' °')]:
            spin=QDoubleSpinBox();spin.setRange(low,high);spin.setValue(value);spin.setSuffix(suffix);spin.setKeyboardTracking(False);form.addRow(name,spin);self.fields.append(spin)
        box.addWidget(QLabel(localize('원근 모서리 이동 · 선택 영역 너비/높이 대비 %', self)))
        form=QFormLayout();box.addLayout(form);self.corners=[]
        for name in (localize('왼쪽 위', self),localize('오른쪽 위', self),localize('오른쪽 아래', self),localize('왼쪽 아래', self)):
            widget=QWidget();row=QHBoxLayout(widget);row.setContentsMargins(0,0,0,0);pair=[]
            for axis in ('X','Y'):
                row.addWidget(QLabel(axis));spin=QDoubleSpinBox();spin.setRange(-100,100);spin.setSuffix(' %');spin.setKeyboardTracking(False);row.addWidget(spin);pair.append(spin)
            form.addRow(name,widget);self.corners.append(pair)
        hint=QLabel(localize('선택 전체에 함께 적용합니다. 배율·기울기 후 원근을 적용합니다.\n기존 마스크도 함께 변형됩니다. 변형 후 새 마스크는 선택 영역으로 만드세요.\n적용 뒤 Ctrl+Z로 한 번에 되돌릴 수 있습니다.', self));hint.setWordWrap(True);box.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Ok).setText(localize('적용', self));buttons.button(QDialogButtonBox.Cancel).setText(localize('취소', self));buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);box.addWidget(buttons)

    def values(self):
        return self.fields[0].value()/100,self.fields[1].value()/100,self.fields[2].value(),self.fields[3].value(),[[s.value() for s in pair] for pair in self.corners]
