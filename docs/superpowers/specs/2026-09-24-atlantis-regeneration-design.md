# Atlantis Background Regeneration — Design

Date: 2026-09-24
Status: approved for planning

## 1. Problem

Regenerate the 96 room backgrounds of *Indiana Jones and the Fate of Atlantis*
(1992, SCUMM v5), already extracted by `~/code/atlantis-textures` into
`out/indexed/rooms/`, as painted high-definition art at exactly 4x native size,
with local models driven through ComfyUI. The kit follows the design of
`~/code/aitd-texture-enhancement` (the *Alone in the Dark 1* kit): stages
joined by hand-editable YAML files, resumable runs, an audit trail per
attempt, deterministic post-processing and a vision-model review loop.

## 2. Decisions

| Question | Decision |
|---|---|
| What consumes the output | Nothing yet; the output is **re-import-safe**: pixel-aligned with the native room at exactly 4x, so the game's objects, actors, walk boxes and z-plane masks would still line up in a future engine or ScummVM fork |
| Target look | **Painted HD**: high-resolution hand-painted adventure-game art. Same colours, lighting and mood; dithering becomes brushwork |
| Room scope | **Scenes and inserts** are regenerated; placeholders are skipped and written as a nearest-neighbour 4x |
| Animation (palette colour cycling) | **Out of scope**; v1 renders stills |
| Architecture | **Approach A**: a new repo adapting the AITD kit; the driver tiles wide rooms into overlapping windows, each later window continuing its already-rendered neighbour through a latent noise mask |

Approaches rejected:

- **B, whole room then tiled upscale.** Scrolling rooms reach 8:1; Qwen-Image
  is trained up to about 16:9, and the upscale pass must tile anyway.
- **C, independent tiles blended.** Independently rendered brushwork does not
  agree in the overlaps; the painted look shows doubled or smeared detail.

## 3. Goals and non-goals

Goals:

- Every `scene` and `insert` room rendered, stitched, checked and promoted to
  `room_NNN.png` at exactly 4x native, RGB.
- Layout fidelity measured objectively (a deterministic geometry check), not
  only judged by a model.
- Every run resumable; every attempt kept for audit; nothing overwritten.
- Unit tests with no GPU and no network.

Non-goals (v1):

- Colour cycling, LTX or any video model.
- Object sprites, costumes, charsets (the extractor has not produced them).
- `make setup` and `make run`: ComfyUI is the existing `~/ComfyUI`; vLLM is
  started and stopped by the user.
- Palette or indexed output: painted HD needs full colour.
- Any change to `~/code/atlantis-textures` or the game files.

## 4. Source

`ATL_SRC`, default `../atlantis-textures/out`, read in place and never
written:

```
manifest.json                   assets[]: room, file, width, height, role, sha256, ...
indexed/rooms/room_NNN.png      P mode, exact 256-colour CLUT, native size
indexed/palettes/room_NNN.png   palette swatch (unused here)
```

Measured corpus (2026-09-24):

- 96 rooms, every one `role: background`, zero decode anomalies.
- Heights are 144 (a gameplay room; the verb bar sits below it) or 200
  (full-screen close-ups, cutscenes, maps).
- Widths are 320 to 1280 (scrolling rooms). 33 rooms are wider than 320;
  the widest are room 75 (1280x200), room 58 (1152x144), rooms 55 and 66 (960).
- Room 58 wraps around: columns 840–1063 repeat columns 0–223 exactly, and
  its last 88 columns are one flat colour. The real panorama is 840 wide.
  No other wide room repeats a span.
- Single-colour placeholder rooms: 20, 68 (320x200), 89, 90 (16x200),
  98 (8x200).
- Rooms 85–88 (labyrinth pieces) are about 55% flat black.
- The manifest carries no room names and no colour-cycle ranges.

`manifest.json` is the only authority on what exists. `source_tree.py` is its
only reader and refuses the tree (`SourceError`, naming the room and the
value) when a listed file is missing, is not P mode, disagrees with the
manifest's width or height, or fails its `sha256`.

## 5. Host and models

The GB10 host: about 121 GB of unified memory shared by CPU and GPU, 93 GB of
free disk. Nothing needs downloading:

