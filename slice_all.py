#!/usr/bin/env python3
"""Slice every penguin sprite sheet in ./incoming into clean, aligned frame sets.

Frames are auto-detected by connected components -- robust to uneven grids, and it
drops the number labels (too small) and any gridlines (too thin, low fill-ratio). They
are ordered reading-order (row bands top->bottom, then left->right), scaled by ONE
global factor so the standing penguin is TARGET_H tall in every set, bottom-aligned +
horizontally centered on a shared canvas, and flipped to face RIGHT (the daemon flips
back to travel left). Output: frames/<set>/NN.png  (+ preview-<set>.png).

Add a sheet by dropping it in incoming/ and listing it in SHEETS, then re-run.
"""
import os
import sys
import numpy as np
from scipy import ndimage
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
INC = os.path.join(HERE, 'incoming')
FRAMES = os.path.join(HERE, 'frames')
TARGET_H = 90
MIN_BLOB = 2000     # px; penguins are 10k+, number labels are a few hundred
MIN_FILL = 0.15     # size / bbox-area; penguins ~0.4+, gridlines ~0.01

SHEETS = [
    ('tux.png', 'walk'),
    ('tux-roll.png', 'roll'),
    ('tux-somersault.png', 'somersault'),
    ('tux-jumping.png', 'jumping'),
    ('tux-flying.png', 'flying'),
]

def detect_frames(path):
    """Ordered list of tight RGBA crops (one per penguin), facing as in the source."""
    arr = np.asarray(Image.open(path).convert('RGBA'))
    lbl, n = ndimage.label(arr[..., 3] > 20)
    if n == 0:
        return []
    sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
    boxes = ndimage.find_objects(lbl)
    keep = []
    for i in range(1, n + 1):
        sl = boxes[i - 1]
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if sizes[i - 1] >= MIN_BLOB and sizes[i - 1] / (h * w) >= MIN_FILL:
            keep.append(i)
    if not keep:
        return []
    # row bands: whitespace gaps between rows separate them regardless of pose
    pen = np.isin(lbl, keep)
    occ = pen.any(axis=1)
    bands, y, H = [], 0, occ.shape[0]
    while y < H:
        if occ[y]:
            y0 = y
            while y < H and occ[y]:
                y += 1
            bands.append((y0, y))
        else:
            y += 1
    cents = ndimage.center_of_mass(arr[..., 3] > 20, lbl, keep)
    items = []
    for comp, (cy, cx) in zip(keep, cents):
        band = next((bi for bi, (a, b) in enumerate(bands) if a <= cy < b), len(bands))
        items.append((band, cx, comp))
    items.sort(key=lambda t: (t[0], t[1]))
    frames = []
    for _, _, comp in items:
        sl = boxes[comp - 1]
        sub = arr[sl].copy()
        m = lbl[sl] == comp
        sub[~m, 3] = 0
        frames.append(sub)
    return frames

# 1) detect frames for every present sheet
sets = {}
for fn, name in SHEETS:
    p = os.path.join(INC, fn)
    if os.path.exists(p):
        fr = detect_frames(p)
        if fr:
            sets[name] = fr
            print(f'{name:12} {len(fr):2d} frames  <- {fn}')
        else:
            print(f'{name:12} (no frames detected in {fn})')
if not sets:
    print('no sheets found in', INC)
    sys.exit(1)

# 2) one global scale so the tallest frame (a standing penguin) == TARGET_H
gmax_h = max(f.shape[0] for fr in sets.values() for f in fr)
scale = TARGET_H / gmax_h
def sized(f):
    return max(1, round(f.shape[1] * scale)), max(1, round(f.shape[0] * scale))
uni_w = max(sized(f)[0] for fr in sets.values() for f in fr)
uni_h = TARGET_H

# 3) place bottom-aligned + h-centered, flip to face right, save per set
for name, fr in sets.items():
    outdir = os.path.join(FRAMES, name)
    os.makedirs(outdir, exist_ok=True)
    for old in os.listdir(outdir):
        os.remove(os.path.join(outdir, old))
    imgs = []
    for i, f in enumerate(fr, start=1):
        sw, sh = sized(f)
        img = Image.fromarray(f, 'RGBA').resize((sw, sh), Image.LANCZOS)
        canvas = Image.new('RGBA', (uni_w, uni_h), (0, 0, 0, 0))
        canvas.alpha_composite(img, ((uni_w - sw) // 2, uni_h - sh))
        canvas = canvas.transpose(Image.FLIP_LEFT_RIGHT)
        canvas.save(os.path.join(outdir, f'{i:02d}.png'))
        imgs.append(canvas)
    pad = 6
    strip = Image.new('RGBA', (len(imgs) * (uni_w + pad) + pad, uni_h + 2 * pad), (120, 124, 130, 255))
    for i, im in enumerate(imgs):
        strip.alpha_composite(im, (pad + i * (uni_w + pad), pad))
    strip.save(os.path.join(HERE, f'preview-{name}.png'))

# tidy leftovers from the earlier flat layout
for old in os.listdir(FRAMES):
    if old.startswith('right-') and old.endswith('.png'):
        os.remove(os.path.join(FRAMES, old))

print(f'unified canvas {uni_w}x{uni_h}, scale {scale:.3f}, sets:',
      {k: len(v) for k, v in sets.items()})
