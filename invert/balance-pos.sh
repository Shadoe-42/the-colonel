#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# balance-pos.sh — auto color-balance every image in ~/claude/positives-cropped,
# one category folder at a time.
#
# HOW TO RUN (that's the whole lesson):
#     cd ~/claude/the_colonel/boas/invert
#     bash balance-pos.sh
#
# Originals are NEVER touched. Balanced copies go to ~/claude/pos_colour,
# in the same folder layout as positives-cropped. Run it again any time —
# it just re-does the work.
#
# This is an AUTOMATIC correction: it does not know what a wall or a shirt
# is supposed to look like, it just stretches each color channel's range.
# Frames with one large, uniform, saturated background (a solid-color wall
# filling most of the shot) can still come out with a residual cast — that's
# a known limitation, not a bug. Expect most images to come out well and a
# minority to need a manual touch-up.

set -u

INPUT_ROOT="$HOME/claude/positives-cropped"
OUTPUT_ROOT="$HOME/claude/pos_colour"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BALANCER="$SCRIPT_DIR/balance_positive.py"
REQUIREMENTS="$SCRIPT_DIR/../crop/requirements.txt"

# ── Pre-flight checks, in plain English ─────────────────────────────────────

if ! command -v python3 >/dev/null 2>&1; then
    echo "PROBLEM: Python isn't installed (or Terminal can't see it)."
    echo "FIX: see 'Step 2: Install Python' in the README in the crop folder."
    exit 1
fi

if [ ! -f "$BALANCER" ]; then
    echo "PROBLEM: can't find balance_positive.py next to this script."
    echo "FIX: make sure balance-pos.sh stays in the same folder as balance_positive.py."
    exit 1
fi

if [ ! -d "$INPUT_ROOT" ]; then
    echo "PROBLEM: can't find the positives-cropped folder at: $INPUT_ROOT"
    echo "FIX: make sure 'positives-cropped' is inside the 'claude' folder in your home folder"
    echo "     (run crop-pos.sh first if it doesn't exist yet)."
    exit 1
fi

if ! python3 -c "import cv2, numpy" >/dev/null 2>&1; then
    echo "PROBLEM: the tool's add-on packages aren't installed yet."
    echo "FIX: run this command, then try again:"
    echo "    pip3 install -r \"$REQUIREMENTS\""
    exit 1
fi

# ── The actual work ──────────────────────────────────────────────────────────

echo "Color-balancing everything in: $INPUT_ROOT"
echo "Balanced copies go to:         $OUTPUT_ROOT"
echo "(Your originals are never changed.)"
echo

start_time=$(date +%s)
folders=0

for d in "$INPUT_ROOT"/*/; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    folders=$((folders + 1))
    echo "──────────────────────────────────────────────────"
    echo "Folder: $name"
    python3 "$BALANCER" "$d" --batch --output-dir "$OUTPUT_ROOT/$name"
    echo
done

# ── Summary ──────────────────────────────────────────────────────────────────

elapsed=$(( $(date +%s) - start_time ))
total=$(find "$OUTPUT_ROOT" -type f -iname '*.jpg' 2>/dev/null | wc -l | tr -d ' ')
errors=$(cat "$OUTPUT_ROOT"/*/balance_log_*.jsonl 2>/dev/null | grep -c '"status": "error_unreadable"')

echo "=================================================="
echo "ALL DONE — $folders folders, $total balanced images, in $((elapsed / 60))m $((elapsed % 60))s."
echo
if [ "$errors" -gt 0 ]; then
    echo "$errors file(s) couldn't be read:"
    cat "$OUTPUT_ROOT"/*/balance_log_*.jsonl 2>/dev/null \
        | grep '"status": "error_unreadable"' \
        | sed 's/.*"input": "\([^"]*\)".*/    \1/'
else
    echo "Every file converted without errors."
fi
echo
echo "Remember: this is automatic, not a final grade. A frame with one large,"
echo "solid-color background (a wall, a backdrop) is the most likely place"
echo "for a residual color cast to still show up — spot-check those first."
