"""Straight-color blend functions inside premultiplied source-over compositing."""
import numpy as np

BLEND_MODES = ('normal', 'multiply', 'screen', 'overlay', 'darken', 'lighten', 'difference', 'exclusion')


def composite(backdrop, backdrop_alpha, source, source_alpha, mode='normal'):
    """RGB inputs/output are premultiplied, linear sRGB; alpha is independent."""
    if mode not in BLEND_MODES:
        raise ValueError('지원하지 않는 혼합 모드입니다.')
    a, b = source_alpha[...,None], backdrop_alpha[...,None]
    alpha = source_alpha+backdrop_alpha*(1-source_alpha)
    if mode == 'normal':
        return source+backdrop*(1-a), alpha
    cb = np.divide(backdrop,b,out=np.zeros_like(backdrop),where=b>1e-8)
    cs = np.divide(source,a,out=np.zeros_like(source),where=a>1e-8)
    # Display blend modes operate on the bounded overlap. Non-overlapping HDR
    # samples keep their original values; normal never clamps highlight headroom.
    cb,cs = np.clip(cb,0,1),np.clip(cs,0,1)
    if mode == 'multiply': mixed=cb*cs
    elif mode == 'screen': mixed=cb+cs-cb*cs
    elif mode == 'overlay': mixed=np.where(cb<=.5,2*cb*cs,1-2*(1-cb)*(1-cs))
    elif mode == 'darken': mixed=np.minimum(cb,cs)
    elif mode == 'lighten': mixed=np.maximum(cb,cs)
    elif mode == 'difference': mixed=np.abs(cb-cs)
    else: mixed=cb+cs-2*cb*cs
    return backdrop*(1-a)+source*(1-b)+mixed*a*b, alpha
