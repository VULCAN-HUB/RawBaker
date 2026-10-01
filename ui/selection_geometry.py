"""Boolean selection outlines, independent from canvas zoom and preview pixels."""
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QPainterPath,QPolygonF


def combine_selection(existing,inverted,points,mode):
    if mode not in ('replace','add','subtract','intersect'):raise ValueError('잘못된 선택 모드입니다.')
    def path_for(value):
        path=QPainterPath()
        rings=value.get('rings',[]) if isinstance(value,dict) else ([value] if value else [])
        for ring in rings:
            path.addPolygon(QPolygonF([QPointF(x*10000,y*10000) for x,y in ring]));path.closeSubpath()
        return path
    fresh=path_for(points)
    if mode=='replace':return points
    old=path_for(existing)
    if inverted:
        bounds=QPainterPath();bounds.addRect(0,0,10000,10000);old=bounds.subtracted(old)
    result={'add':old.united,'subtract':old.subtracted,'intersect':old.intersected}[mode](fresh)
    rings=[[[p.x()/10000,p.y()/10000] for p in polygon] for polygon in result.toSubpathPolygons()]
    if len(rings)>200 or sum(map(len,rings))>2000:raise ValueError('선택 윤곽이 너무 복잡합니다. 영역을 나누어 작업하세요.')
    return {'rings':rings}


def offset_selection(selection,inverted,width,height,pixels):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPainterPathStroker
    path=QPainterPath();bounds=QPainterPath();bounds.addRect(0,0,width,height)
    for ring in selection.get('rings',[]) if isinstance(selection,dict) else [selection]:
        path.addPolygon(QPolygonF([QPointF(x*width,y*height) for x,y in ring]));path.closeSubpath()
    if inverted:path=bounds.subtracted(path)
    if pixels:
        stroke=QPainterPathStroker();stroke.setWidth(abs(pixels)*2);stroke.setJoinStyle(Qt.RoundJoin);stroke.setCapStyle(Qt.RoundCap)
        border=stroke.createStroke(path)
        path=path.united(border) if pixels>0 else path.subtracted(border)
    path=path.intersected(bounds)
    rings=[[[p.x()/width,p.y()/height] for p in polygon] for polygon in path.toSubpathPolygons()]
    if len(rings)>200 or sum(map(len,rings))>2000:raise ValueError('확장/축소 결과가 너무 복잡합니다.')
    return {'rings':rings}


def refine_selection(selection,inverted,width,height,smooth=0,shift=0):
    """Round narrow protrusions/gaps in document pixels, preserving even-odd holes."""
    from core.edit_spec import number
    number(smooth,0,100);number(shift,-500,500)
    if not smooth:return offset_selection(selection,inverted,width,height,shift)
    # Closing followed by opening rounds small gaps and protrusions. Each pass
    # retains existing geometry limits; no document-sized bitmap is allocated.
    result=offset_selection(selection,inverted,width,height,smooth)
    for radius in (-smooth,-smooth,smooth):
        result=offset_selection(result,False,width,height,radius)
    return offset_selection(result,False,width,height,shift)
