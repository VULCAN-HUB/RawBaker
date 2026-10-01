"""PSD interchange: merged appearance or explicitly limited raster layer structure.

The writer adapter is pinned to psd-tools 1.19.0. Native text, adjustments,
smart objects and vector data stay in .rbproj, never claimed as PSD round trips.
"""
from copy import deepcopy
import io
from pathlib import Path
import tempfile
from uuid import uuid4
import numpy as np
from PIL import Image
from psd_tools import PSDImage
from psd_tools.constants import BlendMode, ColorMode
from core.project import Project
from core.render_engine import Frame, to_pixels, RenderCancelled
from core.studio_render import render_document, raster_layer, PhotoRenderer, normalized_layer
from core.safe_output import write_output

MODES = {name: getattr(BlendMode, value) for name,value in {
    'normal':'NORMAL','multiply':'MULTIPLY','screen':'SCREEN','overlay':'OVERLAY',
    'darken':'DARKEN','lighten':'LIGHTEN','difference':'DIFFERENCE','exclusion':'EXCLUSION',
    'pass':'PASS_THROUGH'}.items()}
NOTICE = 'PSD는 RGB 8비트 교환용입니다. 텍스트·도형·사진 보정·레이어 마스크는 픽셀로 변환됩니다. 혼합 모드는 다른 앱에서 재계산 시 색이 달라질 수 있습니다. 편집 원본은 .rbproj로 보관하세요.'


def check_size(width,height,memory_per_pixel=200):
    import psutil
    if max(width,height)>30000 or width*height>60_000_000 or width*height*memory_per_pixel>psutil.virtual_memory().available*.65:
        raise ValueError('PSD 교환 크기 또는 사용 가능한 메모리 한도를 초과했습니다.')


def check_cancel(cancelled):
    if cancelled and cancelled():raise RenderCancelled()


