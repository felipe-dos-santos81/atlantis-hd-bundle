from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scumm.archive import Archive
from scumm.export import save_indexed_png, save_palette_swatch
from scumm.manifest import (EXPECTED, build_manifest, contact_sheet,
                            sha256_file, write_manifest, write_report)
from scumm.room import extract_background


def _room_file(room: int) -> str:
    return f"room_{room:03d}.png"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Extract Fate of Atlantis backgrounds.")
    parser.add_argument("--game", required=True, help="directory containing ATLANTIS.001")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)

    archive = Archive.load(Path(args.game) / "ATLANTIS.001")
    rooms = sorted(archive.room_index())

    out = Path(args.out)
    records = []
    anomalies_total = 0
    sheet_items = []

    for room in rooms:
        bg = extract_background(archive, room)
        anomalies_total += len(bg.anomalies)
        img_rel = f"indexed/rooms/{_room_file(room)}"
        pal_rel = f"indexed/palettes/{_room_file(room)}"
        save_indexed_png(out / img_rel, bg.pixels, bg.width, bg.height, bg.palette)
        save_palette_swatch(out / pal_rel, bg.palette)
        records.append({
            "room": room,
            "name": None,
            "role": "background",
            "width": bg.width,
            "height": bg.height,
            "transparent_index": bg.palette.transparent_index,
            "source_offset": bg.source_offset,
            "codec_ids": list(bg.codec_ids),
            "file": img_rel,
            "palette_file": pal_rel,
            "sha256": sha256_file(out / img_rel),
            "anomalies": [
                {"strip": a.strip, "codec_id": a.codec_id, "reason": a.reason}
                for a in bg.anomalies
            ],
        })
        sheet_items.append((room, str(out / img_rel)))

    manifest = build_manifest(args.game, records, anomalies_total)
    write_manifest(out / "manifest.json", manifest)
    contact_sheet(sheet_items, out / "contact_sheet_backgrounds.png")
    write_report(out / "report.md", manifest)

    print(f"rooms: {len(records)}/{EXPECTED['rooms']}  anomalies: {anomalies_total}")
    return 0 if len(records) == EXPECTED["rooms"] else 1


if __name__ == "__main__":
    sys.exit(main())
