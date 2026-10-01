"""Single-level, contiguous pass-through groups and sibling clipping chains."""
from copy import deepcopy
from uuid import uuid4


def ancestors(document,group_id):
    result=[];groups=document.get('groups',{})
    while group_id is not None:
        if group_id not in groups or group_id in result or len(result)>=8:raise ValueError('그룹 계층이 없거나 순환/8단계 초과입니다.')
        result.append(group_id);group_id=groups[group_id].get('parent_id')
    return result


def members(document,group_id):
    return [l for l in document['layers'] if group_id in ancestors(document,l.get('group_id'))]


def validate_groups(document):
    groups=document.get('groups',{})
    if type(groups) is not dict:raise ValueError('그룹 목록이 잘못되었습니다.')
    for key,group in groups.items():
        if type(key) is not str or not key or type(group) is not dict or not {'name','visible','locked'}<=set(group) or set(group)-{'name','visible','locked','parent_id','blend_mode','opacity','mask'}:
            raise ValueError('그룹 형식이 잘못되었습니다.')
        if type(group['name']) is not str or not group['name'] or len(group['name'])>200 or type(group['visible']) is not bool or type(group['locked']) is not bool:
            raise ValueError('그룹 속성이 잘못되었습니다.')
        ancestors(document,key)
        from core.layer_blend import BLEND_MODES
        from core.edit_spec import number
        number(group.get('opacity',1),0,1)
        if group.get('blend_mode','pass') not in ('pass',)+BLEND_MODES:raise ValueError('그룹 혼합 모드가 잘못되었습니다.')
        if group.get('mask') is not None:
            from core.layer_masks import validate_layer_mask
            validate_layer_mask(group['mask'])
        if group.get('blend_mode','pass')=='pass' and (group.get('opacity',1)!=1 or group.get('mask') is not None):raise ValueError('그룹 불투명도/마스크에는 격리 혼합이 필요합니다.')
    members={};base=None;previous_group=None
    for i,layer in enumerate(document['layers']):
        group=layer.get('group_id')
        if group is not None:
            if group not in groups:raise ValueError('레이어 그룹이 없습니다.')
            for ancestor in ancestors(document,group):members.setdefault(ancestor,[]).append(i)
        if layer.get('clipped',False):
            if base is None or base.get('kind')=='adjustment' or group!=previous_group:raise ValueError('클리핑 기준 레이어가 없습니다.')
        else:base=layer
        previous_group=group
    if set(members)!=set(groups):raise ValueError('비어 있는 그룹입니다.')
    if any(max(indices)-min(indices)+1!=len(indices) for indices in members.values()):
        raise ValueError('그룹 레이어는 연속되어야 합니다.')


def cleanup_structure(document):
    used={g for l in document['layers'] for g in ancestors(document,l.get('group_id'))}
    if 'groups' in document:document['groups']={k:v for k,v in document['groups'].items() if k in used}
    base=None;previous_group=None
    for layer in document['layers']:
        group=layer.get('group_id')
        if layer.get('clipped',False) and (base is None or group!=previous_group):layer['clipped']=False
        if not layer.get('clipped',False):base=layer
        previous_group=group


def group_locked(document,layer):
    return any(document['groups'][g]['locked'] for g in ancestors(document,layer.get('group_id')))


