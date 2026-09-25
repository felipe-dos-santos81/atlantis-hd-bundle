# AGENTS.md

Guidance for agents working on the *Fate of Atlantis* background
regeneration kit. README.md is the user view; this is the agent view. The
design is `docs/superpowers/specs/2026-09-24-atlantis-regeneration-design.md`
and the build plan `docs/superpowers/plans/2026-09-24-atlantis-regeneration.md`.

## 1. Architecture

| Stage | Command | Service | Reads | Writes |
|---|---|---|---|---|
| Caption | `atl_recreate.py caption` | vLLM `:8000` | the source rooms | captions in `rooms.yaml` |
| Batch | `atl_recreate.py batch` | ComfyUI `:8188` | `rooms.yaml`, `reviews.yaml`, the workflow template | `data/rooms-ai/`; geometry rejections in `reviews.yaml` |
| Review | `atl_recreate.py review` | vLLM `:8000` | source and output | `reviews.yaml` |

`verify` audits the output tree.

Rules that must survive any change:

- **The source is atlantis-textures' output**, read in place from `ATL_SRC`.
  `source_tree` is its only reader, and `manifest.json` decides which rooms
  exist. Never write under `ATL_SRC`; never parse paths for meaning.
- **Re-import-safe means geometry.** Every output is exactly 4x native, RGB,
  pixel-aligned with its room. A wraparound's repeat is byte-identical to the
  room's start, flat margins are the source colour, and no render is promoted
  without passing `geometry_check`. Do not loosen the gate to get a room
  through: fix its caption or its settings.
- **Services are external.** The driver never starts or stops vLLM or ComfyUI.
  It checks `GET /v1/models` and `GET /queue`. Its only state-changing ComfyUI
  calls are `POST /free` (at the end of batch and the start of review) and
  `POST /interrupt` (sent only by `comfy_client`) for a prompt that timed out
  or was stopped with Ctrl-C. After a failed or Ctrl-C'd room it deletes that
  room's own leftover renders (`comfy_client.sweep_outputs`, anchored to
  SaveImage's `<room_key>_a<attempt>-<label>_NNNNN_.png` naming). The attempt
  in the ComfyUI-facing name keeps ComfyUI's cache from answering a rerun
  with an old render; the audit tiles keep the plain `window-K` and `seam`
  names.
- **Unified memory.** vLLM holds about 73 GB and a render about 45 GB of the
  GB10's 121 GB. `batch` refuses below `MEMORY_FLOOR_GB` (45) unless
  `--no-memory-check`.
- **Atomic writes.** YAML and JSON go through `<name>.tmp` and a rename,
  images through `<name>.pending` and a rename.
- **Resumable by construction.** Caption skips filled entries. Batch derives
  each room's status from its audit folder (`atl_recreate.room_status`):
  `new`, `stuck`, `failed` (the latest attempt has no record), `rejected` (by
  geometry or review), `missing`, or `done`. It renders every room that is
  not `done` and not `stuck`, unless `--force`. A room is `stuck` when its
  latest judged attempt (one with a record) was rejected and it has
  `MAX_ATTEMPTS` judged attempts; failed attempts never count, so a room that
  keeps failing on infrastructure is retried on every batch (exit code 1). A
  stuck room whose workflow names a `fallback` (`fallback_for`) is rendered
  once more through it on the next batch, and reported STUCK only once that
  attempt is rejected too. A failed attempt keeps its number and its tiles.
  The next attempt's corrections (`corrections_for`) are the current review's
  issues while no later attempt was promoted, whatever the attempts since
  became; a geometry rejection gives the one `prompts.GEOMETRY_CORRECTION`
  sentence instead of the gate's strings. A review of an attempt later than the audit
  folder's latest is stale (`current_review`) and ignored.
- **Renders never depend on other rooms.** A room is consistent within itself
  through the window continuation, and with other rooms through each room's
  colour match toward its own source.
- **Only `comfy_client` knows node ids.**

## 2. Modules

| File | Owns | Must not |
|---|---|---|
| `atl_recreate.py` | CLI and stages, selection, preflights, audit folders, promotion | know node ids or YAML syntax |
| `source_tree.py` | reading and validating `manifest.json`; rooms, selection | talk to services or write files |
| `room_geometry.py` | guide, de-dither, margins, wraparound, windows, composites and masks, stitch, seam, fix-ups | talk to services or know files |
| `geometry_check.py` | shift, edge agreement, seam ratio | know files, rooms or the audit tree |
| `rooms_file.py` | `rooms.yaml` and `reviews.yaml`: shape, validation, folded style, atomic save | do I/O beyond its own files |
| `colour_match.py` | Lab statistics and the `source-relative` transfer | know rooms or files |
| `comfy_client.py` | ComfyUI HTTP, the workflow registry, node ids, staging, output lookup, interrupt, sweep | decide what to render |
| `prompts.py` | caption, render and review prompts, VLM payloads, `parse_review`, `vlm_is_serving` | know files or make targets |

