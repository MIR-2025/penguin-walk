#!/usr/bin/env python3
"""Build a walking (or hopping, or flying) creature for penguin-walk from one or more
green-screen / keyed grid sheets, size-matched across sheets.

Why not slice_all.py? That one blob-detects tux across sheets rendered at the SAME source
resolution and scales them by one shared factor. Image models hand back sheets at DIFFERENT
resolutions, so a single scale would size them differently. Here each sheet gets its own
scale, chosen so every set's MEDIAN silhouette area matches the walk's -- pose-invariant,
so a somersault and a stride come out the same size.

Vertical alignment is per creature:
  'bottom' (default) -- every frame's lowest pixel sits on the floor (right for walkers).
  'ground'           -- frames pin to a SHARED ground line (the lowest-reaching frame), so
                        airborne frames float up -- a real hop/bounce (kangaroo).
  'air'              -- centre each frame on its silhouette centroid, so a flapping body
                        stays put (and rises a touch on the downstroke, like real flight).
                        Fly it up in the air with the daemon's --fly <height>.

Keying is per cell and hole-safe: only background green (touching the cell border) is
removed, so green SPILL on the body isn't punched out -- it's neutralized to grey. Then
saturated semi-transparent fringe (red/yellow/green key spill) is dropped, one edge shaved.

'walk' is the base (defines target size + is what the daemon travels on). Every other set
becomes a trick woven into a crossing. Sources face RIGHT (daemon flips for left travel).

Add a creature by dropping its sheets in incoming/ and adding a CREATURES entry.
Usage:  python3 slice_creature.py [name ...]   (no name = build them all)
Output: frames-<name>/<set>/NN.png  (+ preview-<name>-<set>.png)
"""
import os
import sys
import numpy as np
from scipy import ndimage
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
INC = os.path.join(HERE, 'incoming')

# name -> { target_h, align?, sheets: [(file, rows, cols, set-name), ...] }
CREATURES = {
    'elephant': {
        'target_h': 150,
        'sheets': [
            ('elephant.png',        4, 4, 'walk'),
            ('elephant-tricks.png', 4, 4, 'tumble'),
        ],
    },
    'gorilla': {
        'target_h': 150,
        'sheets': [
            ('gorilla.png',        4, 4, 'walk'),
            ('gorilla-tricks.png', 4, 4, 'tumble'),
        ],
    },
    'kangaroo': {
        'target_h': 150,
        'align': 'ground',                             # a hopper -- keep the bounce
        'sheets': [('kangaroo.png', 4, 4, 'walk')],
    },
    'lion': {
        'target_h': 150,
        'sheets': [('lion.png', 4, 4, 'walk')],
    },
    'trex': {
        'target_h': 170,                               # a big lizard -- stands taller than the mammals
        'flip': True,                                  # source faces LEFT (unlike the mammal sheets)
        'sheets': [('trex.png', 3, 4, 'walk')],        # 3x4 = 12-frame running cycle
    },
    'eagle': {
        'target_h': 150,
        'align': 'air',                                # a flyer -- run the daemon with --fly
        'sheets': [('eagle.png', 4, 4, 'walk')],       # flapping flight cycle
    },
    'pterodactyl': {
        'target_h': 150,
        'align': 'air',                                # a flyer -- run the daemon with --fly
        'flip': True,                                  # source faces LEFT
        'sheets': [('pterodactyl.png', 3, 4, 'walk')], # 3x4 = 12-frame flap/glide cycle
    },
}


