"""Editor canvas selection and corner transform gestures in document coordinates."""
import math
from PyQt5.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt5.QtGui import QColor, QPen, QBrush, QPainterPath, QPolygonF, QPixmap, QPainter
from PyQt5.QtWidgets import QGraphicsItem
from ui.studio_canvas import StudioCanvas


class EditorCanvas(StudioCanvas):
    layerPicked = pyqtSignal(object)
    cornerResized = pyqtSignal(int, object)
    areaSelected = pyqtSignal(object)
    colorPicked = pyqtSignal(object)
    maskPainted = pyqtSignal(object)
    maskPreview = pyqtSignal(object)
    maskSizeStep = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True);self.brush_cursor=None;self.brush_position=None
        self.document_layers=[]; self.document_size=(1,1)
        self.handles=[]; self.outline_points=None; self.resize_corner=None

    def outline(self, points):
        for handle in self.handles:self.scene().removeItem(handle)
        self.handles=[];self.outline_points=points
        visible_points=points if self.tool in ('move','transform') else None
        super().outline(visible_points)
        if visible_points:
            w,h=self.image_size
            for x,y in points:
                handle=self.scene().addRect(QRectF(-3,-3,6,6),QPen(QColor('#d4d4df')),QBrush(QColor('#34343b')))
                handle.setFlag(QGraphicsItem.ItemIgnoresTransformations);handle.setPos(x*w,y*h);handle.setZValue(102)
                self.handles.append(handle)

    def set_frame(self, frame):
        super().set_frame(frame)
        self.draw_area()

    def set_area(self, points=None, inverted=False):
        self.area_points=points; self.area_inverted=inverted; self.draw_area()

    def draw_area(self):
        for item in getattr(self,'area_items',[]): self.scene().removeItem(item)
        self.area_items=[]
        points=getattr(self,'area_points',None)
        if not points:return
        w,h=self.image_size
        path=QPainterPath()
        for ring in points.get('rings',[]) if isinstance(points,dict) else [points]:
            path.addPolygon(QPolygonF([QPointF(x*w,y*h) for x,y in ring]));path.closeSubpath()
        if getattr(self,'area_inverted',False):path.addRect(0,0,w,h)
        for color,style in [('#111111',Qt.SolidLine),('#ffffff',Qt.DashLine)]:
            pen=QPen(QColor(color),1,style);pen.setCosmetic(True)
            item=self.scene().addPath(path,pen);item.setZValue(110);self.area_items.append(item)

    def cancel_gesture(self):
        self.maskPreview.emit(None)
        self.hide_brush_cursor()
        self.edit_points=[];self.resize_corner=None;self.points=[]
        if self.overlay is not None:self.scene().removeItem(self.overlay);self.overlay=None
        self.unsetCursor()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape:
            self.cancel_gesture();event.accept();return
        if self.tool=='mask_brush' and event.key() in (Qt.Key_BracketLeft,Qt.Key_BracketRight):
            self.maskSizeStep.emit(-5 if event.key()==Qt.Key_BracketLeft else 5);event.accept();return
        super().keyPressEvent(event)

    def hide_brush_cursor(self):
        if self.brush_cursor is not None:self.scene().removeItem(self.brush_cursor);self.brush_cursor=None

    def set_mask_radius(self,radius):
        self.mask_radius=radius
        if self.brush_position is not None:self.draw_brush_cursor(self.brush_position)

    def draw_brush_cursor(self,pos):
        self.hide_brush_cursor();self.brush_position=pos
        if self.tool!='mask_brush':return
        center=self.mapToScene(pos);w,h=self.image_size;dw,dh=self.document_size
        rx=getattr(self,'mask_radius',40)*w/dw;ry=getattr(self,'mask_radius',40)*h/dh
        pen=QPen(QColor('#ffffff'),1);pen.setCosmetic(True)
        self.brush_cursor=self.scene().addEllipse(QRectF(center.x()-rx,center.y()-ry,2*rx,2*ry),pen)
        self.brush_cursor.setZValue(130)

    def leaveEvent(self,event):
        self.hide_brush_cursor();self.brush_position=None;super().leaveEvent(event)

    def drawBackground(self,painter,rect):
        super().drawBackground(painter,rect)
        if self.image_item.pixmap().isNull():return
        tile=QPixmap(24,24);tile.fill(QColor('#333337'))
        brush_painter=QPainter(tile);brush_painter.fillRect(0,0,12,12,QColor('#414146'));brush_painter.fillRect(12,12,12,12,QColor('#414146'));brush_painter.end()
        painter.fillRect(self.image_item.boundingRect(),QBrush(tile))

    def raw_normalized(self,pos):
        point=self.mapToScene(pos);w,h=self.image_size
        return [point.x()/w,point.y()/h]

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.tool=='color_select':
            point=self.raw_normalized(event.pos())
            if all(0<=v<=1 for v in point):self.colorPicked.emit(point)
            event.accept();return
        if event.button()==Qt.LeftButton and self.tool in ('select_rect','lasso','mask_brush'):
            self.edit_points=[self.normalized(event.pos())]
            if self.tool=='mask_brush':self.maskPreview.emit(list(self.edit_points))
            event.accept();return
        if event.button()==Qt.LeftButton and self.tool=='transform' and self.outline_points:
            w,h=self.image_size
            for i,(x,y) in enumerate(self.outline_points):
                p=self.mapFromScene(QPointF(x*w,y*h))
                if (p-event.pos()).manhattanLength()<14:
                    self.resize_corner=i;self.resize_start=event.pos();event.accept();return
        if event.button()==Qt.LeftButton and self.tool=='move':
            nx,ny=self.raw_normalized(event.pos());dw,dh=self.document_size;x,y=nx*dw,ny*dh
            picked=None
            for layer in reversed(self.document_layers):
                if not layer['visible'] or layer['locked'] or layer['kind']=='adjustment':continue
                from core.layer_geometry import layer_matrix,map_points
                import numpy as np
                try:lx,ly=map_points(np.linalg.inv(layer_matrix(layer)),[[x,y]])[0]
                except ValueError:continue
                if 0<=lx<=layer['width'] and 0<=ly<=layer['height']:picked=layer['id'];break
            self.layerPicked.emit(picked)
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        self.draw_brush_cursor(event.pos())
        if getattr(self,'edit_points',[]):
            point=self.normalized(event.pos())
            if len(self.edit_points)<1999 and point!=self.edit_points[-1]:self.edit_points.append(point)
            if self.tool=='mask_brush':
                self.maskPreview.emit(list(self.edit_points));event.accept();return
            if self.overlay is not None:self.scene().removeItem(self.overlay)
            w,h=self.image_size;path=QPainterPath()
            if self.tool=='select_rect':
                a,b=self.edit_points[0],point
                path.addRect(QRectF(QPointF(a[0]*w,a[1]*h),QPointF(b[0]*w,b[1]*h)).normalized())
            else:
                path.moveTo(QPointF(self.edit_points[0][0]*w,self.edit_points[0][1]*h))
                for x,y in self.edit_points[1:]:path.lineTo(x*w,y*h)
            pen=QPen(QColor('#ffffff'),0,Qt.DashLine)
            if self.tool=='mask_brush':
                pen=QPen(QColor(240,100,100,140),2*getattr(self,'mask_radius',40)*w/self.document_size[0],Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin)
            self.overlay=self.scene().addPath(path,pen);self.overlay.setZValue(120)
            event.accept();return
        if self.resize_corner is not None:
            if getattr(self,'projective_handles',False):
                points=[list(p) for p in self.outline_points];points[self.resize_corner]=self.raw_normalized(event.pos())
                if self.overlay is not None:self.scene().removeItem(self.overlay);self.overlay=None
                from core.layer_geometry import corner_matrix
                dw,dh=self.document_size
                valid=True
                try:corner_matrix([[x*dw,y*dh] for x,y in self.outline_points],[[x*dw,y*dh] for x,y in points])
                except ValueError:valid=False
                w,h=self.image_size;path=QPainterPath();path.addPolygon(QPolygonF([QPointF(x*w,y*h) for x,y in points]));path.closeSubpath()
                pen=QPen(QColor('#bcb4ef' if valid else '#f27676'),1,Qt.DashLine);pen.setCosmetic(True)
                self.overlay=self.scene().addPath(path,pen);self.overlay.setZValue(120)
            self.setCursor(Qt.SizeFDiagCursor);event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and getattr(self,'edit_points',[]):
            points=self.edit_points+[self.normalized(event.pos())];self.cancel_gesture()
            if self.tool=='mask_brush':self.maskPainted.emit(points)
            else:
                if self.tool=='select_rect':
                    a,b=points[0],points[-1];points=[a,[b[0],a[1]],b,[a[0],b[1]]]
                # A click/line is not a selection; keep the preceding selection.
                if len(points)>=3 and abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1])))>1e-7:
                    self.areaSelected.emit(points)
            event.accept();return
        if self.resize_corner is not None:
            corner=self.resize_corner;point=self.raw_normalized(event.pos())
            moved=(event.pos()-getattr(self,'resize_start',event.pos())).manhattanLength()>=3
            self.cancel_gesture()
            if moved:self.cornerResized.emit(corner,point)
            event.accept();return
        if event.button()==Qt.LeftButton and self.points and self.tool=='move':
            self.points.append(self.normalized(event.pos()))
        super().mouseReleaseEvent(event)
