"""Atomic local, shared-pivot and projective layer transforms."""
from copy import deepcopy
import math
from core.edit_spec import number
from core.layer_groups import ancestors,group_locked


def selection_bounds(document,ids):
    chosen=set(ids);points=[]
    for layer in document['layers']:
        if layer.get('id') not in chosen:continue
        from core.layer_geometry import layer_corners
        points.extend(layer_corners(layer))
    if not points:raise ValueError('변형할 레이어를 선택하세요.')
    return min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)


def transform_layers(project,document_id,ids,scale=1,angle=0,pivot=None):
    number(scale,.01,100);number(angle,-360,360)
    state=deepcopy(project.state);doc=state['documents'][document_id];selected=set(ids)
    layers=[l for l in doc['layers'] if l.get('id') in selected]
    if not layers or len(layers)!=len(selected):raise ValueError('선택한 레이어가 없습니다.')
    if any(l['locked'] or group_locked(doc,l) for l in layers):raise ValueError('잠긴 레이어 또는 그룹입니다.')
    if any(l['kind']=='adjustment' for l in layers):raise ValueError('조정 레이어를 제외하고 변형하세요.')
    if any(doc['groups'][g].get('mask') for l in layers for g in ancestors(doc,l.get('group_id'))):raise ValueError('문서 좌표 그룹 마스크가 있는 레이어는 함께 변형할 수 없습니다.')
    if pivot is None:
        x0,y0,x1,y1=selection_bounds(doc,ids);pivot=((x0+x1)/2,(y0+y1)/2)
    if len(pivot)!=2:raise ValueError('변형 기준점이 잘못되었습니다.')
    for value in pivot:number(value,-1000000,1000000)
    if any('warp' in layer for layer in layers):
        import numpy as np
        c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle));px,py=pivot
        matrix=np.array([[c*scale,-s*scale,px-scale*c*px+scale*s*py],[s*scale,c*scale,py-scale*s*px-scale*c*py],[0,0,1]])
        return transform_world_layers(project,document_id,ids,matrix)
    radians=math.radians(angle);c,s=math.cos(radians),math.sin(radians);px,py=pivot
    for layer in layers:
        dx,dy=(layer['x']-px)*scale,(layer['y']-py)*scale
        layer['x'],layer['y']=px+c*dx-s*dy,py+s*dx+c*dy
        layer['width']*=scale;layer['height']*=scale
        layer['rotation']=(layer['rotation']+angle+180)%360-180
        if 'content_size' in layer:layer['content_size']=[v*scale for v in layer['content_size']]
        if layer['kind']=='text':layer['data']['size']*=scale
    if state!=project.state:project._change(state)


def transform_local_layers(project,document_id,ids,scale_x=1,scale_y=1,flip_x=False,flip_y=False):
    """Scale each selected layer around its own center, in its rotated axes."""
    number(scale_x,.01,100);number(scale_y,.01,100)
    if type(flip_x) is not bool or type(flip_y) is not bool:raise ValueError('뒤집기 값이 잘못되었습니다.')
    state=deepcopy(project.state);doc=state['documents'][document_id];selected=set(ids)
    layers=[l for l in doc['layers'] if l.get('id') in selected]
    if not layers or len(layers)!=len(selected):raise ValueError('선택한 레이어가 없습니다.')
    if any(l['locked'] or group_locked(doc,l) for l in layers):raise ValueError('잠긴 레이어 또는 그룹입니다.')
    if any(l['kind']=='adjustment' for l in layers):raise ValueError('조정 레이어를 제외하고 변형하세요.')
    if any(doc['groups'][g].get('mask') for l in layers for g in ancestors(doc,l.get('group_id'))):raise ValueError('문서 좌표 그룹 마스크가 있는 레이어는 변형할 수 없습니다.')
    if any('warp' in layer for layer in layers):raise ValueError('원근/기울기 레이어는 공통 중심 변형을 사용하세요.')
    if scale_x==scale_y==1 and not flip_x and not flip_y:return
    for layer in layers:
        w,h=layer['width'],layer['height'];nw,nh=w*scale_x,h*scale_y
        c,s=math.cos(math.radians(layer['rotation'])),math.sin(math.radians(layer['rotation']))
        layer['x']+=c*(w-nw)/2-s*(h-nh)/2;layer['y']+=s*(w-nw)/2+c*(h-nh)/2
        if layer['kind'] in ('photo','text') and (scale_x!=1 or scale_y!=1):layer.setdefault('content_size',[w,h])
        layer['width'],layer['height']=nw,nh
        if flip_x:layer['flip_x']=not layer.get('flip_x',False)
        if flip_y:layer['flip_y']=not layer.get('flip_y',False)
    project._change(state)


