"""
Run once to generate a placeholder icon.ico for development.
Replace with the real icon from the client when available.
"""
from PIL import Image, ImageDraw, ImageFont
import os

sizes = [16, 32,48, 64, 128, 256]
images = []

for size in sizes:
    img = Image.new("RGBA", (size, size), (17, 17, 17, 255))
    draw = ImageDraw.Draw(img)

    # Orange background circle
    margin = size // 8
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(211, 84, 0, 255),
    )

    # "RB" text
    font_size = max(6, size // 3)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    text = "RB"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((size - tw) // 2, (size - th) // 2),
        text,
        fill=(255, 255, 255, 255),
        font=font,
    )
    images.append(img)

out = os.path.join(os.path.dirname(__file__), "icon.ico")
images[0].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
print(f"Created: {out}")
