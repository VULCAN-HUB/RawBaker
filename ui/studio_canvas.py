"""Canvas gestures in normalized image coordinates; no edits are committed mid-drag."""
from PyQt5.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
from core.render_engine import to_pixels


class CurveEditor(QWidget):
    edited = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.points = [[0., 0.], [.5, .5], [1., 1.]]
        self.active = None
        self.setMinimumSize(170, 140)
        self.setToolTip("점을 드래그하세요. 빈 곳을 누르면 점 추가, 오른쪽 클릭은 점 삭제.\nDrag points; click to add; right-click to remove.")

    def set_curve(self, points):
        self.points = [list(pair) for pair in points]; self.update()

    def position(self, pair):
        return QPointF(12+pair[0]*(self.width()-24), self.height()-12-pair[1]*(self.height()-24))

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#181818")); painter.setPen(QPen(QColor("#383838"), 1))
        for value in (0, .25, .5, .75, 1):
            painter.drawLine(self.position((value,0)), self.position((value,1)))
            painter.drawLine(self.position((0,value)), self.position((1,value)))
        painter.setPen(QPen(QColor("#d8b48e"), 2))
        painter.drawPolyline(QPolygonF([self.position(pair) for pair in self.points]))
        painter.setBrush(QColor("#d8b48e"))
        for pair in self.points: painter.drawEllipse(self.position(pair), 4, 4)

    def mousePressEvent(self, event):
        point = event.localPos()
        distances = [(self.position(pair)-point).manhattanLength() for pair in self.points]
        nearest = min(range(len(distances)), key=distances.__getitem__)
        if event.button() == Qt.RightButton:
            if distances[nearest] < 16 and 0 < nearest < len(self.points)-1:
                self.points.pop(nearest); self.edited.emit(self.points); self.update()
            return
        if event.button() != Qt.LeftButton: return
        if distances[nearest] >= 16 and len(self.points) < 32:
            x = max(.001, min(.999, (point.x()-12)/(self.width()-24)))
            if min(abs(pair[0]-x) for pair in self.points) > .001:
                self.points.append([x, max(0, min(1, 1-(point.y()-12)/(self.height()-24)))])
                self.points.sort(); nearest = next(i for i, pair in enumerate(self.points) if pair[0] == x)
        self.active = nearest

    def mouseMoveEvent(self, event):
        if self.active is None: return
        index = self.active
        x = (event.localPos().x()-12)/(self.width()-24)
        if 0 < index < len(self.points)-1:
            x = max(self.points[index-1][0]+1e-6, min(self.points[index+1][0]-1e-6, x))
            self.points[index][0] = x
        self.points[index][1] = max(0, min(1, 1-(event.localPos().y()-12)/(self.height()-24)))
        self.update()

    def mouseReleaseEvent(self, event):
        if self.active is not None:
            self.active = None; self.edited.emit(self.points)


class StudioCanvas(QGraphicsView):
    gesture = pyqtSignal(object, bool)
    viewChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.image_item = QGraphicsPixmapItem()
        self.scene().addItem(self.image_item)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#0c0c0e"))
        self.setDragMode(self.ScrollHandDrag)
        self.tool = "view"
        self.points = []
        self.overlay = None
        self.selection = None
        self.auto_fit = True
        self.image_size = (1, 1)
        self.setMinimumSize(240, 180)

    def drawBackground(self, painter, rect):
        painter.save(); painter.resetTransform()
        painter.fillRect(self.viewport().rect(), QColor("#0c0c0e"))
        painter.setPen(QPen(QColor("#252529"), 1))
        painter.drawPoints(QPolygonF([QPointF(x, y) for x in range(12, self.viewport().width(), 22) for y in range(12, self.viewport().height(), 22)]))
        painter.restore()

    def set_frame(self, frame):
        pixels = to_pixels(frame, 8)
        self.set_pixels(pixels)

    def set_pixels(self, pixels):
        h, w, channels = pixels.shape
        fmt = QImage.Format_RGBA8888 if channels == 4 else QImage.Format_RGB888
        image = QImage(pixels.data, w, h, pixels.strides[0], fmt).copy()
        self.image_item.setPixmap(QPixmap.fromImage(image))
        self.image_size = (w, h)
        self.scene().setSceneRect(0, 0, w, h)
        if self.auto_fit:
            self.fit()

    def fit(self):
        self.auto_fit = True
        self.fitInView(self.image_item.boundingRect().adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
        self.viewChanged.emit()

    def outline(self, points):
        if self.selection:
            self.scene().removeItem(self.selection)
            self.selection = None
        if points:
            w, h = self.image_size
            pen = QPen(QColor("#a99ac8"), 0, Qt.DashLine)
            self.selection = self.scene().addPolygon(QPolygonF([QPointF(x*w, y*h) for x, y in points]), pen)
            self.selection.setZValue(100)

    def one_to_one(self):
        self.auto_fit = False
        self.resetTransform()
        self.viewChanged.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.fit()

    def wheelEvent(self, event):
        self.auto_fit = False
        scale = 1.15 if event.angleDelta().y() > 0 else 1/1.15
        if .01 < self.transform().m11()*scale < 50:
            self.scale(scale, scale)
            self.viewChanged.emit()

    def normalized(self, pos):
        p = self.mapToScene(pos)
        w, h = self.image_size
        return [max(0., min(1., p.x()/w)), max(0., min(1., p.y()/h))]

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.tool != "view":
            self.points = [self.normalized(event.pos())]
            self.alt = bool(event.modifiers() & Qt.AltModifier)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.points:
            p = self.normalized(event.pos())
            if len(self.points) < 2000:
                self.points.append(p)
            if self.overlay:
                self.scene().removeItem(self.overlay)
            a, b = self.points[0], self.points[-1]
            w, h = self.image_size
            pen = QPen(QColor("#a99ac8"), 0)
            self.overlay = self.scene().addRect(QRectF(QPointF(a[0]*w, a[1]*h), QPointF(b[0]*w, b[1]*h)).normalized(), pen)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.points:
            points, self.points = self.points, []
            if self.overlay:
                self.scene().removeItem(self.overlay)
                self.overlay = None
            self.gesture.emit(points, self.alt)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
