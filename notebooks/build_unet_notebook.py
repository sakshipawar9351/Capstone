"""
Generate the Colab notebook that trains the crater U-Net.

Written as a generator for the same reason as the detector notebook: a .ipynb
is source code wrapped in JSON escaping, and every later fix would have to go
through a string literal. This file is the source.

Run:  python notebooks/build_unet_notebook.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "train_crater_unet_colab.ipynb"

MD_INTRO = r"""
# LunarSerpent — crater rim segmentation

Trains the detector that supplies craters the Robbins catalogue does not
contain, in the band from roughly 333 m to 1 km.

## What this predicts, and why it is a rim rather than a disc

The network outputs one number per pixel: the probability that the pixel lies
on a crater **rim**. Not a filled circle — craters nest constantly, a small one
inside a large one, and filled discs merge into a blob from which neither is
recoverable. Thin rings stay separate. The rim is also the feature actually
visible from orbit: the lit-and-shadowed edge where the wall catches the sun.

Circles are recovered afterwards by sliding ring templates across the predicted
map, which is where centre and radius come from.

## Why the training data looks the way it does

Two floors had to be made to coincide.

A convolutional network needs roughly **16 pixels** across an object to find it
reliably. Robbins (2019) states his own catalogue's completeness: *"41.8% of the
body is complete for D ≥ 1 km, 93.7% for D ≥ 1.5 km"*, and an independent check
against the catalogue's own power law finds a **14.6 % shortfall at 1 km**.

Label down to 1 km and roughly one in seven of the 1 km craters sitting in a
training image is unlabelled — so the network is taught those are background,
immediately before being asked to find exactly that kind of object.

So the tiles are cut at **125 m/px** with a **2 km label floor**, where a 2 km
crater spans exactly 16 pixels. Label floor and detection floor coincide, and
every crater the network can see is labelled.

## What it is for

Trained at 125 m/px, run at 20.82 m/px. The network never learns metres — only
what a crater looks like at a pixel scale — so the same 16 pixels becomes 333 m
when the imagery is sharper. Nothing is extrapolated; the ruler changes.
"""

CODE_GPU = r"""
import subprocess
print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                      "--format=csv,noheader"],
                     capture_output=True, text=True).stdout.strip() or "NO GPU")
import torch
print("torch", torch.__version__, "| cuda", torch.cuda.is_available())
# Runtime > Change runtime type > T4 GPU if this says NO GPU.
"""

CODE_INSTALL = r"""
%pip install -q segmentation-models-pytorch albumentations
import segmentation_models_pytorch as smp
print("smp", smp.__version__)
"""

CODE_MOUNT = r"""
from google.colab import drive
drive.mount('/content/drive')

import shutil, time
from pathlib import Path

DRIVE = Path('/content/drive/MyDrive')
SRC   = DRIVE / 'LunarSerpent_data' / 'craters_125mpp'      # upload here
WORK  = Path('/content/craters')

# Copied to local disk before training. Drive is a network mount: reading a few
# thousand images from it every epoch is dominated by latency, not compute, and
# an epoch that should take two minutes takes twenty.
assert SRC.exists(), f"not found: {SRC} - upload the dataset folder there"
if not WORK.exists():
    t0 = time.time()
    shutil.copytree(SRC, WORK)
    print(f"copied to local disk in {time.time()-t0:.0f}s")

import json
man = json.loads((WORK / 'manifest.json').read_text())
print(f"\n{man['tiles_written']} tiles, {man['craters_total']:,} craters")
print(f"splits: {man['split_counts']}")
print(f"labels: {man['labels']}")
"""

CODE_DATA = r"""
import numpy as np, torch, random
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset, DataLoader
import albumentations as A

CROP = 256          # the size the published work uses; 640 tiles are cropped to it
SEED = 20260828
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)

