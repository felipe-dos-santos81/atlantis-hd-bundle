"""Shared test support: miniature rooms and AI folders, a fake GOG app and build,
a recording command runner and a tree snapshot. Never re-implement these in a
test module."""
from __future__ import annotations

import struct
import subprocess
from pathlib import Path

from PIL import Image

from importer.rooms import NativeRoom, room_name

APP_NAME = "Indiana Jones® and the Fate of Atlantis™.app"
ARM64_HEADER = struct.pack("<II", 0xFEEDFACF, 0x0100000C)
STOCK_BINARY = b"stock scummvm 2.0.0"

REAL_GAME = Path.home() / "Documents" / APP_NAME / "Contents/Resources/game/game"
REAL_AI = Path.home() / "Documents/Indiana Jones and the Fate of Atlantis-ai"


def make_rooms() -> list[NativeRoom]:
    """Room 1 is 3x2, room 2 is 2x2; both use a grey-ramp palette."""
    palette = bytes(i for i in range(256) for _ in range(3))
    return [
        NativeRoom(1, 3, 2, palette, bytes([1, 2, 3, 4, 5, 6]), 0),
        NativeRoom(2, 2, 2, palette, bytes([7, 7, 8, 8]), 0),
    ]


def write_ai(folder: Path, rooms: list[NativeRoom]) -> Path:
    """A valid AI folder: one RGB PNG per room at exactly 4x."""
    folder.mkdir(parents=True, exist_ok=True)
    for r in rooms:
        Image.new("RGB", (4 * r.width, 4 * r.height), (r.number, 0, 0)).save(folder / f"{room_name(r.number)}.png")
    return folder


def make_app(root: Path) -> Path:
    """The GOG bundle's shape, with stand-in contents."""
    app = root / APP_NAME
    game = app / "Contents/Resources/game"
    (game / "scummvm/Contents/MacOS").mkdir(parents=True)
    (game / "scummvm/Contents/MacOS/scummvm").write_bytes(STOCK_BINARY)
    (game / "game").mkdir()
    (game / "game/ATLANTIS.001").write_bytes(b"game data")
    (game / "game/configfile").write_text("[scummvm]\nversioninfo=1.7.0\n")
    (game / "launch_game.sh").write_text("#!/bin/bash\n")
    return app


def make_build(root: Path, *, patched: bool = True) -> Path:
    """A built ScummVM.app: an arm64 header, plus the engine marker when patched."""
    build = root / "ScummVM.app"
    (build / "Contents/MacOS").mkdir(parents=True)
    body = b"...ATLIDX01..." if patched else b"...stock..."
    (build / "Contents/MacOS/scummvm").write_bytes(ARM64_HEADER + body)
    (build / "Contents/libs").mkdir()
    (build / "Contents/libs/libSDL2-2.0.0.dylib").write_bytes(b"sdl")
    return build


class Runner:
    """Records commands instead of running them. `pgrep` reports `running`;
    any other program returns the code in `fail` (default 0)."""

    def __init__(self, *, fail: dict[str, int] | None = None, running: bool = False):
        self.calls: list[list[str]] = []
        self.fail = fail or {}
        self.running = running

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        program = cmd[0]
        if program == "pgrep":
            code = 0 if self.running else 1
        else:
            code = self.fail.get(program, 0)
        return subprocess.CompletedProcess(cmd, code, "", f"{program} failed" if code else "")

    def programs(self) -> list[str]:
        return [c[0] for c in self.calls]


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under root, by relative path."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
