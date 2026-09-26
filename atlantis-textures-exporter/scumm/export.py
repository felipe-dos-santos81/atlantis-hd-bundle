from __future__ import annotations

from pathlib import Path

from PIL import Image

from .palette import Palette


def save_indexed_png(path, pixels, width: int, height: int, palette: Palette) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img = Image.frombytes("P", (width, height), bytes(pixels))
    flat = [c for rgb in palette.colors for c in rgb]
    img.putpalette(flat)
    img.save(path, format="PNG")


def save_palette_swatch(path, palette: Palette, scale: int = 16) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (16, 16))
    img.putdata(list(palette.colors))
    img = img.resize((16 * scale, 16 * scale), Image.NEAREST)
    img.save(path, format="PNG")