# Augmentation the physics justifies, and nothing else.
#
# Craters seen from orbit have no preferred orientation, so free rotation and
# both flips are honest rather than noise. Solar incidence varies enormously
# across the Moon, so brightness and contrast jitter reproduces a real source of
# variation. Shear and perspective are NOT applied: they imply a camera geometry
# an orthomosaic does not have, and would teach the network that craters are
# ellipses - which the ring-template extraction downstream would then reject.
TRAIN_AUG = A.Compose([
    A.RandomCrop(CROP, CROP),
    A.RandomRotate90(p=1.0),
    A.HorizontalFlip(p=0.5),
    A.VerticalFlip(p=0.5),
    A.RandomBrightnessContrast(0.25, 0.25, p=0.7),
])
EVAL_AUG = A.Compose([A.CenterCrop(CROP, CROP)])


class CraterTiles(Dataset):
    def __init__(self, root: Path, split: str, aug, repeats: int = 1):
        self.img = sorted((root / split / 'images').glob('*.png'))
        self.msk = root / split / 'masks'
        self.aug = aug
        self.repeats = repeats

    def __len__(self):
        return len(self.img) * self.repeats

    def __getitem__(self, i):
        p = self.img[i % len(self.img)]
        x = np.array(Image.open(p).convert('L'))
        y = np.array(Image.open(self.msk / p.name).convert('L'))
        out = self.aug(image=x, mask=y)
        x, y = out['image'], out['mask']
        # Three identical channels so an ImageNet-pretrained encoder applies.
        # Its early filters are edges and gradients, which transfer to grey
        # planetary imagery even though nothing in ImageNet is a crater.
        x = np.repeat(x[None].astype(np.float32) / 255.0, 3, axis=0)
        y = (y > 127).astype(np.float32)[None]
        return torch.from_numpy(x), torch.from_numpy(y)


# Several crops per tile per epoch: one 256 window sees a sixth of a 640 tile,
# so a single crop would waste most of the labelled ground.
train_ds = CraterTiles(WORK, 'train', TRAIN_AUG, repeats=6)
val_ds   = CraterTiles(WORK, 'val',   EVAL_AUG)
test_ds  = CraterTiles(WORK, 'test',  EVAL_AUG)

train_dl = DataLoader(train_ds, batch_size=16, shuffle=True, num_workers=2,
                      pin_memory=True, drop_last=True)
val_dl   = DataLoader(val_ds,   batch_size=16, num_workers=2)
test_dl  = DataLoader(test_ds,  batch_size=16, num_workers=2)
print(f"train {len(train_ds)} crops from {len(train_ds.img)} tiles")
print(f"val   {len(val_ds)}   test {len(test_ds)}")

x, y = train_ds[0]
print(f"batch shapes  image {tuple(x.shape)}  mask {tuple(y.shape)}  "
      f"rim fraction {float(y.mean()):.4f}")
"""

CODE_LOOK = r"""
import matplotlib.pyplot as plt
fig, ax = plt.subplots(2, 4, figsize=(16, 8))
for k in range(4):
    x, y = train_ds[k * 37]
    ax[0, k].imshow(x[0], cmap='gray'); ax[0, k].set_title('image'); ax[0, k].axis('off')
    ov = np.stack([x[0]]*3, -1).copy()
    ov[y[0] > 0.5] = [1, 0.25, 0]
    ax[1, k].imshow(ov); ax[1, k].set_title('rim mask'); ax[1, k].axis('off')
plt.tight_layout(); plt.show()
print("Rings should sit on visible crater rims. If they do not, stop here -")
print("a misaligned mask trains the network to find the wrong thing.")
"""

CODE_MODEL = r"""
import segmentation_models_pytorch as smp
import torch.nn as nn

dev = 'cuda' if torch.cuda.is_available() else 'cpu'
model = smp.Unet('resnet34', encoder_weights='imagenet',
                 in_channels=3, classes=1).to(dev)

# Dice, not plain cross-entropy.
#
# Rim pixels are about 5 % of an image, so a network that predicts "no rim"
# everywhere scores 95 % under pixel accuracy and under unweighted BCE. Dice
# measures overlap of the positive class alone and cannot be won that way. BCE
# is kept at a small weight because Dice alone gives weak gradients early on,
# when the prediction overlaps almost nothing.
dice = smp.losses.DiceLoss(mode='binary')
bce  = nn.BCEWithLogitsLoss()

