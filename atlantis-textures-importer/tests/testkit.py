"""Shared test support: miniature rooms and AI folders, a fake GOG app and build,
a recording command runner and a tree snapshot. Never re-implement these in a
test module."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image

from importer.app import ARM64_HEADER, BUNDLE_BINARY, AppLayout
from importer.cli import DEFAULT_AI, DEFAULT_APP
from importer.rooms import SCALE, NativeRoom, room_name
from importer.stage import IDX_MAGIC

APP_NAME = DEFAULT_APP.name  # the real name, with ® and ™
STOCK_BINARY = b"stock scummvm 2.0.0"

REAL_GAME = AppLayout(DEFAULT_APP).data
REAL_AI = DEFAULT_AI


def make_rooms() -> list[NativeRoom]:
    """Room 1 is 3x2, room 2 is 2x2; both use a grey-ramp palette."""
    palette = bytes(i for i in range(256) for _ in range(3))
    return [
        NativeRoom(1, 3, 2, palette, bytes([1, 2, 3, 4, 5, 6]), 0),
        NativeRoom(2, 2, 2, palette, bytes([7, 7, 8, 8]), 0),
    ]


def write_ai(folder: Path, rooms: list[NativeRoom]) -> Path:
    """A valid AI folder: one RGB PNG per room at exactly SCALE x."""
    folder.mkdir(parents=True, exist_ok=True)
    for r in rooms:
        Image.new("RGB", (SCALE * r.width, SCALE * r.height), (r.number, 0, 0)).save(folder / f"{room_name(r.number)}.png")
    return folder


def make_app(root: Path) -> Path:
    """The GOG bundle's shape, with stand-in contents."""
    app = root / APP_NAME
    layout = AppLayout(app)
    layout.binary.parent.mkdir(parents=True)
    layout.binary.write_bytes(STOCK_BINARY)
    layout.data.mkdir()
    (layout.data / "ATLANTIS.001").write_bytes(b"game data")
    layout.config.write_text("[scummvm]\nversioninfo=1.7.0\n\n[atlantis]\ngameid=atlantis\n")
    (layout.game_root / "launch_game.sh").write_text("#!/bin/bash\n")
    return app


def make_build(root: Path) -> Path:
    """A built, patched ScummVM.app: an arm64 header and the engine marker."""
    build = root / "ScummVM.app"
    (build / BUNDLE_BINARY).parent.mkdir(parents=True)
    (build / BUNDLE_BINARY).write_bytes(ARM64_HEADER + b"..." + IDX_MAGIC + b"...")
    (build / "Contents/libs").mkdir()
    (build / "Contents/libs/libSDL2-2.0.0.dylib").write_bytes(b"sdl")
    return build


class Runner:
    """Records commands instead of running them: `pgrep` reports `running`,
    every other program succeeds."""

    def __init__(self, *, running: bool = False):
        self.calls: list[list[str]] = []
        self.running = running

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        code = int(not self.running) if cmd[0] == "pgrep" else 0
        return subprocess.CompletedProcess(cmd, code, "", "")

    def programs(self) -> list[str]:
        return [c[0] for c in self.calls]


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under root, by relative path."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
