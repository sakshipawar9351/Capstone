"""
Generate the Colab training notebook.

Written as a generator rather than committed as raw .ipynb JSON because a
notebook is mostly source code wrapped in unreadable escaping — every review,
diff and fix would go through a JSON string literal. This file is the source;
``train_detector_colab.ipynb`` is the build product.

Run:  python notebooks/build_colab_notebook.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "train_detector_colab.ipynb"

MD_INTRO = r"""
# LunarSerpent — crater & boulder detector

Trains the detector that Steps 6–8 fuse into the traverse cost surface.

## What is wrong with the existing model, and what this changes

The model already in `models/yolo11/crater_boulder_segmentation` reports:

| metric | box | mask |
|---|---|---|
| precision | 0.834 | 0.819 |
| **recall** | **0.291** | **0.267** |
| mAP50 | 0.328 | 0.298 |

Precision is fine. **Recall 0.29 means it misses 71% of what is there**, and for
hazard detection that is the wrong way round: a false positive costs a detour,
a false negative can cost the vehicle. Two causes, both fixable:

1. **It saw 243 images.** The Drive holds ~19,000 labelled crater images and
   6,208 labelled boulder frames. They were never used.
2. **It trained for 10 epochs**, with the loss still falling on the last one.

## The one design change

The old model was **segmentation**, which needs polygon labels — and only those
243 images have them. This trains **detection** instead, because the ~19,000
crater images carry bounding boxes, not polygons.

Nothing is lost. Fusing a hazard into the cost surface needs its *position and
size*; a polygon would be discarded on the way in. Trading an outline we do not
use for eighty times the training data is the single largest lever on recall.

## Honesty about the training data

The boulder labels come from the Artificial Lunar Landscape set, which is
**rendered, not photographed**. A model trained on renders and applied to real
Chandrayaan-2 OHRC imagery has a domain gap, and this notebook measures it on
real images rather than assuming it away. Crater labels are real imagery.

Report both numbers separately in the paper. A synthetic-only validation score
is not evidence about the Moon.
"""

CODE_GPU = r"""
# What GPU did Colab give us? Runtime > Change runtime type > T4 GPU if this
# says None. Training on CPU is not viable at this scale.
import subprocess
print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                      "--format=csv,noheader"],
                     capture_output=True, text=True).stdout or "NO GPU")
import torch
print("torch", torch.__version__, "| cuda", torch.cuda.is_available())
"""

CODE_INSTALL = r"""
%pip install -q ultralytics
from ultralytics import YOLO
import ultralytics; print("ultralytics", ultralytics.__version__)
"""

CODE_MOUNT = r"""
from google.colab import drive
drive.mount('/content/drive')

from pathlib import Path
DRIVE = Path('/content/drive/MyDrive')
SRC   = DRIVE / 'LunarNavigator_capstone_project_temp' / 'lunar-navigator'
RAW   = SRC / 'data' / 'raw'

# The dataset is BUILT ON LOCAL DISK, not on Drive. Drive is a network mount:
# writing tens of thousands of small files to it takes hours and reading them
# each epoch is slower still. Only the finished weights go back to Drive.
WORK  = Path('/content/lunar_ds')
assert SRC.exists(), f"not found: {SRC}"
print("source :", SRC)
print("work   :", WORK)
"""

CODE_INVENTORY = r"""
KAGGLE = RAW / 'kaggle_craters' / 'more-pics-dataset' / 'more-pics-dataset'
ART    = RAW / 'artificial_lunar'

for split in ('train', 'valid', 'test'):
    n_i = len(list((KAGGLE / split / 'images').glob('*'))) if (KAGGLE/split/'images').exists() else 0
    n_l = len(list((KAGGLE / split / 'labels').glob('*.txt'))) if (KAGGLE/split/'labels').exists() else 0
    print(f"craters  {split:<6} {n_i:>6} images  {n_l:>6} labels")

import csv
box_csv = ART / 'bounding_boxes.csv'
rows = list(csv.DictReader(open(box_csv, newline='', encoding='utf-8-sig')))
frames = sorted({int(r['Frame']) for r in rows})
print(f"\nboulders        {len(rows):>6} boxes   {len(frames):>6} frames")
print(f"real lunar images for the domain-gap check: "
      f"{len(list((ART/'real_moon_images').glob('*')))}")
