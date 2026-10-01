"""Layer-order compositing with disk-backed RGBA buffers and bounded row work."""
from pathlib import Path
import tempfile
import numpy as np
from core.layer_groups import ancestors
from core.layer_blend import composite
from core.layer_masks import layer_mask_pixels
from core.render_engine import Frame
from core.studio_render import PhotoRenderer, normalized_layer, prepare_raster_layer, warp_raster, apply_edit, mask_pixels


def document_pixels(project,document_id,*,matte=False,cancelled=None):
    """Exact document rendering to a single display-sized uint8 buffer."""
    from core.render_engine import RenderCancelled,to_pixels
    import psutil
    doc=project.state['documents'][document_id];w,h=doc['width'],doc['height']
    if w*h*16>psutil.virtual_memory().available*.65:
        raise ValueError('화면 픽셀 버퍼를 만들 메모리가 부족합니다. 빠른 미리보기를 사용하세요.')
    def check():
        if cancelled and cancelled():raise RenderCancelled()
    with tempfile.TemporaryDirectory(prefix='rawbaker-display-') as directory:
        compositor=DiskComposite(directory,project,doc,128,check)
        try:
            canvas=compositor.compose();pixels=np.empty((h,w,3 if matte else 4),np.uint8)
            for lo,hi in compositor.strips():
                tile=canvas[lo:hi];alpha=tile[...,3]
                if matte:frame=Frame(tile[...,:3]+(1-alpha[...,None]))
                else:
                    rgb=np.divide(tile[...,:3],alpha[...,None],out=np.zeros_like(tile[...,:3]),where=alpha[...,None]>1e-8)
                    frame=Frame(rgb,alpha)
                pixels[lo:hi]=to_pixels(frame,8)
            check();return pixels
        finally:compositor.close()


