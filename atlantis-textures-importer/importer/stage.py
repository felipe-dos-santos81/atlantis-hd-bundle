"""The hd/ folder: the AI backgrounds, one index map per room, and the
manifest; staging it and checking an installed copy."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from scumm.manifest import sha256_file, write_manifest

from importer.rooms import NativeRoom, room_name

# The engine reads this format in HDBackground::loadRoom (engine/scumm/hd_background.cpp).
IDX_MAGIC = b"ATLIDX01"

# The files each manifest room record hashes.
_FILES = ((".png", "png_sha256"), (".idx", "idx_sha256"))


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
        record = {"width": room.width, "height": room.height}
        contents = {".png": (ai_dir / f"{name}.png").read_bytes(), ".idx": idx_bytes(room)}
        for suffix, key in _FILES:
            (dst / f"{name}{suffix}").write_bytes(contents[suffix])
            record[key] = hashlib.sha256(contents[suffix]).hexdigest()
        manifest["rooms"][name] = record
    write_manifest(dst / "manifest.json", manifest)
    return manifest


def check_staged(hd: Path) -> list[str]:
    """Every file of an hd/ folder that is missing or changed since staging."""
    manifest_path = hd / "manifest.json"
    if not manifest_path.is_file():
        return [f"{manifest_path}: missing; HD backgrounds are not installed"]
    problems = []
    for name, record in sorted(json.loads(manifest_path.read_text())["rooms"].items()):
        for suffix, key in _FILES:
            path = hd / f"{name}{suffix}"
            if not path.is_file():
                problems.append(f"{path.name}: missing")
            elif sha256_file(path) != record[key]:
                problems.append(f"{path.name}: changed since install")
    return problems
