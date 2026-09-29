"""The GOG app: preflight, install with rollback, uninstall, verify."""
from __future__ import annotations

import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from importer.stage import IDX_MAGIC, check_staged

Runner = Callable[[list[str]], subprocess.CompletedProcess]

ARM64_HEADER = struct.pack("<II", 0xFEEDFACF, 0x0100000C)  # 64-bit Mach-O, CPU_TYPE_ARM64
BUNDLE_BINARY = "Contents/MacOS/scummvm"  # the executable inside a ScummVM bundle
GAME_RUNNING = "the game is running; quit it first"


class InstallError(Exception):
    pass


def run_command(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


@dataclass(frozen=True)
class AppLayout:
    app: Path

    @property
    def game_root(self) -> Path:
        return self.app / "Contents/Resources/game"

    @property
    def engine(self) -> Path:
        return self.game_root / "scummvm"

    @property
    def backup(self) -> Path:
        return self.game_root / "scummvm.orig"

    @property
    def binary(self) -> Path:
        return self.engine / BUNDLE_BINARY

    @property
    def data(self) -> Path:
        return self.game_root / "game"

    @property
    def hd(self) -> Path:
        return self.data / "hd"

    @property
    def config(self) -> Path:
        return self.data / "configfile"

    @property
    def config_backup(self) -> Path:
        return self.data / "configfile.orig"


def with_engine_id(config: str) -> str:
    """GOG's configfile (written by ScummVM 1.7) has no engineid in its
    [atlantis] target; ScummVM 2026 cannot upgrade the target without it."""
    lines = config.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == "[atlantis]"), None)
    if start is None:
        raise InstallError("configfile has no [atlantis] target")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    if any(line.split("=", 1)[0].strip() == "engineid" for line in lines[start + 1:end]):
        return config
    lines.insert(start + 1, "engineid=scumm\n")
    return "".join(lines)


def _running(layout: AppLayout, runner: Runner) -> bool:
    return runner(["pgrep", "-f", str(layout.binary)]).returncode == 0


def check_game(layout: AppLayout) -> list[str]:
    if (layout.data / "ATLANTIS.001").is_file():
        return []
    return [f"{layout.app}: not the GOG Fate of Atlantis app (no ATLANTIS.001)"]


def preflight(layout: AppLayout, build: Path, runner: Runner) -> list[str]:
    """Everything install needs before it touches the app."""
    problems = check_game(layout)
    if not (build / BUNDLE_BINARY).is_file():
        problems.append(f"{build}: no built ScummVM; run make importer-engine-build")
    if _running(layout, runner):
        problems.append(GAME_RUNNING)
    return problems


def _restore(layout: AppLayout) -> bool:
    """Put the stock engine, configfile and data back; True when anything changed."""
    changed = False
    if layout.backup.exists():
        if layout.engine.exists():
            shutil.rmtree(layout.engine)
        layout.backup.rename(layout.engine)
        changed = True
    if layout.config_backup.exists():
        layout.config_backup.replace(layout.config)
        changed = True
    if layout.hd.exists():
        shutil.rmtree(layout.hd)
        changed = True
    return changed


def install(layout: AppLayout, build: Path, staged_hd: Path, runner: Runner) -> None:
    """Swap the patched engine and hd/ in. staged_hd must be on the app's
    filesystem (it is moved). Any failure restores the stock app."""
    try:
        if layout.backup.exists():
            # A previous install (or an interrupted one): the backup is the real original.
            if layout.engine.exists():
                shutil.rmtree(layout.engine)
        else:
            layout.engine.rename(layout.backup)
        if not layout.config_backup.exists():
            shutil.copy2(layout.config, layout.config_backup)
        layout.config.write_bytes(with_engine_id(layout.config.read_bytes().decode()).encode())
        shutil.copytree(build, layout.engine, symlinks=True)
        if layout.hd.exists():
            shutil.rmtree(layout.hd)
        staged_hd.rename(layout.hd)
        runner(["xattr", "-dr", "com.apple.quarantine", str(layout.app)])  # an absent attribute is fine
        # No re-signing: the engine keeps the ad-hoc signature it got at build
        # time, GOG's own 2014 seal already fails modern verification and the
        # app launches regardless, and signing inside iCloud-synced ~/Documents
        # fails (File Provider re-adds com.apple.FinderInfo). Not signing also
        # lets uninstall restore GOG's signature untouched.
    except Exception as error:
        _restore(layout)
        if isinstance(error, InstallError):
            raise
        raise InstallError(f"install failed and was rolled back: {error}") from error
    print(f"installed the patched ScummVM (original kept as {layout.backup.name}) and {layout.hd}")


def uninstall(layout: AppLayout, runner: Runner) -> None:
    if _running(layout, runner):
        raise InstallError(GAME_RUNNING)
    if _restore(layout):
        print(f"restored the original ScummVM and configfile, removed {layout.hd}")
    else:
        print("nothing installed; the app is stock")


def verify(layout: AppLayout) -> list[str]:
    problems = check_staged(layout.hd)
    if not layout.backup.is_dir():
        problems.append(f"{layout.backup}: missing; uninstall could not restore the original")
    data = layout.binary.read_bytes() if layout.binary.is_file() else b""
    if not data.startswith(ARM64_HEADER):
        problems.append(f"{layout.binary}: not an arm64 executable")
    elif IDX_MAGIC not in data:
        problems.append(f"{layout.binary}: not the patched engine")
    return problems
