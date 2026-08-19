#!/usr/bin/env python3
"""A penguin crosses the bottom of the 4K screen (HDMI-0) now and then. He walks
most of the time; once in a while a crossing throws in ONE surprise trick, chosen at
random -- roll, somersault, jump, or a flap of flight -- woven into the same pass at a
steady pace. Ground tricks stay on the floor; the jump arcs; the flight lifts off.

Transparent, click-through, always-on-top overlay for XFCE/X11. Frame sets live in
./frames/<name>/NN.png (produced by slice_all.py); 'walk' is the base, every other
folder is a trick.

Run:            python3 penguin-walk.py
One-off demo:   python3 penguin-walk.py --once   (forces a trick so you can see it)
"""
import gi, os, sys, glob, math, random, fcntl
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
import cairo

HERE = os.path.dirname(os.path.abspath(__file__))


def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


# --frames <dir> runs the same engine on any creature (default: tux in ./frames).
# A relative dir resolves under HERE; the lock is derived so creatures don't collide.
_frames = _arg('--frames', 'frames')
FRAMES_DIR = _frames if os.path.isabs(_frames) else os.path.join(HERE, _frames)
_base = os.path.basename(FRAMES_DIR.rstrip('/'))
LOCK_NAME = '.lock' if _base == 'frames' else '.lock-' + _base

# ---- tunables -------------------------------------------------------------
MIN_GAP     = 15 * 60     # min seconds between crossings
MAX_GAP     = 45 * 60     # max seconds between crossings
FIRST_DELAY = 8           # a hello-crossing this many seconds after start
SPEED       = int(_arg('--speed', 200))     # px/s horizontal; --speed <n> overrides per creature
FRAME_MS    = int(_arg('--frame-ms', 95))   # ms per animation frame; --frame-ms <n> overrides
FLY         = int(_arg('--fly', 0))         # >0: cruise ~this many px above the floor (a flyer)
FLOCK       = int(_arg('--flock', 1))       # >1: cross as a flock of up to N, each its own speed/altitude
TICK_MS     = 20          # movement tick
MARGIN      = 4           # px above the work-area bottom
MONITOR     = 'largest'   # 'largest' = your 4K; or an exact geometry like '3840x2160'
TRICK_PROB  = 0.35        # chance a given crossing includes one surprise trick
# per-set behaviour: lift profile + how many times to loop its frames per trick
META = {
    'walk':       {'lift': None,  'loops': 1},
    'roll':       {'lift': None,  'loops': 1},
    'somersault': {'lift': None,  'loops': 1},
    'jumping':    {'lift': 'arc', 'height': 130, 'loops': 1},   # parabola hop
    'flying':     {'lift': 'fly', 'height': 175, 'loops': 3},   # take off, glide, land
}
DEFAULT_META = {'lift': None, 'loops': 1}
# ---------------------------------------------------------------------------

ONCE = '--once' in sys.argv
MAX_LIFT = max([m.get('height', 0) for m in META.values()] + [0])
MAX_ALT = int(FLY * 1.35)   # tallest random cruise altitude -- sizes the overlay strip


def load_sets():
    sets = {}
    for name in sorted(os.listdir(FRAMES_DIR)):
        d = os.path.join(FRAMES_DIR, name)
        if not os.path.isdir(d):
            continue
        paths = sorted(glob.glob(os.path.join(d, '*.png')))
        if not paths:
            continue
        right = [GdkPixbuf.Pixbuf.new_from_file(p) for p in paths]
        sets[name] = {'right': right, 'left': [pb.flip(True) for pb in right]}
    return sets


def pick_monitor(disp):
    want = None
    if 'x' in MONITOR:
        try:
            want = tuple(int(v) for v in MONITOR.lower().split('x'))
        except Exception:
            want = None
    best, best_area = None, -1
    for i in range(disp.get_n_monitors()):
        g = disp.get_monitor(i).get_geometry()
        if want and (g.width, g.height) == want:
            return disp.get_monitor(i)
        if g.width * g.height > best_area:
            best, best_area = disp.get_monitor(i), g.width * g.height
    return best


def lift_at(kind, h, t):
    """Vertical offset (px above the floor) at progress t in [0,1]."""
    if not kind:
        return 0
    if kind == 'arc':                       # a clean hop, peak at mid-jump
        return h * math.sin(math.pi * max(0.0, min(1.0, t)))
    if kind == 'fly':                       # rise, cruise, descend
        up, dn = 0.20, 0.80
        if t < up:
            s = t / up
        elif t > dn:
            s = (1 - t) / (1 - dn)
        else:
            s = 1.0
        s = s * s * (3 - 2 * s)             # smoothstep the ramps
        return h * s
    return 0


