"""Replayable layer-local masks; originals and linked photo edits stay untouched."""
from copy import deepcopy
import math
import cv2
import numpy as np
from core.edit_spec import number, validate_mask


def validate_layer_mask(mask):
    if not isinstance(mask, dict) or mask.get('kind') != 'paint':
        validate_mask(mask)
        return
    if not {'kind','base','strokes','invert','enabled'}<=set(mask) or set(mask)-{'kind','base','strokes','invert','enabled','feather'}:
        raise ValueError('레이어 마스크 형식이 잘못되었습니다.')
    validate_feather(mask.get('feather',[0,0]))
    if type(mask['base']) is dict:
        validate_mask(mask['base'])  # Legacy masks can be painted without discarding them.
    else:
        number(mask['base'], 0, 1)
    if type(mask['invert']) is not bool or type(mask['enabled']) is not bool:
        raise ValueError('마스크 상태가 잘못되었습니다.')
    if type(mask['strokes']) is not list or len(mask['strokes']) > 200:
        raise ValueError('마스크 작업은 200회까지 지원합니다.')
    total = 0
    for stroke in mask['strokes']:
        if type(stroke) is not dict or not {'kind','points','radius','softness','value'}<=set(stroke) or set(stroke)-{'kind','points','radius','softness','value','clip','rings','space'}:
            raise ValueError('마스크 작업 형식이 잘못되었습니다.')
        if stroke['kind'] not in ('brush','polygon') or ('rings' in stroke and stroke['kind']!='polygon'):
            raise ValueError('지원하지 않는 마스크 도구입니다.')
        if 'space' in stroke:
            if stroke['kind']!='brush':raise ValueError('브러시 좌표계가 잘못되었습니다.')
            validate_brush_space(stroke['space'])
        total += validate_outline(stroke,1 if stroke['kind']=='brush' else 3)
        if type(stroke['radius']) is not list or len(stroke['radius']) != 2:
            raise ValueError('마스크 반경이 잘못되었습니다.')
        for radius in stroke['radius']:number(radius, .000001, 1000000)
        number(stroke['softness'], 0, 1)
        number(stroke['value'], 0, 1)
        clip = stroke.get('clip')
        if clip is not None:
            if type(clip) is not dict or not {'points','invert'}<=set(clip) or set(clip)-{'points','invert','rings','feather'} or type(clip['invert']) is not bool:
                raise ValueError('마스크 선택 제한이 잘못되었습니다.')
            total += validate_outline(clip,3)
            validate_feather(clip.get("feather",[0,0]))
    if total > 20000:
        raise ValueError('마스크 좌표가 너무 많습니다. 작업을 줄이세요.')


def validate_brush_space(values):
    if type(values) is not list or len(values)!=9:raise ValueError('브러시 좌표계가 잘못되었습니다.')
    for value in values:number(value,-1000000000000,1000000000000)
    matrix=np.array(values,dtype=np.float64).reshape(3,3)
    if abs(np.linalg.det(matrix))<1e-12 or np.linalg.cond(matrix)>1e14:raise ValueError('브러시 좌표계가 너무 납작합니다.')
    denominators=(np.array([[0,0,1],[1,0,1],[1,1,1],[0,1,1]])@matrix.T)[:,2]
    if not (np.all(denominators>1e-8) or np.all(denominators<-1e-8)):raise ValueError('브러시 좌표계가 무한대에 닿습니다.')


def projective_brush_coverage(stroke,width,height,content,cancelled):
    """Evaluate the original document-space stroke at local pixel centers.

    Retaining the drawing-time map makes later layer transforms carry the mask.
    Tiles bound temporary memory independently of full-resolution image height.
    """
    matrix=np.array(stroke['space'],dtype=np.float64).reshape(3,3)
    ox,oy,cw,ch=content;radius=stroke['radius'][0]
    points=np.asarray(stroke['points'],dtype=np.float64)
    coverage=np.zeros((height,width),np.float32)
    for top in range(0,height,128):
        if cancelled and cancelled():
            from core.render_engine import RenderCancelled
            raise RenderCancelled()
        yy,xx=np.ogrid[top:min(top+128,height),:width]
        u=ox+(xx+.5)*cw/width;v=oy+(yy+.5)*ch/height
        z=matrix[2,0]*u+matrix[2,1]*v+matrix[2,2]
        x=(matrix[0,0]*u+matrix[0,1]*v+matrix[0,2])/z
        y=(matrix[1,0]*u+matrix[1,1]*v+matrix[1,2])/z
        # Pixel footprint in drawing coordinates supplies scale-aware antialiasing.
        dx=np.hypot(matrix[0,0]-x*matrix[2,0],matrix[1,0]-y*matrix[2,0])*cw/width/np.abs(z)
        dy=np.hypot(matrix[0,1]-x*matrix[2,1],matrix[1,1]-y*matrix[2,1])*ch/height/np.abs(z)
        edge=np.maximum(.75*np.maximum(dx,dy)/radius,stroke['softness'])
        target=coverage[top:top+128]
        for a,b in zip(points,np.concatenate((points[1:],points[-1:]))):
            if cancelled and cancelled():
                from core.render_engine import RenderCancelled
                raise RenderCancelled()
            vx,vy=b-a;length=vx*vx+vy*vy
            t=np.clip(((x-a[0])*vx+(y-a[1])*vy)/max(length,1e-12),0,1)
            distance=np.hypot(x-a[0]-t*vx,y-a[1]-t*vy)/radius
            weight=np.clip((1-distance)/np.maximum(edge,1e-12),0,1)
            weight*=weight*(3-2*weight)
            np.maximum(target,weight,out=target)
    return coverage


