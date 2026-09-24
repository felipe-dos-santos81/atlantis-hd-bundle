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
  failed attempt keeps its number and its tiles. The next attempt's
  corrections (`corrections_for`) are the current review's issues while no
  later attempt was promoted, whatever the attempts since became; a
  geometry rejection gives the one `prompts.GEOMETRY_CORRECTION` sentence
  instead of the gate's strings. A review of an attempt later than the audit
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
   kept by a render edge above `RENDER_EDGE_THRESHOLD` (`EDGE_THRESHOLD / 2`)
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
12 SetLatentNoiseMask, 13 KSampler (40 steps, cfg 1.0, denoise 0.6),
14 VAEDecode, 15 SaveImage.

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

Not run yet. Task 17 of the plan records the first live render of each graph
here; Task 18 records the spike's decisions (the default workflow and its
strength or denoise, the de-dither method, `REFERENCE`,
`WINDOW_WIDTH`/`WINDOW_OVERLAP`, `MIN_EDGE_AGREEMENT`, the colour-match
strength) with their evidence.

- Include room 95 in the spike. It is the corpus's weakest-edge room: a
  320x200 all-texture sea whose 122 strong source edge pixels nearly all sit
  just over `EDGE_THRESHOLD` (98% between 80 and 110). Its own guide agreed
  0.27 before `RENDER_EDGE_THRESHOLD`, 0.64 with a render threshold of 75 and
  0.96 at 70; the spike's calibration of `RENDER_EDGE_THRESHOLD` and
  `MIN_EDGE_AGREEMENT` must keep a good render of it promotable.