def transform_world_layers(project,document_id,ids,matrix):
    import numpy as np
    from core.layer_geometry import layer_matrix,store_matrix
    matrix=np.asarray(matrix,dtype=np.float64)
    if matrix.shape!=(3,3) or not np.isfinite(matrix).all():raise ValueError('변형 행렬이 잘못되었습니다.')
    state=deepcopy(project.state);doc=state['documents'][document_id];chosen=set(ids)
    layers=[l for l in doc['layers'] if l.get('id') in chosen]
    if not layers or len(layers)!=len(chosen):raise ValueError('변형할 레이어가 없습니다.')
    if any(l['locked'] or group_locked(doc,l) for l in layers):raise ValueError('잠긴 레이어 또는 그룹입니다.')
    if any(l['kind']=='adjustment' for l in layers):raise ValueError('조정 레이어를 제외하세요.')
    if any(doc['groups'][g].get('mask') for l in layers for g in ancestors(doc,l.get('group_id'))):raise ValueError('문서 좌표 그룹 마스크를 포함한 변형은 지원하지 않습니다.')
    if np.allclose(matrix,np.eye(3),rtol=0,atol=1e-12):return
    for layer in layers:store_matrix(layer,matrix@layer_matrix(layer))
    project._change(state)


def world_transform_matrix(bounds,scale_x=1,scale_y=1,shear_x=0,shear_y=0,offsets=None):
    import numpy as np
    import cv2
    for value in (scale_x,scale_y):number(value,.01,100)
    for value in (shear_x,shear_y):number(value,-75,75)
    x0,y0,x1,y1=bounds;cx,cy=(x0+x1)/2,(y0+y1)/2
    matrix=np.array([[scale_x,math.tan(math.radians(shear_x))*scale_y,0],[math.tan(math.radians(shear_y))*scale_x,scale_y,0],[0,0,1]],dtype=np.float64)
    if np.linalg.det(matrix)<=.0001:raise ValueError('기울기 조합이 레이어를 뒤집거나 너무 납작하게 만듭니다.')
    matrix=np.array([[1,0,cx],[0,1,cy],[0,0,1]])@matrix@np.array([[1,0,-cx],[0,1,-cy],[0,0,1]])
    if offsets is not None and any(value for pair in offsets for value in pair):
        if len(offsets)!=4 or any(len(pair)!=2 for pair in offsets):raise ValueError('네 모서리가 필요합니다.')
        for pair in offsets:
            for value in pair:number(value,-100,100)
        if x1-x0<.1 or y1-y0<.1:raise ValueError('선택 영역이 너무 작습니다.')
        src=np.array([[x0,y0],[x1,y0],[x1,y1],[x0,y1]],np.float32)
        dst=src+np.array(offsets,np.float32)*[(x1-x0)/100,(y1-y0)/100]
        edges=np.roll(dst,-1,axis=0)-dst
        cross=edges[:,0]*np.roll(edges,-1,axis=0)[:,1]-edges[:,1]*np.roll(edges,-1,axis=0)[:,0]
        if np.any(cross<=1e-5):raise ValueError('모서리가 교차하거나 뒤집히지 않도록 조절하세요.')
        matrix=cv2.getPerspectiveTransform(src,dst.astype(np.float32))@matrix
    return matrix


def move_projective_corner(project,document_id,layer_id,corner,point):
    from core.layer_geometry import layer_corners,corner_matrix
    if type(corner) is not int or corner not in range(4) or len(point)!=2:raise ValueError('모서리를 지정하세요.')
    for value in point:number(value,-1000000,1000000)
    layer=next((l for l in project.state['documents'][document_id]['layers'] if l.get('id')==layer_id),None)
    if layer is None:raise ValueError('레이어가 없습니다.')
    source=layer_corners(layer);destination=deepcopy(source);destination[corner]=list(point)
    if all(abs(a-b)<1e-8 for a,b in zip(source[corner],point)):return
    transform_world_layers(project,document_id,[layer_id],corner_matrix(source,destination))


def move_selection_corner(project,document_id,ids,corner,point):
    """Apply one homography to the whole selection, atomically."""
    from core.layer_geometry import corner_matrix
    if type(corner) is not int or corner not in range(4) or len(point)!=2:raise ValueError('모서리를 지정하세요.')
    for value in point:number(value,-1000000,1000000)
    doc=project.state['documents'][document_id]
    x0,y0,x1,y1=selection_bounds(doc,ids)
    source=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]
    if all(abs(a-b)<1e-8 for a,b in zip(source[corner],point)):return
    destination=deepcopy(source);destination[corner]=list(point)
    transform_world_layers(project,document_id,ids,corner_matrix(source,destination))
