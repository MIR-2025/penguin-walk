#!/usr/bin/env python3
"""Personal, unpublished variant of penguin-walk: Tux FLIES AROUND the whole 65"
(the 4K HDMI-0) for ~15s once an hour, then vanishes until the next hour.

Free 2D roam on a smooth Lissajous path (faces his direction of travel, flaps, fades
in/out) -- full-screen transparent click-through overlay. Reuses the already-sliced
flying frames from ~/penguin-walk/frames/flying. XFCE/X11.

Run: python3 penguin-fly.py
Stop: pkill -f penguin-fly.py
"""
import gi, os, sys, glob, math, random, fcntl
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
import cairo

HERE = os.path.dirname(os.path.abspath(__file__))
FLY_FRAMES = os.path.join(HERE, 'frames', 'flying')  # big, crisp -- run fly_slice.py

# ---- tunables -------------------------------------------------------------
INTERVAL    = 3600        # seconds between flights (every hour)
FIRST_DELAY = 10          # a hello-flight this many seconds after start
DURATION    = 15.0        # seconds per flight
FLY_SCALE   = 1.0         # frames are already sliced big/crisp; bump for even bigger
FLAP_MS     = 90          # ms per wing-flap frame
TICK_MS     = 20          # redraw tick
FADE_IN     = 1.2         # seconds to fade in
FADE_OUT    = 2.0         # seconds to fade out
MONITOR     = 'largest'   # 'largest' = the 4K/65"; or an exact 'WxH'
# path shape is randomized per flight (see roll_path); these are the ranges it draws from
FX_RANGE    = (1.0, 2.6)    # horizontal loops across the flight
FY_RANGE    = (1.0, 2.6)    # vertical loops
AX_FRAC     = (0.34, 0.46)  # horizontal reach (fraction of screen)
AY_FRAC     = (0.30, 0.44)  # vertical reach
CX_FRAC     = (0.42, 0.58)  # path center x -> varies where he enters / roams
CY_FRAC     = (0.40, 0.60)  # path center y
# ---------------------------------------------------------------------------


def load_frames():
    paths = sorted(glob.glob(os.path.join(FLY_FRAMES, '*.png')))
    if not paths:
        print('No flying frames at', FLY_FRAMES, '-- run fly_slice.py first.')
        sys.exit(1)
    right = []
    for p in paths:
        pb = GdkPixbuf.Pixbuf.new_from_file(p)
        if FLY_SCALE != 1.0:
            pb = pb.scale_simple(max(1, round(pb.get_width() * FLY_SCALE)),
                                 max(1, round(pb.get_height() * FLY_SCALE)),
                                 GdkPixbuf.InterpType.HYPER)
        right.append(pb)
    return right, [pb.flip(True) for pb in right]


def pick_monitor(disp):
    want = None
    if 'x' in MONITOR:
        try:
            want = tuple(int(v) for v in MONITOR.lower().split('x'))
        except Exception:
            want = None
    best, area = None, -1
    for i in range(disp.get_n_monitors()):
        g = disp.get_monitor(i).get_geometry()
        if want and (g.width, g.height) == want:
            return disp.get_monitor(i)
        if g.width * g.height > area:
            best, area = disp.get_monitor(i), g.width * g.height
    return best


class Flyer(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.right, self.left = load_frames()
        self.fw = max(pb.get_width() for pb in self.right)
        self.fh = max(pb.get_height() for pb in self.right)

        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.set_app_paintable(True)
        self.stick()
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        else:
            print('No RGBA visual -- enable the XFCE compositor for transparency.')

        self.connect('draw', self.on_draw)
        self.connect('destroy', Gtk.main_quit)

        self.flying = False
        self.elapsed = 0.0
        self.compute_geometry()
        self.set_default_size(self.mw, self.mh)
        self.realize()
        self.move(self.mx, self.my)
        self.click_through()

        GLib.timeout_add_seconds(FIRST_DELAY, self.start_flight)

    def compute_geometry(self):
        g = pick_monitor(Gdk.Display.get_default()).get_geometry()
        self.mx, self.my, self.mw, self.mh = g.x, g.y, g.width, g.height

    def click_through(self):
        try:
            empty = cairo.Region()
            self.input_shape_combine_region(empty)
            w = self.get_window()
            if w:
                w.input_shape_combine_region(empty, 0, 0)
        except Exception as e:
            print('click-through not set:', e)

    def roll_path(self):
        """Pick a fresh random entry point, curve shape, and direction for one flight."""
        self.fx = random.uniform(*FX_RANGE)
        self.fy = random.uniform(*FY_RANGE)
        if abs(self.fx - self.fy) < 0.35:      # near-equal freqs -> a boring near-line
            self.fy += 0.7
        self.ax = self.mw * random.uniform(*AX_FRAC)
        self.ay = self.mh * random.uniform(*AY_FRAC)
        self.cx = self.mw * random.uniform(*CX_FRAC)
        self.cy = self.mh * random.uniform(*CY_FRAC)
        self.px = random.uniform(0, 2 * math.pi)   # phase -> random entry x + path
        self.py = random.uniform(0, 2 * math.pi)   # phase -> random entry y + path

    def pos(self, u):
        """Path point (window-local) at progress u in [0,1], from this flight's params."""
        x = self.cx + self.ax * math.sin(2 * math.pi * self.fx * u + self.px)
        y = self.cy + self.ay * math.sin(2 * math.pi * self.fy * u + self.py)
        vx = math.cos(2 * math.pi * self.fx * u + self.px)   # sign = horizontal travel dir
        return x, y, vx

    def start_flight(self):
        self.compute_geometry()
        self.resize(self.mw, self.mh)
        self.move(self.mx, self.my)
        self.roll_path()          # fresh random entry point + flight path each time
        self.elapsed = 0.0
        self.flying = True
        self.show_all()
        self.click_through()
        GLib.timeout_add(TICK_MS, self.tick)
        return False

    def tick(self):
        if not self.flying:
            return False
        self.elapsed += TICK_MS / 1000.0
        if self.elapsed >= DURATION:
            self.flying = False
            self.hide()
            GLib.timeout_add_seconds(INTERVAL, self.start_flight)
            return False
        self.queue_draw()
        return True

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        if not self.flying:
            return False
        u = self.elapsed / DURATION
        x, y, vx = self.pos(u)
        frames = self.right if vx >= 0 else self.left
        idx = int(self.elapsed * 1000 / FLAP_MS) % len(frames)
        pb = frames[idx]
        # fade in/out envelope so he doesn't pop in and out
        a = 1.0
        if self.elapsed < FADE_IN:
            a = self.elapsed / FADE_IN
        elif self.elapsed > DURATION - FADE_OUT:
            a = max(0.0, (DURATION - self.elapsed) / FADE_OUT)
        cr.set_operator(cairo.OPERATOR_OVER)
        Gdk.cairo_set_source_pixbuf(cr, pb, x - pb.get_width() / 2, y - pb.get_height() / 2)
        cr.paint_with_alpha(a)
        return False


def main():
    lock = open(os.path.join(HERE, '.fly.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('penguin-fly already running')
        sys.exit(0)
    globals()['_lock'] = lock
    Flyer()
    Gtk.main()


if __name__ == '__main__':
    main()
