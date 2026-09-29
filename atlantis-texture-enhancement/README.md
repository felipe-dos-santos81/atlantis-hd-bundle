# Atlantis Background Regeneration

Regenerates the 96 room backgrounds of *Indiana Jones and the Fate of
Atlantis* (LucasArts, 1992) as painted high-definition art at exactly 4x
their native size, with local models:

- ComfyUI running one of two render workflows, chosen per run: Qwen-Image 2.1
  img2img (`qwen-image-2.1-i2i`, the default, with `qwen-image-2.1-i2i-faithful`
  as its fallback for stuck rooms), or Qwen-Image-Edit 2511 with
  the InstantX Canny ControlNet (`qwen-edit-2511-canny`).
- vLLM serving `Qwen/Qwen3.8-27B`, which captions each room before rendering
  and reviews each render afterwards.

Input: `../atlantis-textures-exporter/out/` (override with `ATL_SRC`), the output of
`make exporter-extract`: indexed room PNGs and `manifest.json`.
Output: `data/rooms-ai/room_NNN.png` (override with `ATL_DST`).

**Personal use only.** The extracted and regenerated art is LucasArts/Disney
copyright. Do not redistribute it. `data/` is gitignored; never commit art.

## Pipeline

```
ATL_SRC ──[make enhancer-caption]──▶ rooms.yaml ──(you edit)──┐
            vLLM up                                   ▼
data/rooms-ai/ ◀──[make enhancer-batch]── rooms.yaml + reviews.yaml (rejects only)
   │               ComfyUI up, vLLM stopped
   └──[make enhancer-review]──▶ reviews.yaml   (vLLM up)
```

1. **`make enhancer-caption`** (vLLM up) describes every `scene` and `insert` room
   whose caption is blank and writes it into `rooms.yaml`, saving after each
   room. `force=1` redoes all; blanking one caption redoes that room.
2. **Edit `rooms.yaml`.** The caption becomes the REFERENCE OBSERVATIONS
   block of every window's prompt; an insert's `TEXT:` section becomes the
   lettering its render must reproduce.
3. **`make enhancer-batch`** (ComfyUI up, vLLM stopped) renders every captioned room
   whose output is missing or whose latest attempt was rejected (see Checks),
   and writes each `skip` room as a nearest-neighbour 4x. On exit, even after
   a failure, it frees ComfyUI's models so vLLM can start.
4. **`make enhancer-review`** (vLLM up) judges every promoted room whose latest attempt
   is unreviewed and writes `reviews.yaml`.
5. **`make enhancer-batch` again** redoes only the rejected rooms, with the next seed
   and the issues as corrections. Repeat 4 and 5.
6. **`make enhancer-verify`** audits `data/rooms-ai/`.

`make enhancer-dry-run` prints what `batch` would do (windows, wraparound, margins,
corrections) without touching ComfyUI.

## Swapping the services on this host

vLLM (about 73 GB) and a render (about 45 GB) do not fit together in the
GB10's 121 GB of unified memory.

| Service | Start | Stop |
|---|---|---|
| vLLM | `docker start lmcache-server vllm-server` | `docker stop vllm-server lmcache-server` |
| ComfyUI | `make enhancer-server` (foreground) or `sudo systemctl start comfyui` | Ctrl-C, or `sudo systemctl stop comfyui` |

`make enhancer-batch` refuses to start with less than 45 GB free (`memcheck=0` skips
the guard). If vLLM cannot start after a batch, free ComfyUI's models by hand:

```
curl -X POST http://127.0.0.1:8188/free -H 'Content-Type: application/json' -d '{"unload_models":true,"free_memory":true}'
```

## Rooms

`rooms.yaml` has one entry per manifest room:

```yaml
room_047:
  kind: insert        # scene | insert | skip
  caption: >-
    ...
```

- `scene`: a room or cutscene background.
- `insert`: a close-up with lettering, a map or a puzzle piece; its prompt
  adds the lettering rules and its review checks the lettering.
- `skip`: written as a nearest-neighbour 4x, never rendered. Shipped for rooms
  20, 68, 89, 90 and 98, which are each one flat colour.

## Wide rooms and room 58

A room wider than 320 native columns (1280 px at 4x) renders as overlapping
windows, left to right with one seed, each overlapping the last by at least
64 columns so the brushwork blends instead of seaming.

Room 58 wraps around (detected from its pixels): columns 840–1063 repeat
0–223, and its last 88 columns plus its top 28 and bottom 26 rows are flat
black. The kit renders the panorama plus one seam window across the join,
then copies the repeat and fills the flat margins from the source, so the
output repeats exactly where the game's art does.

## Checks

Before a render is promoted, `make enhancer-batch` colour-matches it toward its guide
in float CIE Lab (a render whose colours already agree comes back within one
level), then checks it:

- **Size:** exactly 4x native, RGB.
- **Geometry:** the render, box-downscaled to native size, must not be
  shifted by half a native pixel or more — over the room and within each
  window — and must keep most of the source's strong edges, per window
  (thresholds: AGENTS.md §3). A failure is written to `reviews.yaml` as
  `source: geometry`, and the next batch retries the room.
- **Seams:** a window boundary whose colour step is far more than the local
  texture's own step there is printed as a warning.

