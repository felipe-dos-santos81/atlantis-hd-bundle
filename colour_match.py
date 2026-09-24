"""Pull a render's colours toward its own source guide.

Rule "source-relative": the render's per-band Lab mean and spread move toward
the guide's (the de-dithered source, upscaled), blended by strength. There are
no anchors: the painted look keeps the game's colours, and the rooms of one
location already share the game's palette. Pure image maths on Pillow's 8-bit
LAB mode (littlecms); knows no rooms or files. The Lab helpers come from the
AITD kit's colour_match.py.
"""
from PIL import Image, ImageCms, ImageStat

RULE = "source-relative"

_SRGB = ImageCms.createProfile("sRGB")
_LAB = ImageCms.createProfile("LAB")
_TO_LAB = ImageCms.buildTransformFromOpenProfiles(_SRGB, _LAB, "RGB", "LAB")
_TO_RGB = ImageCms.buildTransformFromOpenProfiles(_LAB, _SRGB, "LAB", "RGB")


def _to_lab(image):
    return ImageCms.applyTransform(image.convert("RGB"), _TO_LAB)


def lab_stats(image):
    """(means, stds): three floats each, over Pillow's 8-bit L, A, B bands."""
    stat = ImageStat.Stat(_to_lab(image))
    return tuple(stat.mean), tuple(stat.stddev)


def _clamp(value):
    return min(255, max(0, round(value)))


def match(render, guide, strength=1.0):
    """The render shifted and scaled per Lab band toward `guide`'s mean and
    spread, blended by `strength`. Returns a new RGB image of the render's size;
    strength 0 returns the raw pixels unchanged (no Lab round trip)."""
    if strength == 0:
        return render.convert("RGB").copy()
    lab = _to_lab(render)
    stat = ImageStat.Stat(lab)
    target_means, target_stds = lab_stats(guide)
    bands = []
    for band, mean, std, tmean, tstd in zip(lab.split(), stat.mean, stat.stddev,
                                            target_means, target_stds):
        gain = tstd / std if std else 1.0
        table = [_clamp(v + strength * ((v - mean) * gain + tmean - v)) for v in range(256)]
        bands.append(band.point(table))
    return ImageCms.applyTransform(Image.merge("LAB", bands), _TO_RGB)
