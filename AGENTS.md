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
  `POST /interrupt` for a timed-out prompt. After a failed room it deletes
  that room's own leftover renders (`comfy_client.sweep_outputs`, anchored to
  SaveImage's `<room_key>_<label>_NNNNN_.png` naming).
- **Unified memory.** vLLM holds about 73 GB and a render about 45 GB of the
  GB10's 121 GB. `batch` refuses below `MEMORY_FLOOR_GB` (45) unless
  `--no-memory-check`.
- **Atomic writes.** YAML and JSON go through `<name>.tmp` and a rename,
  images through `<name>.pending` and a rename.
- **Resumable by construction.** Caption skips filled entries. Batch derives
  each room's status from its audit folder (`atl_recreate.room_status`):
  `new`, `failed` (the latest attempt has no record), `rejected` (by geometry
  or review), `missing`, or `done`. It renders every room that is not `done`
  and not STUCK (rejected `MAX_ATTEMPTS` times), unless `--force`. A failed
  attempt keeps its number and its tiles.
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
5. `colour_match.match` toward the guide (`--match-strength`), then
   `apply_fixups`.
6. `geometry_check.check` (shift per room and per window, edge agreement,
   seam ratios relative to the guide's); promote on a pass.

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
  REFERENCE OBSERVATIONS (the caption), then corrections. `PAINTED_NEGATIVE`
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

`test_room_geometry.RealCorpusTests` pins the measured corpus: 91 plannable
rooms, room 58 the only wraparound at (840, 224) with margins
(0, 88, 28, 26), and room 85's side margin. It runs whenever
`../atlantis-textures/out` (or `ATL_SRC`) exists.

## 6. Live checks and the spike

Not run yet. Task 17 of the plan records the first live render of each graph
here; Task 18 records the spike's decisions (the default workflow and its
strength or denoise, the de-dither method, `REFERENCE`,
`WINDOW_WIDTH`/`WINDOW_OVERLAP`, `MIN_EDGE_AGREEMENT`, the colour-match
strength) with their evidence.
