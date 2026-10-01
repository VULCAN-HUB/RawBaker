"""Bounded working-set PNG export for layered designs; safe atomic publication."""
import tempfile,struct,zlib
import numpy as np
from core.render_engine import Frame,RenderCancelled,to_pixels
from core.studio_export import _chunk
from core.safe_output import write_output
from core.disk_composite import DiskComposite



def export_document_png(project,document_id,destination,*,bits=16,dpi=300,protected_inputs=(),protected_hashes=(),collision='rename',cancelled=None,progress=None,tile_rows=128):
    if bits not in (8,16) or not 1<=dpi<=9600 or type(tile_rows) is not int or not 1<=tile_rows<=1024:raise ValueError('출력 설정이 잘못되었습니다.')
    doc=project.state['documents'][document_id]
    w,h=doc['width'],doc['height']
    def check():
        if cancelled and cancelled():raise RenderCancelled()
    def write(stream):
        check()
        # Intermediate pixels live in an owned temporary file; each blend/encode
        # operation touches only a bounded strip. No full document Frame copy.
        with tempfile.TemporaryDirectory(prefix='rawbaker-tiles-') as directory:
            compositor=DiskComposite(directory,project,doc,tile_rows,check,progress)
            try:
                canvas=compositor.compose()
                canvas.flush()
                stream.write(b'\x89PNG\r\n\x1a\n')
                stream.write(_chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,bits,6,0,0,0)))
                stream.write(_chunk(b'sRGB',b'\x00'))
                density=round(dpi/.0254);stream.write(_chunk(b'pHYs',struct.pack('>IIB',density,density,1)))
                compressor=zlib.compressobj(6);bpp=4*(bits//8)
                for top in range(0,h,tile_rows):
                    check();tile=canvas[top:top+tile_rows]
                    rgb=np.divide(tile[...,:3],tile[...,3:4],out=np.zeros_like(tile[...,:3]),where=tile[...,3:4]>1e-8)
                    pixels=to_pixels(Frame(rgb,tile[...,3]),bits)
                    packed=pixels.astype('>u2',copy=False).view(np.uint8).reshape(len(tile),-1) if bits==16 else pixels.reshape(len(tile),-1)
                    filtered=packed.copy();filtered[:,bpp:]-=packed[:,:-bpp]
                    rows=np.empty((len(tile),packed.shape[1]+1),np.uint8);rows[:,0]=1;rows[:,1:]=filtered
                    chunk=compressor.compress(rows.tobytes())
                    if chunk:stream.write(_chunk(b'IDAT',chunk))
                    if progress:progress(80+round(20*(top+len(tile))/h))
                chunk=compressor.flush()
                if chunk:stream.write(_chunk(b'IDAT',chunk))
                stream.write(_chunk(b'IEND',b''));check()
            finally:
                # Close every nested mapping before Windows removes its files.
                compositor.close()
    return write_output(write,destination,mode=collision,protected_inputs=protected_inputs,protected_hashes=protected_hashes)
