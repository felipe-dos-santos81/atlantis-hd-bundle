"""Room geometry: the guide image, margins, wraparound, the window plan, each
window's composite and mask, the stitch, the wrap seam and the fix-ups.

Pure image maths on Pillow images and numpy arrays; talks to no service and
knows no file layout. Positions are native room columns unless a comment says
4x; SCALE converts.
"""
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

SCALE = 4
WINDOW_WIDTH = 320          # Wt: the widest window, native columns (the spike tunes it)
WINDOW_OVERLAP = 64         # Ov: the least overlap between neighbouring windows
DEDITHER_METHODS = ("palette-smooth", "gaussian")
DEDITHER_METHOD = "palette-smooth"
DEDITHER_THRESHOLD = 64.0   # palette-smooth: the RGB distance of a neighbour still averaged in
MIN_WRAP_PERIOD = 320       # a wraparound repeats at least one screen later ...
MIN_WRAP_SPAN = 64          # ... over at least this many columns ...
WRAP_MATCH = 0.999          # ... in at least this fraction of their pixels


# ---- guide ------------------------------------------------------------------

def indices(indexed):
    """The palette indices of a P-mode image, a (height, width) uint8 array."""
    return np.asarray(indexed, dtype=np.uint8)


def to_rgb(indexed):
    return indexed.convert("RGB")


def dedither(rgb, method=DEDITHER_METHOD, threshold=DEDITHER_THRESHOLD):
    """`rgb` with its dithering smoothed away, at its own size.

    palette-smooth: each pixel becomes the mean of itself and those of its 3x3
    neighbours within `threshold` RGB distance of it, so a checkerboard of near
    colours melts while an edge between distant colours stays sharp.
    gaussian: a Gaussian blur of radius 1. (A 3x3 median is no candidate: on a
    50% checkerboard each pixel is its neighbourhood's majority.)
    """
    if method == "gaussian":
        return rgb.convert("RGB").filter(ImageFilter.GaussianBlur(1))
    if method != "palette-smooth":
        raise ValueError(f"unknown de-dither method {method!r}; choose one of "
                         + ", ".join(DEDITHER_METHODS))
    a = np.asarray(rgb.convert("RGB"), dtype=np.float32)
    h, w, _ = a.shape
    padded = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode="edge")
    total = np.zeros_like(a)
    count = np.zeros((h, w, 1), np.float32)
    for dy in range(3):
        for dx in range(3):
            n = padded[dy:dy + h, dx:dx + w]
            near = np.sqrt(((n - a) ** 2).sum(axis=2, keepdims=True)) <= threshold
            near = near.astype(np.float32)
            total += n * near
            count += near
    return Image.fromarray(np.round(total / count).astype(np.uint8))


@dataclass(frozen=True)
class Guide:
    native: Image.Image     # de-dithered at native size: what the geometry check compares with
    full: Image.Image       # native upscaled 4x (Lanczos): reference, Canny input, img2img start


def build_guide(indexed, method=DEDITHER_METHOD):
    native = dedither(to_rgb(indexed), method)
    full = native.resize((native.width * SCALE, native.height * SCALE),
                         Image.Resampling.LANCZOS)
    return Guide(native, full)


# ---- margins and wraparound -------------------------------------------------

@dataclass(frozen=True)
class Margins:
    left: int               # columns (left, right) or rows (top, bottom) at each edge
    right: int              # that are all one palette index, the same one throughout
    top: int
    bottom: int


def _flat_run(lines):
    """How many leading lines are each one palette index, the same index throughout."""
    count, value = 0, None
    for line in lines:
        if (line != line[0]).any():
            break
        if value is None:
            value = line[0]
        elif line[0] != value:
            break
        count += 1
    return count


def blank_margins(pixels):
    h, w = pixels.shape
    return Margins(left=_flat_run(pixels[:, x] for x in range(w)),
                   right=_flat_run(pixels[:, x] for x in range(w - 1, -1, -1)),
                   top=_flat_run(pixels[y, :] for y in range(h)),
                   bottom=_flat_run(pixels[y, :] for y in range(h - 1, -1, -1)))


