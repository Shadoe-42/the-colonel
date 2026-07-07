#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) the_colonel contributors
# See LICENSE for terms. Commercial use requires separate agreement.
"""
detect_strip.py
---------------
Detects and crops the center film frame from Gary Lee Boas positive
strip captures — 35mm (or 120) strips photographed on a light table,
where NEIGHBORING FRAMES are visible on either side of the target frame.

Why this exists: detect_rebate.py walks inward from the image edge and
latches onto the first plausible edge — which, on a strip capture, is
the OUTER edge of the inter-frame divider band, so the crop keeps the
divider plus a slice of the neighboring frame. This tool inverts the
approach for left/right:

  - Left/Right: content-anchored, center-out. Sample content brightness
    near frame center, then walk outward until brightness rises into a
    SUSTAINED bright band (the divider / light-table surround). The
    inner edge of that band is the frame edge. Brief bright content
    (a white shirt, a window) doesn't sustain, so it's skipped.
  - Top/Bottom: reuses detect_rebate's validated detectors unchanged.

Also works on single-frame captures (e.g. 6x6 on white surround): the
center-out walk simply meets the surround instead of a divider.

Confidence adds an edge-verification check that detect_rebate lacks:
the band just OUTSIDE each detected left/right edge must be brighter
than the content just inside it, otherwise the crop is flagged.

Usage:
    python detect_strip.py <input> [--output <path>] [--debug]
    python detect_strip.py <input_dir> --batch [--output-dir <path>]

Part of: ~/claude/the_colonel/boas/
"""

import cv2
import numpy as np
from scipy.signal import find_peaks
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor

from detect_rebate import (
    SCALE, INSET, MIN_DIM, SMOOTH_WIN, _smooth,
    find_inner_edge, find_top_gradient_plateau, find_bottom_content_edge,
)


def _smooth_r(profile, win=SMOOTH_WIN):
    """
    Reflect-padded smoothing. detect_rebate's _smooth uses plain
    np.convolve(mode='same'), which zero-pads at the array ends and
    crushes brightness in the outermost ~win/2 samples — enough to make
    a thin light-table surround at the capture edge invisible to
    threshold checks. Reflect padding preserves edge values.
    """
    p = np.pad(np.asarray(profile, dtype=float), win, mode='reflect')
    return np.convolve(p, np.ones(win)/win, mode='same')[win:-win]

# ── Strip-specific parameters ───────────────────────────────────────────────

RISE_FACTOR    = 1.28   # walk fallback: brightness must exceed baseline * this
RISE_FLOOR     = 32     # ...and by at least this many absolute levels
SUSTAIN_FRAC   = 0.012  # walk fallback: rise must persist this fraction of width
MIN_HALF_FRAC  = 0.12   # an edge closer to center than this fraction is suspect
EDGE_CONTRAST  = 12     # outside band must beat inside content by this much

PEAK_PROM      = 18     # min peak prominence for a divider candidate
PEAK_VAL       = 1.15   # divider peak must be at least baseline * this
PEAK_MAX_WFRAC = 0.15   # divider peaks are narrow; content bumps are wide
PEAK_MARGIN    = 2      # px inside the peak's half-height crossing


# ── Center-out left/right detector ──────────────────────────────────────────