def make_group(project,document_id,layer_ids,name='새 그룹'):
    state=deepcopy(project.state);doc=state['documents'][document_id];ids=set(layer_ids)
    indices=[i for i,l in enumerate(doc['layers']) if l.get('id') in ids]
    if not indices or len(indices)!=len(ids):raise ValueError('그룹으로 묶을 레이어를 선택하세요.')
    if max(indices)-min(indices)+1!=len(indices):raise ValueError('쌓임 순서가 연속된 레이어를 선택하세요.')
    selected=[doc['layers'][i] for i in indices]
    if any(l['locked'] or group_locked(doc,l) for l in selected):raise ValueError('잠긴 레이어/그룹을 해제하세요.')
    groups=doc.setdefault('groups',{})
    paths=[ancestors(doc,l.get('group_id'))+[None] for l in selected]
    parent=next(g for g in paths[0] if all(g in path for path in paths))
    if parent is not None and {l['id'] for l in members(doc,parent)}<=ids:parent=groups[parent].get('parent_id')
    children=[g for g,v in groups.items() if v.get('parent_id')==parent and {l['id'] for l in members(doc,g)}&ids]
    if any(not {l['id'] for l in members(doc,g)}<=ids for g in children):raise ValueError('하위 그룹을 나누지 말고 전체 선택하세요.')
    # Do not silently sever an existing clipping chain at either boundary.
    if selected[0].get('clipped') or (max(indices)+1<len(doc['layers']) and doc['layers'][max(indices)+1].get('clipped')):
        raise ValueError('클리핑 기준과 연결된 레이어를 함께 선택하세요.')
    key=str(uuid4());groups[key]=dict(name=name,visible=True,locked=False,parent_id=parent)
    for child in children:groups[child]['parent_id']=key
    for layer in selected:
        if layer.get('group_id')==parent:layer['group_id']=key
    project._change(state);return key


def change_group(project,document_id,group_id,update=None,ungroup=False):
    state=deepcopy(project.state);doc=state['documents'][document_id];group=doc.get('groups',{}).get(group_id)
    if group is None:raise ValueError('그룹이 없습니다.')
    if group_locked(doc,{'group_id':group.get('parent_id')}) or (group['locked'] and (ungroup or set(update or {})!={'locked'})):raise ValueError('잠긴 그룹입니다.')
    if ungroup:
        if group.get('blend_mode','pass')!='pass':raise ValueError('격리 그룹은 통과 모드로 변경한 뒤 해제하세요.')
        for layer in doc['layers']:
            if layer.get('group_id')==group_id:
                layer.pop('group_id');layer['visible']=layer['visible'] and group['visible']
                if group.get('parent_id'):layer['group_id']=group['parent_id']
        for key,child in doc['groups'].items():
            if child.get('parent_id')==group_id:child['parent_id']=group.get('parent_id');child['visible']=child['visible'] and group['visible']
        del doc['groups'][group_id]
    else:
        if not update or set(update)-{'name','visible','locked','blend_mode','opacity','mask'}:raise ValueError('지원하지 않는 그룹 속성입니다.')
        group.update(update)
    if state!=project.state:project._change(state)


def set_clipping(project,document_id,layer_id,enabled):
    state=deepcopy(project.state);doc=state['documents'][document_id];layers=doc['layers']
    index=next(i for i,l in enumerate(layers) if l.get('id')==layer_id);layer=layers[index]
    if layer['locked'] or group_locked(doc,layer):raise ValueError('잠긴 레이어 또는 그룹입니다.')
    if enabled and (index==0 or layers[index-1].get('group_id')!=layer.get('group_id')):
        raise ValueError('같은 그룹 안의 아래 레이어가 필요합니다.')
    layer['clipped']=enabled
    if state!=project.state:project._change(state)


