# penguin-fly

A variant of penguin-walk: instead of waddling along the floor, **Tux flies around the
whole screen** for ~15 seconds once an hour, then vanishes until the next hour. Each
flight enters at a random point and traces a different randomized curve, fading in and
out. Transparent, click-through, always-on-top overlay -- targets the largest monitor.

It reuses penguin-walk's flying sprite sheet (`../incoming/tux-flying.png`), re-sliced
here at high resolution so the airborne Tux reads big and crisp on a large screen.

## Run

Requirements: Python 3, PyGObject (GTK 3), pycairo, Pillow, NumPy, SciPy, and an X11
session with a compositor on (for transparency).

```sh
python3 penguin-fly.py
```

The flying frames are committed, so it runs as-is. To regenerate them (e.g. after
changing `TARGET_H`):

```sh
python3 fly_slice.py     # slices ../incoming/tux-flying.png -> frames/flying/
```

Start at login: copy a `.desktop` entry into `~/.config/autostart/` pointing
`Exec=` at this `penguin-fly.py`. Stop with `pkill -f penguin-fly.py`.

## Tunables (top of `penguin-fly.py`)

- `INTERVAL` -- seconds between flights (default hourly), `DURATION` -- length of each flight
- `FLY_SCALE` -- size multiplier
- `FX_RANGE` / `FY_RANGE` -- how loopy the path is (higher = more squiggle)
- `AX_FRAC` / `AY_FRAC` -- how much of the screen a flight covers
- `CX_FRAC` / `CY_FRAC` -- where the path re-centers (widen for more extreme entry spots)
