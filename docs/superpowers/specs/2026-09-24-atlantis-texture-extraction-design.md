# Atlantis Texture Extraction — Design

Date: 2026-09-24
Status: approved for planning

## 1. Problem

Extract every visual asset from *Indiana Jones and the Fate of Atlantis* into
clean image files suitable for AI regeneration (upscaling, img2img, redraw),
while keeping the output faithful enough that re-import into the game remains
possible later.

## 2. Source

A GOG macOS bundle: `Indiana Jones® and the Fate of Atlantis™.app`, running a
bundled **ScummVM 2.0.0** (x86_64) against a **SCUMM v5** DOS CD English build.

Game data lives in
`Contents/Resources/game/game/`:

| File | Size | Role |
|---|---|---|
| `ATLANTIS.000` | 12 KB | room index |
| `ATLANTIS.001` | 9.8 MB | rooms, scripts, images, costumes, charsets |
| `MONSTER.SOU` | 149 MB | audio (out of scope) |

`ATLANTIS.001` is obfuscated with a **single-byte XOR of `0x69`** across the
whole file. Verified: `25 2c 2a 2f ^ 0x69 = "LECF"`. After XOR the file begins
`LECF … LOFF`.

## 3. Scope

In scope — "everything visual":

- Room backgrounds (96 rooms).
- Object sprites (1372 objects, names available in-data via `OBNA`).
- Actor costumes (240 `COST` resources).
- UI art that is actually stored in the data (5 `CHAR` charsets, inventory
  object images), plus a provenance audit of what is not.

Out of scope (non-goals):

- No re-encoder. Output must be *re-import-safe*, not re-importable today.
- No game modification, no patching the `.app`.
- No script or text extraction.
- No audio (`MONSTER.SOU`).
- No mouse cursors or other art hardcoded in the engine binary.

## 4. Measured resource inventory

Counts obtained by XOR-0x69 decoding `ATLANTIS.001` and counting block tags:

| Tag | Count | Meaning |
|---|---|---|
| `LFLF` / `ROOM` / `RMHD` | 96 | rooms, all containing `RMIM` |
| `IM00` (under `RMIM`) | 96 | exactly one background per room |
| `CLUT` / `TRNS` / `EPAL` | 96 each | palette, transparency index, extra palette |
| `CYCL` | 96 | colour-cycling definitions (metadata) |
| `BOXD` / `BOXM` / `SCAL` | 96 each | walk boxes, matrix, scaling |
| `RMIM` / `RMIH` | 96 each | room image container |
| `SMAP` | 1425 | all bitmaps (backgrounds + object images) |
| `OBIM` / `IMHD` / `CDHD` / `OBNA` / `OBCD` | 1372 each | object sprites, with names |
| `ZP01` / `ZP02` | 1155 / 797 | z-plane masks |
| `COST` | 240 | costumes (classic v5 format) |
| `AKOS` / `AKHD` / `AKCD` / `AKPL` | 0 | **not used** by this game |
| `CHAR` | 5 | charsets / fonts |
| `SCRP` / `LSCR` | 163 / 1079 | scripts (walked, not extracted) |
| `SOUN` | 213 | music (out of scope) |

Two findings that shape the design:

1. **Costumes use the classic v5 `COST` format, not AKOS/AKCD.** This is
   simpler than originally assumed.
2. **Object names are stored in-data** (`OBNA`), so the manifest can carry real
   names. **Room names are not in the data** ("col-offic", "sop-theat" are
   absent), so room names are optional external metadata only.

## 5. Format notes

Container: `LECF → LOFF (room# → offset) → LFLF → ROOM → {RMHD, CYCL, TRNS,
EPAL, BOXD, BOXM, CLUT, SCAL, RMIM{RMIH, IM00{SMAP}}, ZP0n, OBCD}`. Sibling
blocks under `LFLF`: `COST`, `SCRP`, `SOUN`, `CHAR`.

Background bitmap: `SMAP` decomposes the image into vertical strips 8 px wide.
The strip table is `stripCount × u32 LE` offsets; each strip body is
`[codec id][first colour index][bitstream]`. The codec id selects one of nine
ranges, each mapping to (method 1 or 2, horizontal/vertical, transparent or not,
parameter subtract) which also determines the palette-index bit width.

References (public):

- ScummVM wiki — Room resources; Image resources.
- Aaron Giles, "How to make a SCUMM image" (archived).
- grogvm — SCUMM v5 SMAP format.