## 3. The render path

Per room (`atl_recreate.render_room`):

1. `room_geometry.build_guide`: indexed to RGB, de-dithered at native size
   (`DEDITHER_METHOD`), upscaled 4x with Lanczos.
2. `room_geometry.plan_room`: margins, wraparound, the render span, the
   windows.
3. Each window, left to right: `window_inputs` (guide crop, composite, mask),
   `comfy_client.render_window`, `paste_window`.
4. A wraparound: `seam_inputs`, `render_window`, `apply_seam`.
5. `finish_room`: `colour_match.match` toward the guide
   (`--match-strength`; a float sRGB to CIE Lab (D65) transform in numpy,
   exact for every 24-bit colour, where Pillow's 8-bit Lab moved saturated
   colours up to 39 levels), then `apply_fixups`, then
6. `geometry_check.check`: shift per room and per window; edge agreement per
   room and per window (the room's edge maps masked to the window's columns),
   with hysteresis: a source edge is strong above `EDGE_THRESHOLD` (80) and
   kept by a render edge above `RENDER_EDGE_THRESHOLD` (60)
   within 1 px; a window with fewer than `MIN_WINDOW_EDGES` (100) strong
   source edge pixels reads 1.0; seam ratios relative to the guide's.
   Promote on a pass; a rejection goes to `reviews.yaml` as `source: geometry`.

A render that raises (a ComfyUI error, a timeout, a wrong-size window,
Ctrl-C) writes `attempt-N.error.txt` (workflow, seed, window, seconds,
error) and no `attempt-N.json`, so the attempt reads as failed. Batch then
sweeps the room's stray outputs; on Ctrl-C `comfy_client` has already sent
`/interrupt`, and batch re-raises after the sweep and `/free`. Failed
attempts never count toward STUCK, and the next attempt still carries the
current review's corrections (see §1).

Node ids in `recreation_qwen2511_canny.json`: 1 LoadImage (the guide window,
also the Canny input), 2 LoadImage (the composite), 3 LoadImageMask (red),
4 CLIPLoader, 5 UNETLoader (2511 fp8), 6 VAELoader, 7 DifferentialDiffusion,
9/10 positive/negative TextEncodeQwenImageEditPlus (`image1` is the
reference), 11 VAEEncode (the composite), 12 SetLatentNoiseMask, 13 KSampler
(40 steps, cfg 3.0, denoise 1.0), 14 VAEDecode, 15 SaveImage,
22 ModelSamplingAuraFlow, 23 CFGNorm, 30 Canny (0.4/0.8), 31 ControlNetLoader,
32 SetUnionControlNetType (canny), 33 ControlNetApplyAdvanced (strength 0.7,
0–65% of the steps).

Node ids in `recreation_qwen21_i2i.json`: 1 LoadImage (the guide window),
2 LoadImage (the composite), 3 LoadImageMask (red), 4 CLIPLoader (qwen3vl_8b),
5 UNETLoader (2.1 bf16), 6 VAELoader, 7 DifferentialDiffusion,
9 TextEncodeQwenImage21 (prompt, negative_prompt, resolution 0,
`images.image_1` is the reference), 11 VAEEncode (the composite),
12 SetLatentNoiseMask, 13 KSampler (40 steps, cfg 1.0, denoise 1.0),
14 VAEDecode, 15 SaveImage. Its fallback, `qwen-image-2.1-i2i-faithful`, is
the same graph with the registry's `settings` writing denoise 0.9 into node 13.

The 2.1 encoder's reference slot is an autogrow input and must be addressed
as `images.image_1`: the AITD kit's live render showed the flat `image_1`
arrives as an unexpected keyword and kills the render. `resolution: 0` relies
on every window being a multiple of 32 in both dimensions, which `plan_room`
guarantees.

**A graph is only validated by rendering it.** The template tests check each
graph against its registry record, not against ComfyUI's real node schemas.
Render one room through any new or edited graph before trusting it.

## 4. Prompts

