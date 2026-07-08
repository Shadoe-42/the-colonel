#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# invert-neg.sh — convert every cropped negative TIFF to a viewable positive.
#
# HOW TO RUN (that's the whole lesson):
#     cd ~/claude/the_colonel/boas/invert
#     bash invert-neg.sh
#
# Originals are NEVER touched. Positive copies (16-bit TIFF + a JPG proof
# of each) go in a new folder next to your input, with "_positive" added
# to the name. Run it again any time — it just re-does the work.
#
# This is an AUTOMATIC correction, not a calibrated one — there's no clear
# film base visible in these crops to calibrate a "proper" per-roll
# inversion against, so treat the output as a strong starting point, not
# a finished color grade. See the comment at the top of invert_negative.py
# for why.
#
# By default this points at the brother's test batch. To point it
# somewhere else:
#     bash invert-neg.sh /path/to/negatives_cropped /path/to/output_folder

set -u

DEFAULT_INPUT="$HOME/claude/911photo_possitives_2026-07-03_2100/negatives_cropped"
INPUT_ROOT="${1:-$DEFAULT_INPUT}"
OUTPUT_ROOT="${2:-${INPUT_ROOT%/}_positive}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONVERTER="$SCRIPT_DIR/invert_negative.py"
REQUIREMENTS="$SCRIPT_DIR/../crop/requirements.txt"

# ── Pre-flight checks, in plain English ─────────────────────────────────────

if ! command -v python3 >/dev/null 2>&1; then
    echo "PROBLEM: Python isn't installed (or Terminal can't see it)."
    echo "FIX: see 'Step 2: Install Python' in the README in the crop folder."
    exit 1
fi

if [ ! -f "$CONVERTER" ]; then
    echo "PROBLEM: can't find invert_negative.py next to this script."
    echo "FIX: make sure invert-neg.sh stays in the same folder as invert_negative.py."
    exit 1
fi

if [ ! -d "$INPUT_ROOT" ]; then
    echo "PROBLEM: can't find the input folder at: $INPUT_ROOT"
    echo "FIX: pass the folder of cropped negative TIFFs as the first argument, e.g.:"
    echo "    bash invert-neg.sh /path/to/negatives_cropped"
    exit 1
fi

if ! python3 -c "import cv2, numpy, tifffile" >/dev/null 2>&1; then
    echo "PROBLEM: the tool's add-on packages aren't installed yet."
    echo "FIX: run this command, then try again:"
    echo "    pip3 install -r \"$REQUIREMENTS\""
    exit 1
fi

# ── The actual work ──────────────────────────────────────────────────────────

echo "Converting negatives in: $INPUT_ROOT"
echo "Positives go to:         $OUTPUT_ROOT"
echo "(Your originals are never changed.)"
echo

start_time=$(date +%s)

python3 "$CONVERTER" "$INPUT_ROOT" --batch --output-dir "$OUTPUT_ROOT"

# ── Summary ──────────────────────────────────────────────────────────────────

elapsed=$(( $(date +%s) - start_time ))
total=$(find "$OUTPUT_ROOT" -maxdepth 1 -iname '*.tif' 2>/dev/null | wc -l | tr -d ' ')
errors=$(cat "$OUTPUT_ROOT"/invert_log_*.jsonl 2>/dev/null | grep -c '"status": "error_unreadable"')

echo
echo "=================================================="
echo "ALL DONE — $total positives created, in $((elapsed / 60))m $((elapsed % 60))s."
echo "Each TIFF has a matching .jpg next to it for quick viewing."
echo
if [ "$errors" -gt 0 ]; then
    echo "$errors file(s) couldn't be read — check the log for details:"
    ls "$OUTPUT_ROOT"/invert_log_*.jsonl 2>/dev/null | tail -1
else
    echo "Every file converted without errors."
fi
echo
echo "Remember: this is an automatic color correction, not a final grade."
echo "Look through the results — some frames may need a manual touch-up."
