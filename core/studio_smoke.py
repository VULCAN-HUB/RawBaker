"""Small packaged-runtime verification using generated data only."""
from pathlib import Path
import numpy as np
from PIL import Image
from core.project import Project
from core.project_store import save_project, load_project
from core.studio_commands import edit_photos, add_layer, change_layer
from core.studio_render import PhotoRenderer, render_document
from core.studio_export import export_image
from core.render_engine import to_pixels
from core.render_io import decode_photo
from assets.make_test_raw import make_dng


def run_smoke(root):
    root = Path(root)
    root.mkdir(parents=True)
    source = root/"한글 원본.png"
    Image.new("RGBA", (64, 48), (120, 60, 30, 190)).save(source)
    original = source.read_bytes()
    project = Project(root/"project")
    key = project.import_photo(source, engine_version="linear-v1")
    edit_photos(project, [key], {"exposure": .5, "shadows": 10})
    photo = PhotoRenderer().photo(project, key)
    export_image(photo, root/"photo.png", format="PNG", bits=16, protected_inputs=[source])
    export_image(photo, root/"photo.jpg", format="JPEG", dpi=300, protected_inputs=[source])
    assert source.read_bytes() == original
    doc = project.add_document(160, 100, [])
    placed = add_layer(project, doc, "photo", key)
    from core.layer_masks import selection_mask, paint_stroke
    layer = project.state['documents'][doc]['layers'][0]
    mask = selection_mask(layer, project.state['documents'][doc], [[.1,.1],[.65,.1],[.65,.8],[.1,.8]])
    mask = paint_stroke(mask,layer,project.state['documents'][doc],[[.3,.3],[.5,.5]],8,.5,False)
    change_layer(project,doc,placed,{'mask':mask})
    from core.studio_commands import edit_layers
    tint=add_layer(project,doc,'rectangle')
    edit_layers(project,doc,[placed,tint],'update',{'blend_mode':'screen','opacity':.8})
    edit_layers(project,doc,[placed,tint],'move',{'dx':2.,'dy':1.})
    from core.layer_groups import make_group,set_clipping
    set_clipping(project,doc,tint,True)
    make_group(project,doc,[placed,tint],'Smoke group')
    text = add_layer(project, doc, "text", text="한글 RawBaker")
    change_layer(project, doc, text, {"x": 0, "y": 0, "width": 160, "height": 60,
        "data": {"text": "한글 RawBaker", "font": "Noto Sans KR", "size": 16, "color": "#ffffff"}})
    pixels = to_pixels(render_document(project, doc), 16)
    save_project(project, root/"project.rbproj")
    source.unlink()
    reopened, _ = load_project(root/"project.rbproj", root/"reopened")
    np.testing.assert_array_equal(pixels, to_pixels(render_document(reopened, doc), 16))
    from core.psd_io import export_psd,import_psd
    psd_path=export_psd(project,doc,root/'교환.psd',layered=True)
    imported=import_psd(project,psd_path,layered=True)
    assert len(project.state['documents'][imported]['layers'])==3
    from core.layer_groups import change_group
    group=next(iter(project.state['documents'][doc]['groups']))
    change_group(project,doc,group,{'blend_mode':'normal','opacity':.7})
    adjustment=add_layer(project,doc,'adjustment')
    change_layer(project,doc,adjustment,{'data':{'adjustments':{'exposure':.3}}})
    export_psd(project,doc,root/'합쳐진화면.psd')
    save_project(project,root/'advanced.rbproj')
    advanced,_=load_project(root/'advanced.rbproj',root/'advanced-reopened')
    np.testing.assert_array_equal(to_pixels(render_document(project,doc),16),to_pixels(render_document(advanced,doc),16))
    from ui.selection_geometry import combine_selection
    from core.layer_groups import reorder_block
    selected=combine_selection([[0,0],[1,0],[1,1],[0,1]],False,[[.3,.3],[.7,.3],[.7,.7],[.3,.7]],'subtract')
    adj=next(l for l in project.state['documents'][doc]['layers'] if l['id']==adjustment)
    change_layer(project,doc,adjustment,{'mask':selection_mask(adj,project.state['documents'][doc],selected)})
    assert reorder_block(project,doc,group,1,group=True)
    save_project(project,root/'selection.rbproj')
    selected_project,_=load_project(root/'selection.rbproj',root/'selection-reopened')
    np.testing.assert_array_equal(to_pixels(render_document(project,doc),16),to_pixels(render_document(selected_project,doc),16))
    from ui.selection_geometry import offset_selection
    from core.layer_transform import transform_layers
    from core.color_selection import color_selection
    doc_spec=project.state['documents'][doc]
    refined=offset_selection(selected,False,doc_spec['width'],doc_spec['height'],3)
    change_layer(project,doc,adjustment,{'mask':selection_mask(adj,doc_spec,refined,feather=5)})
    transform_layers(project,doc,[placed,tint],.9,5)
    color=color_selection(render_document(project,doc,max_side=128),[.5,.5],20,True)
    assert isinstance(color['rings'],list)
    save_project(project,root/'refined.rbproj')
    refined_project,_=load_project(root/'refined.rbproj',root/'refined-reopened')
    np.testing.assert_array_equal(to_pixels(render_document(project,doc),16),to_pixels(render_document(refined_project,doc),16))
    from core.selection_history import SelectionHistory
    history=SelectionHistory();history.change(color);history.change(color,True);history.change()
    assert history.undo() and history.current[1] and history.redo()
    native_rgb=np.zeros((1025,1025,3),np.float32);native_rgb[512,512]=1
    from core.render_engine import Frame
    native_selection=color_selection(Frame(native_rgb),[.5,.5],0)
    assert native_selection['rings'] and len(native_selection['rings'][0])>=4
    from core.layer_groups import relocate_block
    from copy import deepcopy
    before_move=deepcopy(project.state['documents'][doc])
    assert relocate_block(project,doc,tint,None,'root')
    assert project.undo() and project.state['documents'][doc]==before_move
    from ui.selection_geometry import refine_selection
    edge=refine_selection([[.2,.2],[.8,.2],[.8,.8],[.2,.8]],False,100,100,2,-1)
    assert edge['rings']
    from core.layer_transform import transform_local_layers
    before_local=deepcopy(project.state['documents'][doc])
    transform_local_layers(project,doc,[placed,tint],1.2,.8,True,False)
    save_project(project,root/'local-transform.rbproj')
    transformed,_=load_project(root/'local-transform.rbproj',root/'local-reopened')
    np.testing.assert_array_equal(to_pixels(render_document(project,doc),16),to_pixels(render_document(transformed,doc),16))
    assert project.undo() and project.state['documents'][doc]==before_local
    from core.layer_transform import transform_world_layers,world_transform_matrix,selection_bounds
    matrix=world_transform_matrix(selection_bounds(project.state['documents'][doc],[placed,tint]),1.1,.9,10,0,[[5,0],[-5,0],[0,0],[0,0]])
    transform_world_layers(project,doc,[placed,tint],matrix)
    save_project(project,root/'world-transform.rbproj')
    world,_=load_project(root/'world-transform.rbproj',root/'world-reopened')
    np.testing.assert_array_equal(to_pixels(render_document(project,doc),16),to_pixels(render_document(world,doc),16))
    from core.layer_transform import move_projective_corner
    from core.layer_geometry import layer_corners
    before_corner=deepcopy(project.state['documents'][doc])
    placed_layer=next(l for l in before_corner['layers'] if l['id']==placed)
    corner=layer_corners(placed_layer)[0]
    move_projective_corner(project,doc,placed,0,[corner[0]+1,corner[1]+1])
    assert project.undo() and project.state['documents'][doc]==before_corner
    from core.layer_masks import paint_stroke
    brush_doc=project.state['documents'][doc]
    brush_layer=next(l for l in brush_doc['layers'] if l['id']==placed)
    brush=paint_stroke(brush_layer['mask'],brush_layer,brush_doc,[[.5,.5]],10,.2,False)
    change_layer(project,doc,placed,{'mask':brush})
    brush_pixels=to_pixels(render_document(project,doc),16)
    save_project(project,root/'projective-brush.rbproj')
    painted,_=load_project(root/'projective-brush.rbproj',root/'brush-reopened')
    np.testing.assert_array_equal(to_pixels(render_document(painted,doc),16),brush_pixels)
    assert project.undo() and project.state['documents'][doc]==before_corner
    from core.layer_transform import move_selection_corner
    x0,y0,x1,y1=selection_bounds(project.state['documents'][doc],[placed,tint])
    move_selection_corner(project,doc,[placed,tint],0,[x0+1,y0+1])
    assert project.undo() and project.state['documents'][doc]==before_corner
    from core.tiled_export import export_document_png
    tile_doc=project.add_document(80,60,[])
    tile_layer=add_layer(project,tile_doc,'rectangle')
    tile_path=root/'strip-export.png'
    export_document_png(project,tile_doc,tile_path,bits=16,tile_rows=13)
    np.testing.assert_allclose(to_pixels(decode_photo(tile_path),16),to_pixels(render_document(project,tile_doc),16),atol=1)
    adjustment=add_layer(project,tile_doc,'adjustment')
    change_layer(project,tile_doc,adjustment,{'data':{'adjustments':{'exposure':.5,'sharpness':30}}})
    from core.layer_groups import make_group,change_group
    group=make_group(project,tile_doc,[tile_layer,adjustment])
    change_group(project,tile_doc,group,{'blend_mode':'normal','opacity':.7})
    export_document_png(project,tile_doc,root/'complex-export.png',tile_rows=7)
    np.testing.assert_allclose(to_pixels(decode_photo(root/'complex-export.png'),16),to_pixels(render_document(project,tile_doc),16),atol=1)
    from core.disk_composite import document_pixels,export_document_jpeg
    np.testing.assert_array_equal(document_pixels(project,tile_doc),to_pixels(render_document(project,tile_doc),8))
    export_document_jpeg(project,tile_doc,root/'document.jpg')
    with Image.open(root/'document.jpg') as image:assert image.size==(80,60)
    raw = root/"한글 RAW.dng"
    make_dng(str(raw), 128, 128)
    frame = decode_photo(raw)
    assert frame.rgb.dtype == np.float32 and np.isfinite(frame.rgb).all()
    from ui.editor_i18n import localize
    from types import SimpleNamespace
    assert localize("취소", SimpleNamespace(lang_key="en")) == "Cancel"
    return {"editor_english_catalog": True, "photo_render": True, "png16_jpeg_export": True, "original_protection": True,
            "portable_project": True, "linked_design": True, "korean_font": True,
            "actual_libraw_synthetic_dng": True, "layer_mask_roundtrip": True,
            "blend_multi_layer_roundtrip": True, "group_clipping_roundtrip": True, "psd_layered_and_merged": True, "adjustment_isolated_group": True, "boolean_selection_mask": True, "group_order_roundtrip": True, "feather_color_selection": True, "multi_transform_roundtrip": True, "native_tiny_color_selection": True, "selection_history": True, "layer_relocation_undo": True, "edge_refinement": True, "local_transform_roundtrip": True, "world_transform_roundtrip": True, "projective_corner_undo": True, "projective_brush_roundtrip": True, "multi_corner_undo": True, "tiled_png_export": True, "complex_disk_export": True, "native_document_pixels": True, "document_jpeg": True}
