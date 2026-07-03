#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) the_colonel contributors
# See LICENSE for terms. Commercial use requires separate agreement.
"""
detect_holder.py
-----------------
Detects and crops the film frame from lightbox-and-holder captures —
35mm negatives shot with a digital camera while mounted in a physical
film holder on a lightbox, rather than scanned on a flatbed. This is a
different capture method than crop/detect_rebate.py handles, with a
different signal to key off:

  - No scanner bed, no sprocket-hole rebate bump.
  - Frames are separated by a solid-color holder divider bar (a physical
    part of the holder, not a scan artifact) — visibly maroon/magenta in
    the uninverted orange negative mask, but this script keys off
    luminance (bar is consistently *darker* than surrounding content),
    not a fixed color, so it tolerates the color-cast drift seen across
    the sample batch (one frame in the initial 36 read distinctly more
    pink/violet than the rest).
  - One long edge often fades into raw overexposed lightbox glow; the
    other is a dark holder rail. Left/right edge detection here is a
    first pass and has NOT been validated across the batch the way the
    top/bottom divider-bar detection has — treat with more suspicion.

Detection strategy (top/bottom, the validated part):
  - Sample a content-luminance baseline from a narrow band near the
    vertical center of the frame (away from edges, where the bars live).
  - Restrict the search for each divider bar to the zone where bars were
    empirically observed across the survey sample (roughly 5-35% depth
    for the top bar, 65-97% for the bottom), rather than scanning the
    full frame. This is what keeps dark clothing/hair in the photo itself
    from being mistaken for a divider — those show up nearer the center,
    outside these zones, in every sample checked.
  - A bar is a *sustained* run of rows below an adaptive dark threshold
    (relative to the content baseline, not a fixed value) — a minimum
    run length is required so a small shadow or dark prop doesn't trip
    it.

Raw file support: reads .NEF (and other common raw extensions) via
rawpy, decoded with camera white balance and auto-brightness disabled
so detection thresholds behave consistently run to run. Output is
16-bit TIFF to preserve tonal range for downstream inversion/color work
— this script does not invert or color-correct, only crops.

Usage:
    python detect_holder.py <input> [--output <path>] [--debug]
    python detect_holder.py <input_dir> --batch [--output-dir <path>]

Part of: ~/claude/the_colonel/boas/
"""

import argparse
import json
import sys
import numpy as np
import tifffile
import rawpy
import cv2
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor

# ── Detection parameters ────────────────────────────────────────────────────

SCALE          = 0.12   # work at 12% resolution for detection, like detect_rebate.py
SMOOTH_WIN     = 9
MIN_BAR_RUN    = 0.008  # minimum sustained dark run, as a fraction of frame height,
                        # to count as a divider bar rather than noise/shadow
TOP_ZONE       = (0.03, 0.38)   # empirical: top bar found 5-35% depth across survey sample
BOTTOM_ZONE    = (0.62, 0.97)   # empirical: bottom bar found 65-90% depth
CONTENT_ZONE   = (0.45, 0.60)   # baseline content sample, deliberately away from both zones
BRIGHT_RATIO   = 0.90    # a row counts as "still content" only above content baseline * this ratio
INSET          = 12      # pixels to step inside detected bar edge (full res)
MIN_DIM        = 400     # minimum crop dimension — smaller = flag for review

RAW_EXTS  = {'.nef', '.cr2', '.cr3', '.arw', '.dng', '.raf', '.orf'}
STD_EXTS  = {'.jpg', '.jpeg', '.tif', '.tiff', '.png'}
SUPPORTED = RAW_EXTS | STD_EXTS


# ── Image loading ───────────────────────────────────────────────────────────

def load_image(path: Path):
    """
    Returns a 16-bit RGB numpy array. Raw files are demosaiced with camera
    white balance and auto-brightness OFF (so a dark divider bar in one
    frame reads the same relative darkness as in every other frame —
    auto-bright would fight the adaptive threshold below).
    """
    if path.suffix.lower() in RAW_EXTS:
        with rawpy.imread(str(path)) as raw:
            rgb16 = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=True,
                output_bps=16,
            )
        return rgb16
    else:
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.ndim == 3 and img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if img.dtype != np.uint16:
            img = img.astype(np.uint16) * (257 if img.dtype == np.uint8 else 1)
        return img


# ── Core edge finders ───────────────────────────────────────────────────────

def _smooth(profile, win=SMOOTH_WIN):
    return np.convolve(profile, np.ones(win) / win, mode='same')


