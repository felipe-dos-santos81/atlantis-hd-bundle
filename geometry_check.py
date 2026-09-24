"""The deterministic geometry check of a 4x render against its native source.

The re-import-safe gate: a render whose content slid, or that lost the
source's edges, is not promoted. Numpy maths on Pillow images; knows no files,
rooms or audit tree. Windows are native (x0, x1) column pairs; seam boundaries
are 4x columns.

Each measure has one job. Phase correlation finds a slid room or window (a
2-pixel shift reads as 2.0). Edge agreement finds lost or moved structure,
over the room and within each window: on the real art a 2-pixel shift still
keeps most edges within 1 pixel, so it is no shift detector.

Edge agreement has hysteresis. A source edge is strong above EDGE_THRESHOLD;
it is kept when the render has an edge above RENDER_EDGE_THRESHOLD within
1 pixel. Resampling to 4x and box-filtering back is not the identity, and it
weakens marginal edges (room 95's sea) under a single shared threshold.
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image

MAX_SHIFT = 0.5             # native px, whole room and per window
EDGE_THRESHOLD = 80.0       # Sobel magnitude on 0-255 luminance of a strong source edge
# A render edge above this keeps a source edge. Room 95's own guide agrees 0.27 at 80 and
# 0.96 at 70; 60 keeps every real room's own guide at 1.0 without blinding the gate.
RENDER_EDGE_THRESHOLD = 60.0
MIN_EDGE_AGREEMENT = 0.80   # the least fraction of source edges the render keeps within 1 px
MIN_WINDOW_EDGES = 100      # a window with fewer strong source edge pixels is too sparse to judge
SEAM_WARN = 3.0             # the step across a stitch boundary against the local column steps
SEAM_BAND = 64              # 4x columns either side of a boundary that set the local step
SEAM_CAP = 999.0            # a step where there is no local variation at all reads as this


@dataclass(frozen=True)
class GeometryResult:
    shift: tuple            # (dx, dy) of the whole room, native px
    window_shifts: tuple    # ((dx, dy), ...) per window
    edge_agreement: float
    window_agreements: tuple  # per window; 1.0 for a window too sparse to judge
    seam_ratios: tuple      # per stitch boundary; warnings only
    issues: tuple           # why the render fails; empty when it passes

    @property
    def passed(self):
        return not self.issues

    def as_dict(self):
        return {"passed": self.passed, "shift": list(self.shift),
                "window_shifts": [list(s) for s in self.window_shifts],
                "edge_agreement": self.edge_agreement,
                "window_agreements": list(self.window_agreements),
                "seam_ratios": list(self.seam_ratios), "issues": list(self.issues)}


def luminance(image):
    return np.asarray(image.convert("L"), dtype=np.float64)


def phase_shift(a, b):
    """(dx, dy) by which luminance array `b` is displaced from `a`, sub-pixel.

    Phase correlation under a Hann window, refined by a parabola through the
    peak. A flat array has no position to measure and reads as (0, 0).
    """
    if a.std() < 1 or b.std() < 1:
        return (0.0, 0.0)
    h, w = a.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    fa = np.fft.fft2((a - a.mean()) * window)
    fb = np.fft.fft2((b - b.mean()) * window)
    cross = fb * np.conj(fa)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.ifft2(cross).real
    py, px = np.unravel_index(np.argmax(corr), corr.shape)

    def refine(before, peak, after):
        denominator = before - 2 * peak + after
        return 0.0 if denominator == 0 else 0.5 * (before - after) / denominator

    dy = py + refine(corr[(py - 1) % h, px], corr[py, px], corr[(py + 1) % h, px])
    dx = px + refine(corr[py, (px - 1) % w], corr[py, px], corr[py, (px + 1) % w])
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return (round(float(dx), 3) + 0.0, round(float(dy), 3) + 0.0)


def sobel(lum):
    """The Sobel gradient magnitude of the 2-D array `lum`, at its own size.

    Edge pixels are repeated at the border, so a flat array reads 0 everywhere;
    a step of height d between two columns reads 4d on both sides of it.
    """
    p = np.pad(lum, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy)


def _grow(mask):
    """`mask` grown by one pixel in every direction."""
    p = np.pad(mask, 1)
    out = np.zeros_like(mask)
    for dy in range(3):
        for dx in range(3):
            out |= p[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return out


def edge_maps(source, render):
    """(strong, kept): the source's strong edge pixels, and those of them with a
    render edge within 1 px. Arrays are native-size luminance."""
    strong = sobel(source) > EDGE_THRESHOLD
    return strong, strong & _grow(sobel(render) > RENDER_EDGE_THRESHOLD)


def _fraction(strong, kept, min_edges=1):
    """kept over strong; 1.0 when there are fewer than `min_edges` strong pixels."""
    count = int(strong.sum())
    return 1.0 if count < max(1, min_edges) else float(kept.sum() / count)


def edge_agreement(source, render):
    """The fraction of the source's strong edge pixels with a render edge within
    1 px; 1.0 when the source has no edges. Arrays are native-size luminance."""
    return _fraction(*edge_maps(source, render))


def seam_ratio(image, x, band=SEAM_BAND):
    """The colour step between 4x columns x-1 and x, over the median step
    between neighbouring columns within `band` on either side."""
    lo, hi = max(0, x - band - 1), min(image.width, x + band + 1)
    a = np.asarray(image.crop((lo, 0, hi, image.height)).convert("RGB"), dtype=np.float64)
    steps = np.abs(np.diff(a, axis=1)).mean(axis=(0, 2))    # steps[i]: column i to i + 1
    at = x - 1 - lo
    around = np.concatenate([steps[:at], steps[at + 1:]])
    base = float(np.median(around)) if around.size else 0.0
    step = float(steps[at])
    if base == 0:
        return 0.0 if step == 0 else SEAM_CAP
    return round(min(step / base, SEAM_CAP), 3)


def check(render, source, windows=(), boundaries=(), reference=None):
    """Compare the 4x `render` with its de-dithered native `source` (both RGB).

    A seam ratio is the render's step at a boundary over its local steps; with a
    4x `reference` (the guide) it is divided by the reference's own ratio there,
    so a boundary that falls on a real edge of the source is not called a seam.
    """
    small = luminance(render.resize(source.size, Image.Resampling.BOX))
    base = luminance(source)
    issues = []
    shift = phase_shift(base, small)
    if max(abs(shift[0]), abs(shift[1])) >= MAX_SHIFT:
        issues.append(f"geometry: the room is shifted {shift[0]:+.1f},{shift[1]:+.1f} px")
    window_shifts = []
    for k, (x0, x1) in enumerate(windows, 1):
        ws = phase_shift(base[:, x0:x1], small[:, x0:x1])
        window_shifts.append(ws)
        if max(abs(ws[0]), abs(ws[1])) >= MAX_SHIFT:
            issues.append(f"geometry: window {k} is shifted {ws[0]:+.1f},{ws[1]:+.1f} px")
    strong, kept = edge_maps(base, small)
    agreement = round(_fraction(strong, kept), 4)
    if agreement < MIN_EDGE_AGREEMENT:
        issues.append(f"geometry: edge agreement {agreement:.2f}, needs "
                      f"{MIN_EDGE_AGREEMENT:.2f}")
    # Each window is judged on the whole room's edge maps, masked to its
    # columns, so a window's own borders add no Sobel artefacts.
    window_agreements = []
    for k, (x0, x1) in enumerate(windows, 1):
        wa = round(_fraction(strong[:, x0:x1], kept[:, x0:x1], MIN_WINDOW_EDGES), 4)
        window_agreements.append(wa)
        if wa < MIN_EDGE_AGREEMENT:
            issues.append(f"geometry: window {k} edge agreement {wa:.2f}, needs "
                          f"{MIN_EDGE_AGREEMENT:.2f}")
    ratios = []
    for x in boundaries:
        ratio = seam_ratio(render, x)
        if reference is not None:
            ratio = round(ratio / max(1.0, seam_ratio(reference, x)), 3)
        ratios.append(ratio)
    return GeometryResult(shift, tuple(window_shifts), agreement, tuple(window_agreements),
                          tuple(ratios), tuple(issues))
