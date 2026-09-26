"""Staging hd/: the AI backgrounds, one index map per room, and the manifest."""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path

from importer.rooms import NativeRoom, room_name

# The engine reads this format in HDBackground::loadRoom (engine/scumm/hd_background.cpp).
IDX_MAGIC = b"ATLIDX01"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def idx_bytes(room: NativeRoom) -> bytes:
    return IDX_MAGIC + struct.pack("<HH", room.width, room.height) + room.palette + room.pixels


def source_id(root: Path) -> str:
    """A short hash of the engine sources, recorded in the manifest."""
    digest = hashlib.sha256()
    files = sorted([*(root / "patches").glob("*.patch"), *(root / "engine/scumm").glob("hd_*")])
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def stage(rooms: list[NativeRoom], ai_dir: Path, dst: Path, source: str) -> dict:
    dst.mkdir(parents=True)
    manifest = {"format": 1, "source": source, "rooms": {}}
    for room in rooms:
        name = room_name(room.number)
        png = dst / f"{name}.png"
        shutil.copyfile(Path(ai_dir) / f"{name}.png", png)
        idx = dst / f"{name}.idx"
        idx.write_bytes(idx_bytes(room))
        manifest["rooms"][name] = {
            "width": room.width,
            "height": room.height,
            "png_sha256": sha256_file(png),
            "idx_sha256": sha256_file(idx),
        }
    (dst / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