def key_cell(cell):
    """Remove the background from ONE raw RGBA cell without holing the creature."""
    a = cell.copy()
    R, G, B = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    green = (G > 100) & (G - R > 25) & (G - B > 25)
    if green.any():
        lbl, _ = ndimage.label(green)
        border = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
        border.discard(0)
        if border:
            a[..., 3][np.isin(lbl, list(border))] = 0
    spill = (a[..., 3] > 200) & (G > R) & (G > B) & ((G - (R + B) // 2) > 15)
    a[..., 1][spill] = ((R[spill] + B[spill]) // 2).astype(a.dtype)
    sat = np.maximum(np.maximum(R, G), B) - np.minimum(np.minimum(R, G), B)
    a[..., 3][(sat > 100) & (a[..., 3] < 210)] = 0
    solid = ndimage.binary_erosion(a[..., 3] > 40, iterations=1)
    a[..., 3][~solid] = 0
    return a


def cells(path, rows, cols):
    """Split into an even grid; key + tight-crop each non-empty cell. Returns (crop,
    bottom_in_cell) -- the cell row where content ends, used by ground alignment."""
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
            crop = k[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
            out.append((crop, int(ys.max())))
    return out


def area(f):
    return int((f[..., 3] > 20).sum())


def build(name, cfg):
    target_h = cfg['target_h']
    align = cfg.get('align', 'bottom')
    flip = cfg.get('flip', False)                      # mirror to face right (daemon travels 'right' set forward)
    sets = {}
    for fn, rows, cols, sname in cfg['sheets']:
        p = os.path.join(INC, fn)
        if not os.path.exists(p):
            print('  missing', p)
            continue
        fr = cells(p, rows, cols)
        if fr:
            sets[sname] = fr
            print('  %-8s %2d frames <- %s' % (sname, len(fr), fn))
    if 'walk' not in sets:
        print('  %s: no walk set, skipping' % name)
        return

    def crops(s):
        return [c for c, _ in sets[s]]

    # walk defines the size; every other set scaled so its median silhouette area matches
    s_walk = target_h / max(c.shape[0] for c in crops('walk'))
    a_target = float(np.median([area(c) * s_walk * s_walk for c in crops('walk')]))
    scales = {'walk': s_walk}
    for sname in sets:
        if sname != 'walk':
            m = float(np.median([area(c) for c in crops(sname)])) or 1.0
            scales[sname] = (a_target / m) ** 0.5

    def scaled(c, sname):
        s = scales[sname]
        return max(1, round(c.shape[1] * s)), max(1, round(c.shape[0] * s))

    # per-frame placement (top-left x,y) on a shared uni_w x uni_h canvas
    place = {}
    if align == 'air':
        hh = hw = 0.0
        cent = {}
        for sname, fr in sets.items():
            s = scales[sname]
            cent[sname] = []
            for c, _ in fr:
                ys, xs = np.where(c[..., 3] > 20)
                cx, cy = float(xs.mean()) * s, float(ys.mean()) * s
                sw, sh = scaled(c, sname)
                cent[sname].append((cx, cy))
                hh = max(hh, cy, sh - cy)
                hw = max(hw, cx, sw - cx)
        uni_w, uni_h = int(np.ceil(2 * hw)), int(np.ceil(2 * hh))
        for sname, lst in cent.items():
            place[sname] = [(round(uni_w / 2 - cx), round(uni_h / 2 - cy)) for cx, cy in lst]
    else:
        lifts = {}
        for sname, fr in sets.items():
            if align == 'ground':
                ground = max(b for _, b in fr)
                lifts[sname] = [ground - b for _, b in fr]
            else:
                lifts[sname] = [0] * len(fr)
        uni_h = max(scaled(c, s)[1] + int(round(lifts[s][i] * scales[s]))
                    for s, fr in sets.items() for i, (c, _) in enumerate(fr))
        uni_w = max(scaled(c, s)[0] for s, fr in sets.items() for c, _ in fr)
        for sname, fr in sets.items():
            lst = []
            for i, (c, _) in enumerate(fr):
                sw, sh = scaled(c, sname)
                lst.append(((uni_w - sw) // 2, uni_h - sh - int(round(lifts[sname][i] * scales[sname]))))
            place[sname] = lst

    for sname, fr in sets.items():
        outdir = os.path.join(HERE, 'frames-' + name, sname)
        os.makedirs(outdir, exist_ok=True)
        for old in os.listdir(outdir):
            os.remove(os.path.join(outdir, old))
        imgs = []
        for i, (c, _) in enumerate(fr):
            sw, sh = scaled(c, sname)
            img = Image.fromarray(c, 'RGBA').resize((sw, sh), Image.LANCZOS)
            canvas = Image.new('RGBA', (uni_w, uni_h), (0, 0, 0, 0))
            canvas.alpha_composite(img, place[sname][i])
            if flip:
                canvas = canvas.transpose(Image.FLIP_LEFT_RIGHT)
            canvas.save(os.path.join(outdir, '%02d.png' % (i + 1)))
            imgs.append(canvas)
        pad = 6
        strip = Image.new('RGBA', (len(imgs) * (uni_w + pad) + pad, uni_h + 2 * pad), (120, 124, 130, 255))
        for i, im in enumerate(imgs):
            strip.alpha_composite(im, (pad + i * (uni_w + pad), pad))
        strip.save(os.path.join(HERE, 'preview-%s-%s.png' % (name, sname)))
    print('  %s: canvas %dx%d, align %s, scales %s' % (name, uni_w, uni_h, align, {k: round(v, 3) for k, v in scales.items()}))


if __name__ == '__main__':
    wanted = sys.argv[1:] or list(CREATURES)
    for nm in wanted:
        if nm not in CREATURES:
            print('unknown creature:', nm, '(have:', ', '.join(CREATURES), ')')
            continue
        print(nm + ':')
        build(nm, CREATURES[nm])