def find_side_edges(col_profile, sw):
    """
    Locate the divider bands flanking the center frame.

    Empirically (see the Boas positive strips) dividers are only modestly
    brighter than content — an absolute threshold fails — but they are
    NARROW peaks with strong prominence in the column-brightness profile,
    while in-frame content bumps are wide and low. So:

      1. Primary: find_peaks over the profile; keep peaks that are
         narrow, prominent, brighter than baseline, and not too close
         to center. Nearest qualifying peak on each side is the divider;
         the frame edge is that peak's inner half-height crossing.
      2. Fallback (per side, e.g. divider merged with the surround at
         the strip's end): center-out walk to the first SUSTAINED rise
         above baseline.

    Returns (left, right) in small-image coordinates.
    """
    smooth  = _smooth_r(col_profile)
    center  = sw // 2
    # Baseline: median of central 20% — robust to bright content patches
    baseline = float(np.median(smooth[int(sw*0.40):int(sw*0.60)]))

    # ── primary: divider peaks ──
    peaks, props = find_peaks(smooth, prominence=PEAK_PROM, width=2)
    min_off = int(sw * MIN_HALF_FRAC)

    def divider_edge(side):
        """side: -1 = left of center, +1 = right of center."""
        best = None
        for k, p in enumerate(peaks):
            if smooth[p] < baseline * PEAK_VAL:            continue
            if props['widths'][k] > sw * PEAK_MAX_WFRAC:   continue
            if side < 0 and not (0 < p <= center - min_off):        continue
            if side > 0 and not (center + min_off <= p < sw - 1):   continue
            # nearest qualifying peak to center wins
            if best is None or abs(p - center) < abs(peaks[best] - center):
                best = k
        if best is None:
            return None
        if side < 0:
            return min(int(props['right_ips'][best]) + PEAK_MARGIN, center)
        return max(int(props['left_ips'][best]) - PEAK_MARGIN, center)

    # ── fallback: sustained-rise walk ──
    thresh  = max(baseline * RISE_FACTOR, baseline + RISE_FLOOR)
    sustain = max(2, int(sw * SUSTAIN_FRAC))

    def walk(direction):
        i = center
        while 0 <= i < sw:
            if smooth[i] > thresh:
                run_end, run_len, j = i, 0, i
                while 0 <= j < sw and smooth[j] > thresh:
                    run_len += 1
                    run_end  = j
                    j += direction
                if run_len >= sustain or j < 0 or j >= sw:
                    return i          # inner edge of sustained bright band
                i = run_end + direction  # brief spike — skip past it
            else:
                i += direction
        return 0 if direction < 0 else sw - 1   # frame touches capture edge

    left  = divider_edge(-1)
    right = divider_edge(+1)
    if left  is None: left  = walk(-1)
    if right is None: right = walk(+1)
    return left, right


# ── Center-out top/bottom detector ──────────────────────────────────────────
#
# The inherited detect_rebate bottom logic expects the rebate to be BRIGHTER
# than content (true for flatbed negative scans). On positive strip captures
# the bottom rebate is a narrow DARK band (with bright "KODAK SAFETY FILM"
# edge printing) sitting just inside the bright light-table surround, so the
# old detector sails past it and keeps the band.
#
# Strategy per side: (1) anchor on the surround — unambiguously bright;
# (2) peel back toward center; (3) a dark dip just inside the surround is
# rebate ONLY if it's narrow (≤ REBATE_MAX_FRAC of height). Wide dark
# regions are picture content (e.g. dark scenes on medium format) and must
# not be peeled, or we'd cut into the image.

SURROUND_MIN   = 150    # absolute brightness floor for light-table surround
SURROUND_FACT  = 1.4    # ...or baseline * this, whichever is higher
REBATE_DARK    = 0.92   # dip must fall below baseline * this to be a band
REBATE_MAX_FRAC = 0.10  # dark band wider than this fraction of height = content
TB_MARGIN_FRAC = 0.008  # extra inset past a detected top/bottom edge: eats the
                        # blur/transition zone at the physical frame edge, which
                        # otherwise survives as a faint 1-2% band in the crop


GLOW_CAP_FRAC   = 0.08  # max distance the glow-decay walk may move an edge
GLOW_STEEP      = 2.5   # gradient magnitude that counts as decay ramp
GLOW_FLAT       = 1.0   # gradient magnitude that counts as content plateau


def _decay_to_plateau(smooth, start, step, n):
    """
    Light-table halation bleeds past the frame edge as a bright ramp that
    a threshold crossing doesn't remove. From `start`, walk toward frame
    center (direction `step`) while the profile is steeply decaying; stop
    where it flattens into the content plateau. Capped so bright content
    can't drag the edge deep into the frame. Returns adjusted edge index.
    """
    d = np.gradient(smooth)
    cap = int(n * GLOW_CAP_FRAC)
    saw_steep = False
    i = start
    for _ in range(cap):
        j = i + step
        if not (0 <= j < n):
            break
        if abs(d[j]) >= GLOW_STEEP:
            saw_steep = True
            i = j
        elif saw_steep and abs(d[j]) <= GLOW_FLAT:
            return j
        else:
            i = j
    return start if not saw_steep else i