| Use | File in `~/ComfyUI/models/` |
|---|---|
| Qwen-Image-Edit 2511 | `diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors`, `text_encoders/qwen_2.5_vl_7b_uncensored_comfy_ready_bf16.safetensors`, `vae/qwen_image_vae.safetensors` |
| Canny ControlNet | `controlnet/Qwen-Image-InstantX-ControlNet-Union.safetensors` |
| Qwen-Image 2.1 | `diffusion_models/qwen_image_2.1_bf16.safetensors`, `text_encoders/qwen3vl_8b_bf16.safetensors`, `vae/qwen_image_2.1_vae_bf16.safetensors` |
| Captions, review | `Qwen/Qwen3.8-27B` served by vLLM at `http://127.0.0.1:8000/v1` (weights in the Hugging Face cache) |

`~/ComfyUI` is at c194dd0 (2026-09-20), past the 6bfaacc commit the
`TextEncodeQwenImage21` node needs. vLLM (about 73 GB) and a render (about
45 GB) cannot be resident together; the user swaps them between stages.

## 6. Data files

### rooms.yaml (tracked, hand-owned)

One entry per manifest room, keyed `room_NNN`, shipped with every `kind`
filled:

```yaml
room_001:
  kind: scene          # scene | insert | skip
  caption: >-          # written by `make caption`, then the user's to edit
    ...
```

Shipped kinds:

- `skip`: 20, 68, 89, 90, 98.
- `insert`: 8 (passport), 9 and 47 (newspapers), 83 (book), 70 and 75 (maps),
  84–88 (the stone tablet and the labyrinth pieces).
- `scene`: every other room.

A room in the manifest with no entry, or an entry with an unknown `kind`, is
a validation error. Wraparounds and margins are not configured: they are
detected from the source pixels (section 9).

### reviews.yaml (gitignored, machine-written)

Per room: `attempt`, `accepted`, `issues`. Geometry rejections are written
here too, with `source: geometry`, so one file decides what `batch` retries.

## 7. Output contract

`ATL_DST`, default `data/rooms-ai/`:

```
room_NNN.png                          RGB, exactly 4x native width and height
.quality/room_NNN/
  attempt-N.png                       raw stitch, before colour match
  attempt-N.tiles/window-K.png        each window's render
  attempt-N.prompt.txt                starts "workflow: NAME"; the full prompts
  attempt-N.json                      seed, window plan, fix-ups, geometry and
                                      seam metrics, colour-match record, timings
```

Re-import-safe means geometry:

- Width and height exactly 4x native. RGB, no alpha.
- Every window passes the geometry check (section 10) before promotion.
- A wraparound's repeated span is byte-identical to its original at 4x.
- A blank margin is the source's flat colour.
- `skip` rooms are a nearest-neighbour 4x of the source (`workflow: nearest`),
  so the tree is complete for a future importer.

Nothing but these files is written to `ATL_DST`. Outputs are written as
`<name>.pending` and renamed; YAML and JSON as `<name>.tmp` and renamed.

## 8. Stages

```
ATL_SRC ──[make caption]──▶ rooms.yaml ──(user edits)──┐
            vLLM up                                     ▼
ATL_DST ◀──[make batch]── rooms.yaml + reviews.yaml (rejected attempts)
   │        ComfyUI up, vLLM stopped
   └──[make review]──▶ reviews.yaml
            vLLM up
```

1. **`make caption`** (vLLM up). For every `scene` or `insert` room whose
   `caption` is blank: the VLM sees the room at 2x (a wide room: the whole
   strip plus the window crops) and answers `CAPTION_QUESTION`: SCENE, VIEW,
   LAYOUT (left to right), OBJECTS, LIGHTING, PALETTE, TEXT (verbatim
   transcription of legible lettering; required for inserts, "none"
   otherwise), INVARIANTS. It is told backgrounds are empty stages: no people.
   Saves after each room. `force=1` redoes all; blanking one caption redoes
   that room.
2. **Edit `rooms.yaml`.**
3. **`make batch`** (ComfyUI up, vLLM stopped). For every selected room whose
   output or latest audit render is missing, or whose latest attempt
   `reviews.yaml` rejects: build the guide, plan the windows, render them in
   order, stitch, colour-match, apply the fix-ups, run the size and geometry
   checks, and promote only when every check passes. Refuses to start below
   45 GB free (`memcheck=0` skips the check). Calls ComfyUI `POST /free` on
   exit, after a failure too. `skip` rooms are written without ComfyUI.
4. **`make review`** (vLLM up). For each promoted room whose latest attempt is
   unreviewed: the source guide and the render per window, plus the whole room
   downscaled; records the verdict. `force=1` reviews again.
5. **`make batch` again** redoes only the rejected rooms: next seed, the
   issues appended as corrections. Repeat 4 and 5.
