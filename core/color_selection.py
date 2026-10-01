"""Color selection at proxy or native resolution, with bounded temporary memory."""
import cv2
import numpy as np
import psutil
from core.render_engine import linear_to_srgb,RenderCancelled


def check_color_budget(width,height):
    if max(width,height)>30000 or width*height>60_000_000:
        raise ValueError('원본 색상 선택은 최대 60MP·한 변 30,000px입니다.')
    if width*height*64>psutil.virtual_memory().available*.5:
        raise ValueError('색상 선택 메모리가 부족합니다. 빠른 선택 모드를 사용하세요.')


def color_selection(frame,point,tolerance=20,contiguous=True,cancelled=None):
    if not 0<=tolerance<=100:raise ValueError('허용 범위는 0~100입니다.')
    if len(point)!=2 or any(not np.isfinite(v) or not 0<=v<=1 for v in point):raise ValueError('문서 안의 색상을 선택하세요.')
    h,w=frame.rgb.shape[:2];check_color_budget(w,h)
    x,y=min(w-1,int(point[0]*w)),min(h-1,int(point[1]*h))
    if frame.alpha is not None and frame.alpha[y,x]<=.01:return {'rings':[]}
    def check():
        if cancelled and cancelled():raise RenderCancelled()
    def pixels(rgb):return np.rint(np.clip(linear_to_srgb(rgb),0,1)*255).astype(np.int16)
    sample=pixels(frame.rgb[y,x]);selected=np.empty((h,w),np.uint8)
    for top in range(0,h,128):
        check();bottom=min(h,top+128)
        delta=np.max(np.abs(pixels(frame.rgb[top:bottom])-sample),axis=2)
        match=delta<=tolerance*2.55
        if frame.alpha is not None:match &= frame.alpha[top:bottom]>.01
        selected[top:bottom]=match
    check()
    components,labels=cv2.connectedComponents(selected,connectivity=4)
    if contiguous:selected=(labels==labels[y,x]).astype(np.uint8)
    elif components-1>200:raise ValueError('색상 선택 영역이 너무 많습니다. 연속 선택을 사용하세요.')
    del labels
    check()
    background,labels=cv2.connectedComponents(1-selected,connectivity=4)
    del labels
    if background>202:raise ValueError('색상 선택의 구멍이 너무 많습니다. 허용 범위를 바꾸세요.')
    check()
    # Nearest-neighbor doubling gives even single pixels / 1px strokes a closed
    # contour. Original contour tracing discarded these as degenerate lines.
    enlarged=cv2.resize(selected,(w*2,h*2),interpolation=cv2.INTER_NEAREST)
    contours,_=cv2.findContours(enlarged,cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
    del enlarged,selected
    check()
    if len(contours)>200:raise ValueError('색상 선택 윤곽이 너무 많습니다. 허용 범위를 바꾸세요.')
    # Keep the former complexity tolerance for ordinary photos, while never
    # dropping a small closed region merely because approximation collapses it.
    for epsilon in (.25,.5,.8,1.2):
        rings=[];count=0;overflow=False
        for contour in contours:
            check()
            simplified=cv2.approxPolyDP(contour,epsilon,True).reshape(-1,2)
            if len(simplified)<3:simplified=contour.reshape(-1,2)
            if len(simplified)<3:raise ValueError('색상 윤곽을 만들 수 없습니다.')
            count+=len(simplified)
            if count>2000:overflow=True;break
            rings.append([[(float(px)+.5)/(w*2),(float(py)+.5)/(h*2)] for px,py in simplified])
        if not overflow:return {'rings':rings}
    raise ValueError('색상 선택이 너무 복잡합니다. 연속 선택을 켜거나 허용 범위를 바꾸세요.')
