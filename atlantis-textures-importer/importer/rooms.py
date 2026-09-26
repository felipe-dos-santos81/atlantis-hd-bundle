"""The game's native rooms, read with the exporter's decoder, and the check of
an AI folder against them."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

SCALE = 4


@dataclass(frozen=True)
class NativeRoom:
    number: int
    width: int
    height: int
    palette: bytes  # 768 bytes: the room's CLUT
    pixels: bytes  # width * height palette indices
    anomalies: int  # decoder anomalies; any makes the index map untrustworthy


def room_name(number: int) -> str:
    return f"room_{number:03d}"


def load_native_rooms(game_dir: Path) -> list[NativeRoom]:
    """Decode every room background from ATLANTIS.001 (needs the exporter on PYTHONPATH)."""
    from scumm.archive import Archive
    from scumm.room import extract_background

    archive = Archive.load(Path(game_dir) / "ATLANTIS.001")
    rooms = []
    for number in sorted(archive.room_index()):
        bg = extract_background(archive, number)
        palette = bytes(c for rgb in bg.palette.colors for c in rgb)
        rooms.append(NativeRoom(number, bg.width, bg.height, palette, bytes(bg.pixels), len(bg.anomalies)))
    return rooms


def validate(rooms: list[NativeRoom], ai_dir: Path) -> list[str]:
    """Every reason the AI folder cannot be installed; empty when it is ready."""
    problems = []
    for room in rooms:
        name = room_name(room.number)
        if room.anomalies:
            problems.append(f"{name}: the decoder reported {room.anomalies} anomalies; its index map would be wrong")
        path = Path(ai_dir) / f"{name}.png"
        if not path.is_file():
            problems.append(f"{path.name}: missing")
            continue
        with Image.open(path) as image:
            if image.mode != "RGB":
                problems.append(f"{path.name}: mode {image.mode}, expected RGB")
            expected = (SCALE * room.width, SCALE * room.height)
            if image.size != expected:
                problems.append(f"{path.name}: {image.width}x{image.height}, expected {expected[0]}x{expected[1]}")
    return problems
