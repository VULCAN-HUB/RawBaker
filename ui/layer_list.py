"""Internal drag surface; the project command alone owns row mutations."""
from ui.editor_i18n import localize
from PyQt5.QtCore import Qt, QMimeData, pyqtSignal
from PyQt5.QtGui import QDrag, QPainter, QPen, QColor
from PyQt5.QtWidgets import QListWidget, QAbstractItemView


class LayerList(QListWidget):
    relocateRequested=pyqtSignal(str,object,str)
    dragHint=pyqtSignal(str)
    MIME='application/x-rawbaker-layer'

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setDragEnabled(True);self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction);self.setAutoScroll(True)
        self._drop=None
        self.setToolTip(localize('한 행을 드래그하여 순서 변경 · 그룹 가운데: 안으로 이동 · 빈 공간: 문서 맨 아래', self))

    def startDrag(self,actions):
        selected=self.selectedItems()
        if len(selected)!=1:
            self.dragHint.emit(localize('드래그할 레이어 또는 그룹 한 행을 선택하세요.', self));return
        mime=QMimeData();mime.setData(self.MIME,selected[0].data(Qt.UserRole).encode('utf-8'))
        drag=QDrag(self);drag.setMimeData(mime);drag.exec_(Qt.MoveAction)
        self._drop=None;self.viewport().update()

    def drop_location(self,pos):
        item=self.itemAt(pos)
        if item is None:return None,'root',None
        rect=self.visualItemRect(item);key=item.data(Qt.UserRole);fraction=(pos.y()-rect.top())/max(1,rect.height())
        mode='inside' if key.startswith('group:') and .25<=fraction<=.75 else ('above' if fraction<.5 else 'below')
        return key,mode,rect

    def dragEnterEvent(self,event):
        if event.source() is self and event.mimeData().hasFormat(self.MIME):event.acceptProposedAction()
        else:event.ignore()

    def dragMoveEvent(self,event):
        if event.source() is not self or not event.mimeData().hasFormat(self.MIME):event.ignore();return
        bar=self.verticalScrollBar()
        if event.pos().y()<20:bar.setValue(bar.value()-bar.singleStep())
        elif event.pos().y()>self.viewport().height()-20:bar.setValue(bar.value()+bar.singleStep())
        self._drop=self.drop_location(event.pos());self.viewport().update()
        self.dragHint.emit({'inside':localize('그룹 안으로 이동', self),'above':localize('대상 위로 이동', self),'below':localize('대상 아래로 이동', self),'root':localize('그룹 밖 · 문서 맨 아래로 이동', self)}[self._drop[1]])
        event.acceptProposedAction()

    def dragLeaveEvent(self,event):
        self._drop=None;self.viewport().update();event.accept()

    def dropEvent(self,event):
        if event.source() is not self or not event.mimeData().hasFormat(self.MIME):event.ignore();return
        target,mode,_=self.drop_location(event.pos())
        source=bytes(event.mimeData().data(self.MIME)).decode('utf-8')
        self._drop=None;self.viewport().update()
        self.relocateRequested.emit(source,target,mode);event.acceptProposedAction()

    def paintEvent(self,event):
        super().paintEvent(event)
        if not self._drop:return
        _,mode,rect=self._drop;painter=QPainter(self.viewport());painter.setPen(QPen(QColor('#bab4e8'),2))
        if rect is None:painter.drawRect(self.viewport().rect().adjusted(2,2,-3,-3))
        elif mode=='inside':painter.drawRect(rect.adjusted(1,1,-2,-2))
        else:
            y=rect.top() if mode=='above' else rect.bottom()
            painter.drawLine(2,y,self.viewport().width()-3,y)