@dataclass(frozen=True)
class Wrap:
    period: int             # columns [period, period + span) repeat columns [0, span)
    span: int


def find_wrap(pixels, content_end):
    """The room's wraparound, or None.

    The smallest period from MIN_WRAP_PERIOD at which columns
    [period, content_end) repeat columns [0, content_end - period) in at least
    WRAP_MATCH of their pixels, over at least MIN_WRAP_SPAN columns.
    """
    for period in range(MIN_WRAP_PERIOD, content_end - MIN_WRAP_SPAN + 1):
        span = content_end - period
        if (pixels[:, period:content_end] == pixels[:, :span]).mean() >= WRAP_MATCH:
            return Wrap(period, span)
    return None


# ---- windows ----------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    x0: int                 # native columns [x0, x1), full height
    x1: int

    @property
    def width(self):
        return self.x1 - self.x0


def plan_windows(start, end, width=WINDOW_WIDTH, overlap=WINDOW_OVERLAP):
    """Windows over columns [start, end): at most `width` wide, neighbours
    overlapping by at least `overlap`, each start `start` plus a multiple of 8,
    the first at `start` and the last flush with `end`."""
    span = end - start
    if span <= width:
        return (Window(start, end),)
    n = math.ceil((span - overlap) / (width - overlap))
    while True:
        step = (span - width) / (n - 1)
        starts = [start + 8 * math.floor(i * step / 8) for i in range(n - 1)] + [end - width]
        if all(a + width - b >= overlap for a, b in zip(starts, starts[1:])):
            return tuple(Window(s, s + width) for s in starts)
        n += 1


@dataclass(frozen=True)
class RoomPlan:
    width: int              # the room's native size
    height: int
    margins: Margins
    wrap: Wrap | None
    span: tuple             # (start, end): the native columns the windows cover
    windows: tuple          # of Window, left to right


def plan_room(indexed, width=WINDOW_WIDTH, overlap=WINDOW_OVERLAP):
    """Margins, wraparound and windows of one room.

    The span skips whole-column margins, rounded out to 8 columns so every
    window's 4x width is a multiple of 32; a wraparound room's span ends at its
    period. Raises ValueError for a room with nothing to render.
    """
    pixels = indices(indexed)
    h, w = pixels.shape
    margins = blank_margins(pixels)
    if margins.left >= w:
        raise ValueError("the room is one flat colour: nothing to render (set kind: skip)")
    content_end = w - margins.right
    wrap = find_wrap(pixels, content_end)
    if wrap and wrap.period < width:
        raise ValueError(f"the wraparound period {wrap.period} is narrower than one "
                         f"window ({width}); lower WINDOW_WIDTH")
    start = 8 * (margins.left // 8)
    end = wrap.period if wrap else min(w, 8 * math.ceil(content_end / 8))
    windows = plan_windows(start, end, width, overlap)
    if any(win.width % 8 for win in windows):
        raise ValueError(f"window widths must be multiples of 8 native columns: {windows}")
    return RoomPlan(w, h, margins, wrap, (start, end), windows)


def stitch_from(window, previous):
    """The native column from which `window`'s render replaces the stitch: the
    middle of its overlap with `previous`, or its start when it is the first."""
    return window.x0 if previous is None else window.x0 + (previous.x1 - window.x0) // 2


def stitch_boundaries(plan, width=WINDOW_WIDTH):
    """The 4x columns where the stitched image switches from one render to another."""
    xs = {stitch_from(win, prev) * SCALE for prev, win in zip(plan.windows, plan.windows[1:])}
    if plan.wrap:
        q, period = width // 4, plan.wrap.period
        xs |= {(period - q) * SCALE, q * SCALE, period * SCALE}
    return sorted(xs)
