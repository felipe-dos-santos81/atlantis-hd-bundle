"""Pull a render's colours toward its own source guide.

Rule "source-relative": the render's per-band Lab mean and spread move toward
the guide's (the de-dithered source, upscaled), blended by strength. There are
no anchors: the painted look keeps the game's colours, and the rooms of one
location already share the game's palette. Pure image maths on Pillow images
through a float sRGB <-> CIE Lab (D65) transform in numpy; knows no rooms or
files.

The transform is float end to end because Pillow's 8-bit Lab round trip is
lossy: it moves saturated colours by up to 39 levels even when nothing is
matched. Lab here is CIE L* (0-100), a* and b*.
"""
import numpy as np
from PIL import Image

RULE = "source-relative"

# Linear sRGB to CIE XYZ (D65). The white point is the matrix's row sums, so
# sRGB white is exactly L* 100, a* 0, b* 0 and the round trip is exact.
_RGB_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                        [0.2126729, 0.7151522, 0.0721750],
                        [0.0193339, 0.1191920, 0.9503041]])
_XYZ_TO_RGB = np.linalg.inv(_RGB_TO_XYZ)
_WHITE = _RGB_TO_XYZ.sum(axis=1)
_DELTA = 6 / 29
_LEVELS = np.arange(256) / 255
_LINEAR = np.where(_LEVELS <= 0.04045, _LEVELS / 12.92, ((_LEVELS + 0.055) / 1.055) ** 2.4)


def _to_lab(image):
    """(h, w, 3) float CIE Lab of `image`."""
    linear = _LINEAR[np.asarray(image.convert("RGB"))]
    t = linear @ _RGB_TO_XYZ.T / _WHITE
    f = np.where(t > _DELTA ** 3, np.cbrt(t), t / (3 * _DELTA ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def _to_rgb(lab):
    """An RGB image of the (h, w, 3) float CIE Lab `lab`, clipped to the sRGB gamut."""
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], axis=-1)
    t = np.where(f > _DELTA, f ** 3, 3 * _DELTA ** 2 * (f - 4 / 29))
    linear = np.clip((t * _WHITE) @ _XYZ_TO_RGB.T, 0, 1)
    c = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    return Image.fromarray(np.round(np.clip(c, 0, 1) * 255).astype(np.uint8))


def _stats(lab):
    pixels = lab.reshape(-1, 3)
    return pixels.mean(axis=0), pixels.std(axis=0)


def lab_stats(image):
    """(means, stds): three floats each, over the CIE L*, a*, b* bands."""
    means, stds = _stats(_to_lab(image))
    return tuple(float(v) for v in means), tuple(float(v) for v in stds)


def match(render, guide, strength=1.0):
    """The render shifted and scaled per Lab band toward `guide`'s mean and
    spread, blended by `strength`. Returns a new RGB image of the render's size;
    strength 0 returns the raw pixels unchanged (no Lab round trip)."""
    if strength == 0:
        return render.convert("RGB").copy()
    lab = _to_lab(render)
    means, stds = _stats(lab)
    target_means, target_stds = lab_stats(guide)
    # A band that is really constant still has a float64 std of about 1e-12
    # (the Lab transform's own rounding), not exactly 0; a bare `> 0` guard
    # let that near-zero std blow the gain up and paint noise onto a flat or
    # greyscale render.
    gain = np.divide(target_stds, stds, out=np.ones(3), where=stds > 1e-6)
    moved = (lab - means) * gain + target_means
    return _to_rgb(lab + strength * (moved - lab))