class Penguin(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.sets = load_sets()
        if not self.sets:
            print('No frame sets in', FRAMES_DIR, '-- run slice_all.py first.')
            sys.exit(1)
        self.base = 'walk' if 'walk' in self.sets else sorted(self.sets)[0]
        self.tricks = [n for n in sorted(self.sets) if n != self.base]
        self.fw = self.sets[self.base]['right'][0].get_width()
        self.ph = self.sets[self.base]['right'][0].get_height()
        self.strip_h = self.ph + (MAX_ALT if FLY else MAX_LIFT) + MARGIN

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

        self.walking = False
        self.seg = self.sets[self.base]['right']
        self.seg_len = len(self.seg)
        self.seg_i = 0
        self.seg_lift = None
        self.seg_h = 0
        self.x = 0.0
        self.dir = 1
        self.flock = []           # non-empty -> flock mode (list of independent flyers)
        self._frame_timer = None

        self.compute_geometry()
        self.set_default_size(self.strip_w, self.strip_h)
        self.realize()
        self.move(self.strip_x, self.strip_y)
        self.click_through()

        GLib.timeout_add_seconds(1 if ONCE else FIRST_DELAY, self.start_crossing)

    def compute_geometry(self):
        wa = pick_monitor(Gdk.Display.get_default()).get_workarea()
        self.strip_w = wa.width
        self.strip_x = wa.x
        self.strip_y = wa.y + wa.height - self.strip_h

    def click_through(self):
        try:
            empty = cairo.Region()
            self.input_shape_combine_region(empty)
            w = self.get_window()
            if w:
                w.input_shape_combine_region(empty, 0, 0)
        except Exception as e:
            print('click-through not set:', e)

    # ---- flow: mostly walk; maybe one random trick this crossing -----------
    def next_segment_name(self):
        if (self._trick_at is not None and not self._did_trick
                and self._walk_run >= self._trick_at):
            self._did_trick = True
            return self._trick_name
        self._walk_run += 1
        return self.base

    def start_segment(self):
        name = self.next_segment_name()
        key = 'right' if self.dir > 0 else 'left'
        self.seg = self.sets[name][key]
        m = META.get(name, DEFAULT_META)
        self.seg_lift = m.get('lift')
        self.seg_h = m.get('height', 0)
        self.seg_len = len(self.seg) * m.get('loops', 1)
        self.seg_i = 0

    def setup_single(self):
        self.flock = []
        self.dir = random.choice((1, -1))
        self._alt = random.randint(int(FLY * 0.6), MAX_ALT) if FLY else 0   # this flight's height
        self._walk_run = 0
        self._did_trick = False
        if self.tricks and (ONCE or random.random() < TRICK_PROB):
            self._trick_at = random.randint(1, 3)
            self._trick_name = random.choice(self.tricks)
        else:
            self._trick_at = None
            self._trick_name = None
        self.x = -self.fw if self.dir > 0 else self.strip_w
        self.start_segment()

    def setup_flock(self):
        # A flock crosses together (one shared direction) but each bird gets its own speed,
        # altitude, wing phase, and a staggered entry so they string out instead of overlapping.
        d = random.choice((1, -1))
        seg = self.sets[self.base]['right' if d > 0 else 'left']
        self.flock = []
        for _ in range(random.randint(2, FLOCK)):
            lead = random.uniform(0, 900)          # stagger entry over ~900px -> a loose flock, not a column
            self.flock.append({
                'x': (-self.fw - lead) if d > 0 else (self.strip_w + lead),
                'dir': d,
                'speed': SPEED * random.uniform(0.65, 1.35),
                'alt': random.randint(int(FLY * 0.5), MAX_ALT) if FLY else 0,
                'seg': seg,
                'seg_i': random.randint(0, len(seg) - 1),
            })

    def start_crossing(self):
        self.compute_geometry()
        self.resize(self.strip_w, self.strip_h)
        self.move(self.strip_x, self.strip_y)
        if FLOCK > 1:
            self.setup_flock()
        else:
            self.setup_single()
        self.walking = True
        self.show_all()
        self.click_through()
        self._frame_timer = GLib.timeout_add(FRAME_MS, self.on_frame)
        GLib.timeout_add(TICK_MS, self.tick)
        return False

    def on_frame(self):
        if not self.walking:
            return False
        if self.flock:
            for f in self.flock:
                f['seg_i'] += 1
            return True
        self.seg_i += 1
        if self.seg_i >= self.seg_len:
            self.start_segment()
        return True

    def tick(self):
        if not self.walking:
            return False
        if self.flock:
            for f in self.flock:
                f['x'] += (f['speed'] * TICK_MS / 1000.0) * f['dir']
            self.flock = [f for f in self.flock if not (
                (f['dir'] > 0 and f['x'] > self.strip_w) or (f['dir'] < 0 and f['x'] < -self.fw))]
            if not self.flock:
                self.end_crossing()
                return False
            self.queue_draw()
            return True
        self.x += (SPEED * TICK_MS / 1000.0) * self.dir
        if (self.dir > 0 and self.x > self.strip_w) or (self.dir < 0 and self.x < -self.fw):
            self.end_crossing()
            return False
        self.queue_draw()
        return True

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        if not self.walking:
            return False
        cr.set_operator(cairo.OPERATOR_OVER)
        if self.flock:
            for f in self.flock:
                pb = f['seg'][f['seg_i'] % len(f['seg'])]
                y = self.strip_h - pb.get_height() - f['alt']
                Gdk.cairo_set_source_pixbuf(cr, pb, f['x'], y)
                cr.paint()
            return False
        pb = self.seg[self.seg_i % len(self.seg)]
        if FLY:
            lift = self._alt                       # cruise this crossing's altitude, flapping
        else:
            t = self.seg_i / max(1, self.seg_len - 1)
            lift = lift_at(self.seg_lift, self.seg_h, t)
        y = self.strip_h - pb.get_height() - lift
        Gdk.cairo_set_source_pixbuf(cr, pb, self.x, y)
        cr.paint()
        return False

    def end_crossing(self):
        self.walking = False
        if self._frame_timer:
            GLib.source_remove(self._frame_timer)
            self._frame_timer = None
        self.hide()
        if ONCE:
            Gtk.main_quit()
            return
        GLib.timeout_add_seconds(random.randint(MIN_GAP, MAX_GAP), self.start_crossing)


def main():
    if not ONCE:
        lock = open(os.path.join(HERE, LOCK_NAME), 'w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('penguin-walk already running')
            sys.exit(0)
        globals()['_lock'] = lock
    Penguin()
    Gtk.main()


if __name__ == '__main__':
    main()