def band_edge(smooth, n, baseline, direction):
    """
    Find one frame edge (top: direction=-1, bottom: +1) by anchoring on the
    bright surround and peeling back any narrow dark rebate band.
    Returns edge index, or None if no surround found (fall back to legacy).
    """
    center  = n // 2
    sustain = max(2, int(n * 0.012))
    s_thresh = max(SURROUND_MIN, baseline * SURROUND_FACT)

    # 1. Walk center → edge looking for sustained surround brightness
    surround = None
    i = center
    while 0 <= i < n:
        if smooth[i] > s_thresh:
            j, run = i, 0
            while 0 <= j < n and smooth[j] > s_thresh:
                run += 1
                j += direction
            if run >= sustain or j < 0 or j >= n:
                surround = i
                break
            i = j
        else:
            i += direction
    if surround is None:
        return None

    # 2. Look for a dark rebate band just inside the surround
    window = int(n * 0.12)
    if direction > 0:
        w0, w1 = max(surround - window, center), surround
    else:
        w0, w1 = surround, min(surround + window, center)
    region = smooth[w0:w1+1]
    if region.size == 0:
        return surround
    m_rel  = int(np.argmin(region))
    m_idx  = w0 + m_rel
    m_val  = float(region[m_rel])

    if m_val >= baseline * REBATE_DARK:
        # No dark band — frame meets surround; strip the halation ramp
        return _decay_to_plateau(smooth, surround, -direction, n)

    # 3. Narrowness check: how wide is the contiguous dark run around the min?
    dark_thresh = baseline * REBATE_DARK
    lo = m_idx
    while lo - 1 >= 0 and smooth[lo - 1] < dark_thresh:
        lo -= 1
    hi = m_idx
    while hi + 1 < n and smooth[hi + 1] < dark_thresh:
        hi += 1
    if (hi - lo + 1) > n * REBATE_MAX_FRAC:
        # Wide dark region = content, don't peel — but still strip halation
        return _decay_to_plateau(smooth, surround, -direction, n)

    # 4. Peel: walk from the dip toward center until brightness recovers
    #    to near-baseline, sustained. Recovering only to the dip/baseline
    #    midpoint leaves a visible half-dark strip in the crop.
    mid = max((baseline + m_val) / 2.0, baseline * 0.93)
    i = m_idx
    step = -direction
    while 0 <= i < n and i != center:
        if smooth[i] >= mid:
            j, run = i, 0
            while 0 <= j < n and smooth[j] >= mid and run < sustain:
                run += 1
                j += step
            if run >= sustain:
                return i
            i = j
        else:
            i += step
    return surround


# ── Frame finder ────────────────────────────────────────────────────────────