def criterion(pred, true):
    return dice(pred, true) + 0.5 * bce(pred, true)

opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
print(f"{sum(p.numel() for p in model.parameters())/1e6:.1f} M parameters on {dev}")
"""

CODE_TRAIN = r"""
import time, json
from pathlib import Path

CKPT = DRIVE / 'LunarSerpent_models' / 'crater_unet'
CKPT.mkdir(parents=True, exist_ok=True)
EPOCHS = 40

@torch.no_grad()
def evaluate(loader):
    model.eval()
    inter = union = tp = fp = fn = 0.0
    for x, y in loader:
        x, y = x.to(dev), y.to(dev)
        p = (torch.sigmoid(model(x)) > 0.5).float()
        inter += (p * y).sum().item()
        union += ((p + y) > 0).float().sum().item()
        tp += (p * y).sum().item()
        fp += (p * (1 - y)).sum().item()
        fn += ((1 - p) * y).sum().item()
    iou  = inter / max(union, 1)
    prec = tp / max(tp + fp, 1)
    rec  = tp / max(tp + fn, 1)
    f1   = 2 * prec * rec / max(prec + rec, 1e-9)
    return {'iou': iou, 'precision': prec, 'recall': rec, 'f1': f1}

# Resume if a run was interrupted. Colab disconnects, and losing four hours to
# a dropped tab is avoidable with three lines.
start, best = 0, 0.0
if (CKPT / 'last.pt').exists():
    st = torch.load(CKPT / 'last.pt', map_location=dev)
    model.load_state_dict(st['model']); opt.load_state_dict(st['opt'])
    start, best = st['epoch'] + 1, st['best']
    print(f"resuming from epoch {start}, best F1 so far {best:.4f}")

hist = []
for ep in range(start, EPOCHS):
    model.train(); t0 = time.time(); run = 0.0
    for x, y in train_dl:
        x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
        opt.zero_grad()
        loss = criterion(model(x), y)
        loss.backward(); opt.step()
        run += loss.item()
    m = evaluate(val_dl)
    m.update(epoch=ep, loss=run / max(len(train_dl), 1),
             seconds=round(time.time() - t0, 1))
    hist.append(m)
    print(f"  epoch {ep:>2}  loss {m['loss']:.4f}  IoU {m['iou']:.3f}  "
          f"P {m['precision']:.3f}  R {m['recall']:.3f}  F1 {m['f1']:.3f}  "
          f"({m['seconds']:.0f}s)")

    torch.save({'model': model.state_dict(), 'opt': opt.state_dict(),
                'epoch': ep, 'best': best}, CKPT / 'last.pt')
    if m['f1'] > best:
        best = m['f1']
        torch.save(model.state_dict(), CKPT / 'best.pt')
        (CKPT / 'history.json').write_text(json.dumps(hist, indent=1))
        print(f"           saved best (F1 {best:.4f})")
print(f"\nbest validation F1: {best:.4f}")
"""

CODE_TEST = r"""
# The held-out longitude bands. This is the only number that means anything:
# the validation bands were used to pick the checkpoint, so they are no longer
# unseen ground.
model.load_state_dict(torch.load(CKPT / 'best.pt', map_location=dev))
m = evaluate(test_dl)
print(f"{'':<14}{'IoU':>8}{'precision':>11}{'recall':>9}{'F1':>8}")
print("-" * 50)
print(f"{'held-out band':<14}{m['iou']:>8.3f}{m['precision']:>11.3f}"
      f"{m['recall']:>9.3f}{m['f1']:>8.3f}")