6. **`make verify`** audits `ATL_DST` against the manifest, the size rule and
   the recorded geometry results.
7. **`make dry-run`** prints each room's kind, window plan, fix-ups, workflow
   and whether `batch` would render it. It never touches ComfyUI and always
   exits 0.

Every stage target also takes `room="1 29 58"`, `force=1`, `src=DIR` and
`dst=DIR`; `batch` and `dry-run` also take `workflow=NAME` and `strength=X`. `make server` starts `~/ComfyUI`
(`COMFY_DIR`); `make check`, `make test` and `make clean` as in AITD.
Environment overrides: `ATL_SRC`, `ATL_DST`, `ATL_ROOMS`, `ATL_REVIEWS`,
`ATL_WORKFLOW`, `ATL_MATCH_STRENGTH`, `COMFY_URL`, `COMFY_DIR`,
`VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY`.

The driver never starts or stops a service. It checks that `GET /v1/models`
lists `VLM_MODEL`, and its only state-changing ComfyUI calls are `POST /free`
and `POST /interrupt` for a timed-out prompt.

## 9. Render core

### 9.1 Guide image

Per room, deterministic:

1. Indexed to RGB through the room's exact palette.
2. De-dither at native size with an edge-preserving filter. Two candidates,
   chosen by the spike:
   - **palette-aware smoothing**: each pixel becomes the mean of its 3x3
     neighbours whose colour lies within a distance threshold of it, so
     checkerboard dithering melts and edges survive;
   - **median 3x3**.
3. Upscale 4x with Lanczos.

The guide is the reference image, the Canny input and the img2img start.
Canny on the raw source would fire on every dither dot.

### 9.2 Source analysis

- **Blank margins**: maximal runs of whole columns (from the left or right
  edge) or whole rows (from the top or bottom edge) whose every pixel is one
  and the same palette index. Excluded from rendering; written as that flat
  source colour.
- **Wraparound**: the smallest `P` such that columns `[P, P+k)` equal columns
  `[0, k)` in at least 99.9% of pixels, with `k ≥ 64`. The render span becomes
  `[0, P)`. Room 58: `P = 840`, `k = 224`.

### 9.3 Window plan

- Windows are full height and at most `Wt` native columns wide (default 320).
- Adjacent windows overlap by at least `Ov` native columns (default 64, which
  is 256 px at 4x).
- `n = ceil((span − Ov) / (Wt − Ov))` windows, spaced evenly, every start
  rounded to a multiple of 8 native, the last flush with the span's end.
- A span of at most `Wt` is one window of the span's width.
- Every 4x window size is a multiple of 32: widths are multiples of 8 native,
  and heights are 144 or 200 (576 or 800 at 4x).

### 9.4 Rendering

- Windows render left to right with one seed per attempt (attempt N uses
  `42 + N − 1`), shared by every window of the room.
- **Window 1** renders fresh.
- **Window K > 1**: the input is the guide window with its overlap columns
  replaced by the stitch so far. The noise mask is 0 over the outer half of
  the overlap (held), ramps from 0 to 1 across the inner half, and is 1 over
  the new columns. The graph applies it with `SetLatentNoiseMask` and
  `DifferentialDiffusion`, so the new brushwork continues the neighbour's.
  The stitch takes window K's pixels from the overlap's inner half onward.
- **Wrap seam** (a wraparound room only): after `[0, P)` is stitched, one
  seam window renders the rolled strip `[P − Wt/2, P) + [0, Wt/2)`, holding its
  outer quarters and regenerating the middle half, and writes the result back
  to both ends.
- **Fix-ups**, after the colour match: the 4x columns `[0, k)` are copied onto
  `[P, P+k)`, and margins are filled with the flat source colour.

### 9.5 Workflows

`comfy_client.WORKFLOWS` holds both graphs. Each receives a window image, a
composite and mask, the prompts, a seed and a size; the record names the node
ids, model files and node classes, as in AITD.

- **`qwen-edit-2511-canny`**: the guide window as the
  `TextEncodeQwenImageEditPlus` reference; Canny of the guide window into the
  InstantX Union ControlNet (type canny; strength and step schedule are
  tunables in the JSON); latent = VAE-encoded composite with the noise mask,
  denoise 1.0.
- **`qwen-image-2.1-i2i`**: the guide window as `images.image_1` of
  `TextEncodeQwenImage21` (addressed by that container path, per the AITD
  finding); latent = VAE-encoded composite with the noise mask, KSampler
  denoise `d` (spike range 0.5–0.8), cfg 1.0.

