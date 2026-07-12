"""
Generate a minimal but rawpy-decodable DNG file.
DNG = TIFF container + specific tags required by LibRaw.
"""
import struct, os, numpy as np


def write_uint16_le(v): return struct.pack('<H', v)
def write_uint32_le(v): return struct.pack('<I', v)


def make_dng(path: str, width: int = 128, height: int = 128):
    """Produce a minimal 16-bit Bayer DNG that rawpy can decode."""

    # --- Bayer raw data (RGGB pattern, 16-bit) ---
    raw = np.zeros((height, width), dtype=np.uint16)
    raw[0::2, 0::2] = 8192   # R
    raw[0::2, 1::2] = 12000  # Gr
    raw[1::2, 0::2] = 12000  # Gb
    raw[1::2, 1::2] = 8192   # B
    raw_bytes = raw.tobytes()

    # --- Extra data blobs (values > 4 bytes stored outside IFD) ---
    dng_version    = bytes([1, 4, 0, 0])
    dng_back_ver   = bytes([1, 1, 0, 0])
    camera_model   = b'RawBaker TestCam\x00'
    # ColorMatrix1: identity 3x3 as 9 signed rationals (num/den pairs, SHORT pairs)
    # We encode as a flat SHORT array: 1/1 0/1 0/1  0/1 1/1 0/1  0/1 0/1 1/1
    color_matrix = struct.pack('<18h',
        10000,10000, 0,1, 0,1,
        0,1, 10000,10000, 0,1,
        0,1, 0,1, 10000,10000,
    )
    # AsShotNeutral: [1/1, 1/1, 1/1] as 3 SHORT rationals
    as_shot = struct.pack('<6H', 1,1, 1,1, 1,1)

    # Calculate offsets (TIFF header = 8 bytes)
    # IFD starts at offset 8
    N_ENTRIES = 18
    ifd_size  = 2 + N_ENTRIES * 12 + 4  # count field + entries + next_ifd ptr
    ifd_start = 8

    # Extra data right after IFD
    extra_start = ifd_start + ifd_size
    off_dng_ver    = extra_start
    off_dng_back   = off_dng_ver    + len(dng_version)
    off_cam_model  = off_dng_back   + len(dng_back_ver)
    off_color_mat  = off_cam_model  + len(camera_model)
    off_as_shot    = off_color_mat  + len(color_matrix)
    off_raw        = off_as_shot    + len(as_shot)

    # Align raw to 4-byte boundary
    pad = (4 - off_raw % 4) % 4
    off_raw += pad

    # IFD entry builder
    # type codes: 1=BYTE 3=SHORT 4=LONG 7=UNDEFINED 10=SRATIONAL
    SHORT, LONG, BYTE, UNDEF = 3, 4, 1, 7

    def entry(tag, typ, count, value_or_offset):
        """Pack a 12-byte IFD entry. value_or_offset fits in 4 bytes or is a file offset."""
        if isinstance(value_or_offset, bytes):
            # Inline bytes (count <= 4)
            data = value_or_offset.ljust(4, b'\x00')[:4]
            return struct.pack('<HHI4s', tag, typ, count, data)
        else:
            return struct.pack('<HHII', tag, typ, count, value_or_offset)

    entries = b''.join([
        entry(0x00FE, LONG,  1, 0),                         # NewSubfileType: full image
        entry(0x0100, SHORT, 1, width),                     # ImageWidth
        entry(0x0101, SHORT, 1, height),                    # ImageLength
        entry(0x0102, SHORT, 1, 16),                        # BitsPerSample
        entry(0x0103, SHORT, 1, 1),                         # Compression: none
        entry(0x0106, SHORT, 1, 32803),                     # PhotometricInterp: CFA
        entry(0x0111, LONG,  1, off_raw),                   # StripOffsets
        entry(0x0115, SHORT, 1, 1),                         # SamplesPerPixel
        entry(0x0116, SHORT, 1, height),                    # RowsPerStrip
        entry(0x0117, LONG,  1, len(raw_bytes)),            # StripByteCounts
        entry(0x011C, SHORT, 1, 1),                         # PlanarConfig: chunky
        entry(0x828D, SHORT, 2, struct.pack('<2H', 2, 2)),  # CFARepeatPatternDim: 2x2
        entry(0x828E, BYTE,  4, bytes([0, 1, 1, 2])),       # CFAPattern: RGGB
        entry(0xC612, UNDEF, 4, off_dng_ver),               # DNGVersion
        entry(0xC613, UNDEF, 4, off_dng_back),              # DNGBackwardVersion
        entry(0xC614, BYTE,  len(camera_model), off_cam_model),  # UniqueCameraModel
        entry(0xC621, SHORT, 18, off_color_mat),            # ColorMatrix1
        entry(0xC61D, SHORT, 1, 16383),                     # WhiteLevel
    ])

    # Build file
    tiff_header = b'II' + struct.pack('<HI', 42, ifd_start)  # LE, magic, IFD offset
    ifd_count   = struct.pack('<H', N_ENTRIES)
    ifd_next    = struct.pack('<I', 0)  # no more IFDs

    buf = bytearray()
    buf += tiff_header
    buf += ifd_count + entries + ifd_next

    # Extra data section
    buf += dng_version + dng_back_ver + camera_model + color_matrix + as_shot
    buf += b'\x00' * pad   # alignment padding
    buf += raw_bytes        # raw image data

    with open(path, 'wb') as f:
        f.write(buf)
    print(f'Created {path} ({len(buf)//1024}KB)')


if __name__ == '__main__':
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'test_images')
    os.makedirs(out_dir, exist_ok=True)
    make_dng(os.path.join(out_dir, 'test_synthetic.dng'), 256, 256)
