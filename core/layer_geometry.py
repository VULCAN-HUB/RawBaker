"""One projective coordinate model shared by rendering, masks and hit testing."""
import math
import numpy as np


def layer_matrix(layer):
    if 'warp' in layer:matrix=np.array(layer['warp'],dtype=np.float64).reshape(3,3)
    else:
        c,s=math.cos(math.radians(layer['rotation'])),math.sin(math.radians(layer['rotation']))
        matrix=np.array([[c,-s,0],[s,c,0],[0,0,1]],dtype=np.float64)
    return np.array([[1,0,layer['x']],[0,1,layer['y']],[0,0,1]],dtype=np.float64)@matrix


def map_points(matrix,points):
    data=np.column_stack((np.asarray(points,dtype=np.float64),np.ones(len(points))))@matrix.T
    if not np.isfinite(data).all() or np.any(np.abs(data[:,2])<1e-8):raise ValueError('변형 경계가 무한대에 닿습니다.')
    return (data[:,:2]/data[:,2:]).tolist()


def layer_corners(layer):
    return map_points(layer_matrix(layer),[(0,0),(layer['width'],0),(layer['width'],layer['height']),(0,layer['height'])])


def validate_warp(layer):
    values=layer['warp']
    if layer['kind']=='adjustment' or type(values) is not list or len(values)!=9:raise ValueError('변형 행렬이 잘못되었습니다.')
    from core.edit_spec import number
    for value in values:number(value,-1000000,1000000)
    matrix=np.array(values,dtype=np.float64).reshape(3,3)
    if abs(matrix[2,2]-1)>1e-8 or abs(matrix[0,2])+abs(matrix[1,2])>1e-8:raise ValueError('변형 기준점이 잘못되었습니다.')
    if abs(np.linalg.det(matrix))<1e-8 or np.linalg.cond(matrix)>1e10:raise ValueError('변형이 너무 납작합니다.')
    corners=np.array([[0,0,1],[layer['width'],0,1],[layer['width'],layer['height'],1],[0,layer['height'],1]])
    if np.min((corners@matrix.T)[:,2])<=1e-5:raise ValueError('원근 변형이 레이어를 뒤집거나 무한대로 보냅니다.')
    if np.max(np.abs(layer_corners(layer)))>1000000:raise ValueError('변형 결과가 너무 큽니다.')


def store_matrix(layer,matrix):
    if abs(matrix[2,2])<1e-8:raise ValueError('변형 기준점이 무한대에 닿습니다.')
    matrix=matrix/matrix[2,2];x,y=matrix[:2,2]
    local=np.array([[1,0,-x],[0,1,-y],[0,0,1]])@matrix
    local[0,2]=local[1,2]=0
    layer['x'],layer['y']=float(x),float(y);layer['rotation']=0.;layer['warp']=local.ravel().tolist()
    validate_warp(layer)


def corner_matrix(source,destination):
    import cv2
    source=np.asarray(source,dtype=np.float64);destination=np.asarray(destination,dtype=np.float64)
    if source.shape!=(4,2) or destination.shape!=(4,2) or not np.isfinite(destination).all() or np.max(np.abs(destination))>1000000:raise ValueError('모서리 좌표가 잘못되었습니다.')
    edges=np.roll(destination,-1,axis=0)-destination
    cross=edges[:,0]*np.roll(edges,-1,axis=0)[:,1]-edges[:,1]*np.roll(edges,-1,axis=0)[:,0]
    if np.any(cross<=1e-5):raise ValueError('모서리가 교차하거나 뒤집히지 않도록 조절하세요.')
    return cv2.getPerspectiveTransform(source.astype(np.float32),destination.astype(np.float32))