The spike picks the default (`DEFAULT_WORKFLOW`). `workflow=` selects per run.
Preflight checks the record's model files on disk and `GET /object_info/<class>`
for each node class, so a missing model or old ComfyUI fails before rendering.

### 9.6 Prompts

- **Positive** = `PAINTED_RULES` (a hand-painted high-definition adventure-game
  background with visible brushwork; the reference's exact composition,
  perspective and colours; nothing added or removed; no people) + the caption
  + for a multi-window room a window note ("this window is x–y% of a wide
  room; paint only what the reference shows") + for an insert "reproduce this
  lettering exactly:" with the caption's TEXT + corrections from a rejected
  attempt.
- **Negative** = `PAINTED_NEGATIVE`: photograph, photorealistic, 3D render,
  pixel art, dithering, JPEG artefacts, people, characters, altered or extra
  text.

### 9.7 Colour match

After stitching, before the fix-ups: the render's Lab mean and spread are
pulled toward its own guide's (rule `source-relative`), blended by `strength`
(0 to 1; default set by the spike). There are no anchors or groups: the
painted look keeps the game's colours, and every room of a location already
shares the game's palette. Reuses AITD's `colour_match` Lab helpers. The raw
stitch stays in the audit folder; the record names rule and strength.

## 10. Quality gates

Run inside `make batch`, in this order, before promotion:

1. **Size**: exactly 4x native width and height, RGB, no alpha.
2. **Geometry** (the re-import-safe gate). The colour-matched render is
   box-downscaled to native and compared with the de-dithered source:
   - **Shift**: phase correlation over the whole room and per window must be
     under 0.5 native px.
   - **Edge agreement**: of the source's strong edges (Sobel magnitude over
     `EDGE_THRESHOLD`, one constant applied to both images), the fraction
     with a render edge within 1 native px must be at least `τ` (starting
     value 0.80). The spike calibrates both constants. This measures recall
     of the source's edges only, so added brushwork is not penalised.
   - **Fix-ups**: repeated spans byte-identical, margins flat.
3. **Seams** (multi-window rooms): at each boundary, the colour and texture
   energy step across the boundary against the variation inside each window.
   A high ratio is a printed and recorded warning, not a rejection.

A size failure fails the room. A geometry failure writes a rejection to
`reviews.yaml` (`source: geometry`, with issues such as `shifted 1.3 px in
window 2` or `edge agreement 0.71`) and the room is not promoted; the next
`batch` retries it. After `max_attempts` (default 4) a room stays rejected and
`batch` reports it instead of retrying.

4. **Review** (`make review`, Qwen3.8-27B). `REVIEW_QUESTION` returns
   `{"accepted": bool, "issues": [str]}`, parsed by AITD's tolerant parser,
   which rejects contradictory verdicts. Rubric, in priority order:
   1. layout and objects match the source: nothing added, dropped or moved;
      any person or character counts as added;
   2. painted HD: neither a photograph or 3D render, nor the source's flat,
      dithered pixels;
   3. inserts: lettering matches the caption's TEXT and is legible where the
      source is;
   4. no visible seams, doubled objects or repeated detail across windows.

Review judges the promoted output. A room without a promoted output is not
reviewed.

## 11. Modules

| File | Owns | Must not |
|---|---|---|
| `atl_recreate.py` | CLI and stages (`caption`, `batch`, `review`, `verify`, `dry-run`), selection flags, preflights, audit folders, promotion | know node ids or YAML syntax |
| `source_tree.py` | reading and validating `manifest.json`; rooms, kinds, selection | talk to services or write files |
| `room_geometry.py` | guide, de-dither, margins, wrap detection, window plan, composites and masks, stitch, fix-ups | talk to services |
| `geometry_check.py` | shift, edge agreement, seam metrics (numpy) | know files, rooms or the audit tree |
| `rooms_file.py` | `rooms.yaml` and `reviews.yaml`: shape, folded style, validation, atomic save | do I/O beyond its own files |
| `colour_match.py` | Lab statistics and the `source-relative` transfer on Pillow images | know rooms or files |
| `comfy_client.py` | ComfyUI HTTP, the workflow registry, node ids, staging into `input/`, output lookup, interrupt and sweep | decide what to render |
| `prompts.py` | caption, render and review prompts, VLM payloads, `parse_review`, `vlm_is_serving` | know files or make targets |

