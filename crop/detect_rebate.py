#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) the_colonel contributors
# See LICENSE for terms. Commercial use requires separate agreement.
"""
detect_rebate.py
----------------
Detects and crops the film frame from Gary Lee Boas negative scans.
Works on 35mm color negatives scanned on a flatbed, handling variable
film stocks, exposures, and scanner bed brightness.

Detection strategy:
  - All four edges use brightness profile analysis at 12% resolution
  - Top/Left: find valley (gap between bed and rebate), then trailing
    edge of rebate bump as it drops into image content
  - Top (gradient fallback): for scans with no valley, detect where
    the steep brightness gradient from the bed flattens into content
  - Bottom: detect where stable content plateau first rises toward
    sprocket holes / rebate
  - Right: same as left, reversed

Usage:
    python detect_rebate.py <input> [--output <path>] [--debug]
    python detect_rebate.py <input_dir> --batch [--output-dir <path>]

Part of: ~/claude/the_colonel/boas/
"""

import cv2
import numpy as np
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor

# ── Detection parameters ────────────────────────────────────────────────────

SCALE        = 0.12   # work at 12% resolution for detection
SMOOTH_WIN   = 10     # brightness profile smoothing window
INSET        = 15     # pixels to step inside detected edge (full res)
MIN_DIM      = 500    # minimum crop dimension — smaller = flag for review


# ── Core edge finders ───────────────────────────────────────────────────────

def _smooth(profile, win=SMOOTH_WIN):
    return np.convolve(profile, np.ones(win)/win, mode='same')


def find_inner_edge(profile, reverse=False, search_limit=0.35):
    """
    Valley → rebate bump → trailing edge detector.
    Scans inward from one side:
      1. Skip scanner bed (>160 brightness)
      2. Find dark valley (gap between bed/holder and rebate)
      3. Find rebate bump rising from valley
      4. Return where bump trails off into image content
    """
    n = len(profile)
    smooth = _smooth(profile)

    if reverse:
        zone   = smooth[int(n*(1-search_limit)):]
        offset = int(n*(1-search_limit))
        idxs   = range(len(zone)-1, -1, -1)
    else:
        zone   = smooth[:int(n*search_limit)]
        offset = 0
        idxs   = range(len(zone))

    # Skip bed from outside edge
    film_start = 0
    for i in idxs:
        if zone[i] < 160:
            film_start = i
            break

    search_zone = zone[film_start:] if not reverse else zone[:film_start+1]
    if len(search_zone) == 0:
        return int(n*0.08) if not reverse else int(n*0.92)

    # Adaptive valley threshold based on actual minimum in zone
    valley_min   = search_zone.min()
    valley_thresh = min(valley_min * 2.5, valley_min + 30)

    state       = 'seeking_valley'
    rebate_peak = 0
    walk = range(film_start, len(zone)) if not reverse else range(film_start, -1, -1)

    for i in walk:
        v = zone[i]
        if state == 'seeking_valley':
            if v <= valley_thresh:
                state = 'in_valley'
        elif state == 'in_valley':
            if v > valley_thresh + 20:
                state = 'in_rebate'
                rebate_peak = v
        elif state == 'in_rebate':
            rebate_peak = max(rebate_peak, v)
            if v < rebate_peak * 0.65 or v < valley_thresh + 15:
                return offset + i

    # No bump found — valley edge is frame edge
    for i in walk:
        if zone[i] <= valley_thresh:
            return offset + i

    return int(n*0.08) if not reverse else int(n*0.92)


def find_top_gradient_plateau(profile, n):
    """
    Fallback top detector for scans with no dark valley at top
    (e.g. outdoor/bright scenes where rebate blends into content).
    Finds where the steep brightness drop from scanner bed flattens
    into the content plateau — that inflection point is the inner edge.
    """
    smooth = _smooth(profile, win=6)
    d1     = np.gradient(smooth.astype(float))

    film_start = 0
    for i in range(n):
        if smooth[i] < 160:
            film_start = i
            break

    limit     = int(n * 0.35)
    saw_steep = False

    for i in range(film_start, limit):
        if d1[i] < -8.0:
            saw_steep = True
        if saw_steep and abs(d1[i]) < 1.5:
            return i

    # Fallback to valley method
    return find_inner_edge(profile, reverse=False, search_limit=0.35)


def find_bottom_content_edge(profile, n):
    """
    Bottom edge detector that anchors to content rather than rebate,
    avoiding false positives on sprocket holes between content and rebate.
    Samples the stable content brightness level from mid-image,
    then finds where it first rises toward the sprocket/rebate zone.
    """
    smooth = _smooth(profile)

    # Sample content brightness from well inside the frame
    content_sample = smooth[int(n*0.55):int(n*0.68)]
    content_level  = content_sample.mean()
    rise_thresh    = content_level * 1.30

    # Scan downward from 68% to find where content rises above threshold
    for i in range(int(n*0.68), int(n*0.98)):
        if smooth[i] > rise_thresh:
            return i

    # Fallback to valley method
    return find_inner_edge(profile, reverse=True, search_limit=0.25)


# ── Frame finder ────────────────────────────────────────────────────────────

