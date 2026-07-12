from PIL import Image
import os, struct, io

src = os.path.join(os.path.dirname(__file__), "icon_source.png.png")
out = os.path.join(os.path.dirname(__file__), "icon.ico")

base = Image.open(src).convert("RGBA")
sizes = [16, 24, 32, 48, 64, 128, 256]

# Build ICO manually for reliable multi-size output
imgs = []
for s in sizes:
    resized = base.resize((s, s), Image.LANCZOS)
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    imgs.append((s, buf.getvalue()))

# ICO header
num = len(imgs)
header = struct.pack("<HHH", 0, 1, num)  # reserved, type=1, count

# Directory entries (each 16 bytes) + data offset
dir_offset = 6 + num * 16
entries = b""
data_parts = b""
offset = dir_offset
for (s, data) in imgs:
    w = 0 if s == 256 else s
    h = 0 if s == 256 else s
    entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
    data_parts += data
    offset += len(data)

with open(out, "wb") as f:
    f.write(header + entries + data_parts)

print(f"icon.ico 생성: {os.path.getsize(out):,} bytes, {len(imgs)} sizes")

# Also save logo.png (256x256)
logo_out = os.path.join(os.path.dirname(__file__), "logo.png")
base.resize((256, 256), Image.LANCZOS).save(logo_out, "PNG")
print(f"logo.png 생성: {logo_out}")