def find_divider_bar(profile, zone, content_level, n, content_at):
    """
    Finds the boundary between frame content and a divider bar within
    `zone` (fractional (start, end) of the profile). `content_at` is
    'z1' or 'z0' — whichever end of the zone borders the actual content
    zone, i.e. which direction to scan from.

    This is content-anchored rather than bar-anchored: instead of
    tracing the dark bar and hoping it's uniform, it scans from the
    content side and looks for the point where brightness *permanently*
    falls away from content level (below content_level * BRIGHT_RATIO
    for a sustained run). That's the more reliable signal — the divider
    bar itself isn't always uniform (a printed mark or reflection on the
    holder can put a patch inside the bar that's noticeably brighter
    than the bar's darkest parts, though still well below true content
    brightness), so trying to detect "is this dark enough to be the
    bar" is fragile. "Is this still confidently content" is not.
    """
    smooth = _smooth(profile, win=15)
    z0, z1 = int(n * zone[0]), int(n * zone[1])
    bright_thresh = content_level * BRIGHT_RATIO
    min_run = max(3, int(n * MIN_BAR_RUN))

    idxs = range(z1 - 1, z0 - 1, -1) if content_at == 'z1' else range(z0, z1)

    run_start = None
    for i in idxs:
        dim = smooth[i] < bright_thresh
        if dim:
            if run_start is None:
                run_start = i
            if abs(i - run_start) + 1 >= min_run:
                return run_start, 'found'
        else:
            run_start = None

    return None, 'not_found'


def find_frame(img16):
    """
    Main frame detection on a 16-bit RGB array. Returns
    (x1, y1, x2, y2, notes) in full resolution, where notes flags
    any part of the detection that fell back to a default.
    """
    h, w = img16.shape[:2]
    img8 = (img16 / 256).astype(np.uint8)
    small = cv2.resize(img8, (max(1, int(w * SCALE)), max(1, int(h * SCALE))))
    sh, sw = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    cx0, cx1 = int(sw * 0.3), int(sw * 0.7)
    row_profile = gray[:, cx0:cx1].mean(axis=1)

    content_level = np.median(row_profile[int(sh * CONTENT_ZONE[0]):int(sh * CONTENT_ZONE[1])])

    notes = []

    # TOP_ZONE's content-adjacent boundary is its far end (z1, nearest
    # CONTENT_ZONE); scan backward from there toward the frame edge.
    top, top_status = find_divider_bar(row_profile, TOP_ZONE, content_level, sh, content_at='z1')
    if top is None:
        top = int(sh * TOP_ZONE[1] * 0.4)  # conservative fallback
        notes.append('top_bar_not_found_fallback')

    # BOTTOM_ZONE's content-adjacent boundary is its near end (z0,
    # nearest CONTENT_ZONE); scan forward from there toward the frame edge.
    bot, bot_status = find_divider_bar(row_profile, BOTTOM_ZONE, content_level, sh, content_at='z0')
    if bot is None:
        bot = int(sh * (BOTTOM_ZONE[0] + (1 - BOTTOM_ZONE[0]) * 0.6))
        notes.append('bottom_bar_not_found_fallback')

    # Left/right: first-pass only, NOT validated the way top/bottom is.
    # Skip overexposed lightbox glow (near-white) and dark holder rail
    # (near-black), from both sides, toward the middle third.
    col_profile = gray[int(sh * 0.4):int(sh * 0.6), :].mean(axis=0)
    left = 0
    for i in range(0, int(sw * 0.35)):
        v = col_profile[i]
        if 40 < v < 235:
            left = i
            break
    else:
        notes.append('left_edge_not_found_fallback')

    right = sw - 1
    for i in range(sw - 1, int(sw * 0.65), -1):
        v = col_profile[i]
        if 40 < v < 235:
            right = i
            break
    else:
        notes.append('right_edge_not_found_fallback')

    return (int(left / SCALE), int(top / SCALE),
            int(right / SCALE), int(bot / SCALE), notes)


# ── Processing ───────────────────────────────────────────────────────────────

