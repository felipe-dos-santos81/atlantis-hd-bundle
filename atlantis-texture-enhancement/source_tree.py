"""Read and validate the extractor's manifest.json: which rooms exist, their
native sizes and their files.

The source tree is atlantis-textures' output (`make extract` there):
indexed/rooms/room_NNN.png in P mode at native size, and manifest.json whose
assets[] records carry room, file, width, height, role and sha256. This module
is its only reader. It never writes: ATL_SRC is read in place.
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

SCALE = 4               # every output is exactly 4x its room's native size
ROLE = "background"     # the manifest role of a room background


class SourceError(ValueError):
    """The source tree disagrees with its manifest, or a selection is not in it."""


@dataclass(frozen=True)
class Room:
    number: int
    rel: Path           # the indexed PNG, relative to the source root
    width: int          # native size
    height: int
    sha256: str

    @property
    def key(self):
        """The rooms.yaml and reviews.yaml key, audit folder and output name stem."""
        return f"room_{self.number:03d}"

    @property
    def out_name(self):
        return f"{self.key}.png"

    @property
    def out_size(self):
        return (self.width * SCALE, self.height * SCALE)


@dataclass(frozen=True)
class Source:
    root: Path
    rooms: tuple        # of Room, by number


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _room(root, record, where):
    number = record.get("room")
    rel = record.get("file")
    width, height = record.get("width"), record.get("height")
    digest = record.get("sha256")
    if type(number) is not int or number < 0:
        raise SourceError(f'{where}: "room" must be a non-negative integer, got {number!r}')
    if (not isinstance(rel, str) or not rel or rel.startswith("/")
            or ".." in Path(rel).parts):
        raise SourceError(f'{where}: "file" must be a relative path inside the source tree')
    for name, value in (("width", width), ("height", height)):
        # SMAP images are built from 8-pixel strips; every window size relies on it.
        if type(value) is not int or value <= 0 or value % 8:
            raise SourceError(f'{where}: "{name}" must be a positive multiple of 8, got {value!r}')
    if not isinstance(digest, str) or len(digest) != 64:
        raise SourceError(f'{where}: "sha256" must be 64 hex digits')
    path = root / rel
    label = f"room {number} ({rel})"
    if not path.is_file():
        raise SourceError(f"{label}: file not found")
    try:
        with Image.open(path) as im:
            mode, size = im.mode, im.size
    except OSError as error:
        raise SourceError(f"{label}: not a readable image: {error}") from error
    if mode != "P":
        raise SourceError(f"{label}: mode {mode}, expected P (indexed)")
    if size != (width, height):
        raise SourceError(f"{label}: is {size[0]}x{size[1]}, the manifest says {width}x{height}")
    if file_sha256(path) != digest:
        raise SourceError(f"{label}: sha256 differs from the manifest - re-run make extract")
    return Room(number, Path(rel), width, height, digest)


def load(root):
    """Every background room the manifest lists, each checked against its file."""
    root = Path(root)
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise SourceError(f"{manifest}: not found - run make extract in atlantis-textures")
    try:
        doc = json.loads(manifest.read_text())
    except ValueError as error:
        raise SourceError(f"{manifest}: invalid JSON: {error}") from error
    assets = doc.get("assets") if isinstance(doc, dict) else None
    if not isinstance(assets, list):
        raise SourceError(f'{manifest}: expected a mapping with an "assets" list')
    rooms = {}
    for i, record in enumerate(assets):
        if not isinstance(record, dict) or record.get("role") != ROLE:
            continue
        room = _room(root, record, f"{manifest}: assets[{i}]")
        if room.number in rooms:
            raise SourceError(f"{manifest}: assets[{i}]: duplicate room {room.number}")
        rooms[room.number] = room
    if not rooms:
        raise SourceError(f"{manifest}: lists no background rooms")
    return Source(root, tuple(rooms[n] for n in sorted(rooms)))


def select(source, numbers=None):
    """The rooms `numbers` names, by number; every room when it is empty or None."""
    if not numbers:
        return list(source.rooms)
    by_number = {room.number: room for room in source.rooms}
    unknown = sorted({n for n in numbers if n not in by_number})
    if unknown:
        raise SourceError("not in the manifest: room " + ", ".join(map(str, unknown)))
    return [by_number[n] for n in sorted(set(numbers))]


def open_indexed(root, room):
    """The room's image, loaded: P mode with the game's palette."""
    with Image.open(Path(root) / room.rel) as im:
        im.load()
        return im.copy()