- `CAPTION_QUESTION`: SCENE, VIEW, LAYOUT (left to right, as fractions of the
  room's width), OBJECTS, LIGHTING, PALETTE, TEXT (legible lettering verbatim,
  or none), INVARIANTS; under 600 words; "no people" unless painted in.
- The positive prompt (`render_prompt`) is `PAINTED_RULES` (with the
  workflow's reference phrase), then the insert rules (the caption's TEXT as
  LETTERING when present), then the window note for a multi-window room, then
  REFERENCE OBSERVATIONS (the caption), then corrections (the review's
  issues, or `GEOMETRY_CORRECTION` after a geometry rejection). `PAINTED_NEGATIVE`
  goes to the negative encoder: 2511's node 10, and 2.1's node 9
  `negative_prompt` (ignored at cfg 1).
- `REVIEW_QUESTION` sends (guide window, render window) pairs and the whole
  render, and returns `{"accepted", "issues"}`. `parse_review` tolerates
  fences and chatter, and refuses contradictory verdicts.

## 5. Testing

```bash
make check   # py_compile every module
make test    # unittest discover: every test_*.py
```

Tests never touch the network or the GPU. `testkit.py` is the one shared
test-support module:
- the miniature source: `make_source`, and `DEFAULT_ROOMS`, which holds a
  one-window room, a two-window room, a room-58-shaped wraparound and a flat
  placeholder;
- `write_rooms` and `run_cli`;
- `fake_render`, which "renders" a window as its own composite, optionally
  through a transform such as `shift_right`;
- `comfy_stub` and `vlm_stub`.

Never re-implement these in a test module.

Rules:
- one test module per production module;
- data-only variations are one `subTest` table;
- keep the suite small: a test covers one behaviour, and the facets of one
  run are asserted in one test; add a separate test only for a different
  behaviour or a named regression;
- a rule is tested once, at the layer that owns it;
- a regression test names what it guards.

Two test classes run on the real corpus, whenever `../atlantis-textures/out`
(or `ATL_SRC`) exists; `testkit.REAL_SRC`, `testkit.needs_real_corpus` and
`testkit.real_rooms()` are their one definition of it:
- `test_room_geometry.RealCorpusTests` pins the measured corpus: 91 plannable
  rooms, room 58 the only wraparound at (840, 224) with margins
  (0, 88, 28, 26), and room 85's side margin.
- `test_atl_recreate.RealCorpusTests` pins the gate: each of the 91 rooms'
  own guide, through `finish_room` at `DEFAULT_MATCH_STRENGTH`, passes
  `geometry_check.check` with its windows and boundaries (a perfect render
  of any real room is promotable). Measured at the fix wave: every room and
  every window agrees 1.0; without the hysteresis room 95 agrees 0.27. It
  takes about 20 s, most of it the colour match.

## 6. Live checks and the spike

**Live check (2026-09-24, GB10).** Both graphs render, which the template
tests could not prove; no graph fix was needed. vLLM (`Qwen/Qwen3.8-27B`,
570 s to load) captioned the spike rooms 1, 29, 47, 52, 58, 85 and 95 with no
failures. Five captions needed a hand correction against the room image:
- room 1 has a pot-bellied stove, not a "cylindrical tank";
- room 47's portrait caption is "Dr. Hans Ubermann", which the VLM read as
  "Debian: Dreemann";
- room 52's skeleton is painted in, and its blue-green shaft is a waterfall;
- room 58's "two human figures" are two dark-red Minoan columns;
- room 95 is the open sea, not an "abstract texture".

Read every caption before a batch.

Seed 42, match strength 0.5:
- `qwen-edit-2511-canny`, room 1: 309.5 s a window. Rejected by the gate:
  shift −0.96, +0.80 native px over the room and its window; edge agreement
  0.88. It is a faithful painted HD repaint, slightly displaced: the drift the
  gate exists to catch.
- `qwen-image-2.1-i2i`, room 1: 65.3 s a window. Promoted: shift +0.003,
  −0.005; edge agreement 1.0. At denoise 0.6 it reads as a clean upscale more
  than a repaint.
- `qwen-image-2.1-i2i`, room 29 (two windows): 41.9 s a window. Promoted:
  window shifts under 0.01 px, window agreements 0.9999, seam ratio 1.18. The
  second window continues the first one's painting across the overlap
  (native columns 248–320) with no visible join.

**Spike (2026-09-24, GB10).** Rooms 1, 29, 47, 52, 58, 85 and 95, seed 42,
match strength 0.5, vLLM stopped; the lowest MemAvailable while rendering was
71.9 GB. Shift is the worst over the room and its windows, in native px; edge
is the lowest room or window agreement.