def reorder_block(project,document_id,key,offset,*,group=False):
    """Swap adjacent sibling blocks without splitting groups or clipping chains."""
    if offset not in (-1,1):raise ValueError('잘못된 순서 이동입니다.')
    state=deepcopy(project.state);doc=state['documents'][document_id];layers=doc['layers'];groups=doc.get('groups',{})
    target=None if group else next((l for l in layers if l.get('id')==key),None)
    if (group and key not in groups) or (not group and target is None):raise ValueError('순서를 변경할 대상이 없습니다.')
    parent=groups[key].get('parent_id') if group else target.get('group_id')
    blocks=[];seen=set()
    for layer in layers:
        chain=list(reversed(ancestors(doc,layer.get('group_id'))))
        if parent is not None:
            if parent not in chain:continue
            chain=chain[chain.index(parent)+1:]
        if chain:
            child=chain[0]
            if child not in seen:blocks.append(members(doc,child));seen.add(child)
        elif layer.get('clipped'):
            blocks[-1].append(layer)
        else:blocks.append([layer])
    ids={l['id'] for l in members(doc,key)} if group else {key}
    index=next(i for i,b in enumerate(blocks) if ids & {l['id'] for l in b})
    other=index+offset
    if not 0<=other<len(blocks):return False
    a,b=blocks[index],blocks[other]
    if any(l['locked'] or group_locked(doc,l) for l in a+b):raise ValueError('잠긴 레이어 또는 그룹의 순서는 변경할 수 없습니다.')
    first=min(layers.index(l) for l in a+b);last=max(layers.index(l) for l in a+b)
    if last-first+1!=len(a)+len(b):raise ValueError('연속된 형제 순서만 변경할 수 있습니다.')
    layers[first:last+1]=(b+a if offset==1 else a+b)
    project._change(state);return True


def relocate_block(project, document_id, source, target=None, position='above'):
    """Move a group subtree or complete clipping chain in one validated edit.

    Keys use ``group:`` for groups. Above/below refer to the displayed stack.
    """
    if position not in ('above','below','inside','root'):raise ValueError('잘못된 삽입 위치입니다.')
    state=deepcopy(project.state);doc=state['documents'][document_id]
    layers=doc['layers'];groups=doc.get('groups',{})
    def block(key):
        if isinstance(key,str) and key.startswith('group:'):
            gid=key[6:]
            if gid not in groups:raise ValueError('그룹이 없습니다.')
            return members(doc,gid),gid
        index=next((i for i,l in enumerate(layers) if l['id']==key),None)
        if index is None:raise ValueError('레이어가 없습니다.')
        while layers[index].get('clipped'):index-=1
        end=index+1
        while end<len(layers) and layers[end].get('clipped') and layers[end].get('group_id')==layers[index].get('group_id'):end+=1
        return layers[index:end],None
    moving,gid=block(source);ids={l['id'] for l in moving}
    if any(l['locked'] or group_locked(doc,l) for l in moving):raise ValueError('잠긴 레이어 또는 그룹은 이동할 수 없습니다.')
    if position=='root':parent=None;destination=[]
    else:
        destination,target_group=block(target)
        if position=='inside':
            if target_group is None:raise ValueError('그룹 안으로만 이동할 수 있습니다.')
            parent=target_group
        else:parent=groups[target_group].get('parent_id') if target_group else destination[0].get('group_id')
        if gid and parent is not None and gid in ancestors(doc,parent):raise ValueError('자신 또는 하위 그룹 안으로 이동할 수 없습니다.')
        if source==target:return False
        if any(l['locked'] or group_locked(doc,l) for l in destination):raise ValueError('잠긴 대상에는 이동할 수 없습니다.')
        if position!='inside' and ids & {l['id'] for l in destination}:
            # A child may leave its ancestor next to the whole ancestor block.
            if not target_group:return False
    if parent is not None and group_locked(doc,{'group_id':parent}):raise ValueError('잠긴 그룹입니다.')
    remaining=[l for l in layers if l['id'] not in ids]
    anchors=[i for i,l in enumerate(remaining) if l in destination]
    if position=='root':index=0
    elif anchors:index=max(anchors)+1 if position in ('above','inside') else min(anchors)
    else:
        # Moving an only child next to its parent removes the empty parent.
        index=sum(1 for l in layers[:layers.index(moving[0])] if l['id'] not in ids)
    if gid:groups[gid]['parent_id']=parent
    else:
        for layer in moving:
            layer.pop('group_id',None)
            if parent is not None:layer['group_id']=parent
    doc['layers']=remaining[:index]+moving+remaining[index:]
    used={g for l in doc['layers'] for g in ancestors(doc,l.get('group_id'))}
    if 'groups' in doc:doc['groups']={k:v for k,v in groups.items() if k in used}
    if state==project.state:return False
    project._change(state);return True