A rejected room's next attempts carry the rejection's issues as corrections
until one is promoted, even across a failed attempt in between; a geometry
rejection's correction is one fixed sentence asking the model to keep the
reference layout.

A room is **STUCK** when its latest judged attempt (one with a record — see
Outputs below) was rejected and it has had 4 judged attempts. With the
default workflow, the next batch renders it once more through
`qwen-image-2.1-i2i-faithful` (denoise 0.9 instead of 1.0: a cleaner
upscale that keeps closer to the source). If that is rejected too, batch
reports the room and leaves it alone. Fix its caption, then run
`make enhancer-batch room=N force=1`. A failed attempt (a ComfyUI error, a timeout, Ctrl-C) has no
record and never counts, so a room only failing on infrastructure is
retried on every run instead, and batch exits 1.

To restart a room from scratch, delete `data/rooms-ai/.quality/room_NNN/`
**and** its entry in `reviews.yaml` — a leftover entry becomes current again
once new attempts reach its attempt number — then run
`make enhancer-batch room=N force=1`.

## Outputs and the audit folder

```
data/rooms-ai/room_NNN.png            the promoted render
data/rooms-ai/.quality/room_NNN/
  attempt-N.png                       the raw stitch, before the colour match
  attempt-N.tiles/                    window-K.{guide,composite,mask}.png, window-K.png, seam.*
  attempt-N.prompt.txt                starts "workflow: NAME"; every window's prompt
  attempt-N.json                      seed, windows, wrap, margins, match, geometry, promoted, sha256, seconds
  attempt-N.error.txt                 a failed attempt: workflow, seed, window, seconds, error (no .json)
  attempt-N.review.json               the VLM verdict
```

## Commands

Run these from the repository root:

| Target | What it does |
|---|---|
| `make enhancer-caption [room=] [force=1]` | Write captions into `rooms.yaml` |
| `make enhancer-dry-run [room=] [workflow=] [strength=] [force=1]` | Show what `batch` would render |
| `make enhancer-batch [room=] [workflow=] [strength=] [memcheck=0] [force=1]` | Render and promote into `data/rooms-ai/` |
| `make enhancer-review [room=] [force=1]` | Write `reviews.yaml` |
| `make enhancer-verify [room=]` | Audit `data/rooms-ai/` |
| `make enhancer-server` | Start ComfyUI from `~/ComfyUI` on :8188 |
| `make enhancer-install` / `make enhancer-check` / `make enhancer-test` / `make enhancer-clean` | venv / byte-compile / unit tests / caches |

`room="1 29 58"` selects rooms by number; every stage target also takes
`src=DIR` and `dst=DIR`. Environment overrides: `ATL_SRC`, `ATL_DST`,
`ATL_ROOMS`, `ATL_REVIEWS`, `ATL_WORKFLOW`, `ATL_MATCH_STRENGTH`, `COMFY_URL`,
`COMFY_DIR`, `VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY`.

## Setup

- `make enhancer-install` creates `.venv` with Pillow, PyYAML and numpy.
- ComfyUI at `~/ComfyUI` (override with `COMFY_DIR`), at or after commit
  c194dd0 (2026-09-20), with these files under `models/`:
  - `qwen-edit-2511-canny`: `diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors`,
    `text_encoders/qwen_2.5_vl_7b_uncensored_comfy_ready_bf16.safetensors`,
    `vae/qwen_image_vae.safetensors`,
    `controlnet/Qwen-Image-InstantX-ControlNet-Union.safetensors`;
  - `qwen-image-2.1-i2i` and its fallback: `diffusion_models/qwen_image_2.1_bf16.safetensors`,
    `text_encoders/qwen3vl_8b_bf16.safetensors`,
    `vae/qwen_image_2.1_vae_bf16.safetensors`.

  `make enhancer-batch` checks the files and the node classes before rendering.
- vLLM serving `Qwen/Qwen3.8-27B` at `http://127.0.0.1:8000/v1`.

## Project structure

| File | Purpose |
|---|---|
| `atl_recreate.py` | Driver: `caption`, `batch`, `review`, `verify`; preflights, audit folders, promotion |
| `source_tree.py` | Reads and validates the extractor's `manifest.json` |
| `rooms_file.py` | `rooms.yaml` and `reviews.yaml` |
| `room_geometry.py` | Guide image, margins, wraparound, windows, composites, stitch, seam, fix-ups |
| `geometry_check.py` | The shift, edge and seam measures |
| `colour_match.py` | The Lab transfer of a render toward its source |
| `prompts.py` | Caption, render and review prompts; VLM requests; the review parser |
| `comfy_client.py` | ComfyUI HTTP client and the workflow registry; the only place that knows node ids |
| `recreation_qwen2511_canny.json`, `recreation_qwen21_i2i.json` | ComfyUI API graphs |
| `rooms.yaml` | Kinds and captions of the 96 rooms |
| `run_batch.sh`, `run_server.sh` | Wrappers (targets live in the root `Makefile`) |
| `testkit.py`, `test_*.py` | Test support and unit tests (no GPU, no network) |
| `docs/superpowers/` | Historical design spec and implementation plan (they predate the root `Makefile` target names) |