def process_image(input_path: Path, output_path: Path, debug: bool = False) -> dict:
    img16 = load_image(input_path)
    if img16 is None:
        return _log(input_path, output_path, None, 'error_unreadable', [])

    h, w = img16.shape[:2]
    x1, y1, x2, y2, notes = find_frame(img16)

    x1 = min(x1 + INSET, w);  y1 = min(y1 + INSET, h)
    x2 = max(x2 - INSET, 0);  y2 = max(y2 - INSET, 0)

    if x2 - x1 < MIN_DIM or y2 - y1 < MIN_DIM:
        print(f"  [FLAGGED] {input_path.name} — crop too small ({x2-x1}x{y2-y1})")
        return _log(input_path, output_path, (x1, y1, x2, y2), 'flagged_small', notes)

    ratio = ((x2 - x1) * (y2 - y1)) / (w * h)
    if notes:
        confidence = 'low_flagged'
    elif 0.25 < ratio < 0.85:
        confidence = 'high'
    elif 0.15 < ratio <= 0.25 or 0.85 <= ratio < 0.93:
        confidence = 'medium'
    else:
        confidence = 'low_flagged'

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cropped = img16[y1:y2, x1:x2]
    tifffile.imwrite(str(output_path), cropped, photometric='rgb')

    if debug:
        _save_debug(img16, input_path, output_path, x1, y1, x2, y2)

    tag = f" [{','.join(notes)}]" if notes else ""
    print(f"  [{confidence.upper()}] {input_path.name} -> {output_path.name} "
          f"| {x2-x1}x{y2-y1} | ratio={ratio:.2f}{tag}")

    return _log(input_path, output_path, (x1, y1, x2, y2), confidence, notes)


def _save_debug(img16, input_path, output_path, x1, y1, x2, y2):
    img8 = (img16 / 256).astype(np.uint8)
    h, w = img8.shape[:2]
    small = cv2.resize(img8, (int(w * SCALE), int(h * SCALE)))
    sh, sw = small.shape[:2]
    dbg = cv2.cvtColor(small, cv2.COLOR_RGB2BGR).copy()
    s = SCALE
    cv2.line(dbg, (0, int(y1 * s)), (sw, int(y1 * s)), (0, 255, 0), 2)
    cv2.line(dbg, (0, int(y2 * s)), (sw, int(y2 * s)), (0, 0, 255), 2)
    cv2.line(dbg, (int(x1 * s), 0), (int(x1 * s), sh), (255, 0, 0), 2)
    cv2.line(dbg, (int(x2 * s), 0), (int(x2 * s), sh), (0, 165, 255), 2)
    # Debug overlays go next to the *output* crop, never back into the
    # source directory — the source is never written to.
    dbg_path = output_path.parent / f"{input_path.stem}_debug.jpg"
    cv2.imwrite(str(dbg_path), dbg)


def _log(input_path, output_path, rect, confidence, notes):
    return {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "input":      str(input_path),
        "output":     str(output_path),
        "frame_rect": list(rect) if rect else None,
        "confidence": confidence,
        "notes":      notes,
        "pipeline":   "negative_holder_v1",
    }


# ── Batch processing ─────────────────────────────────────────────────────────

def _process_image_star(args):
    return process_image(*args)


def batch_process(input_dir: Path, output_dir: Path, workers: int = 4, debug: bool = False):
    files = [f for f in sorted(input_dir.iterdir())
             if f.suffix.lower() in SUPPORTED]

    if not files:
        print(f"No supported image files found in {input_dir}")
        return

    print(f"Processing {len(files)} files with {workers} workers...")
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / f"crop_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"

    args = [(f, output_dir / f"{f.stem}.tif", debug) for f in files]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_process_image_star, args))

    with open(log_path, 'w') as lf:
        for r in results:
            lf.write(json.dumps(r) + '\n')

    flagged = [r for r in results if 'flag' in r.get('confidence', '')]
    print(f"\nDone. {len(results)} processed, {len(flagged)} flagged for review.")
    print(f"Log: {log_path}")

    if flagged:
        print("\nFlagged files:")
        for r in flagged:
            print(f"  {r['input']}  [{r['confidence']}] notes={r['notes']}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Crop film frame from lightbox/holder captures of Boas negatives.")
    parser.add_argument("input", help="Input image/raw file or directory (with --batch)")
    parser.add_argument("--output", help="Output image path (single file mode)")
    parser.add_argument("--output-dir", help="Output directory (batch mode)")
    parser.add_argument("--batch", action="store_true", help="Process all images in input directory")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for batch mode (default: 4)")
    parser.add_argument("--debug", action="store_true", help="Save debug overlay thumbnails")
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
            else input_path.parent / f"{input_path.stem}_cropped.tif"
        result = process_image(input_path, output_path, args.debug)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