| Variant | Rooms | s a window | Promoted | Worst shift | Lowest edge |
|---|---|---|---|---|---|
| `qwen-edit-2511-canny`, strength 0.7 | all | 245–290 | 29, 47 | 1.0 (58's window 2: 2.1) | 0.88 (room 1); room 95 0.05 |
| `qwen-edit-2511-canny`, strength 0.9 | all | 247–293 | 29, 47 | 1.0 (58's window 2: 2.0) | 0.89 (room 1); room 95 0.05 |
| `qwen-image-2.1-i2i`, denoise 0.6 | all | 39–57 | all | 0.01 | 1.00 |
| `qwen-image-2.1-i2i`, denoise 0.75 | all | 39–55 | all | 0.02 | 1.00 |
| `qwen-image-2.1-i2i`, denoise 0.9 (chosen) | all | 39–55 | all | 0.06 | 0.999 |
| 2.1 0.9, `DEDITHER_METHOD = "gaussian"` | 1, 52, 85 | 39–55 | all | 0.34 (room 52) | 1.00 |
| 2.1 0.9, `REFERENCE = "composite"` | 29, 58 | 39–42 | all | 0.04 | 0.999 |
| 2.1 0.9, `WINDOW_WIDTH = 256` | 29, 58 | 32–33 | all | 0.06 | 0.999 |

- 2511 repaints in the painted HD look but drifts 0.4–2 native px in rooms
  1, 52, 58 and 85 at either strength, and invents: room 1's door loses its
  glass and gains light shafts and a tool, and room 95's waves are replaced
  (edge 0.05; its +31, +16 px shift is phase correlation misreading the
  texture). The ControlNet strength does not move the drift.
- 2.1 holds the geometry at every denoise but stays close to the guide: its
  raw stitches differ from the Lanczos guide by 2–4 levels (mean absolute)
  against 2511's 6–15, and at 0.9 a window with an all-white mask moves 3.8
  levels from its composite. The reference image (`images.image_1`, the
  guide) pins the output more than the denoise does.

Decisions: the user picked the first six from the sheets; the last follows
from the calibration.
- `DEFAULT_WORKFLOW = "qwen-image-2.1-i2i"`: the only family that passes the
  gate. Its denoise went from 0.9 to 1.0 after the look probes below, with
  0.9 as the stuck rooms' fallback.
- `DEDITHER_METHOD` stays `"palette-smooth"`: gaussian is softer and loses
  fine detail such as room 52's cracks.
- `REFERENCE` stays `"guide"`: the composite reference looked the same on
  rooms 29 and 58.
- `WINDOW_WIDTH` stays 320: 256 is about 20% faster a window but takes more
  windows and invented a small object in room 29.
- `DEFAULT_MATCH_STRENGTH` stays 0.5.
- `RENDER_EDGE_THRESHOLD` stays 60. Every spike render re-checked at 40, 60
  and 75: every 2.1 render agrees 0.99 or more at 40 and 60, but room 95's
  drop to 0.73–0.87 at 75. 40 gains nothing here and is less of a gate: one
  window blurred with radius 8 at 4x was caught in 20 of the 33 multi-window
  rooms at 60, but in 3 at 40.
- `MIN_EDGE_AGREEMENT` stays 0.80. Edge agreement does not separate good from
  bad: 2511's drifting renders agree 0.88–0.99 (0.05 only on room 95), and
  its promoted rooms 29 and 47 agree 1.00 like the 2.1 renders. The shift
  gate catches the drift.

**Look probes (2026-09-25, GB10).** The same rooms and settings, 2.1 only:

| Variant | Promoted | s a window | Look |
|---|---|---|---|
| denoise 0.95 | all | 37–55 | the same soft upscale as 0.9 |
| denoise 1.0 | 1, 47, 85, 95 | 40–59 | painted HD; room 1 a faithful repaint (edge 0.99) |
| denoise 0.9, no reference image | none | 33–47 | painted, layout lost: shifts up to 92 px, edge 0.04–0.97 |

At 1.0, room 29's second window invented a flower stall and a gate (edge
0.74), room 52 shifted 0.9 px and room 58 3.1 px; the gate caught each. The
look changes all at once between 0.95 and 1.0, and without the reference
image nothing holds the layout, even at 0.9. The user chose denoise 1.0, with retries on new seeds and one
attempt at 0.9 for a room still rejected after `MAX_ATTEMPTS`.
