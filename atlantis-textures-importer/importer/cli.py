"""python -m importer {validate,install,uninstall,verify}"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from importer.app import AppLayout, InstallError, install, preflight, run, uninstall, verify
from importer.rooms import load_native_rooms, validate
from importer.stage import source_id, stage

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AI = Path.home() / "Documents/Indiana Jones and the Fate of Atlantis-ai"
DEFAULT_APP = Path.home() / "Documents/Indiana Jones® and the Fate of Atlantis™.app"
DEFAULT_BUILD = ROOT / "vendor/scummvm/ScummVM.app"


def _report(problems: list[str], ok: str) -> int:
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(ok)
    return 0


def main(argv: list[str] | None = None, runner=run, load_rooms=load_native_rooms) -> int:
    parser = argparse.ArgumentParser(prog="importer", description="HD backgrounds in the GOG Fate of Atlantis app.")
    parser.add_argument("command", choices=["validate", "install", "uninstall", "verify"])
    parser.add_argument("--ai", type=Path, default=DEFAULT_AI, help="folder of AI room_NNN.png backgrounds")
    parser.add_argument("--app", type=Path, default=DEFAULT_APP, help="the GOG .app")
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD, help="the built ScummVM.app")
    args = parser.parse_args(argv)
    layout = AppLayout(args.app)

    try:
        if args.command == "uninstall":
            uninstall(layout, runner)
            return 0
        if args.command == "verify":
            return _report(verify(layout), "installed and intact")

        installing = args.command == "install"
        problems = preflight(layout, args.build if installing else None, runner if installing else None)
        if problems:
            return _report(problems, "")
        rooms = load_rooms(layout.data)
        problems = validate(rooms, args.ai)
        if problems or not installing:
            return _report(problems, f"{len(rooms)} rooms ready")

        work = Path(tempfile.mkdtemp(prefix=".atlantis-hd-", dir=args.app.parent))
        try:
            stage(rooms, args.ai, work / "hd", source_id(ROOT))
            install(layout, args.build, work / "hd", runner)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return 0
    except InstallError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
