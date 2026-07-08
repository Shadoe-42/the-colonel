#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) the_colonel contributors
# See LICENSE for terms. Commercial use requires separate agreement.
"""
balance_positive.py
--------------------
Automatic color-cast correction for images that are ALREADY positive
(not negatives — no inversion needed) but carry an inconsistent color
cast, e.g. the `positives-cropped/` archive, which was converted from
raw by a third-party tool with per-shoot white balance that isn't
reliable.

This is a sibling to invert/invert_negative.py, not the same script,
because the inputs are fundamentally different:
  - invert_negative.py takes 16-bit TIFF orange-mask negatives and has
    to both flip polarity and remove the mask before any color
    correction makes sense, then applies a full gamma curve to bring
    linear-ish data up to a viewable range.
  - balance_positive.py takes 8-bit JPEGs that are already
    gamma-encoded and already viewable — they just have the wrong
    white balance. Running the negative pipeline's aggressive
    percentile clip + full 2.2 gamma curve on data like this would
    double up the gamma encoding and blow out the image. This script
    only does the per-channel percentile stretch (a standard "auto
    levels" operation), with gentler clip points than the negative
    pipeline because 8-bit JPEGs have much less tonal headroom to
    push around before banding shows up.

Usage:
    python balance_positive.py <input> [--output <path>]
    python balance_positive.py <input_dir> --batch [--output-dir <path>]
"""

import argparse
import json
import sys
import numpy as np
import cv2
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor

# ── Correction parameters ───────────────────────────────────────────────────

LOW_PCT   = 1.0    # gentler than invert_negative.py's 0.5 — less headroom in 8-bit
HIGH_PCT  = 99.0
GAMMA     = 1.0     # no extra curve by default: input is already gamma-encoded.
                    # Bump slightly (e.g. 1.1-1.2) only if a shoot looks flat/dark
                    # after the levels stretch — don't default to it blindly.

SUPPORTED = {'.jpg', '.jpeg', '.tif', '.tiff', '.png'}


def balance(img8: np.ndarray) -> np.ndarray:
    """
    img8: HxWx3 uint8 RGB, already positive, already gamma-encoded.
    Returns a corrected HxWx3 uint8 RGB image.
    """
    img = img8.astype(np.float64)
    out = np.empty_like(img)

    for c in range(3):
        chan = img[:, :, c]
        lo, hi = np.percentile(chan, [LOW_PCT, HIGH_PCT])
        if hi <= lo:
            hi = lo + 1
        stretched = np.clip((chan - lo) / (hi - lo), 0, 1)
        out[:, :, c] = stretched

    if GAMMA != 1.0:
        out = np.power(out, 1.0 / GAMMA)

    return (out * 255).astype(np.uint8)


def process_image(input_path: Path, output_path: Path) -> dict:
    img_bgr = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if img_bgr is None:
        return _log(input_path, output_path, 'error_unreadable')

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    corrected = balance(img_rgb)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), cv2.cvtColor(corrected, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 92])

    print(f"  [OK] {input_path.name} -> {output_path.name}")
    return _log(input_path, output_path, 'converted')


def _log(input_path, output_path, status):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input":     str(input_path),
        "output":    str(output_path),
        "status":    status,
        "params":    {"low_pct": LOW_PCT, "high_pct": HIGH_PCT, "gamma": GAMMA},
        "pipeline":  "balance_positive_v1",
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

    print(f"Balancing {len(files)} files with {workers} workers...")
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / f"balance_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    args = [(f, output_dir / f.name) for f in files]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_process_image_star, args))

    with open(log_path, 'w') as lf:
        for r in results:
            lf.write(json.dumps(r) + '\n')

    print(f"\nDone. {len(results)} balanced.")
    print(f"Log: {log_path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Auto white-balance already-positive images (no inversion).")
    parser.add_argument("input", help="Input image file or directory (with --batch)")
    parser.add_argument("--output", help="Output image path (single file mode)")
    parser.add_argument("--output-dir", help="Output directory (batch mode)")
    parser.add_argument("--batch", action="store_true", help="Process all images in input directory")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for batch mode (default: 4)")
    args = parser.parse_args()

    input_path = Path(args.input)

    if args.batch:
        if not input_path.is_dir():
            print(f"Error: {input_path} is not a directory"); sys.exit(1)
        output_dir = Path(args.output_dir) if args.output_dir \
            else input_path.parent / (input_path.name + "_balanced")
        batch_process(input_path, output_dir, args.workers)
    else:
        if not input_path.exists():
            print(f"Error: {input_path} not found"); sys.exit(1)
        output_path = Path(args.output) if args.output \
            else input_path.parent / f"{input_path.stem}_balanced{input_path.suffix}"
        result = process_image(input_path, output_path)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
