#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) the_colonel contributors
# See LICENSE for terms. Commercial use requires separate agreement.
"""
invert_negative.py
-------------------
Converts cropped color-negative frames (still in their orange-mask,
uninverted state, as produced by crop/detect_holder.py or
crop/detect_rebate.py) into viewable positive images.

Why this is "automatic" rather than "calibrated":
  Traditional negative-to-positive conversion (including tools like
  Negative Lab Pro) calibrates per roll by sampling a patch of
  unexposed, clear film base/rebate — that sample tells you exactly
  how strong the orange mask is for that specific film stock and
  processing run, so the inversion can remove precisely that much.

  The lightbox/holder capture rig this project uses doesn't give us
  that: the border around each frame is the physical film holder's
  divider bar, not a strip of the film itself, so there's no clear
  film base visible anywhere in these crops to calibrate against.

  Instead, this script does automatic per-frame correction: invert,
  then independently stretch each color channel's histogram between
  robust low/high percentiles (clipping outliers), then apply a
  gamma curve for a natural-looking tonal response. This won't be as
  accurate as a properly calibrated per-roll inversion, but it's a
  solid, consistent starting point — good enough to work from, not
  a finished color grade. Treat the output as a proof, not a final.

Usage:
    python invert_negative.py <input> [--output <path>]
    python invert_negative.py <input_dir> --batch [--output-dir <path>]

Part of: ~/claude/the_colonel/boas/
"""

import argparse
import json
import sys
import numpy as np
import tifffile
import cv2
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor

# ── Correction parameters ───────────────────────────────────────────────────

LOW_PCT   = 0.5     # per-channel black point, as a percentile
HIGH_PCT  = 99.5    # per-channel white point, as a percentile
GAMMA     = 2.2      # display gamma applied after the levels stretch

SUPPORTED = {'.tif', '.tiff'}


def invert_and_balance(img16: np.ndarray) -> np.ndarray:
    """
    img16: HxWx3 uint16 array, orange-mask negative (not yet inverted).
    Returns an 8-bit HxWx3 uint8 positive image.
    """
    img = img16.astype(np.float64)

    # Invert. This is a simple linear inversion, not a density-space
    # inversion — good enough given we're already doing automatic
    # per-channel correction downstream to compensate.
    inv = 65535.0 - img

    out = np.empty_like(inv)
    for c in range(3):
        chan = inv[:, :, c]
        lo, hi = np.percentile(chan, [LOW_PCT, HIGH_PCT])
        if hi <= lo:
            hi = lo + 1
        stretched = np.clip((chan - lo) / (hi - lo), 0, 1)
        out[:, :, c] = stretched

    out = np.power(out, 1.0 / GAMMA)
    return (out * 255).astype(np.uint8)


def process_image(input_path: Path, output_path: Path, jpg_preview: bool = True) -> dict:
    img16 = tifffile.imread(str(input_path))
    if img16 is None or img16.ndim != 3:
        return _log(input_path, output_path, 'error_unreadable')

    positive = invert_and_balance(img16)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(str(output_path), positive, photometric='rgb')

    if jpg_preview:
        preview_path = output_path.with_suffix('.jpg')
        cv2.imwrite(str(preview_path), cv2.cvtColor(positive, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 90])

    print(f"  [OK] {input_path.name} -> {output_path.name}")
    return _log(input_path, output_path, 'converted')


def _log(input_path, output_path, status):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input":     str(input_path),
        "output":    str(output_path),
        "status":    status,
        "params":    {"low_pct": LOW_PCT, "high_pct": HIGH_PCT, "gamma": GAMMA},
        "pipeline":  "invert_negative_v1",
    }


# ── Batch processing ─────────────────────────────────────────────────────────

def _process_image_star(args):
    return process_image(*args)


def batch_process(input_dir: Path, output_dir: Path, workers: int = 4):
    files = [f for f in sorted(input_dir.iterdir())
             if f.suffix.lower() in SUPPORTED]

    if not files:
        print(f"No supported image files found in {input_dir}")
        return

    print(f"Converting {len(files)} files with {workers} workers...")
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / f"invert_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    args = [(f, output_dir / f.name, True) for f in files]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_process_image_star, args))

    with open(log_path, 'w') as lf:
        for r in results:
            lf.write(json.dumps(r) + '\n')

    print(f"\nDone. {len(results)} converted.")
    print(f"Log: {log_path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Invert and auto color-correct cropped color-negative frames.")
    parser.add_argument("input", help="Input TIFF file or directory (with --batch)")
    parser.add_argument("--output", help="Output image path (single file mode)")
    parser.add_argument("--output-dir", help="Output directory (batch mode)")
    parser.add_argument("--batch", action="store_true", help="Process all TIFFs in input directory")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for batch mode (default: 4)")
    args = parser.parse_args()

    input_path = Path(args.input)

    if args.batch:
        if not input_path.is_dir():
            print(f"Error: {input_path} is not a directory"); sys.exit(1)
        output_dir = Path(args.output_dir) if args.output_dir \
            else input_path.parent / (input_path.name + "_positive")
        batch_process(input_path, output_dir, args.workers)
    else:
        if not input_path.exists():
            print(f"Error: {input_path} not found"); sys.exit(1)
        output_path = Path(args.output) if args.output \
            else input_path.parent / f"{input_path.stem}_positive.tif"
        result = process_image(input_path, output_path)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
