# boas-crop

**Automated film frame detection and cropping for the Gary Lee Boas archive.**

Gary Lee Boas spent decades photographing the people and edges of a New York that no longer exists — Studio 54 on an ordinary Tuesday night, celebrities caught unguarded on the street, the texture of a city at its most alive and most dangerous. He shot nearly everything on 35mm, and he shot constantly.

The result is an archive of approximately 50,000 negatives and prints spanning the early 1970s through the 1990s. A retrospective book is in production with a Paris-based publisher. A gallery show is being planned.

This tool exists because every one of those scans came off a flatbed with scanner bed, film holder, rebate border, and sprocket holes surrounding the actual image. Before any of that work can happen, 50,000 frames need to be cropped.

---

## What it does

Detects and crops the actual film frame from flatbed scans of 35mm color negatives. Handles:

- Variable film stocks and color casts across decades of shooting
- Inconsistent exposure — from dark club interiors to bright outdoor street shots
- Sprocket holes and inter-frame rebate bleeding into the scan
- Scanner bed brightness gradients around the film strip
- Scans where the rebate-to-content boundary has no clean dark valley

Does not destructively modify originals. Outputs to a separate directory. Logs every decision with crop coordinates and confidence score for review.

---

## How it works

Detection runs at 12% of full resolution for speed, then scales coordinates back up. Four edges are found independently using brightness profile analysis.

**Standard edge detection (left, right, most top edges):**
1. Skip the scanner bed (brightness >160)
2. Find the dark valley between the bed/film holder and the rebate border — threshold adapts to the actual minimum in each scan rather than a fixed value
3. Find the rebate brightness bump rising from the valley
4. Return the trailing edge of that bump as it drops into image content

**Gradient plateau detection (top edge fallback for bright scenes):**
For outdoor or overexposed frames where there is no dark valley at the top, the rebate blends continuously into the content. These scans show a steep brightness gradient from the scanner bed that abruptly flattens when it reaches the content plateau. The inflection point is the inner rebate edge.

**Content-anchor bottom detection:**
The bottom of the strip often has sprocket holes sitting between the image content and the rebate, creating a false brightness bump that fools standard detectors. This method samples the stable content brightness level from well inside the frame, then scans downward to find where the content first rises toward the sprocket zone — anchoring to content rather than rebate.

The algorithm selects which method to use per-edge based on signal characteristics in each scan.

---

## Usage

**Single image:**
```bash
python crop/detect_rebate.py input.tif --output output.tif
```

**Single image with debug overlay:**
```bash
python crop/detect_rebate.py input.tif --output output.tif --debug
```
Debug mode saves a thumbnail with detection lines drawn:
- Green = top edge
- Red = bottom edge  
- Blue = left edge
- Orange = right edge

**Batch mode:**
```bash
python crop/detect_rebate.py /path/to/scans/ --batch --output-dir /path/to/cropped/
```

**Batch with parallel workers:**
```bash
python crop/detect_rebate.py /path/to/scans/ --batch --output-dir /path/to/cropped/ --workers 8
```

Supported formats: `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.png`

---

## Output and logging

Every processed file generates a JSON log entry:

```json
{
  "timestamp": "2026-07-02T14:33:25+00:00",
  "input": "/path/to/scan.tif",
  "output": "/path/to/cropped/scan.tif",
  "frame_rect": [1415, 531, 4635, 3568],
  "confidence": "high",
  "pipeline": "negative_rebate_v1"
}
```

Batch runs write a `.jsonl` log to the output directory. Confidence levels:

| Level | Meaning |
|-------|---------|
| `high` | Crop ratio 25–80% of scan area — expected range |
| `medium` | Crop ratio at edges of expected range — worth a look |
| `low_flagged` | Outside expected range — manual review needed |
| `flagged_small` | Crop dimensions below minimum — detection likely failed |
| `error_unreadable` | File could not be opened |

Flagged files are listed in the terminal summary after a batch run. A manual review UI is in development.

---

## Installation

```bash
pip install -r requirements.txt
```

Requires Python 3.10+.

---

## Project structure

```
boas/
├── crop/
│   └── detect_rebate.py    # frame detection and cropping
├── classify/               # negative vs print classifier (coming)
├── review/                 # manual review UI (coming)
├── logs/                   # batch run logs (gitignored)
├── requirements.txt
└── README.md
```

---

## Context

This is one part of a larger archival pipeline being built for the Boas collection. The classifier (to route between the negative pipeline here and a separate prints pipeline) and the review UI are next. The full pipeline will handle approximately 50,000 files across both negative and print scans of varying age and condition.

The tool is named after Steve Cropper — essential, precise, never a wasted note.

---

## License

AGPL v3. See [LICENSE](LICENSE).

If you want to use this in a closed or commercial context, get in touch.
