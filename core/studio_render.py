"""Photo edits, spatial masks and linked design composition, shared by display/export."""
from __future__ import annotations
from collections import OrderedDict
from pathlib import Path
import math
import sys
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

from core.edit_spec import GLOBAL_KEYS, BANDS, validate_edit
from core.render_engine import Frame, Adjustments, RenderCancelled, render, resize, srgb_to_linear, linear_to_srgb
from core.render_io import decode_photo

FONT_PATH = (Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent) / "assets/fonts/NotoSansKR-Regular.otf"


def mask_pixels(spec, width, height):
    yy, xx = np.ogrid[:height, :width]
    x, y = (xx + .5) / width, (yy + .5) / height
    points = spec["points"]
    feather = spec["feather"]
    if spec["kind"] == "linear":
        a, b = points
        dx, dy = b[0] - a[0], b[1] - a[1]
        value = ((x-a[0])*dx + (y-a[1])*dy) / max(dx*dx+dy*dy, 1e-10)
        value = np.broadcast_to(np.clip(value, 0, 1), (height, width)).astype(np.float32).copy()
    elif spec["kind"] == "radial":
        a, b = points
        distance = np.sqrt(((x-a[0])/max(abs(b[0]-a[0]), .001))**2 + ((y-a[1])/max(abs(b[1]-a[1]), .001))**2)
        value = np.clip((1-distance)/feather, 0, 1).astype(np.float32)
    else:
        # Draw continuous center line then distance-transform for a soft, round brush.
        seed = np.ones((height, width), dtype=np.uint8)
        coords = [(min(width-1, round(p[0]*width)), min(height-1, round(p[1]*height))) for p in points]
        for a, b in zip(coords, coords[1:]):
            cv2.line(seed, a, b, 0, 1)
        for p in coords:
            seed[p[1], p[0]] = 0
        distance = cv2.distanceTransform(seed, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        radius = spec["radius"] * min(width, height)
        value = np.clip((radius-distance)/max(radius*feather, .5), 0, 1)
    value = value * value * (3 - 2 * value)
    return 1-value if spec["invert"] else value


def _retouch(frame, edits, cancelled):
    if not edits:
        return frame
    rgb = frame.rgb.copy()
    h, w = rgb.shape[:2]
    # Clone reads the current composite; each stroke remains a replayable command.
    for item in edits:
        if cancelled and cancelled():
            raise RenderCancelled()
        sx, sy = item["source"][0]*w, item["source"][1]*h
        tx, ty = item["target"][0]*w, item["target"][1]*h
        radius = max(1, item["radius"]*min(w, h))
        x0, y0 = max(0, int(tx-radius)), max(0, int(ty-radius))
        x1, y1 = min(w, math.ceil(tx+radius)), min(h, math.ceil(ty+radius))
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        source = cv2.remap(rgb, xx+sx-tx, yy+sy-ty, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        target = rgb[y0:y1, x0:x1]
        coverage = np.clip((1-np.sqrt((xx-tx)**2+(yy-ty)**2)/radius)*3, 0, 1)[..., None]
        if frame.alpha is not None:
            source_alpha = cv2.remap(frame.alpha, xx+sx-tx, yy+sy-ty, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
            coverage *= source_alpha[..., None]
        if item["kind"] == "heal":
            source += target.mean(axis=(0, 1), keepdims=True)-source.mean(axis=(0, 1), keepdims=True)
        target[:] = target*(1-coverage)+source*coverage
    return Frame(rgb, frame.alpha)


def apply_edit(frame, edit, cancelled=None):
    validate_edit(edit)
    frame = _retouch(frame, edit.get("retouch", []), cancelled)
    frame = render(frame, Adjustments(**{k: v for k, v in edit.items() if k in GLOBAL_KEYS}), cancelled=cancelled)
    if edit.get("colors"):
        # Hue selection is based on the unmodified hue so neighboring edits don't drift.
        hsv = cv2.cvtColor(np.clip(linear_to_srgb(frame.rgb), 0, 1), cv2.COLOR_RGB2HSV)
        original_hue = hsv[..., 0].copy()
        centers = (0, 30, 60, 120, 180, 240, 270, 300)
        for name, (dh, ds, dv) in edit["colors"].items():
            center = centers[BANDS.index(name)]
            distance = np.abs((original_hue-center+180) % 360-180)
            weight = np.clip(1-distance/45, 0, 1)
            hsv[..., 0] += weight*dh*.6
            hsv[..., 1] *= 1+weight*ds/100
            hsv[..., 2] *= 1+weight*dv/100
        hsv[..., 0] %= 360
        hsv[..., 1:] = np.clip(hsv[..., 1:], 0, 1)
        adjusted = srgb_to_linear(cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB))
        # Don't destroy highlight headroom in pixels outside the display gamut.
        changed = np.max(frame.rgb, axis=2) <= 1
        frame = Frame(np.where(changed[..., None], adjusted, frame.rgb), frame.alpha)
    for item in edit.get("masks", []):
        localized = render(frame, Adjustments(**item["adjustments"]), cancelled=cancelled)
        h, w = frame.rgb.shape[:2]
        weight = mask_pixels(item["mask"], w, h)[..., None]
        frame = Frame(frame.rgb*(1-weight)+localized.rgb*weight, frame.alpha)
    x, y, cw, ch = edit.get("crop", [0, 0, 1, 1])
    h, w = frame.rgb.shape[:2]
    left, top = min(w-1, int(x*w)), min(h-1, int(y*h))
    right, bottom = max(left+1, round((x+cw)*w)), max(top+1, round((y+ch)*h))
    rgb = frame.rgb[top:bottom, left:right]
    alpha = frame.alpha[top:bottom, left:right] if frame.alpha is not None else None
    turns = -(edit.get("rotation", 0)//90)
    return Frame(np.rot90(rgb, turns), np.rot90(alpha, turns) if alpha is not None else None)


class PhotoRenderer:
    """Worker-owned one-photo decode cache; export uses a separate instance."""
    def __init__(self):
        self.cache = OrderedDict()

    def photo(self, project, photo_id, max_side=None, cancelled=None, before=False, fast=True):
        photo = project.state["photos"][photo_id]
        asset = photo["asset_id"]
        name = project.state["assets"][asset]["name"]
        path = project.root / "assets" / asset
        # Decode by original extension without trusting it as a path component.
        import os
        import shutil
        extension = Path(name).suffix.lower()
        folder = project.root / "decoded-inputs"
        folder.mkdir(exist_ok=True)
        named = folder / (asset + extension)
        if not named.exists():
            try:
                os.link(path, named)
            except OSError:
                shutil.copyfile(path, named)
        auto_bright = project.state["ui"]["options"].get("auto_bright", True)
        key = (str(project.root), asset, photo["engine_version"], max_side, auto_bright, fast)
        if key not in self.cache:
            # A miss replaces the single-photo cache. Release it before decoding
            # so the previous full-resolution buffer does not overlap the next.
            self.cache.clear()
            if photo["engine_version"] == "legacy-v1":
                from core.image_io import open_raw_full, open_normal, RAW_EXTS, AUTO_BRIGHT_FACTOR
                image = open_raw_full(str(named), bright=AUTO_BRIGHT_FACTOR if auto_bright else 1.0) if extension in RAW_EXTS else open_normal(str(named))
                rgba = np.asarray(image.convert("RGBA"))
                base = Frame(srgb_to_linear(rgba[..., :3].astype(np.float32)/255), rgba[..., 3].astype(np.float32)/255)
            else:
                base = decode_photo(named,max_side=max_side if fast else None,fast=bool(fast and max_side))
            if max_side and fast:
                base = resize(base, max_side)
            self.cache[key] = base
        base = self.cache[key]
        if cancelled and cancelled():
            raise RenderCancelled()
        if before:
            return resize(base,max_side) if max_side and not fast else base
        if photo["engine_version"] == "legacy-v1":
            from core.pipeline import apply_adjustments
            from core.render_engine import to_pixels
            pixels = np.asarray(apply_adjustments(Image.fromarray(to_pixels(base)), photo["adjustments"]).convert("RGBA"))
            result=Frame(srgb_to_linear(pixels[..., :3].astype(np.float32)/255), pixels[..., 3].astype(np.float32)/255)
        else:result=apply_edit(base, photo["adjustments"], cancelled)
        return resize(result,max_side) if max_side and not fast else result


def normalized_layer(layer, document):
    if "kind" in layer:
        return layer
    return dict(id=layer["photo_id"], kind="photo", name="Photo", x=0, y=0,
                width=document["width"], height=document["height"], rotation=0, opacity=1.,
                visible=True, locked=False, mask=None, data=layer)


def prepare_raster_layer(project, document, layer, renderer, scale, cancelled=None, max_side=None):
    bw,bh=layer.get('content_size',[layer['width'],layer['height']])
    lw, lh = max(1, round(bw*scale)), max(1, round(bh*scale))
    stretch_x,stretch_y=layer['width']/bw,layer['height']/bh
    if lw*lh > 60_000_000:
        raise ValueError("레이어가 너무 큽니다.")
    if layer["kind"] == "photo":
        # Conservative transform magnification avoids under-sampling stretched/warped photos.
        magnification=max(stretch_x,stretch_y)
        if 'warp' in layer:
            from core.layer_geometry import layer_matrix
            m=layer_matrix(layer);corners=np.array([[0,0,1],[layer['width'],0,1],[layer['width'],layer['height'],1],[0,layer['height'],1]])
            q=corners@m.T;z=np.min(q[:,2]);bound=[]
            for r in range(2):
                for c in range(2):bound.append(np.max(np.abs(m[r,c]*q[:,2]-q[:,r]*m[2,c]))/z**2)
            magnification*=max(1,float(np.linalg.norm(bound)))
        target=max(1,math.ceil(max(lw,lh)*magnification))
        image = renderer.photo(project, layer["data"]["photo_id"], max_side=target, cancelled=cancelled,fast=bool(max_side))
    else:
        image8 = Image.new("RGBA", (lw, lh))
        draw = ImageDraw.Draw(image8)
        data = layer["data"]
        if layer["kind"] == "text":
            if data["font"] != "Noto Sans KR" or not FONT_PATH.is_file():
                raise ValueError("문서에 필요한 글꼴이 없습니다: " + data["font"])
            font = ImageFont.truetype(str(FONT_PATH), max(1, round(data["size"]*scale)))
            draw.multiline_text((0, 0), data["text"], font=font, fill=data["color"], spacing=4*scale)
        elif layer["kind"] == "ellipse":
            draw.ellipse((0, 0, lw-1, lh-1), fill=data["color"])
        else:
            draw.rectangle((0, 0, lw-1, lh-1), fill=data["color"])
        pixels = np.asarray(image8).astype(np.float32)/255
        image = Frame(srgb_to_linear(pixels[..., :3]), pixels[..., 3])
    ih, iw = image.rgb.shape[:2]
    offset_x = offset_y = 0
    if layer["kind"] == "photo":
        ratio = min(lw/iw, lh/ih)
        offset_x, offset_y = (lw-iw*ratio)/2, (lh-ih*ratio)/2
        lw, lh = iw*ratio, ih*ratio
    offset_x*=stretch_x;offset_y*=stretch_y;lw*=stretch_x;lh*=stretch_y
    opacity = image.alpha.copy() if image.alpha is not None else np.ones((ih, iw), np.float32)
    if layer["mask"]:
        from core.layer_masks import layer_mask_pixels
        content = (offset_x/(layer['width']*scale), offset_y/(layer['height']*scale),
                   lw/(layer['width']*scale), lh/(layer['height']*scale))
        opacity *= layer_mask_pixels(layer["mask"], iw, ih, layer, content, mask_pixels, cancelled)
    opacity *= layer["opacity"]
    angle = math.radians(layer["rotation"])
    c, s = math.cos(angle), math.sin(angle)
    matrix = np.array([[c*lw/iw, -s*lh/ih, layer["x"]*scale+c*offset_x-s*offset_y],
                       [s*lw/iw, c*lh/ih, layer["y"]*scale+s*offset_x+c*offset_y]], np.float32)
    if layer.get('flip_x') or layer.get('flip_y'):
        # Reflect pixel centers around the complete layer bounds, including fit padding.
        fx=-1 if layer.get('flip_x') else 1;fy=-1 if layer.get('flip_y') else 1
        ox=(layer['width']*scale-offset_x-lw/iw) if fx<0 else offset_x
        oy=(layer['height']*scale-offset_y-lh/ih) if fy<0 else offset_y
        matrix=np.array([[c*fx*lw/iw,-s*fy*lh/ih,layer['x']*scale+c*ox-s*oy],
                         [s*fx*lw/iw,c*fy*lh/ih,layer['y']*scale+s*ox+c*oy]],np.float32)
    if 'warp' in layer:
        from core.layer_geometry import layer_matrix
        fx=-1 if layer.get('flip_x') else 1;fy=-1 if layer.get('flip_y') else 1
        ox=(layer['width']*scale-offset_x-lw/iw) if fx<0 else offset_x
        oy=(layer['height']*scale-offset_y-lh/ih) if fy<0 else offset_y
        fit=np.array([[fx*lw/iw/scale,0,ox/scale],[0,fy*lh/ih/scale,oy/scale],[0,0,1]])
        matrix=np.diag([scale,scale,1])@layer_matrix(layer)@fit
    if matrix.shape==(2,3):matrix=np.vstack((matrix,[0,0,1]))
    return image.rgb*opacity[...,None],opacity,matrix


def warp_raster(prepared,w,h,origin=(0,0)):
    rgb,alpha,matrix=prepared
    inverse=np.linalg.inv(matrix)
    output=np.empty((h,w,3),np.float32);coverage=np.empty((h,w),np.float32)
    # Absolute destination coordinates give identical interpolation at strip
    # boundaries; translated warp matrices can round differently by 1/32px.
    for top in range(0,h,128):
        yy,xx=np.ogrid[top+origin[1]:min(top+128,h)+origin[1],origin[0]:w+origin[0]]
        denominator=inverse[2,0]*xx+inverse[2,1]*yy+inverse[2,2]
        valid=np.abs(denominator)>1e-12
        mx=np.divide(inverse[0,0]*xx+inverse[0,1]*yy+inverse[0,2],denominator,out=np.full((len(yy),w),-1e6),where=valid).astype(np.float32)
        my=np.divide(inverse[1,0]*xx+inverse[1,1]*yy+inverse[1,2],denominator,out=np.full((len(yy),w),-1e6),where=valid).astype(np.float32)
        output[top:top+128]=cv2.remap(rgb,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        coverage[top:top+128]=cv2.remap(alpha,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    return output,coverage


def raster_layer(project,document,layer,renderer,scale,w,h,cancelled=None,max_side=None):
    return warp_raster(prepare_raster_layer(project,document,layer,renderer,scale,cancelled,max_side),w,h)


def render_document(project, document_id, renderer=None, max_side=None, cancelled=None):
    from core.layer_groups import ancestors
    from core.layer_blend import composite
    from core.layer_masks import layer_mask_pixels
    document=project.state['documents'][document_id];groups=document.get('groups',{})
    scale=min(1,max_side/max(document['width'],document['height'])) if max_side else 1
    w,h=max(1,round(document['width']*scale)),max(1,round(document['height']*scale))
    depth=max((len(ancestors(document,g)) for g in groups),default=0)
    import psutil
    if w*h*(160+32*depth)>psutil.virtual_memory().available*.65:
        raise ValueError('이 문서를 합성할 메모리가 부족합니다. 출력 크기를 줄이세요.')
    renderer=renderer or PhotoRenderer()
    layers=[normalized_layer(l,document) for l in document['layers']]
    def nodes(parent):
        seen=set()
        for layer in layers:
            chain=list(reversed(ancestors(document,layer.get('group_id'))))
            if parent is not None:
                if parent not in chain:continue
                chain=chain[chain.index(parent)+1:]
            if chain:
                child=chain[0]
                if child not in seen:seen.add(child);yield child
            else:yield layer
    def compose(parent,rgb=None,alpha=None):
        if rgb is None:rgb=np.zeros((h,w,3),np.float32);alpha=np.zeros((h,w),np.float32)
        pending=None
        def flush():
            nonlocal rgb,alpha,pending
            if pending is not None:
                rgb,alpha=composite(rgb,alpha,pending[0],pending[1],pending[2]);pending=None
        for node in nodes(parent):
            if cancelled and cancelled():raise RenderCancelled()
            if isinstance(node,str):
                flush();group=groups[node]
                if not group['visible']:continue
                mode=group.get('blend_mode','pass')
                if mode=='pass':rgb,alpha=compose(node,rgb,alpha)
                else:
                    gr,ga=compose(node)
                    weight=group.get('opacity',1.)
                    if group.get('mask'):
                        weight=weight*layer_mask_pixels(group['mask'],w,h,{'width':document['width'],'height':document['height']},(0,0,1,1),mask_pixels,cancelled)
                    gr*=weight if np.isscalar(weight) else weight[...,None];ga*=weight
                    rgb,alpha=composite(rgb,alpha,gr,ga,mode)
                continue
            layer=node;clipped=layer.get('clipped',False)
            if not clipped:flush()
            if not layer['visible']:continue
            if layer['kind']=='adjustment':
                straight=np.divide(rgb,alpha[...,None],out=np.zeros_like(rgb),where=alpha[...,None]>1e-8)
                adjusted=apply_edit(Frame(straight,alpha),layer['data']['adjustments'],cancelled)
                weight=layer['opacity']
                if layer['mask']:weight=weight*layer_mask_pixels(layer['mask'],w,h,layer,(0,0,1,1),mask_pixels,cancelled)
                weight=weight if np.isscalar(weight) else weight[...,None]
                rgb=(straight*(1-weight)+adjusted.rgb*weight)*alpha[...,None]
                continue
            if clipped and pending is None:continue
            sr,sa=raster_layer(project,document,layer,renderer,scale,w,h,cancelled,max_side)
            if clipped:
                br,ba,bm=pending
                straight=np.divide(br,ba[...,None],out=np.zeros_like(br),where=ba[...,None]>1e-8)
                color,_=composite(straight,np.ones_like(ba),sr,sa,layer.get('blend_mode','normal'))
                pending=(color*ba[...,None],ba,bm)
            else:pending=(sr,sa,layer.get('blend_mode','normal'))
        flush();return rgb,alpha
    rgb,alpha=compose(None)
    np.divide(rgb,alpha[...,None],out=rgb,where=alpha[...,None]>1e-8)
    return Frame(rgb,alpha)