## 6. Approaches considered

- **A — Extend Nicola Ariutti's `SCUMM_experiments` FOA extractor.** Purpose
  built for exactly `ATLANTIS.000`/`.001`. Rejected as the base: the repository
  has **no license** (so it cannot be copied or derived from), it asserts hard
  on unexpected input, decodes only `IM00`, handles no objects/costumes/UI, and
  writes scaled RGB (violates re-import-safe). Retained as an optional
  independent verification oracle only.
- **B — New self-contained Python decoder, phased, from public specs.**
  **Chosen.** Clean ownership, extensible to every asset class, genuinely
  re-import-safe, per-module testable, license-clean.
- **C — Drive ScummVM or `scummvm-tools`.** Rejected on capability. ScummVM's
  SCUMM debugger has no image-dump command (verified in source: only `room`,
  `actor`, `objects`, `cosdump`, `importres`). `scummvm-tools` has no
  background dumper. Screenshots include sprites/UI and capture only the
  320×200 viewport, never full scrolling rooms, palettes, or alpha.

## 7. Architecture

One Python 3.12 package, dependency: **Pillow** only.

```
atlantis-textures/
  scumm/
    archive.py    XOR 0x69; tolerant nested-block reader; LOFF room index
    palette.py    CLUT/EPAL/TRNS parse; CYCL ranges (metadata)
    smap.py       SMAP -> indexed buffer; both codec methods, all nine ID
                  ranges, h/v direction, transparency; returns anomalies
    room.py       RMHD/CLUT/TRNS/EPAL + every IMxx frame + ZP0n masks
    object.py     OBIM (IMHD + IMxx) -> RGBA sprite, alpha from TRNS
    costume.py    classic COST cel decode -> per-costume sprite sheet (RGBA)
    charset.py    CHAR -> font glyph sheet
  export.py       writers: indexed PNG (P mode, exact CLUT, native size),
                  RGB preview, palette swatch, z-plane mask, RGBA sprite
  manifest.py     manifest.json + contact sheets + report.md
  extract.py      CLI: --game DIR --out DIR --phases bg,objects,costumes,ui
```

### Boundaries

- `archive.py` knows bytes and block tags, nothing about images.
- `smap.py` knows one bitmap, nothing about rooms.
- `room.py` / `object.py` / `costume.py` know their container and delegate
  pixels to `smap.py`.
- `export.py` knows output formats, nothing about SCUMM.

Each unit is testable alone: SMAP against hand-built strips, each extractor
against a single fixture room.

### Shared interface

```
decode_smap(payload, width, height, transparent_index)
    -> (bytearray, list[Anomaly])
```

`Anomaly` is a value `(offset, strip, codec_id, reason)`. Recoverable input
never raises; it is recorded. This single contract is what makes tolerant,
assert-free decoding possible while staying diagnosable.

## 8. Data flow

```
ATLANTIS.001 ──XOR 0x69──▶ bytes
   archive: LECF -> LOFF {room# -> offset}; per-room LFLF block tree
   per room:  RMHD/CLUT/TRNS/EPAL/CYCL + RMIM{RMIH, IM00..} + ZP0n + OBIM[] + OBCD
       backgrounds: IM00 -> smap.decode -> indexed buffer + CLUT -> P-mode PNG
       objects:     OBIM -> IMHD/IMxx -> smap.decode(transparent)
                    -> P-mode + tRNS PNG (+ RGBA preview)
   global:    COST[] -> costume.decode -> RGBA cel sheet
              CHAR[] -> charset.decode -> glyph sheet
   manifest.build + contact sheets + report.md
```

Deterministic: sorted keys, no embedded timestamps, same input yields
byte-identical output. Runs are diffable and two runs must match.

## 9. Output contract

```
out/
  indexed/                       source of truth, re-import-safe
    rooms/room_001.png           P mode, exact 256-entry CLUT, native W×H
    rooms/room_001.pal.png       palette swatch
    rooms/room_001.zp01.png      z-plane mask(s)
    objects/room_001_obj_042.png P mode + PNG tRNS = transparent index
    costumes/costume_001.png     RGBA cel sheet
    fonts/charset_001.png
  rgb/                           only with --rgb; RGB(A) copies for AI pipelines
  manifest.json
  contact_sheet_backgrounds.png  96 labeled tiles
  report.md
```

Re-import-safe guarantees, enforced not merely conventional:

