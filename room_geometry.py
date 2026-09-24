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
