"""Document navigator backed by the live canvas, including viewport and pan."""
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtWidgets import QWidget


class Navigator(QWidget):
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.setFixedHeight(156)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip("미리보기에서 클릭하거나 드래그해 이동 / Click or drag to pan")
        canvas.horizontalScrollBar().valueChanged.connect(self.update)
        canvas.verticalScrollBar().valueChanged.connect(self.update)
        canvas.viewChanged.connect(self.update)

    def image_rect(self):
        pix = self.canvas.image_item.pixmap()
        if pix.isNull(): return QRectF()
        size = pix.size(); size.scale(self.width()-12, self.height()-12, Qt.KeepAspectRatio)
        return QRectF((self.width()-size.width())/2, (self.height()-size.height())/2, size.width(), size.height())

    def paintEvent(self, event):
        p = QPainter(self); p.fillRect(self.rect(), QColor("#101011"))
        rect = self.image_rect()
        if rect.isEmpty():
            p.setPen(QColor("#77777c")); p.drawText(self.rect(), Qt.AlignCenter, "Navigator"); return
        pix = self.canvas.image_item.pixmap()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(rect, pix, QRectF(pix.rect()))
        view = self.canvas.mapToScene(self.canvas.viewport().rect()).boundingRect().intersected(self.canvas.image_item.boundingRect())
        w, h = self.canvas.image_size
        viewport = QRectF(rect.x()+view.x()/w*rect.width(), rect.y()+view.y()/h*rect.height(), view.width()/w*rect.width(), view.height()/h*rect.height())
        p.setPen(QPen(QColor("#aaa2c4"), 1)); p.drawRect(viewport)

    def pan(self, pos):
        rect = self.image_rect()
        if rect.isEmpty(): return
        x = max(0, min(1, (pos.x()-rect.x())/rect.width()))
        y = max(0, min(1, (pos.y()-rect.y())/rect.height()))
        w, h = self.canvas.image_size
        self.canvas.centerOn(QPointF(x*w, y*h)); self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton: self.pan(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton: self.pan(event.pos())