- Indexed `P` mode, palette order preserved verbatim (256 entries, RGB).
- Native dimensions, no scaling.
- Transparency carried as PNG `tRNS`.
- Every asset records its **source byte offset**, so a future re-encoder can
  locate the exact resource to replace.

### manifest.json

Machine index. Per asset: id, optional name, role
(`background` / `object` / `costume` / `font`), W×H, source offset, codec ids
used, transparent index, `sha256`, and `anomalies[]`. A top-level `summary`
carries found-versus-expected counts:

```
rooms 96, backgrounds 96, objects 1372, costumes 240, fonts 5
```

### Naming

Keyed on in-data identifiers (room number, object number, costume number) for
authority and stability. Human names are appended only when available: object
names come free from `OBNA`; room names require an external table and are
omitted otherwise. Filenames are filesystem-sanitized.

### Costumes

One RGBA sheet per costume; each cel's rect is recorded in the manifest,
keeping file count sane while preserving exact cel geometry for a future
re-encoder.

## 10. Error handling

Input is an untrusted binary; every read is bounds-checked. A truncated or
corrupted file must degrade to anomalies, never a traceback or hang.

Three tiers:

- **Fatal** — bad file or XOR failure: abort with a clear message.
- **Recoverable** — clamp and record, keep going.
- **Expected-unknown** — skip and note.

SMAP-specific recovery rules:

- codec-2 RLE run length may overshoot remaining pixels → clamp to strip end.
- bitstream EOF mid-strip → fill remainder with last index.
- palette index out of range → clamp to 255.
- width not a multiple of 8 → decode `ceil(width/8)` strips, crop.
- unknown compression id → mark strip, fill, continue.

Processing is room-by-room to bound memory. Exit non-zero only if a whole phase
fails or found-counts miss expected-counts.

## 11. Verification

1. **Completeness** — found counts equal expected counts derived from `LOFF`
   and the tag inventory (rooms 96, backgrounds 96, objects 1372, costumes 240,
   fonts 5). Any miss fails the run.
2. **Integrity** — every output PNG reopens in Pillow, dimensions match the
   manifest, backgrounds are `P` mode with a 256-entry palette, `sha256`
   recorded; a second run is byte-identical.
3. **Anomaly triage** — every logged anomaly is classified; the run is not
   "done" while any is unexplained.
4. **Visual** — `contact_sheet_backgrounds.png` (96 labeled tiles) plus
   object/costume/font sheets for a one-glance glitch check.
5. **Optional independent oracle** — pixel-compare the 96 backgrounds against
   Ariutti's output (NEAREST-downscaled to native). Run when his tool is
   available; not a hard dependency.

## 12. Milestones

Each milestone is independently shippable with tests at every step.

| Milestone | Deliverable | Risk |
|---|---|---|
| M0 | `archive` + `palette` + `smap` with unit tests on synthetic strips | low |
| M1 | **96 background PNGs + manifest + contact sheet + report** (primary value) | low |
| M2 | 1372 object sprites with alpha | low |
| M3 | 240 costume sheets | medium (format unknown) |
| M4 | 5 charsets + inventory + UI provenance audit | partial by nature |

M1 first: highest value, lowest risk, existing oracle. M2 reuses the SMAP
decoder. M3 is isolated so an unknown cannot block the rest. M4 extracts what
exists and documents what does not.

## 13. Project setup

- Project root: `~/code/mine/atlantis-textures/` (new, `git init`).
- Game files are read in place from the `.app`; never copied or committed.
- The `.app` is code-signed and is never modified.

## 14. Legal

- Extracted and regenerated art is LucasArts/Disney copyright. **Personal use
  only; do not redistribute.** This constraint is repeated in the README.
- Tool code is ours. If ScummVM's GPL costume logic is ported, the tool becomes
  GPL-3.0; otherwise it stays permissive. Prefer implementing from format docs.
- Ariutti's tool has no license, so it is never copied — only optionally run
  externally as an oracle.

## 15. Open items

- Exact classic `COST` cel layout — resolved during M3 from the ScummVM v5
  costume path, pinned by a structural test and eyeballed on the costume sheet.
- Whether extra `IMxx` blocks sit under `RMIM` (multi-layer background) or
  `OBIM` (object) — resolved at parse time and tagged with `role` either way, so
  nothing is dropped.
- UI provenance — enumerated during M4; the report states exactly what is
  in-data versus engine-hardcoded.
