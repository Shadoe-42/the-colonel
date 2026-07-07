#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# crop-pos.sh — crop every image in ~/claude/positives, one folder at a time.
#
# HOW TO RUN (that's the whole lesson):
#     cd ~/claude/the_colonel/boas/crop
#     bash crop-pos.sh
#
# Originals are NEVER touched. Cropped copies go to ~/claude/positives-cropped,
# in the same folder layout. Run it again any time — it just re-does the work.

set -u

INPUT_ROOT="$HOME/claude/positives"
OUTPUT_ROOT="$HOME/claude/positives-cropped"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECTOR="$SCRIPT_DIR/detect_strip.py"

# ── Pre-flight checks, in plain English ─────────────────────────────────────

if ! command -v python3 >/dev/null 2>&1; then
    echo "PROBLEM: Python isn't installed (or Terminal can't see it)."
    echo "FIX: see 'Step 2: Install Python' in the README in this folder."
    exit 1
fi

if [ ! -d "$INPUT_ROOT" ]; then
    echo "PROBLEM: can't find the positives folder at: $INPUT_ROOT"
    echo "FIX: make sure the 'positives' folder is inside the 'claude' folder in your home folder."
    exit 1
fi

if ! python3 -c "import cv2, numpy, scipy" >/dev/null 2>&1; then
    echo "PROBLEM: the tool's add-on packages aren't installed yet."
    echo "FIX: run this command, then try again:"
    echo "    pip3 install -r \"$SCRIPT_DIR/requirements.txt\""
    exit 1
fi

# ── The actual work ──────────────────────────────────────────────────────────

echo "Cropping everything in: $INPUT_ROOT"
echo "Cropped copies go to:   $OUTPUT_ROOT"
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
    python3 "$DETECTOR" "$d" --batch --output-dir "$OUTPUT_ROOT/$name"
    echo
done

# ── Summary ──────────────────────────────────────────────────────────────────

elapsed=$(( $(date +%s) - start_time ))
total=$(find "$OUTPUT_ROOT" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.tif' -o -iname '*.tiff' -o -iname '*.png' \) 2>/dev/null | wc -l | tr -d ' ')
flagged=$(cat "$OUTPUT_ROOT"/*/crop_log_*.jsonl 2>/dev/null | grep -cE '"confidence": "(low_flagged|flagged_small|error_unreadable)"')

echo "=================================================="
echo "ALL DONE — $folders folders, $total cropped images, in $((elapsed / 60))m $((elapsed % 60))s."
echo
if [ "$flagged" -gt 0 ]; then
    echo "$flagged images need a human eye (the tool wasn't sure about them):"
    cat "$OUTPUT_ROOT"/*/crop_log_*.jsonl 2>/dev/null \
        | grep -E '"confidence": "(low_flagged|flagged_small|error_unreadable)"' \
        | sed 's/.*"input": "\([^"]*\)".*/    \1/'
    echo
    echo "Open each one in the cropped folder and check it looks right."
else
    echo "Nothing was flagged — every crop passed the tool's own checks."
fi