Other files: `recreation_qwen2511_canny.json` and `recreation_qwen21_i2i.json`
(ComfyUI API graphs), `rooms.yaml`, `Makefile`, `run_server.sh`, `testkit.py`,
`test_*.py`, `README.md` (user view, with the personal-use notice),
`AGENTS.md` and `CLAUDE.md` (agent view), `pyproject.toml` (Pillow, PyYAML,
numpy).

## 12. Error handling

- **Source**: `SourceError` on any manifest disagreement; the run refuses to
  start.
- **Preflight**: ComfyUI not answering, a missing model file, a missing node
  class, or less memory than the floor: exit 1 before any render. vLLM not
  listing the model: `caption` and `review` exit 1.
- **Window failure** (HTTP error, ComfyUI execution error, timeout): the whole
  room fails for this attempt. Rendered windows stay in the audit folder; the
  next attempt restarts the room from window 1. On timeout the driver sends
  `POST /interrupt` for that prompt and deletes that room's own leftover
  output files, matched on ComfyUI's exact `SaveImage` naming.
- **Room isolation**: one room's failure never stops the others. `batch` exits
  1 if any room failed or stayed rejected at `max_attempts`.
- **Resumability**: caption skips filled entries; batch skips a room whose
  output and latest audit render exist unless its latest attempt is rejected;
  attempt numbers continue from the audit folder; a crash leaves only
  `.pending` or `.tmp` files, which the next run replaces.

## 13. Testing

`unittest`, no GPU, no network. `make test` runs every `test_*.py`;
`make check` byte-compiles every module.

- `testkit.py` is the single shared test support: a miniature extractor
  output (indexed PNGs with palettes and a manifest, including a 320x144
  room, a 568x144 two-window room, a wraparound room with a blank margin, and
  a placeholder), `comfy_stub` and `vlm_stub` context managers, and `run_cli`.
- Pure-function tests: window plans (spans, 8-column starts, multiples of 32,
  single window), wrap and margin detection on synthetic strips, composites
  and masks, stitch and fix-ups (the repeated span byte-identical), geometry
  metrics (an identical render passes; one shifted 2 px fails; added texture
  alone does not fail edge agreement), colour match, YAML round-trip and
  validation, the review parser, each registry record against its graph's
  node ids.
- CLI tests cover orchestration: selection, skip and retry rules, window order,
  promotion only after every gate, geometry rejections written to
  `reviews.yaml`, `max_attempts`, `/free` on exit after a failure.
- One test module per production module; a rule is tested once, at the layer
  that owns it; data-only variations are one `subTest` table; a regression
  test names the bug it guards.

## 14. Spike

The first task after the scaffolding, before any full batch. Rooms:

| Room | Why |
|---|---|
| 1 | 320x200 interior, one window |
| 29 | 568x144 street, two windows |
| 58 | the wraparound: tiling, the seam window, the fix-ups |
| 47 | newspaper insert: the headline "German Wizard Splits Atom" |
| 52 | dark Atlantis stone |

Grid: `qwen-edit-2511-canny` at ControlNet strength 0.7 and 0.9;
`qwen-image-2.1-i2i` at denoise 0.6 and 0.75. Measure time and peak memory per
window. Decide and record in `AGENTS.md` (with the evidence, as AITD recorded
its 2026-09-20 spike):

- the default workflow and its denoise or ControlNet strength;
- the de-dither filter;
- `Wt` and `Ov`;
- whether a continuation window's reference image is the guide window or the
  composite (the composite shows the model the painted overlap);
- `τ`, from the geometry scores of renders judged good and bad by eye;
- the default colour-match strength.

A graph is only validated by rendering it: every new or edited graph renders
one room before it is trusted.

## 15. Risks and open items

- **Flat black voids.** Rooms 85–88 are about 55% flat black; the model may
  paint texture into them. Edge agreement will not catch that. Watch in the
  spike; if it happens, add a flat-region preserve rule (large single-index
  regions restored from the source) as a follow-up.
- **Captions for wide rooms.** One caption per room describes objects outside
  a given window. The window note and the image guidance should keep the model
  from painting them in; the spike confirms this on rooms 29 and 58.
- **Insert lettering.** Body text in the newspapers is illegible in the source
  and should stay illegible texture; only legible lettering is transcribed.
- **Non-square pixels.** The game displays 320x200 on a 4:3 screen, so pixels
  are 1.2 tall. The output keeps native geometry at 4x; aspect correction stays
  the display's job, as the source art already assumes.

## 16. Legal

The extracted and regenerated art is LucasArts/Disney copyright. Personal use
only; do not redistribute. `ATL_DST` (`data/`) is gitignored and the README
repeats this notice.