"""

CODE_BUILD = r"""
# Build one YOLO detection dataset: class 0 = crater, class 1 = boulder.
#
# Craters copy straight across — the Roboflow labels are already YOLO format
# with class 0. Boulders are converted from pixel corners to normalised
# centre/width/height, which is what the format wants.
import shutil, csv, random
from PIL import Image

random.seed(20260822)          # a fixed split, so runs are comparable

for split in ('train', 'val', 'test'):
    (WORK / 'images' / split).mkdir(parents=True, exist_ok=True)
    (WORK / 'labels' / split).mkdir(parents=True, exist_ok=True)

# ---- craters -------------------------------------------------------------
copied = {'train': 0, 'val': 0, 'test': 0}
for src_split, dst_split in (('train', 'train'), ('valid', 'val'), ('test', 'test')):
    img_dir, lbl_dir = KAGGLE / src_split / 'images', KAGGLE / src_split / 'labels'
    if not img_dir.exists():
        continue
    for img in img_dir.iterdir():
        lbl = lbl_dir / (img.stem + '.txt')
        if not lbl.exists():
            continue                     # an image with no label teaches nothing
        shutil.copy(img, WORK / 'images' / dst_split / f'cr_{img.name}')
        shutil.copy(lbl, WORK / 'labels' / dst_split / f'cr_{img.stem}.txt')
        copied[dst_split] += 1
print("craters copied:", copied)

# ---- boulders ------------------------------------------------------------
by_frame = {}
for r in csv.DictReader(open(ART / 'bounding_boxes.csv', newline='', encoding='utf-8-sig')):
    by_frame.setdefault(int(r['Frame']), []).append(r)

frames = sorted(by_frame)
random.shuffle(frames)
n = len(frames)
cut1, cut2 = int(n * 0.8), int(n * 0.9)
assign = {f: ('train' if i < cut1 else 'val' if i < cut2 else 'test')
          for i, f in enumerate(frames)}