def find_frame(img):
    """
    Main frame detection. Returns (x1, y1, x2, y2) in full resolution.
    Automatically selects best algorithm per edge based on image characteristics.
    """
    h, w = img.shape[:2]
    small = cv2.resize(img, (int(w*SCALE), int(h*SCALE)))
    sh, sw = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    cx0, cx1 = int(sw*0.3), int(sw*0.7)
    cy0, cy1 = int(sh*0.3), int(sh*0.7)

    row_profile = gray[:, cx0:cx1].mean(axis=1)
    col_profile = gray[cy0:cy1, :].mean(axis=0)

    # Try standard top, fall back to gradient plateau if result is too high
    top = find_inner_edge(row_profile, reverse=False, search_limit=0.35)
    if top < int(sh * 0.05):
        top = find_top_gradient_plateau(row_profile, sh)

    bot   = find_bottom_content_edge(row_profile, sh)
    left  = find_inner_edge(col_profile, reverse=False, search_limit=0.40)
    right = find_inner_edge(col_profile, reverse=True,  search_limit=0.35)

    return (int(left/SCALE), int(top/SCALE),
            int(right/SCALE), int(bot/SCALE))


# ── Processing ──────────────────────────────────────────────────────────────

def process_image(input_path: Path, output_path: Path, debug: bool = False) -> dict:
    img = cv2.imread(str(input_path))
    if img is None:
        return _log(input_path, output_path, None, 'error_unreadable')

    h, w = img.shape[:2]
    x1, y1, x2, y2 = find_frame(img)

    # Apply inset
    x1 = min(x1 + INSET, w);  y1 = min(y1 + INSET, h)
    x2 = max(x2 - INSET, 0);  y2 = max(y2 - INSET, 0)

    # Sanity check
    if x2 - x1 < MIN_DIM or y2 - y1 < MIN_DIM:
        print(f"  [FLAGGED] {input_path.name} — crop too small ({x2-x1}x{y2-y1})")
        return _log(input_path, output_path, (x1,y1,x2,y2), 'flagged_small')

    # Confidence heuristic based on crop ratio
    ratio = ((x2-x1)*(y2-y1)) / (w*h)
    if 0.25 < ratio < 0.80:
        confidence = 'high'
    elif 0.15 < ratio <= 0.25 or 0.80 <= ratio < 0.90:
        confidence = 'medium'
    else:
        confidence = 'low_flagged'

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cropped = img[y1:y2, x1:x2]
    cv2.imwrite(str(output_path), cropped)

    if debug:
        _save_debug(img, input_path, x1, y1, x2, y2)

    print(f"  [{confidence.upper()}] {input_path.name} → {output_path.name} "
          f"| {x2-x1}x{y2-y1} | ratio={ratio:.2f}")

    return _log(input_path, output_path, (x1,y1,x2,y2), confidence)


def _save_debug(img, input_path, x1, y1, x2, y2):
    h, w = img.shape[:2]
    scale = SCALE
    small = cv2.resize(img, (int(w*scale), int(h*scale)))
    sh, sw = small.shape[:2]
    dbg = small.copy()
    cv2.line(dbg, (0, int(y1*scale)),     (sw, int(y1*scale)),     (0,255,0),   2)
    cv2.line(dbg, (0, int(y2*scale)),     (sw, int(y2*scale)),     (0,0,255),   2)
    cv2.line(dbg, (int(x1*scale), 0),     (int(x1*scale), sh),     (255,0,0),   2)
    cv2.line(dbg, (int(x2*scale), 0),     (int(x2*scale), sh),     (0,165,255), 2)
    dbg_path = input_path.parent / f"{input_path.stem}_debug{input_path.suffix}"
    cv2.imwrite(str(dbg_path), dbg)


def _log(input_path, output_path, rect, confidence):
    return {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "input":      str(input_path),
        "output":     str(output_path),
        "frame_rect": list(rect) if rect else None,
        "confidence": confidence,
        "pipeline":   "negative_rebate_v1"
    }


# ── Batch processing ─────────────────────────────────────────────────────────

SUPPORTED = {'.jpg', '.jpeg', '.tif', '.tiff', '.png'}

def batch_process(input_dir: Path, output_dir: Path, workers: int = 4,
                  debug: bool = False):
    files = [f for f in sorted(input_dir.iterdir())
             if f.suffix.lower() in SUPPORTED]

    if not files:
        print(f"No supported image files found in {input_dir}")
        return

    print(f"Processing {len(files)} files with {workers} workers...")
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / f"crop_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"

    args = [(f, output_dir / f.name, debug) for f in files]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda a: process_image(*a), args))

    with open(log_path, 'w') as lf:
        for r in results:
            lf.write(json.dumps(r) + '\n')

    flagged = [r for r in results if 'flag' in r.get('confidence','')]
    print(f"\nDone. {len(results)} processed, {len(flagged)} flagged for review.")
    print(f"Log: {log_path}")

    if flagged:
        print("\nFlagged files:")
        for r in flagged:
            print(f"  {r['input']}  [{r['confidence']}]")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Crop film rebate from Gary Lee Boas negative scans.")
    parser.add_argument("input",
        help="Input image file or directory (with --batch)")
    parser.add_argument("--output",
        help="Output image path (single file mode)")
    parser.add_argument("--output-dir",
        help="Output directory (batch mode)")
    parser.add_argument("--batch", action="store_true",
        help="Process all images in input directory")
    parser.add_argument("--workers", type=int, default=4,
        help="Parallel workers for batch mode (default: 4)")
    parser.add_argument("--debug", action="store_true",
        help="Save debug overlay thumbnails")
    args = parser.parse_args()

    input_path = Path(args.input)

    if args.batch:
        if not input_path.is_dir():
            print(f"Error: {input_path} is not a directory"); sys.exit(1)
        output_dir = Path(args.output_dir) if args.output_dir \
                     else input_path.parent / (input_path.name + "_cropped")
        batch_process(input_path, output_dir, args.workers, args.debug)
    else:
        if not input_path.exists():
            print(f"Error: {input_path} not found"); sys.exit(1)
        output_path = Path(args.output) if args.output \
                      else input_path.parent / f"{input_path.stem}_cropped{input_path.suffix}"
        result = process_image(input_path, output_path, args.debug)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