def encode_psd(project,document_id,*,layered=False,cancelled=None):
    doc=project.state['documents'][document_id];check_size(doc['width'],doc['height'],64 if layered else 48)
    layers=[normalized_layer(l,doc) for l in doc['layers']]
    if layered:
        if any(l['kind']=='adjustment' for l in layers):
            raise ValueError('조정 레이어가 있는 문서는 «합쳐진 화면» PSD로 내보내세요. 원본 편집은 .rbproj에 보존됩니다.')
        if any(g.get('mask') for g in doc.get('groups',{}).values()):
            raise ValueError('그룹 마스크가 있는 문서는 «합쳐진 화면» PSD로 내보내세요.')
        if len(layers)>500:raise ValueError('PSD 레이어는 최대 500개입니다.')
        import psutil
        if doc['width']*doc['height']*(64+8*len(layers))>psutil.virtual_memory().available*.65:
            raise ValueError('레이어 PSD를 만들 메모리가 부족합니다. 합쳐진 화면을 선택하세요.')
    from core.disk_composite import document_pixels
    merged=Image.fromarray(document_pixels(project,document_id,cancelled=cancelled))
    psd=PSDImage.frompil(merged)
    from PIL import ImageCms
    from psd_tools.constants import Resource
    from psd_tools.psd.image_resources import ImageResource
    psd.image_resources[Resource.ICC_PROFILE]=ImageResource(key=Resource.ICC_PROFILE,data=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    if layered:
        groups={};renderer=PhotoRenderer()
        def group_for(key):
            if key is None:return psd
            if key not in groups:
                spec=doc['groups'][key];parent=group_for(spec.get('parent_id'))
                group=psd.create_group(name='Group',blend_mode=MODES[spec.get('blend_mode','pass')],opacity=round(spec.get('opacity',1)*255))
                group.name=spec['name'][:200];group.visible=spec['visible']
                if parent is not psd:parent.append(group)
                groups[key]=group
            return groups[key]
        for layer in layers:
            check_cancel(cancelled)
            parent=group_for(layer.get('group_id'))
            spec=deepcopy(layer);spec['opacity']=1
            from core.disk_composite import layer_pixels
            image=Image.fromarray(layer_pixels(project,doc,spec,renderer,cancelled))
            pixel=psd.create_pixel_layer(image,name='Layer',opacity=round(layer['opacity']*255),blend_mode=MODES[layer.get('blend_mode','normal')])
            pixel.name=layer['name'][:200];pixel.visible=layer['visible'];pixel.clipping=layer.get('clipped',False)
            if parent is not psd:parent.append(pixel)
    else:
        pixel=psd.create_pixel_layer(merged,name='RawBaker composite')
    check_cancel(cancelled)
    # Public save recomposites in a different blending space and omits the merged
    # alpha marker. Compile records, then write our exact preview + PSD alpha flag.
    psd._update_record()
    info=psd._record.layer_and_mask_information.layer_info
    info.layer_count=-abs(info.layer_count)
    # PSD merged RGB is matted against white; layer channels remain straight.
    preview=np.array(merged)
    for top in range(0,len(preview),128):
        check_cancel(cancelled);tile=preview[top:top+128].astype(np.float32);alpha=tile[...,3:4]/255
        preview[top:top+128,:,:3]=np.rint(tile[...,:3]*alpha+255*(1-alpha)).astype(np.uint8)
    matted=Image.fromarray(preview)
    psd._record.image_data.set_data([c.tobytes() for c in matted.split()],psd._record.header)
    output=io.BytesIO();psd._record.write(output)
    return output.getvalue()


def export_psd(project,document_id,path,*,layered=False,protected_inputs=(),cancelled=None):
    data=encode_psd(project,document_id,layered=layered,cancelled=cancelled)
    check_cancel(cancelled)
    return write_output(data,path,mode='rename',protected_inputs=protected_inputs,protected_hashes=project.state['assets'])


def import_psd(project,path,*,layered=False,cancelled=None):
    """Stage state and commit once. Unsupported layered input fails before mutation."""
    import psutil
    psd=PSDImage.open(path,max_alloc_bytes=min(512*1024**2,int(psutil.virtual_memory().available*.25)))
    # Import stages 8-bit PIL rasters, not full-document float32 composites.
    # The aggregate layer-area check below additionally bounds layered inputs.
    check_size(psd.width,psd.height,48)
    if psd.depth!=8 or psd.color_mode!=ColorMode.RGB:raise ValueError('현재 PSD 가져오기는 RGB 8비트만 지원합니다.')
    reverse={v:k for k,v in MODES.items()}
    if layered:
        all_layers=list(psd.descendants())
        if not all_layers or len(all_layers)>500:raise ValueError('PSD 레이어 수는 1~500개여야 합니다.')
        if sum(l.width*l.height for l in all_layers if not l.is_group())*24>psutil.virtual_memory().available*.65:
            raise ValueError('PSD 레이어를 가져올 메모리가 부족합니다.')
        from psd_tools.constants import Tag
        for layer in all_layers:
            if layer.tagged_blocks.get_data(Tag.BLEND_FILL_OPACITY,255)!=255:
                raise ValueError('채우기 불투명도가 있는 PSD는 합쳐진 화면으로 가져오세요.')
            if layer.kind not in ('pixel','group') or layer.has_mask() or layer.has_vector_mask() or len(layer.effects) or layer.blend_mode not in reverse:
                raise ValueError('지원하지 않는 PSD 레이어·마스크·효과가 있습니다. «합쳐진 화면»으로 가져오세요.')
            if layer.is_group() and (not len(layer) or layer.clipping):raise ValueError('빈 그룹 또는 클리핑 그룹은 지원하지 않습니다.')
            if layer.is_group() and layer.blend_mode==BlendMode.PASS_THROUGH and layer.opacity!=255:
                raise ValueError('불투명도가 있는 통과 그룹은 합쳐진 화면으로 가져오세요.')
            if not layer.is_group() and (layer.width<=0 or layer.height<=0):raise ValueError('빈 픽셀 레이어는 지원하지 않습니다.')
    staged=Project(project.root,project.state)
    original=staged.import_photo(path,engine_version='linear-v1')
    del staged.state['photos'][original];staged.state['ui']['photo_order'].remove(original)
    doc={'width':psd.width,'height':psd.height,'layers':[],'groups':{}}
    with tempfile.TemporaryDirectory(prefix='rawbaker-psd-') as folder:
        def add_image(image,name,x=0,y=0,opacity=1,visible=True,mode='normal',parent=None,clipped=False):
            check_cancel(cancelled)
            if image is None:raise ValueError('PSD에 읽을 수 있는 픽셀이 없습니다.')
            target=Path(folder)/(str(uuid4())+'.png');image.convert('RGBA').save(target)
            photo=staged.import_photo(target,engine_version='linear-v1')
            layer=dict(id=str(uuid4()),kind='photo',name=name[:200],x=x,y=y,width=image.width,height=image.height,rotation=0,opacity=opacity,visible=visible,locked=False,mask=None,data={'photo_id':photo},blend_mode=mode,clipped=clipped)
            if parent:layer['group_id']=parent
            doc['layers'].append(layer)
        def walk(container,parent=None,depth=0):
            if depth>8:raise ValueError('PSD 그룹 중첩은 최대 8단계입니다.')
            for layer in container:
                check_cancel(cancelled)
                if layer.is_group():
                    key=str(uuid4());doc['groups'][key]=dict(name=layer.name[:200] or '그룹',parent_id=parent,opacity=layer.opacity/255,visible=layer.visible,locked=False,blend_mode=reverse[layer.blend_mode])
                    walk(layer,key,depth+1)
                else:add_image(layer.topil(),layer.name,layer.left,layer.top,layer.opacity/255,layer.visible,reverse[layer.blend_mode],parent,layer.clipping)
        if layered:walk(psd)
        else:add_image(psd.topil(),Path(path).stem)
    key=str(uuid4());staged.state['documents'][key]=doc
    check_cancel(cancelled);project._change(staged.state)
    return key