print("\nThese are pixel-level rim metrics, not crater counts. Crater-level")
print("precision and recall come after circle extraction, back in the project -")
print("a network can score well on rim pixels and still merge two craters into")
print("one circle, which only the extraction step can reveal.")
"""

CODE_SAVE = r"""
import json, datetime
meta = {
  'trained_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
  'architecture': 'U-Net, resnet34 encoder, ImageNet initialisation',
  'predicts': 'per-pixel probability of crater rim',
  'input': f'{CROP}x{CROP} crops of 640x640 Kaguya tiles at 125 m/px',
  'imagery': man['imagery'],
  'labels': man['labels'],
  'label_floor_km': man['min_diameter_km'],
  'gsd_m': man['gsd_m'],
  'tiles': man['tiles_written'],
  'craters': man['craters_total'],
  'split': f"longitude bands of {man['band_deg']} degrees, blocked",
  'epochs': EPOCHS,
  'seed': SEED,
  'val_best_f1': best,
  'test': m,
  'intended_use': ('Run at finer sampling than it was trained on. 16 px is '
                   '2 km at 125 m/px and 333 m at 20.82 m/px; the network '
                   'learns pixel scale, not metres.'),
  'caveats': [
      'Image-based, so illumination-sensitive. Every detection must be '
      'confirmed against the DEM using Pike (1977) before it is catalogued.',
      'Scale transfer from 125 m/px to 20.82 m/px is physically justified '
      '(craters 333 m - 15 km are all simple and self-similar) but is an '
      'assumption until measured against independent labels.',
      'Trained only between 70 degrees north and south.',
  ],
}
(CKPT / 'model_card.json').write_text(json.dumps(meta, indent=1))
print("saved to", CKPT)
for f in sorted(CKPT.iterdir()):
    print(f"  {f.name:<18} {f.stat().st_size/1e6:.1f} MB")
"""

MD_BACK = r"""
## Bringing it back

The weights land in `MyDrive/LunarSerpent_models/crater_unet/`, visible on the
project machine as `G:`. Copy them across:

```
mkdir D:\Lunar_Serpent\data\models
copy "G:\My Drive\LunarSerpent_models\crater_unet\best.pt"         D:\Lunar_Serpent\data\models\
copy "G:\My Drive\LunarSerpent_models\crater_unet\model_card.json" D:\Lunar_Serpent\data\models\
```

Keep the model card with the weights. It records the sampling the network was
trained at, which is the one number the inference side must not get wrong.

### What happens next, back in the project

1. **Circle extraction** — slide ring templates across the predicted rim map to
   recover centre and radius. Pixel-level F1 above is not crater-level accuracy;
   only this step reveals whether two craters were merged into one.
2. **Multi-scale inference** — run at z=7…10 and merge, so the full size range
   is covered rather than one octave of it.
3. **DEM confirmation** — accept a candidate only where the topography shows a
   depression consistent with Pike (1977). This is what rejects bright ejecta
   and makes the output a measurement rather than a classification.
4. **Fusion** — detections into the cost surface, then re-run the five frozen
   control cases and report the delta.

Step 4 only means something because the baseline was recorded first, at a
posting that must not change between control and treatment.
"""


def md(src): return {"cell_type": "markdown", "metadata": {},
                     "source": src.strip("\n").splitlines(keepends=True)}


def code(src): return {"cell_type": "code", "metadata": {}, "execution_count": None,
                       "outputs": [], "source": src.strip("\n").splitlines(keepends=True)}


def main() -> None:
    cells = [
        md(MD_INTRO),
        md("## 1 · Runtime"), code(CODE_GPU), code(CODE_INSTALL),
        md("## 2 · Data"), code(CODE_MOUNT), code(CODE_DATA),
        md("## 3 · Look at it before training on it"), code(CODE_LOOK),
        md("## 4 · Model and loss"), code(CODE_MODEL),
        md("## 5 · Train"), code(CODE_TRAIN),
        md("## 6 · Held-out bands"), code(CODE_TEST),
        md("## 7 · Save"), code(CODE_SAVE),
        md(MD_BACK),
    ]
    nb = {"cells": cells,
          "metadata": {"accelerator": "GPU",
                       "colab": {"provenance": [], "gpuType": "T4"},
                       "kernelspec": {"display_name": "Python 3", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 0}
    OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB, {len(cells)} cells)")


if __name__ == "__main__":
    main()