def find_frame(img):
    """
    Returns ((x1, y1, x2, y2) full-res, edge_ok) where edge_ok reports
    whether the left/right edges passed the outside-brighter-than-inside
    verification.
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

    # Top/bottom: surround-anchored band peel; legacy detectors as fallback
    row_smooth = _smooth_r(row_profile)
    row_base   = float(np.median(row_smooth[int(sh*0.40):int(sh*0.60)]))
    top = band_edge(row_smooth, sh, row_base, direction=-1)
    bot = band_edge(row_smooth, sh, row_base, direction=+1)
    margin = max(1, int(sh * TB_MARGIN_FRAC))
    if top is not None:
        top = min(top + margin, sh // 2)
    if bot is not None:
        bot = max(bot - margin, sh // 2)
    if top is None:
        top = find_inner_edge(row_profile, reverse=False, search_limit=0.35)
        if top < int(sh * 0.05):
            top = find_top_gradient_plateau(row_profile, sh)
    if bot is None:
        bot = find_bottom_content_edge(row_profile, sh)

    # Left/right: center-out
    left, right = find_side_edges(col_profile, sw)

    # Sanity: an edge imploding toward center means detection failed —
    # fall back to detect_rebate's inward walk for that side.
    if (sw//2 - left) < int(sw * MIN_HALF_FRAC):
        left = find_inner_edge(col_profile, reverse=False, search_limit=0.40)
    if (right - sw//2) < int(sw * MIN_HALF_FRAC):
        right = find_inner_edge(col_profile, reverse=True, search_limit=0.35)

    # Edge verification: just outside each side edge should be brighter
    # than content just inside it.
    smooth = _smooth_r(col_profile)
    pad = max(3, int(sw * 0.02))

    def _band_ok(edge, outside_dir):
        """Mean brightness just outside the edge must beat just inside."""
        if edge <= 0 or edge >= sw - 1:
            return True   # frame touches capture edge — nothing to verify
        if outside_dir < 0:
            outside = smooth[max(edge - pad, 0):edge]
            inside  = smooth[edge:min(edge + pad, sw)]
        else:
            outside = smooth[edge:min(edge + pad, sw)]
            inside  = smooth[max(edge - pad, 0):edge]
        if outside.size == 0 or inside.size == 0:
            return True
        return float(outside.mean()) - float(inside.mean()) >= EDGE_CONTRAST

    edge_ok = _band_ok(left, -1) and _band_ok(right, +1)

    rect = (int(left/SCALE), int(top/SCALE), int(right/SCALE), int(bot/SCALE))
    return rect, edge_ok


# ── Output sliver check ─────────────────────────────────────────────────────
#
# Last line of defense against the one silent failure mode left: a crop
# that's loose by a thin band (divider, rebate, or surround remnant) on one
# edge. Such a band is (a) clearly brighter or darker than the content just
# inside it, and (b) UNIFORM along its length — picture content isn't.
# We only flag, never auto-trim: a false trim would cut into the image,
# a false flag just costs one human glance.

SLIVER_BAND_FRAC  = 0.02   # thickness of the edge band examined
SLIVER_INNER_LO   = 0.08   # content reference zone: this deep...
SLIVER_INNER_HI   = 0.14   # ...to this deep (past any wide-ish sliver)
SLIVER_CONTRAST   = 22     # band vs inner mean difference to qualify
SLIVER_UNIFORMITY = 20     # max std of band's lengthwise profile


def detect_slivers(crop):
    """Returns list of edges ('left','right','top','bottom') with a
    probable leftover band on the given cropped BGR image."""
    small = cv2.resize(crop, (0, 0), fx=0.25, fy=0.25) \
            if max(crop.shape[:2]) > 1200 else crop
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    bt, bl = max(2, int(h*SLIVER_BAND_FRAC)),  max(2, int(w*SLIVER_BAND_FRAC))
    t0, t1 = int(h*SLIVER_INNER_LO), int(h*SLIVER_INNER_HI)
    l0, l1 = int(w*SLIVER_INNER_LO), int(w*SLIVER_INNER_HI)
    zones = {
        'left':   (gray[:, :bl],        gray[:, l0:l1],          0),
        'right':  (gray[:, -bl:],       gray[:, w-l1:w-l0],      0),
        'top':    (gray[:bt, :],        gray[t0:t1, :],          1),
        'bottom': (gray[-bt:, :],       gray[h-t1:h-t0, :],      1),
    }
    slivers = []
    for edge, (band, inner, axis) in zones.items():
        if band.size == 0 or inner.size == 0:
            continue
        diff = abs(float(band.mean()) - float(inner.mean()))
        lengthwise = band.mean(axis=axis)   # profile along the edge
        if diff >= SLIVER_CONTRAST and float(lengthwise.std()) <= SLIVER_UNIFORMITY:
            slivers.append(edge)
    return slivers


# ── Processing ──────────────────────────────────────────────────────────────

def process_image(input_path: Path, output_path: Path, debug: bool = False) -> dict:
    img = cv2.imread(str(input_path))
    if img is None:
        return _log(input_path, output_path, None, 'error_unreadable')

    h, w = img.shape[:2]
    (x1, y1, x2, y2), edge_ok = find_frame(img)

    x1 = min(x1 + INSET, w);  y1 = min(y1 + INSET, h)
    x2 = max(x2 - INSET, 0);  y2 = max(y2 - INSET, 0)

    if x2 - x1 < MIN_DIM or y2 - y1 < MIN_DIM:
        print(f"  [FLAGGED] {input_path.name} — crop too small ({x2-x1}x{y2-y1})")
        return _log(input_path, output_path, (x1,y1,x2,y2), 'flagged_small')

    ratio = ((x2-x1)*(y2-y1)) / (w*h)
    full_width = (x1 <= INSET) and (x2 >= w - INSET - 1)
    cropped = img[y1:y2, x1:x2]
    slivers = detect_slivers(cropped)
    if not edge_ok or full_width or slivers:
        # full_width: a strip capture cropped to full capture width almost
        # certainly means both side detections failed, not a full-bleed frame.
        # slivers: a leftover divider/rebate/surround band on a crop edge.
        confidence = 'low_flagged'
    elif 0.25 < ratio < 0.80:
        confidence = 'high'
    elif 0.15 < ratio <= 0.25 or 0.80 <= ratio < 0.90:
        confidence = 'medium'
    else:
        confidence = 'low_flagged'

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), cropped)

    if debug:
        _save_debug(img, input_path, x1, y1, x2, y2)

    sliver_note = f" | sliver:{'+'.join(slivers)}" if slivers else ""
    print(f"  [{confidence.upper()}] {input_path.name} → {output_path.name} "
          f"| {x2-x1}x{y2-y1} | ratio={ratio:.2f} | edges={'ok' if edge_ok else 'WEAK'}{sliver_note}")

    return _log(input_path, output_path, (x1,y1,x2,y2), confidence, slivers)


def _save_debug(img, input_path, x1, y1, x2, y2):
    h, w = img.shape[:2]
    small = cv2.resize(img, (int(w*SCALE), int(h*SCALE)))
    sh, sw = small.shape[:2]
    dbg = small.copy()
    cv2.line(dbg, (0, int(y1*SCALE)), (sw, int(y1*SCALE)), (0,255,0),   2)
    cv2.line(dbg, (0, int(y2*SCALE)), (sw, int(y2*SCALE)), (0,0,255),   2)
    cv2.line(dbg, (int(x1*SCALE), 0), (int(x1*SCALE), sh), (255,0,0),   2)
    cv2.line(dbg, (int(x2*SCALE), 0), (int(x2*SCALE), sh), (0,165,255), 2)
    dbg_path = input_path.parent / f"{input_path.stem}_debug{input_path.suffix}"
    cv2.imwrite(str(dbg_path), dbg)


def _log(input_path, output_path, rect, confidence, slivers=None):
    return {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "input":      str(input_path),
        "output":     str(output_path),
        "frame_rect": list(rect) if rect else None,
        "confidence": confidence,
        "slivers":    slivers or [],
        "pipeline":   "positive_strip_v2"
    }


# ── Batch processing ─────────────────────────────────────────────────────────

SUPPORTED = {'.jpg', '.jpeg', '.tif', '.tiff', '.png'}

def _process_image_star(args):
    return process_image(*args)


def batch_process(input_dir: Path, output_dir: Path, workers: int = 4,
                  debug: bool = False):
    files = [f for f in sorted(input_dir.iterdir())
             if f.suffix.lower() in SUPPORTED and '_debug' not in f.stem]

    if not files:
        print(f"No supported image files found in {input_dir}")
        return

    print(f"Processing {len(files)} files with {workers} workers...")
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / f"crop_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    args = [(f, output_dir / f.name, debug) for f in files]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_process_image_star, args))

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
        description="Crop center frame from Gary Lee Boas positive strip captures.")
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
