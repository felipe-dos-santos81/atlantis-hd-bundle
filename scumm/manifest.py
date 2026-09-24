from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

EXPECTED = {"rooms": 96, "backgrounds": 96, "objects": 1372, "costumes": 240, "fonts": 5}


def sha256_file(path) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def build_manifest(game_dir: str, records: list[dict], anomalies: int) -> dict:
    ordered = sorted(records, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return {
        "game": {"dir": str(game_dir)},
        "assets": ordered,
        "summary": {
            "rooms": len(ordered),
            "backgrounds": len(ordered),
            "objects": 0,
            "costumes": 0,
            "fonts": 0,
            "anomalies": anomalies,
            "expected": dict(EXPECTED),
        },
    }


def write_manifest(path, manifest: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def contact_sheet(items: list[tuple[int, str]], out_path, cell=(320, 200), cols: int = 8) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    rows = (len(items) + cols - 1) // cols if items else 1
    sheet = Image.new("RGB", (cell[0] * cols, cell[1] * rows), (0, 0, 0))
    for i, (_room, file) in enumerate(items):
        img = Image.open(file).convert("RGB").resize(cell, Image.NEAREST)
        sheet.paste(img, ((i % cols) * cell[0], (i // cols) * cell[1]))
    sheet.save(out_path, format="PNG")


def write_report(path, manifest: dict) -> None:
    s = manifest["summary"]
    lines = [
        "# Atlantis texture extraction report",
        "",
        f"Rooms/backgrounds: {s['rooms']}",
        f"Anomalies: {s['anomalies']}",
        "",
        "## Expected vs found",
        "",
    ]
    for key in ("rooms", "backgrounds", "objects", "costumes", "fonts"):
        lines.append(f"- {key}: found {s.get(key, 0)} / expected {s['expected'][key]}")
    lines.append("")
    if s["anomalies"]:
        lines.append("Unexplained anomalies present; triage before considering complete.")
    else:
        lines.append("No anomalies.")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")
