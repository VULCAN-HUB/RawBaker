"""Synthetic renderer benchmark; excludes file decoding and GUI latency."""
from __future__ import annotations

import argparse
import gc
import json
import platform
from time import perf_counter

import numpy as np
import psutil

from core.render_engine import Adjustments, Frame, render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--height", type=int, default=1365)
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    if min(args.width, args.height, args.repeats) < 1:
        parser.error("Dimensions/repeats must be positive")
    ramp = np.linspace(0, 1, args.width, dtype=np.float32)[None, :, None]
    frame = Frame(np.broadcast_to(ramp, (args.height, args.width, 3)))
    settings = Adjustments(exposure=.3, contrast=1.1, saturation=1.1,
                           highlights=-20, shadows=20, sharpness=30)
    timings = []
    for _ in range(args.repeats + 1):
        start = perf_counter()
        result = render(frame, settings)
        timings.append((perf_counter() - start) * 1000)
        del result
    gc.collect()
    memory = psutil.Process().memory_info()
    print(json.dumps({"platform": platform.platform(), "python": platform.python_version(),
                      "numpy": np.__version__, "width": args.width, "height": args.height,
                      "warm_repeats": args.repeats, "cold_render_ms": timings[0],
                      "warm_p50_ms": float(np.percentile(timings[1:], 50)),
                      "warm_p95_ms": float(np.percentile(timings[1:], 95)),
                      "peak_rss_mib": getattr(memory, "peak_wset", memory.rss) / 1024 ** 2,
                      "peak_is_os_recorded": hasattr(memory, "peak_wset"),
                      "scope": "synthetic RGB render only; excludes decode, encode, GUI, layers"}, indent=2))


if __name__ == "__main__":
    main()