def export_document_jpeg(project,document_id,path,*,quality=95,dpi=300,protected_inputs=(),cancelled=None):
    from PIL import Image,ImageCms
    from core.safe_output import write_output
    from core.render_engine import RenderCancelled
    if not 1<=quality<=100 or not 1<=dpi<=9600:raise ValueError('품질/DPI 설정이 잘못되었습니다.')
    def write(stream):
        pixels=document_pixels(project,document_id,matte=True,cancelled=cancelled)
        image=Image.fromarray(pixels)
        image.save(stream,format='JPEG',quality=quality,dpi=(dpi,dpi),icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        if cancelled and cancelled():raise RenderCancelled()
    return write_output(write,path,mode='overwrite',protected_inputs=protected_inputs,protected_hashes=project.state['assets'])


def layer_pixels(project,document,layer,renderer=None,cancelled=None):
    """PSD raster layer, preserving its mask but excluding group/clip composition."""
    from core.render_engine import RenderCancelled,to_pixels
    renderer=renderer or PhotoRenderer()
    prepared=prepare_raster_layer(project,document,layer,renderer,1,cancelled)
    renderer.cache.clear()
    w,h=document['width'],document['height'];pixels=np.empty((h,w,4),np.uint8)
    for lo in range(0,h,128):
        if cancelled and cancelled():raise RenderCancelled()
        hi=min(h,lo+128);rgb,alpha=warp_raster(prepared,w,hi-lo,(0,lo))
        np.divide(rgb,alpha[...,None],out=rgb,where=alpha[...,None]>1e-8)
        pixels[lo:hi]=to_pixels(Frame(rgb,alpha),8)
    return pixels


class DiskComposite:
    def __init__(self, directory, project, document, rows, check, progress=None):
        self.directory=Path(directory);self.project=project;self.doc=document
        self.w=document['width'];self.h=document['height'];self.rows=rows
        self.check=check;self.progress=progress;self.serial=0;self.live={};self.done=0
        self.layers=[normalized_layer(l,document) for l in document['layers']]
        self.groups=document.get('groups',{});self.renderer=PhotoRenderer()

    def strips(self):
        for top in range(0,self.h,self.rows):
            self.check();yield top,min(self.h,top+self.rows)

    def allocate(self):
        self.serial+=1;path=self.directory/f'{self.serial}.rgba'
        value=np.memmap(path,dtype=np.float32,mode='w+',shape=(self.h,self.w,4))
        self.live[id(value)]=(value,path)
        for lo,hi in self.strips():value[lo:hi]=0
        return value

    def release(self,value):
        _,path=self.live.pop(id(value));value._mmap.close();path.unlink()

    def close(self):
        self.renderer.cache.clear()
        for value,path in list(self.live.values()):
            value._mmap.close();path.unlink()
        self.live.clear()

    def nodes(self,parent):
        seen=set()
        for layer in self.layers:
            chain=list(reversed(ancestors(self.doc,layer.get('group_id'))))
            if parent is not None:
                if parent not in chain:continue
                chain=chain[chain.index(parent)+1:]
            if chain:
                child=chain[0]
                if child not in seen:seen.add(child);yield child
            else:yield layer

    def mask(self,spec,layer):
        # One scalar mask remains full-size to preserve polygon/feather sampling.
        return layer_mask_pixels(spec,self.w,self.h,layer,(0,0,1,1),mask_pixels,self.check_cancelled) if spec else None

    def check_cancelled(self):
        self.check();return False

    def blend(self,target,source,mode,opacity=1.,mask=None):
        for lo,hi in self.strips():
            b=target[lo:hi];s=source[lo:hi]
            weight=opacity if mask is None else opacity*mask[lo:hi]
            sr=s[...,:3]* (weight if np.isscalar(weight) else weight[...,None])
            sa=s[...,3]*weight
            rgb,alpha=composite(b[...,:3],b[...,3],sr,sa,mode)
            b[...,:3]=rgb;b[...,3]=alpha

    def adjustment(self,canvas,layer):
        # Read from an immutable pass: sharpening's three-row halo must never
        # read pixels already adjusted by the preceding strip.
        output=self.allocate();edit=layer['data']['adjustments']
        halo=3 if edit.get('sharpness') else 0
        mask=self.mask(layer.get('mask'),layer)
        for lo,hi in self.strips():
            start,end=max(0,lo-halo),min(self.h,hi+halo)
            src=canvas[start:end];alpha=src[...,3]
            straight=np.divide(src[...,:3],alpha[...,None],out=np.zeros_like(src[...,:3]),where=alpha[...,None]>1e-8)
            adjusted=apply_edit(Frame(straight,alpha),edit,self.check_cancelled)
            take=slice(lo-start,hi-start);weight=layer['opacity']
            if mask is not None:weight=weight*mask[lo:hi][...,None]
            output[lo:hi,: ,:3]=(straight[take]*(1-weight)+adjusted.rgb[take]*weight)*alpha[take,...,None]
            output[lo:hi,:,3]=alpha[take]
        for lo,hi in self.strips():canvas[lo:hi]=output[lo:hi]
        self.release(output)

    def compose(self,parent=None,canvas=None):
        if canvas is None:canvas=self.allocate()
        pending=None;pending_mode='normal'
        def flush():
            nonlocal pending
            if pending is not None:
                self.blend(canvas,pending,pending_mode);self.release(pending);pending=None
        for node in self.nodes(parent):
            self.check()
            if isinstance(node,str):
                flush();group=self.groups[node]
                if not group['visible']:continue
                mode=group.get('blend_mode','pass')
                if mode=='pass':self.compose(node,canvas)
                else:
                    child=self.compose(node)
                    mask=self.mask(group.get('mask'),{'width':self.w,'height':self.h})
                    self.blend(canvas,child,mode,group.get('opacity',1.),mask)
                    del mask;self.release(child)
                continue
            layer=node;clipped=layer.get('clipped',False)
            if not clipped:flush()
            if not layer['visible']:continue
            if layer['kind']=='adjustment':self.adjustment(canvas,layer)
            elif not clipped or pending is not None:
                prepared=prepare_raster_layer(self.project,self.doc,layer,self.renderer,1,self.check_cancelled)
                self.renderer.cache.clear()
                if not clipped:pending=self.allocate();pending_mode=layer.get('blend_mode','normal')
                for lo,hi in self.strips():
                    rgb,alpha=warp_raster(prepared,self.w,hi-lo,(0,lo))
                    dest=pending[lo:hi]
                    if clipped:
                        ba=dest[...,3]
                        straight=np.divide(dest[...,:3],ba[...,None],out=np.zeros_like(dest[...,:3]),where=ba[...,None]>1e-8)
                        color,_=composite(straight,np.ones_like(ba),rgb,alpha,layer.get('blend_mode','normal'))
                        dest[...,:3]=color*ba[...,None]
                    else:dest[...,:3]=rgb;dest[...,3]=alpha
                del prepared
            self.done+=1
            if self.progress:self.progress(round(self.done*80/max(1,len(self.layers))))
        flush();return canvas
