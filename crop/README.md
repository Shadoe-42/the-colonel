# boas-crop

**Automated film frame detection and cropping for the Gary Lee Boas archive.**

Gary Lee Boas spent decades photographing the people and edges of a New York that no longer exists — Studio 54 on an ordinary Tuesday night, celebrities caught unguarded on the street, the texture of a city at its most alive and most dangerous. He shot nearly everything on 35mm, and he shot constantly.

The result is an archive of approximately 50,000 negatives and prints spanning the early 1970s through the 1990s. A retrospective book is in production with a Paris-based publisher. A gallery show is being planned.

This tool exists because every one of those scans/photos came with a scanner bed, film holder, rebate border, or sprocket holes surrounding the actual image. Before any of that work can happen, 50,000 frames need to be cropped down to just the picture.

This README is written for whoever needs to run these tools next, even if that's someone who has never opened a terminal before. If you already know your way around a command line, skip to [Running the tools](#running-the-tools).

---

## Table of contents

1. [What's in this repo](#whats-in-this-repo)
2. [Before you start: what you'll need](#before-you-start-what-youll-need)
3. [Step 1: Open a terminal](#step-1-open-a-terminal)
4. [Step 2: Install Python](#step-2-install-python)
5. [Step 3: Install Git](#step-3-install-git)
6. [Step 4: Get this code onto your computer](#step-4-get-this-code-onto-your-computer)
7. [Step 5: Install the tool's dependencies](#step-5-install-the-tools-dependencies)
8. [Which tool do I use?](#which-tool-do-i-use)
9. [Running the tools](#running-the-tools)
10. [Understanding the output](#understanding-the-output)
11. [Troubleshooting](#troubleshooting)
12. [Project structure](#project-structure)
13. [License](#license)

---

## What's in this repo

There are two cropping tools, because the negatives in this archive have been captured two different ways:

- **`crop/detect_rebate.py`** — for negatives or prints that were scanned on a flatbed scanner. It finds the edge between the scanner bed / film holder and the actual picture.
- **`crop/detect_holder.py`** — for negatives that were photographed with a digital camera while sitting in a physical film holder on a lightbox (this is how the negatives your brother sent over were captured). It finds the edge between the holder's divider bars and the actual picture.

Both tools work the same way from the outside: point them at a folder of images, and they'll crop every image and drop the results in a new folder, leaving your originals completely untouched.

---

## Before you start: what you'll need

This guide assumes you're on a **Mac**. Everything below is done by typing commands into an app called Terminal — that's normal for this kind of tool, there's no button-clicking version, sorry.

Here's the plan, in order:

1. Open Terminal (a program already on your Mac).
2. Install Python (the programming language the tools are written in).
3. Install Git (a tool for downloading/updating code, if you don't already have this repo on your computer).
4. Get this code onto your computer, if you don't have it already.
5. Install a handful of add-on packages the tools depend on.
6. Run the tool.

Each step below tells you exactly what to type. When you see a gray box, that's a command — type it (or copy/paste it) into Terminal exactly as written, then press Enter/Return.

---

## Step 1: Open a terminal

1. Press `Command (⌘) + Space` to open Spotlight search.
2. Type `Terminal`.
3. Press Enter when "Terminal" shows up (it has a black or dark icon that looks like a little screen).

A window will open with some text and a blinking cursor. This is where you'll type all the commands in this guide. It's normal for it to look intimidating — you're not going to break anything by typing a command wrong, at worst you'll just get an error message you can read and ignore/fix.

---

## Step 2: Install Python

Check if you already have it:

```bash
python3 --version
```

If you see something like `Python 3.11.4`, you're set — skip to Step 3. If you see an error like `command not found`, you need to install Python:

1. Go to [python.org/downloads](https://www.python.org/downloads/) in your web browser.
2. Click the big yellow "Download Python" button (it'll pick the right version for your Mac automatically).
3. Open the downloaded file and click through the installer (Continue → Continue → Agree → Install). It'll ask for your Mac password near the end — that's normal.
4. Close and reopen Terminal (important — it won't see the new install otherwise), then run `python3 --version` again to confirm.

---

## Step 3: Install Git

Check if you already have it:

```bash
git --version
```

If it prints a version number, you're done. If not, macOS will usually pop up a window asking to install "Command Line Developer Tools" — click **Install**, agree to the license, and wait a few minutes for it to finish. If no popup appears, run:

```bash
xcode-select --install
```

and follow the same prompt.

---

## Step 4: Get this code onto your computer

If you're reading this file from your own computer already (e.g. it's sitting in a `the_colonel` folder), you can skip this step entirely.

Otherwise, in Terminal:

```bash
cd ~
git clone https://github.com/Shadoe-42/the-colonel.git
```

This creates a folder called `the-colonel` in your home folder with everything in it, including this repo (`boas/`).

If you already have the folder and just want the latest version of the tools:

```bash
cd ~/claude/the_colonel/boas
git pull
```

---

## Step 5: Install the tool's dependencies

The tools use a few add-on Python packages (for image processing and reading camera raw files). Navigate to the `crop` folder and install them:

```bash
cd ~/claude/the_colonel/boas/crop
pip3 install -r requirements.txt
```

This will download and install several packages — you'll see a bunch of text scroll by, that's normal. It can take a couple of minutes. When it's done, you'll get your prompt back with no red error text.

If you get a permissions error, try:

```bash
pip3 install -r requirements.txt --user
```

---

## Which tool do I use?

Ask yourself how the images were captured:

- **Scanned on a flatbed scanner** (you'd see a scanner-bed brightness gradient and sprocket holes in the raw scan) → use **`detect_rebate.py`**.
- **Photographed with a digital camera on a lightbox, negatives sitting in a physical film holder** (you'll typically have `.NEF`, `.CR2`, `.CR3`, `.ARW`, or `.DNG` raw camera files, with a solid-color divider bar between frames rather than sprocket holes) → use **`detect_holder.py`**.

If you're not sure, open one of the images and look for sprocket holes (little rectangular perforations along the edge of the film) — if you see them, it's a scan. If you instead see a solid painted/plastic divider strip between frames, it's a holder photo.

---

## Running the tools

All commands below assume you're in the `crop` folder:

```bash
cd ~/claude/the_colonel/boas/crop
```

### Crop a single image

```bash
python3 detect_rebate.py /path/to/scan.tif --output /path/to/scan_cropped.tif
```

(swap `detect_rebate.py` for `detect_holder.py` if that's the one you need, and point `/path/to/...` at your actual file)

### Crop a whole folder of images at once (batch mode)

This is what you'll use for a real batch of negatives:

```bash
python3 detect_holder.py /path/to/negatives --batch --output-dir /path/to/negatives_cropped
```

- `/path/to/negatives` is the folder full of your raw/scanned files.
- `/path/to/negatives_cropped` is a **new** folder the tool will create for you — your original files in `/path/to/negatives` are never modified or deleted.

You can also add `--debug` to save small thumbnail images with colored lines showing exactly where it cropped, which is useful for checking the tool's work:

```bash
python3 detect_holder.py /path/to/negatives --batch --output-dir /path/to/negatives_cropped --debug
```

A batch run can take a while — raw camera files in particular take a few seconds each to process, so a folder of a few hundred files could take 20-30 minutes. You can just let Terminal run in the background; it'll print progress as it goes and let you know when it's done.

---

## Understanding the output

After a batch run finishes, your output folder will have:

- One cropped image per input file.
- A log file named something like `crop_log_20260703_221500.jsonl` — this is a plain text file (one entry per line) recording exactly what the tool did to each image: the crop coordinates, a timestamp, and a confidence rating.

The confidence ratings, printed in the terminal and saved in the log, mean:

| Rating | What it means |
|---|---|
| `high` | The tool is confident this crop is correct — expected range, no red flags. |
| `medium` | Probably fine, but the crop landed at the edge of what's typical — worth a quick glance. |
| `low_flagged` | The tool wasn't confident it found the right edges. Worth opening and checking by eye. |
| `flagged_small` | The crop came out much smaller than expected — likely a detection failure. Check this one. |
| `error_unreadable` | The file couldn't be opened at all (corrupt file, wrong format, etc). |

At the end of a batch run, the terminal will print a summary and list every file that got flagged, so you don't have to hunt through the log by hand.

---

## Troubleshooting

**`command not found: python3` or `command not found: git`** — go back to Step 2 or Step 3, the install didn't complete or Terminal needs to be reopened.

**`ModuleNotFoundError: No module named 'cv2'` (or `rawpy`, `numpy`, etc.)** — the dependencies didn't install. Re-run Step 5. Make sure you're running the install command from inside the `crop` folder.

**`Error: <path> not found`** — double check the path you typed. You can drag a folder from Finder directly into the Terminal window after typing a command like `python3 detect_holder.py ` (with a trailing space) and it'll paste in the correct path automatically.

**The tool runs but almost everything gets flagged** — that usually means it's the wrong tool for this batch (see [Which tool do I use?](#which-tool-do-i-use)), or the images are a genuinely unusual capture setup that needs a closer look before running the full batch.

**It's taking forever** — that's expected for raw camera files, especially in large batches. Camera raw decoding is slow no matter what computer you're on. Let it run.

---

## Project structure

```
boas/
├── crop/
│   ├── detect_rebate.py     # crop tool for flatbed scanner captures
│   ├── detect_holder.py     # crop tool for lightbox/holder camera captures
│   ├── requirements.txt
│   ├── LICENSE
│   └── README.md            # this file
├── classify/                # negative vs print classifier (coming)
├── review/                  # manual review UI (coming)
├── logs/                    # batch run logs (gitignored)
└── .gitignore
```

(Note: requirements.txt, LICENSE, and this README currently live under `crop/` rather than the repo root — that's just where the project happened to grow. Worth moving to the root at some point since they cover the whole `boas/` project, not just `crop/`, but not changed here to avoid an unrelated churn commit.)

---

## How the detection works (technical appendix)

Skip this section unless you're curious or debugging. Both tools work at a low resolution (12% of full size) for speed, then scale detected coordinates back up to full resolution.

**`detect_rebate.py`** (flatbed scans): four edges are found independently via brightness-profile analysis.
- Top/left/right: skip the scanner bed (brightness > 160), find the dark valley between the bed/holder and the rebate border (threshold adapts to the actual minimum in each scan), find the rebate brightness bump rising from that valley, and return the trailing edge of the bump as it drops into image content.
- Top (fallback): for bright/outdoor scenes with no dark valley, detect where the steep brightness gradient from the scanner bed flattens into the content plateau.
- Bottom: anchors to content rather than rebate, since sprocket holes between content and rebate can create a false brightness bump. Samples stable content brightness from well inside the frame, then scans downward for where it first rises toward the sprocket zone.

**`detect_holder.py`** (lightbox/camera-in-holder captures): a different problem, because there's no scanner bed or sprocket holes — frames are separated by a solid-color physical divider bar on the film holder. Detection is content-anchored: it samples a baseline brightness from near the center of the frame, then scans outward toward the top and bottom, looking for where brightness *permanently* drops away from that baseline (not just a brief dip) — that's the boundary between content and the divider bar. The search is restricted to the zones where the divider bars were empirically found to sit (roughly 3-38% and 62-97% of frame height), which is what keeps dark clothing or hair in the photo itself from being mistaken for a divider bar. Left/right edge detection in this tool is a simpler first pass and hasn't been validated as thoroughly as top/bottom — treat those with more suspicion if you spot something off.

Both tools flag anything uncertain rather than guessing silently — see [Understanding the output](#understanding-the-output).

---

## Context

This is one part of a larger archival pipeline being built for the Boas collection. The classifier (to route between the negative and print pipelines) and the review UI are next. The full pipeline will handle approximately 50,000 files across both negative and print scans of varying age and condition.

The tool is named after Steve Cropper — essential, precise, never a wasted note.

---

## License

AGPL v3. See [LICENSE](LICENSE).

If you want to use this in a closed or commercial context, get in touch.