def validate_feather(value):
    if type(value) is not list or len(value)!=2:raise ValueError('페더 값이 잘못되었습니다.')
    for v in value:number(v,0,10000)


def soften(value,feather,width,height,content):
    sx,sy=feather[0]*width/content[2]/3,feather[1]*height/content[3]/3
    if sx<=0 and sy<=0:return value
    # Bound Gaussian work for large document radii at small preview scales.
    w=max(1,round(width/max(1,sx/12)));h=max(1,round(height/max(1,sy/12)))
    reduced=cv2.resize(value,(w,h),interpolation=cv2.INTER_AREA) if (w,h)!=(width,height) else value
    result=cv2.GaussianBlur(reduced,(0,0),max(.01,sx*w/width),sigmaY=max(.01,sy*h/height),borderType=cv2.BORDER_REPLICATE)
    if (w,h)!=(width,height):result=cv2.resize(result,(width,height),interpolation=cv2.INTER_LINEAR)
    # Gaussian/area resampling can overshoot 1 by a few float32 ULPs.
    # Coverage remains bounded, including before inversion/group compositing.
    return np.clip(result,0,1,out=result)


def validate_outline(value,minimum):
    points=value['points']
    if 'rings' in value:
        if points!=[] or type(value['rings']) is not list or len(value['rings'])>200:raise ValueError('선택 윤곽이 잘못되었습니다.')
        rings=value['rings']
    else:rings=[points]
    total=0
    for ring in rings:
        if type(ring) is not list or not minimum<=len(ring)<=2000:raise ValueError('선택 좌표 수가 잘못되었습니다.')
        total+=len(ring)
        for point in ring:
            if type(point) is not list or len(point)!=2:raise ValueError('선택 좌표가 잘못되었습니다.')
            for coordinate in point:number(coordinate,-1000000,1000000)
    return total


def local_outline(layer,document,selection):
    if isinstance(selection,dict):return dict(points=[],rings=[local_points(layer,document,r) for r in selection['rings']])
    return dict(points=local_points(layer,document,selection))


def paint_mask(existing=None):
    if existing and existing.get('kind') == 'paint':
        return deepcopy(existing)
    return dict(kind='paint', base=deepcopy(existing) if existing else 1.,
                strokes=[], invert=False, enabled=True)


def local_points(layer, document, points):
    if 'warp' in layer:
        from core.layer_geometry import layer_matrix,map_points
        local=map_points(np.linalg.inv(layer_matrix(layer)),[[x*document['width'],y*document['height']] for x,y in points])
        return [[1-x/layer['width'] if layer.get('flip_x') else x/layer['width'],1-y/layer['height'] if layer.get('flip_y') else y/layer['height']] for x,y in local]
    angle = math.radians(layer['rotation']); c, s = math.cos(angle), math.sin(angle)
    result = []
    for nx, ny in points:
        dx, dy = nx*document['width']-layer['x'], ny*document['height']-layer['y']
        x,y=(c*dx+s*dy)/layer['width'],(-s*dx+c*dy)/layer['height']
        result.append([1-x if layer.get('flip_x') else x,1-y if layer.get('flip_y') else y])
    return result


def paint_stroke(existing, layer, document, points, radius, softness, reveal, selection=None, inverted=False, feather=0):
    mask = paint_mask(existing)
    # Keep visible painting semantics even when an existing mask is inverted.
    value = float(bool(reveal) != mask['invert'])
    mask['strokes'].append(dict(kind='brush', points=[] if 'warp' in layer else local_points(layer, document, points),
        radius=[radius/layer['width'],radius/layer['height']], softness=softness, value=value))
    if 'warp' in layer:
        from core.layer_geometry import layer_matrix
        w,h=layer['width'],layer['height']
        local=np.array([[-w if layer.get('flip_x') else w,0,w if layer.get('flip_x') else 0],
                        [0,-h if layer.get('flip_y') else h,h if layer.get('flip_y') else 0],[0,0,1]])
        stroke=mask['strokes'][-1]
        stroke.update(space=(layer_matrix(layer)@local).ravel().tolist(),
                      points=[[x*document['width'],y*document['height']] for x,y in points],radius=[radius,radius])
        if selection:
            # Clip to the finite layer footprint before inverse mapping, avoiding
            # horizons crossed by selections outside the transformed layer.
            selected=selection_mask(layer,document,selection,inverted)
            polygon=selected['strokes'][0]
            selection={'rings':polygon.get('rings',[polygon['points']])}
            stroke['clip']=dict(points=[],rings=selection['rings'],invert=False)
            if feather:stroke['clip']['feather']=[feather/w,feather/h]
        mask['enabled']=True
        validate_layer_mask(mask)
        return mask
    if selection:
        mask['strokes'][-1]['clip'] = dict(**local_outline(layer,document,selection),invert=inverted)
        if feather:mask['strokes'][-1]['clip']['feather']=[feather/layer['width'],feather/layer['height']]
    mask['enabled'] = True
    validate_layer_mask(mask)
    return mask


