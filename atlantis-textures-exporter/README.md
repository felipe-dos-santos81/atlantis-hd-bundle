# atlantis-textures-exporter

Extracts the visual assets of *Indiana Jones and the Fate of Atlantis* (SCUMM v5,
GOG/ScummVM build) from `ATLANTIS.001` for AI regeneration. Output is
re-import-safe: indexed 8-bit PNGs at native size with the exact game palette.

## Requirements

- Python 3.12
- Pillow (installed by `make exporter-install`)

## Quick start

Run these from the repository root:

    make exporter-install   # create .venv and install Pillow + pytest
    make exporter-extract   # write PNGs to out/ (reads the installed game bundle by default)
    make exporter-test      # run the pytest suite

Override the game directory or output path:

    make exporter-extract game="/path/to/game" out=out

## Output

    out/
      indexed/rooms/room_NNN.png      indexed P-mode, exact 256-colour CLUT, native size
      indexed/palettes/room_NNN.png   palette swatch
      manifest.json                   per-asset role, codec ids, sha256, source offset, anomalies
      contact_sheet_backgrounds.png   labelled tiles of all 96 rooms
      report.md                       found vs expected counts and anomaly summary

## Status

M1 complete: all 96 room backgrounds. Later milestones add object sprites,
costumes, and UI art.

## Legal

The extracted and regenerated art is LucasArts/Disney copyright. Personal use
only. Do not redistribute the extracted art or derived work.
