from PIL import Image

from scumm.archive import Archive
from scumm.export import save_indexed_png, save_palette_swatch
from scumm.room import extract_background


def test_save_indexed_png_roundtrip(tmp_path):
    colors = tuple((i, i, i) for i in range(256))
    from scumm.palette import Palette
    pal = Palette(colors, 5, ())
    pixels = bytearray([0, 1, 2, 3])
    out = tmp_path / "r.png"
    save_indexed_png(out, pixels, 2, 2, pal)
    img = Image.open(out)
    assert img.mode == "P"
    assert img.size == (2, 2)
    assert list(img.getdata()) == [0, 1, 2, 3]
    assert img.getpalette()[:3] == [0, 0, 0]


def test_save_background_is_indexed(archive_path, tmp_path):
    a = Archive.load(archive_path)
    bg = extract_background(a, 1)
    out = tmp_path / "room1.png"
    save_indexed_png(out, bg.pixels, bg.width, bg.height, bg.palette)
    img = Image.open(out)
    assert img.mode == "P"
    assert img.size == (320, 200)
    assert img.getpalette()[3:6] == [0, 0, 171]


def test_save_palette_swatch(archive_path, tmp_path):
    a = Archive.load(archive_path)
    bg = extract_background(a, 1)
    out = tmp_path / "pal.png"
    save_palette_swatch(out, bg.palette, scale=4)
    img = Image.open(out)
    assert img.mode == "RGB"
    assert img.size == (64, 64)
