"""Development entry point: python -m core.render_cli input output.png --exposure 1"""
from __future__ import annotations

import argparse

from core.render_engine import Adjustments, render, resize
from core.render_io import decode_photo, export_png


def main():
    parser = argparse.ArgumentParser(description="RawBaker linear-v1 고정밀 보정 검증 도구")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--bits", type=int, choices=(8, 16), default=16)
    parser.add_argument("--max-side", type=int, help="보정 후 축소할 긴 변 크기")
    for key in ("exposure", "contrast", "temperature", "tint", "saturation", "highlights", "shadows", "whites", "blacks", "sharpness"):
        parser.add_argument("--" + key, type=float, default=getattr(Adjustments(), key))
    args = parser.parse_args()
    try:
        settings = Adjustments(**{key: getattr(args, key) for key in Adjustments.__dataclass_fields__ if key != "curve"})
        frame = render(decode_photo(args.source), settings)
        if args.max_side is not None:
            frame = resize(frame, args.max_side)
        saved = export_png(frame, args.destination, bits=args.bits, protected_inputs=(args.source,))
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"오류: {error}\n")
    print(saved)


if __name__ == "__main__":
    main()
