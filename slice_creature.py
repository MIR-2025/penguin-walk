#!/usr/bin/env python3
"""Build a walking creature for penguin-walk from one or more green-screen / keyed grid
sheets, size-matched across sheets.

Why not slice_all.py? That one blob-detects tux across sheets rendered at the SAME source
resolution and scales them by one shared factor. Image models hand back sheets at DIFFERENT
resolutions (the elephant's walk sheet is a 4x4 at 256px-tall cells; a trick sheet may be a
4x4 too but drawn larger), so a single scale would size them differently. Here each sheet
gets its own scale, chosen so every set's MEDIAN silhouette area matches the walk's --
pose-invariant, so a somersault and a stride come out the same size. All frames land
bottom-aligned + horizontally centered on ONE shared canvas tall enough for the biggest pose.

Keying is per cell and hole-safe: only background green (the green region touching the
cell border) is removed, so green SPILL on the creature's body isn't punched out -- it's
neutralized to grey instead. Then saturated semi-transparent fringe (red/yellow key spill)
is dropped and one edge pixel shaved.

'walk' is the base (defines the target size: its tallest frame == TARGET_H). Every other
set becomes a trick the daemon can weave into a crossing. Sources are assumed to already
face RIGHT (the daemon flips for left travel).

Output: frames-<name>/<set>/NN.png  (+ preview-<name>-<set>.png).  Add a creature by
copying the CREATURE block. Re-run after dropping sheets in incoming/.
"""
import os
import sys
import numpy as np
from scipy import ndimage
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
INC = os.path.join(HERE, 'incoming')

# name, target standing height (px), and its sheets: (file, rows, cols, set-name)
CREATURE = {
    'name': 'elephant',
    'target_h': 150,
    'sheets': [
        ('elephant.png',        4, 4, 'walk'),     # green-screen walk cycle (16 frames)
        ('elephant-tricks.png', 4, 4, 'tumble'),   # leap / somersault / roll / prance
    ],
}


def key_cell(cell):
    """Remove the background from ONE raw RGBA cell without holing the creature.
    Background green = the green region touching the cell border; interior green spill is
    kept and de-greened to grey. Then saturated semi-transparent fringe is dropped and a
    one-pixel halo shaved."""
    a = cell.copy()
    R, G, B = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    green = (G > 100) & (G - R > 25) & (G - B > 25)
    if green.any():
        lbl, _ = ndimage.label(green)
        border = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
        border.discard(0)
        if border:
            a[..., 3][np.isin(lbl, list(border))] = 0          # drop background green only
    # neutralize green spill left ON the body (opaque, green-dominant) -> grey
    spill = (a[..., 3] > 200) & (G > R) & (G > B) & ((G - (R + B) // 2) > 15)
    a[..., 1][spill] = ((R[spill] + B[spill]) // 2).astype(a.dtype)
    # drop saturated semi-transparent fringe (red/yellow key spill)
    sat = np.maximum(np.maximum(R, G), B) - np.minimum(np.minimum(R, G), B)
    a[..., 3][(sat > 100) & (a[..., 3] < 210)] = 0
    solid = ndimage.binary_erosion(a[..., 3] > 40, iterations=1)
    a[..., 3][~solid] = 0
    return a


def cells(path, rows, cols):
    """Split into an even rows x cols grid; key + tight-crop each non-empty cell."""
    a = np.asarray(Image.open(path).convert('RGBA'))
    H, W = a.shape[0], a.shape[1]
    ch, cw = H // rows, W // cols
    out = []
    for r in range(rows):
        for c in range(cols):
            k = key_cell(a[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw])
            ys, xs = np.where(k[..., 3] > 20)
            if len(xs) < 100:
                continue
            out.append(k[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy())
    return out


def area(f):
    return int((f[..., 3] > 20).sum())


NAME = CREATURE['name']
TARGET_H = CREATURE['target_h']

sets = {}
for fn, rows, cols, sname in CREATURE['sheets']:
    p = os.path.join(INC, fn)
    if not os.path.exists(p):
        print('missing', p)
        continue
    fr = cells(p, rows, cols)
    if fr:
        sets[sname] = fr
        print('%-8s %2d frames <- %s' % (sname, len(fr), fn))

if 'walk' not in sets:
    print('need a walk set')
    sys.exit(1)

# walk defines the size; every other set is scaled so its median silhouette area matches
s_walk = TARGET_H / max(f.shape[0] for f in sets['walk'])
A_target = float(np.median([area(f) * s_walk * s_walk for f in sets['walk']]))
scales = {'walk': s_walk}
for name, fr in sets.items():
    if name == 'walk':
        continue
    m = float(np.median([area(f) for f in fr])) or 1.0
    scales[name] = (A_target / m) ** 0.5

uni_h = max(int(round(f.shape[0] * scales[n])) for n, fr in sets.items() for f in fr)
uni_w = max(int(round(f.shape[1] * scales[n])) for n, fr in sets.items() for f in fr)

for name, fr in sets.items():
    s = scales[name]
    outdir = os.path.join(HERE, 'frames-' + NAME, name)
    os.makedirs(outdir, exist_ok=True)
    for old in os.listdir(outdir):
        os.remove(os.path.join(outdir, old))
    imgs = []
    for i, f in enumerate(fr, start=1):
        sw = max(1, round(f.shape[1] * s))
        sh = max(1, round(f.shape[0] * s))
        img = Image.fromarray(f, 'RGBA').resize((sw, sh), Image.LANCZOS)
        canvas = Image.new('RGBA', (uni_w, uni_h), (0, 0, 0, 0))
        canvas.alpha_composite(img, ((uni_w - sw) // 2, uni_h - sh))   # bottom-align, center
        canvas.save(os.path.join(outdir, '%02d.png' % i))
        imgs.append(canvas)
    pad = 6
    strip = Image.new('RGBA', (len(imgs) * (uni_w + pad) + pad, uni_h + 2 * pad), (120, 124, 130, 255))
    for i, im in enumerate(imgs):
        strip.alpha_composite(im, (pad + i * (uni_w + pad), pad))
    strip.save(os.path.join(HERE, 'preview-%s-%s.png' % (NAME, name)))

print('%s: canvas %dx%d, scales %s' % (NAME, uni_w, uni_h, {k: round(v, 3) for k, v in scales.items()}))
