"""Atomic history operations: one UI action equals one undo entry."""
from copy import deepcopy
from uuid import uuid4
from core.edit_spec import globals_only, validate_edit


def edit_photos(project, photo_ids, settings, *, synchronize=False):
    validate_edit(settings)
    state = deepcopy(project.state)
    for key in photo_ids:
        photo = state["photos"][key]
        if photo["engine_version"] != "linear-v1":
            raise ValueError("기존 보정은 새 보정본을 만든 후 편집하세요.")
        if synchronize:
            retained = {k: v for k, v in photo["adjustments"].items() if k not in globals_only(photo["adjustments"])}
            photo["adjustments"] = {**retained, **globals_only(settings)}
        else:
            photo["adjustments"] = deepcopy(settings)
    if state != project.state:
        project._change(state)


def linear_copy(project, photo_id):
    state = deepcopy(project.state)
    key = str(uuid4())
    photo = deepcopy(state["photos"][photo_id])
    photo["engine_version"], photo["adjustments"] = "linear-v1", {}
    state["photos"][key] = photo
    if photo_id in state["ui"].get("photo_names", {}):
        state["ui"]["photo_names"][key] = state["ui"]["photo_names"][photo_id]
    state["ui"]["photo_order"].append(key)
    project._change(state)
    return key


def add_layer(project, document_id, kind, photo_id=None, text="RawBaker"):
    state = deepcopy(project.state)
    doc = state["documents"][document_id]
    key = str(uuid4())
    data = {"photo_id": photo_id} if kind == "photo" else ({'adjustments':{}} if kind=='adjustment' else ({"text": text, "font": "Noto Sans KR", "size": 64, "color": "#ffffff"} if kind == "text" else {"color": "#e6a66b"}))
    doc["layers"].append(dict(id=key, kind=kind, name=text if kind == "text" else kind,
        x=doc["width"]*.1, y=doc["height"]*.1, width=doc["width"]*.6, height=doc["height"]*.5,
        rotation=0., opacity=1., visible=True, locked=False, mask=None, data=data, blend_mode='normal'))
    if kind=='adjustment':doc['layers'][-1].update(x=0.,y=0.,width=doc['width'],height=doc['height'],name='조정 레이어')
    project._change(state)
    return key


def change_layer(project, document_id, layer_id, update):
    state = deepcopy(project.state)
    layer = next(l for l in state["documents"][document_id]["layers"] if l.get("id") == layer_id)
    from core.layer_groups import group_locked
    if group_locked(state['documents'][document_id],layer):raise ValueError('잠긴 그룹입니다.')
    if layer["locked"] and set(update) != {"locked"}:
        raise ValueError("잠긴 레이어입니다.")
    layer.update(deepcopy(update))
    if state != project.state:
        project._change(state)


def edit_layers(project, document_id, layer_ids, operation, values=None):
    """All-or-nothing multi-layer operation, including validation and one undo."""
    ids=set(layer_ids)
    if not ids:return []
    state=deepcopy(project.state);layers=state['documents'][document_id]['layers']
    document=state['documents'][document_id]
    from core.layer_groups import group_locked,cleanup_structure
    selected=[layer for layer in layers if layer.get('id') in ids]
    if len(selected)!=len(ids):raise ValueError('선택한 레이어가 없습니다.')
    if operation not in ('move','update','duplicate','delete'):raise ValueError('지원하지 않는 레이어 작업입니다.')
    if operation!='duplicate' and any(layer['locked'] or group_locked(document,layer) for layer in selected):
        raise ValueError('선택에 잠긴 레이어가 있습니다. 잠금을 해제하세요.')
    result=[layer['id'] for layer in selected]
    if operation=='duplicate':
        copies=deepcopy(selected);result=[]
        groups=document.get('groups',{});group_copies={}
        from core.layer_groups import members
        for key,group in list(groups.items()):
            member_ids={l['id'] for l in members(document,key)}
            if member_ids and member_ids<=ids:
                new_key=str(uuid4());group_copies[key]=new_key
                groups[new_key]={**deepcopy(group),'name':group['name']+' 복사','locked':False}
        for old,new in group_copies.items():groups[new]['parent_id']=group_copies.get(groups[old].get('parent_id'))
        clip_base={};base=None;previous_group=None
        for layer in layers:
            if not layer.get('clipped') or layer.get('group_id')!=previous_group:base=layer.get('id')
            clip_base[layer.get('id')]=base;previous_group=layer.get('group_id')
        for layer in copies:
            if layer.get('clipped') and clip_base[layer['id']] not in ids:layer['clipped']=False
            group=layer.pop('group_id',None)
            if group in group_copies:layer['group_id']=group_copies[group]
            layer['id']=str(uuid4());layer['name']+=' 복사';layer['locked']=False;result.append(layer['id'])
        from core.layer_groups import ancestors
        touched={g for l in selected for g in ancestors(document,l.get('group_id'))}
        last=max(i for i,layer in enumerate(layers) if layer.get('id') in ids or set(ancestors(document,layer.get('group_id')))&touched)
        layers[last+1:last+1]=copies
    elif operation=='delete':
        base=None
        for layer in layers:
            if not layer.get('clipped'):base=layer.get('id')
            elif base in ids and layer.get('id') not in ids:
                if layer['locked'] or group_locked(document,layer):raise ValueError('잠긴 클리핑 레이어의 기준을 삭제할 수 없습니다.')
                layer['clipped']=False
        layers[:]=[layer for layer in layers if layer.get('id') not in ids];result=[]
        cleanup_structure(document)
    elif operation=='move':
        if type(values) is not dict or set(values)!={'dx','dy'}:raise ValueError('이동 값이 잘못되었습니다.')
        for layer in selected:layer['x']+=values['dx'];layer['y']+=values['dy']
    else:
        if type(values) is not dict or not values or set(values)-{'opacity','blend_mode','visible'}:
            raise ValueError('일괄 변경할 수 없는 속성입니다.')
        for layer in selected:layer.update(deepcopy(values))
    if state!=project.state:project._change(state)
    return result
