#!/usr/bin/env python3
"""Slice tux-flying.png into BIG, crisp, centered frames just for penguin-fly.

The shared penguin-walk frames are downscaled small (standing penguin = 90px), which
looks soft when blown up. Here we slice the flying sheet straight from the source at a
large target so the fly-around Tux is big AND sharp. Output: ~/penguin-fly/frames/flying/NN.png
(penguin centered in a shared canvas, facing right; the daemon flips for leftward flight).
"""
import os
import numpy as np
from scipy import ndimage
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'incoming', 'tux-flying.png')   # penguin-walk's flying sheet
OUT = os.path.join(HERE, 'frames', 'flying')
TARGET_H = 210          # tallest flying frame, in px -- bump for even bigger
MIN_BLOB = 2000
MIN_FILL = 0.15

os.makedirs(OUT, exist_ok=True)

def detect_frames(path):
    arr = np.asarray(Image.open(path).convert('RGBA'))
    lbl, n = ndimage.label(arr[..., 3] > 20)
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

frames = detect_frames(SRC)
scale = TARGET_H / max(f.shape[0] for f in frames)
def sized(f):
    return max(1, round(f.shape[1] * scale)), max(1, round(f.shape[0] * scale))
uni_w = max(sized(f)[0] for f in frames)
uni_h = max(sized(f)[1] for f in frames)

for old in os.listdir(OUT):
    os.remove(os.path.join(OUT, old))
for i, f in enumerate(frames, start=1):
    sw, sh = sized(f)
    img = Image.fromarray(f, 'RGBA').resize((sw, sh), Image.LANCZOS)
    canvas = Image.new('RGBA', (uni_w, uni_h), (0, 0, 0, 0))
    canvas.alpha_composite(img, ((uni_w - sw) // 2, (uni_h - sh) // 2))   # centered
    canvas = canvas.transpose(Image.FLIP_LEFT_RIGHT)                      # face right
    canvas.save(os.path.join(OUT, f'{i:02d}.png'))
print(f'wrote {len(frames)} flying frames, canvas {uni_w}x{uni_h} (scale {scale:.2f}) -> {OUT}')