# `render` is the photorealistic variant; `clean` is the same scene without
# the camera effects. Training on render is the closer match to real imagery.
IMG_ROOT, PREFIX = ART / 'images' / 'render', 'render'
made = {'train': 0, 'val': 0, 'test': 0}
skipped = 0
for f in frames:
    src = IMG_ROOT / f'{PREFIX}{f:04d}.png'
    if not src.exists():
        skipped += 1
        continue
    try:
        W, H = Image.open(src).size
    except Exception:
        skipped += 1
        continue
    lines = []
    for r in by_frame[f]:
        x, y = float(r['TopLeftCornerX']), float(r['TopLeftCornerY'])
        w, h = float(r['Length']), float(r['Height'])
        cx, cy = (x + w / 2) / W, (y + h / 2) / H
        nw, nh = w / W, h / H
        if not (0 < nw <= 1 and 0 < nh <= 1 and 0 <= cx <= 1 and 0 <= cy <= 1):
            continue                     # a box outside the frame is a bad label
        lines.append(f"1 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
    if not lines:
        continue
    sp = assign[f]
    shutil.copy(src, WORK / 'images' / sp / f'bl_{src.name}')
    (WORK / 'labels' / sp / f'bl_{src.stem}.txt').write_text("\n".join(lines))
    made[sp] += 1
print("boulders written:", made, "| skipped:", skipped)

for sp in ('train', 'val', 'test'):
    print(f"  {sp:<6} {len(list((WORK/'images'/sp).glob('*'))):>6} images")
"""

CODE_YAML = r"""
# Written line by line rather than as one block string: this file is itself
# generated, and nesting triple quotes inside a generator is how a notebook
# ends up shipping a syntax error.
yaml_lines = [
    f"path: {WORK}",
    "train: images/train",
    "val: images/val",
    "test: images/test",
    "nc: 2",
    "names:",
    "  0: crater",
    "  1: boulder",
]
(WORK / 'dataset.yaml').write_text(chr(10).join(yaml_lines) + chr(10))
print(chr(10).join(yaml_lines))
"""

CODE_TRAIN = r"""
# 120 epochs, not 10. The previous run's mAP50 was still climbing on its final
# epoch (0.302 -> 0.328), which means it was stopped mid-improvement rather
# than converged. `patience` will stop it early if it genuinely plateaus.
#
# If Colab disconnects, re-run this cell with resume=True and it continues from
# the last checkpoint rather than starting again.
from ultralytics import YOLO

model = YOLO('yolo11m.pt')          # detection, not -seg: see the intro
results = model.train(
    data=str(WORK / 'dataset.yaml'),
    epochs=120,
    patience=25,
    imgsz=640,
    batch=16,                        # T4 (16 GB) fits this at 640; drop to 8 on OOM
    device=0,
    project='/content/runs',
    name='crater_boulder_det',
    exist_ok=True,
    resume=False,
    # Augmentation the terrain actually justifies: craters and boulders have no
    # preferred orientation seen from orbit, so free rotation and flips are
    # physically honest rather than noise. Illumination varies hugely with
    # solar incidence, so brightness/contrast jitter is realistic too.
    degrees=180.0, fliplr=0.5, flipud=0.5,
    hsv_v=0.4, hsv_s=0.3, scale=0.5, translate=0.1,
    mosaic=1.0, close_mosaic=15,
    seed=20260822,
)
"""

CODE_VALIDATE = r"""
# Validate, and read recall first. It is the metric this project is short on
# and the one that matters for safety.
best = YOLO('/content/runs/crater_boulder_det/weights/best.pt')
m = best.val(data=str(WORK / 'dataset.yaml'), split='test', device=0)

print(f"\n{'':<12}{'precision':>11}{'recall':>9}{'mAP50':>9}{'mAP50-95':>10}")
print("-" * 51)
print(f"{'overall':<12}{m.box.mp:>11.3f}{m.box.mr:>9.3f}"
      f"{m.box.map50:>9.3f}{m.box.map:>10.3f}")
for i, name in best.names.items():
    try:
        p, r, ap50, ap = m.box.class_result(i)
        print(f"{name:<12}{p:>11.3f}{r:>9.3f}{ap50:>9.3f}{ap:>10.3f}")
    except Exception:
        pass

print("\nprevious model, for comparison:")
print(f"{'old':<12}{0.834:>11.3f}{0.291:>9.3f}{0.328:>9.3f}{0.227:>10.3f}")
"""

CODE_THRESHOLD = r"""
# Where to set the confidence threshold.
#
# The default 0.25 is tuned for balanced benchmarks. This is a hazard detector:
# a false positive costs a detour of a few hundred metres, a false negative can
# end a mission. That asymmetry justifies accepting lower precision to buy
# recall -- but the choice has to be stated in the paper, not made silently.
import numpy as np
rows = []
for conf in (0.05, 0.10, 0.15, 0.20, 0.25, 0.35, 0.50):
    r = best.val(data=str(WORK / 'dataset.yaml'), split='test',
                 conf=conf, device=0, verbose=False)
    rows.append((conf, r.box.mp, r.box.mr, r.box.map50))

print(f"{'conf':>6}{'precision':>11}{'recall':>9}{'mAP50':>9}   note")
print("-" * 52)
for c, p, rc, m50 in rows:
    note = "<- default" if abs(c - 0.25) < 1e-9 else ""
    print(f"{c:>6.2f}{p:>11.3f}{rc:>9.3f}{m50:>9.3f}   {note}")
print("\nPick for recall, and say so explicitly when you report it.")
"""

CODE_DOMAIN = r"""
# The domain-gap check that decides whether the boulder numbers mean anything.
#
# Boulder labels are rendered images. These are real photographs. There are no
# labels here, so this cannot produce a score -- it shows whether the detector
# fires sensibly on real terrain at all. A model that lights up on renders and
# goes blank on real imagery has learned the renderer, not the Moon.
from PIL import Image
import matplotlib.pyplot as plt

reals = sorted((ART / 'real_moon_images').glob('*'))[:6]
if reals:
    preds = best.predict([str(p) for p in reals], conf=0.15, verbose=False)
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    for ax, pr, p in zip(axes.ravel(), preds, reals):
        ax.imshow(pr.plot()[:, :, ::-1]); ax.axis('off')
        ax.set_title(f"{p.name}  |  {len(pr.boxes)} detections", fontsize=9)
    plt.tight_layout(); plt.show()
    tot = sum(len(pr.boxes) for pr in preds)
    print(f"{tot} detections across {len(reals)} real images")
    print("Judge these by eye. Plausible detections on real terrain are the "
          "minimum bar before any boulder result goes in the paper.")
else:
    print("no real_moon_images found")
"""

CODE_SAVE = r"""
# Only the weights and the metrics go back to Drive -- not the dataset.
import shutil, json, datetime
DEST = DRIVE / 'LunarSerpent_models' / 'crater_boulder_det'
DEST.mkdir(parents=True, exist_ok=True)

shutil.copy('/content/runs/crater_boulder_det/weights/best.pt', DEST / 'best.pt')
for extra in ('results.csv', 'args.yaml'):
    src = Path('/content/runs/crater_boulder_det') / extra
    if src.exists():
        shutil.copy(src, DEST / extra)

meta = {
    'trained_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    'architecture': 'yolo11m (detection)',
    'classes': {0: 'crater', 1: 'boulder'},
    'epochs_requested': 120,
    'imgsz': 640,
    'train_images': len(list((WORK / 'images' / 'train').glob('*'))),
    'val_images': len(list((WORK / 'images' / 'val').glob('*'))),
    'test_images': len(list((WORK / 'images' / 'test').glob('*'))),
    'crater_labels': 'real lunar imagery (Roboflow more-pics-dataset)',
    'boulder_labels': 'SYNTHETIC - Artificial Lunar Landscape renders',
    'caveat': ('Boulder training data is rendered, not photographed. Validate '
               'on Chandrayaan-2 OHRC before publishing any boulder result.'),
    'metrics_test': {'precision': float(m.box.mp), 'recall': float(m.box.mr),
                     'mAP50': float(m.box.map50), 'mAP50_95': float(m.box.map)},
    'supersedes': {'model': 'yolo11m-seg 10 epochs / 243 images',
                   'recall': 0.291, 'mAP50': 0.328},
}
(DEST / 'model_card.json').write_text(json.dumps(meta, indent=2))
print("saved to", DEST)
for f in sorted(DEST.iterdir()):
    print(f"  {f.name:<20} {f.stat().st_size/1e6:.1f} MB")
"""

MD_IMPORT = r"""
## Bringing `best.pt` back into LunarSerpent

The weights land in `MyDrive/LunarSerpent_models/crater_boulder_det/`, which is
already visible on this machine as `G:`. Copy them into the project:

```
mkdir -p D:\Lunar_Serpent\data\models
copy "G:\My Drive\LunarSerpent_models\crater_boulder_det\best.pt"        D:\Lunar_Serpent\data\models\
copy "G:\My Drive\LunarSerpent_models\crater_boulder_det\model_card.json" D:\Lunar_Serpent\data\models\
```

Keep `model_card.json` with the weights. It records what the model was trained
on, what it scored, and that the boulder half is synthetic — all of which has
to travel with any number the detector produces.

### Then, on this side

1. **Detect** over a region, at the posting the baseline is pinned to (29.6 m
   for craters from the DEM; OHRC imagery for boulders).
2. **Fuse** detections into the cost surface — craters as cells, boulders as
   point hazards, because a 3 m boulder is 1 % of a 29.6 m cell and can never
   be a DEM feature.
3. **Re-run the five frozen cases** in `docs/results/baseline_terrain_only.json`
   and report the delta.

Step 3 only means something because the baseline was recorded first, at this
same posting, with the conditions hashed. Do not change the pinned source
between the control and the treatment — the resolution effect is 2.7–5.5× at
the Apollo sites and would swamp anything the detector does.
"""


def md(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": src.strip("\n").splitlines(keepends=True)}


def code(src: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": src.strip("\n").splitlines(keepends=True)}


def main() -> None:
    cells = [
        md(MD_INTRO),
        md("## 1 · Runtime"), code(CODE_GPU), code(CODE_INSTALL),
        md("## 2 · Data"), code(CODE_MOUNT), code(CODE_INVENTORY),
        md("## 3 · Build the dataset\n\n"
           "243 images becomes roughly 19,000. This is the change that "
           "addresses recall."),
        code(CODE_BUILD), code(CODE_YAML),
        md("## 4 · Train"), code(CODE_TRAIN),
        md("## 5 · Validate — read recall first"), code(CODE_VALIDATE),
        md("## 6 · Choose the operating point"), code(CODE_THRESHOLD),
        md("## 7 · Does it work on real imagery?"), code(CODE_DOMAIN),
        md("## 8 · Save the weights"), code(CODE_SAVE),
        md(MD_IMPORT),
    ]
    nb = {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4, "nbformat_minor": 0,
    }
    OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB, {len(cells)} cells)")


if __name__ == "__main__":
    main()