def selection_mask(layer, document, points, inverted=False, feather=0):
    if 'warp' in layer:
        from core.layer_geometry import layer_corners
        from ui.selection_geometry import combine_selection
        footprint=[[x/document['width'],y/document['height']] for x,y in layer_corners(layer)]
        points=combine_selection(points,inverted,footprint,'intersect');inverted=False
    mask = paint_mask()
    mask['base'] = float(inverted)
    if feather:mask['feather']=[feather/layer['width'],feather/layer['height']]
    mask['strokes'] = [dict(kind='polygon', **local_outline(layer, document, points),
                            radius=[.001,.001], softness=0., value=float(not inverted))]
    validate_layer_mask(mask)
    return mask


def layer_mask_pixels(mask, width, height, layer, content, legacy_renderer, cancelled=None):
    """content=(x,y,w,h) is the fitted image's rectangle in normalized layer bounds."""
    if mask.get('kind') != 'paint':
        return legacy_renderer(mask, width, height)
    if not mask['enabled']:
        return np.ones((height, width), np.float32)
    base = mask['base']
    value = (legacy_renderer(base, width, height) if isinstance(base, dict)
             else np.full((height, width), base, np.float32))
    ox, oy, cw, ch = content
    def polygon_coverage(points,rings=None):
        raster = np.zeros((height,width),np.uint8)
        vertices=[]
        for ring in rings if rings is not None else [points]:
            coords=np.array([[(x-ox)*width/cw-.5,(y-oy)*height/ch-.5] for x,y in ring],np.float64)
            vertices.append(np.clip(np.rint(coords*256),-1000000000,1000000000).astype(np.int32))
        if vertices:cv2.fillPoly(raster,vertices,255,lineType=cv2.LINE_AA,shift=8)
        return raster.astype(np.float32)/255
    for stroke in mask['strokes']:
        if cancelled and cancelled():
            from core.render_engine import RenderCancelled
            raise RenderCancelled()
        coords = np.array([[(x-ox)*width/cw-.5, (y-oy)*height/ch-.5]
                           for x, y in stroke['points']], np.float64)
        if stroke['kind'] == 'polygon':
            # Fixed-point subpixel edge antialiasing, bounded allocation at render size.
            coverage = polygon_coverage(stroke['points'],stroke.get('rings'))
        elif 'space' in stroke:
            coverage=projective_brush_coverage(stroke,width,height,content,cancelled)
        else:
            rx,ry = stroke['radius'][0]*width/cw,stroke['radius'][1]*height/ch
            # Analytical distance to continuous line segments in bounded tiles. Handles
            # strokes outside the layer without clamping them onto its border.
            coverage = np.zeros((height, width), np.float32)
            for a, b in zip(coords, np.concatenate((coords[1:], coords[-1:]))):
                x0 = max(0, math.floor(min(a[0], b[0])-rx-1))
                y0 = max(0, math.floor(min(a[1], b[1])-ry-1))
                x1 = min(width, math.ceil(max(a[0], b[0])+rx+1))
                y1 = min(height, math.ceil(max(a[1], b[1])+ry+1))
                dx, dy = (b-a)/[rx,ry]; length = dx*dx+dy*dy
                for top in range(y0, y1, 128):
                    if cancelled and cancelled():
                        from core.render_engine import RenderCancelled
                        raise RenderCancelled()
                    if x1 <= x0: break
                    yy, xx = np.ogrid[top:min(top+128,y1), x0:x1]
                    x,y=(xx-a[0])/rx,(yy-a[1])/ry
                    t = np.clip((x*dx+y*dy)/max(length,1e-12),0,1)
                    distance = np.hypot(x-t*dx, y-t*dy)
                    edge = max(.75/min(rx,ry), stroke['softness'])
                    weight = np.clip((1-distance)/edge,0,1).astype(np.float32)
                    weight *= weight*(3-2*weight)
                    target = coverage[top:min(top+128,y1),x0:x1]
                    np.maximum(target, weight, out=target)
        clip=stroke.get('clip')
        if clip:
            selected=polygon_coverage(clip['points'],clip.get('rings'))
            selected=soften(selected,clip.get('feather',[0,0]),width,height,content)
            coverage *= 1-selected if clip['invert'] else selected
        value *= 1-coverage
        value += coverage*stroke['value']
    value=soften(value,mask.get('feather',[0,0]),width,height,content)
    return 1-value if mask['invert'] else value
