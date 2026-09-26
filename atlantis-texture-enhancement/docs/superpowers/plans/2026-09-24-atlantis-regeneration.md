# Atlantis Background Regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `~/code/atlantis-texture-enhancement`, a kit that regenerates the 96 *Indiana Jones and the Fate of Atlantis* room backgrounds as painted high-definition art at exactly 4x their native size through ComfyUI, with a deterministic geometry gate and a vLLM caption and review loop.

**Architecture:** Flat Python modules adapted from `~/code/aitd-texture-enhancement`: pure units for the source manifest (`source_tree`), the YAML files (`rooms_file`), room geometry (`room_geometry`), the geometry gate (`geometry_check`), colour (`colour_match`), prompts (`prompts`) and ComfyUI (`comfy_client`), driven by one CLI (`atl_recreate.py`) whose stages are make targets. The driver cuts each room into overlapping 4x windows; every later window continues its already-rendered neighbour through a latent noise mask; a wraparound room gets one seam window; the stitch is colour-matched toward its own source, fixed up, and checked before it is promoted.

**Tech Stack:** Python 3.12, Pillow, PyYAML, numpy, stdlib `urllib` and `unittest`; ComfyUI at `~/ComfyUI` (Qwen-Image-Edit 2511 with the InstantX Union ControlNet, Qwen-Image 2.1); vLLM serving `Qwen/Qwen3.8-27B`.

**Spec:** `docs/superpowers/specs/2026-09-24-atlantis-regeneration-design.md`. Read it before Task 1; "spec §N" below points into it.

**Reference kit:** `~/code/aitd-texture-enhancement`. Several modules here adapt its `comfy_client.py`, `recreation_quality.py`, `captions_file.py`, `colour_match.py` and `batch_recreate.py`. You do not need to open them: every line this plan needs is in the tasks.

## Global Constraints

- Python 3.12 or newer. Runtime dependencies are exactly Pillow (>= 10), PyYAML (>= 6) and numpy (>= 1.26); HTTP uses stdlib `urllib` only.
- Flat module layout at the repository root, no package, as in the AITD kit. The project interpreter is `.venv/bin/python`, made by `make install`.
- Tests: stdlib `unittest`, never the network or the GPU. `make test` runs `unittest discover` over every `test_*.py`. One test module per production module; data-only variations are one `subTest` table; a rule is tested once, at the layer that owns it; a regression test names what it guards.
- `testkit.py` is the only shared test-support module. Never re-implement its helpers in a test module.
- The source (`ATL_SRC`, default `../atlantis-textures/out`) is read in place and never written. `source_tree` is its only reader.
- Every output is exactly 4x native width and height, RGB, no alpha. Nothing but `room_NNN.png` files and the `.quality/` audit folder is written under `ATL_DST` (default `data/rooms-ai`).
- Atomic writes: YAML and JSON go through `<name>.tmp` and a rename; output images through `<name>.pending` and a rename.
- Only `comfy_client` knows workflow node ids. The driver never starts or stops a service; its only state-changing ComfyUI calls are `POST /free` and `POST /interrupt`.
- Constants and their starting values: `SCALE = 4`; `WINDOW_WIDTH = 320`; `WINDOW_OVERLAP = 64`; `MIN_WRAP_PERIOD = 320`; `MIN_WRAP_SPAN = 64`; `WRAP_MATCH = 0.999`; `DEDITHER_METHOD = "palette-smooth"`; `DEDITHER_THRESHOLD = 64.0`; `MAX_SHIFT = 0.5`; `EDGE_THRESHOLD = 80.0`; `MIN_EDGE_AGREEMENT = 0.80`; `SEAM_WARN = 3.0`; `MEMORY_FLOOR_GB = 45`; `SEED = 42`; `MAX_ATTEMPTS = 4`; `DEFAULT_MATCH_STRENGTH = 0.5`; `REFERENCE = "guide"`; `DEFAULT_WORKFLOW = "qwen-edit-2511-canny"`. Task 18 (the spike) is the only task that changes them.
- Environment names: `ATL_SRC`, `ATL_DST`, `ATL_ROOMS`, `ATL_REVIEWS`, `ATL_WORKFLOW`, `ATL_MATCH_STRENGTH`, `COMFY_URL`, `COMFY_DIR`, `VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY`.
- Style: match the AITD kit. A module docstring says what the module owns; non-trivial functions have docstrings; a comment explains a non-obvious why, never what the code says.
- Legal: the extracted and regenerated art is LucasArts/Disney copyright, personal use only. `data/` is gitignored; never commit an image of the game.
- Every commit message ends with the session's `Co-Authored-By` trailer.

## Review Focus

Inputs and failure modes the spec implies that a person using this kit will meet; each has a test in the task named.

1. **ComfyUI hands back a render of another size than the window** (a changed graph, a model that rounds): the room fails with a message naming the window and both sizes, and nothing is promoted. Test: Task 13, `test_a_wrong_size_render_fails_the_room`.
2. **A batch dies mid-room** (a timeout, Ctrl-C, a crash): the rerun starts a new attempt from window 1, promotes it, and keeps the failed attempt's tiles for audit. Test: Task 14, `test_an_interrupted_room_starts_over_as_a_new_attempt`.
3. **A hand edit marks a flat placeholder `scene`**: that room fails with a message saying `set kind: skip`, and the other rooms still render. Test: Task 14, `test_a_flat_room_marked_scene_fails_cleanly`.
4. **Half-black rooms** (the labyrinth pieces 85–88 are about 55% flat black): a flat window has no position to measure and must not read as shifted. Tests: Task 7, `test_flat_reads_as_zero` and `test_a_flat_window_passes`.
5. **The real corpus is not the fixtures**: margins that are not multiples of 8, letterbox rows, the single wraparound. The window plan must hold on all 91 real scene and insert rooms. Test: Task 5, `RealCorpusTests`.

## File map

| File | Task | Responsibility |
|---|---|---|
| `.gitignore`, `pyproject.toml` | 1 | Ignore rules; project metadata and dependencies |
| `Makefile` | 1, 16 | `install`, `check`, `test`, `clean`; then the pipeline targets |
| `source_tree.py` | 1 | Reads and validates `manifest.json`: rooms, sizes, files |
| `testkit.py` | 1, 11–13 | Miniature source; `write_rooms`, `run_cli`; `vlm_stub`; `fake_render`, `shift_right`, `comfy_stub` |
| `rooms_file.py`, `rooms.yaml` | 2 | `rooms.yaml` and `reviews.yaml`; the shipped kinds |
| `room_geometry.py` | 3–6 | Guide, margins, wraparound, windows, composites, stitch, seam, fix-ups |
| `geometry_check.py` | 7 | Shift, edge agreement, seam ratio |
| `colour_match.py` | 8 | Lab transfer toward the room's own guide |
| `prompts.py` | 9 | Caption, render and review prompts; VLM requests; review parser |
| `comfy_client.py`, `recreation_qwen2511_canny.json`, `recreation_qwen21_i2i.json` | 10 | ComfyUI HTTP, the workflow registry, the two graphs |
| `atl_recreate.py` | 11–15 | The CLI driver: `verify`, `caption`, `batch`, `review` |
| `run_batch.sh`, `run_server.sh`, `test_scripts.py`, `README.md`, `AGENTS.md`, `CLAUDE.md` | 16 | Wrappers, make-target test, user and agent docs |

## How to work

- Repository: `/home/felipe/code/atlantis-texture-enhancement`, already a git repository on `main` holding only the spec. Work on the branch or worktree your executing skill sets up.
- Run a test module: `.venv/bin/python -m unittest test_source_tree -v` (after Task 1's `make install`). Run everything: `make test`.
- The real corpus is the sibling repository's output, `../atlantis-textures/out` (96 rooms). Task 2 reads it to write `rooms.yaml`; Task 5's `RealCorpusTests` runs against it and would skip if it were absent (it is present on this host: do not accept a skip there).
- Tasks 1–16 need no GPU and no service. Tasks 17 and 18 run ComfyUI and vLLM on this host and end at a human checkpoint.

---

### Task 1: Scaffold and the source-tree reader

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `Makefile`, `testkit.py`, `test_source_tree.py`, `source_tree.py`

**Interfaces:**
- Consumes: nothing.
- Produces (`source_tree`): `SCALE = 4`; `SourceError(ValueError)`; `Room(number: int, rel: Path, width: int, height: int, sha256: str)` with properties `key` (`"room_001"`), `out_name` (`"room_001.png"`), `out_size` (`(4 * width, 4 * height)`); `Source(root: Path, rooms: tuple[Room, ...])`; `file_sha256(path) -> str`; `load(root) -> Source`; `select(source, numbers: list[int] | None) -> list[Room]`; `open_indexed(root, room) -> PIL.Image.Image` (mode P).
- Produces (`testkit`): `BASE`, `PALETTE` (256 RGB tuples; indices 2–13 far apart, index 0 black); `room(number, width, height, *, seed=None, wrap=None, right_margin=0, flat=None) -> dict`; `DEFAULT_ROOMS` (room 1: 320x144; room 2: 568x144; room 3: 1152x144 whose columns 840–1063 repeat 0–223, with an 88-column right margin of index 0; room 4: 16x200, all index 0); `room_pixels(spec) -> np.ndarray`; `indexed_image(pixels, palette=PALETTE) -> Image`; `make_source(root, rooms=DEFAULT_ROOMS) -> Path` (writes and returns `<root>/out`); `rewrite_manifest(src, change)`.

- [ ] **Step 1: Write the project files**

`.gitignore`:

```
__pycache__/
*.py[cod]
.venv/
/data/
/reviews.yaml
*.tmp
*.pending
.superpowers/
```

`pyproject.toml`:

```toml
[project]
name = "atlantis_regen"
version = "0.1.0"
description = "Caption, render and review painted high-definition 4x recreations of the Indiana Jones and the Fate of Atlantis room backgrounds with ComfyUI (Qwen-Image) and a local Qwen3.8 VLM"
requires-python = ">=3.12"
dependencies = [
    "pillow>=10.0.0",
    "pyyaml>=6.0",
    "numpy>=1.26",
]
```

`Makefile` (recipe lines start with a real tab character):

```make
# Makefile for the Atlantis background regeneration kit
# Pipeline: caption -> (edit rooms.yaml) -> batch -> review -> batch ... -> verify
SERVICE = Atlantis Background Regen

VENV_DIR = .venv
PY = $(VENV_DIR)/bin/python

.PHONY: help install check test clean

help: ## Print this help message
	@printf '\033[01;32m${SERVICE}\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

# ── Environment ──────────────────────────────────────────────────────────────

install: ## Create .venv with Pillow, PyYAML and numpy (re-running is safe)
	@if [ ! -x "$(PY)" ]; then python3 -m venv $(VENV_DIR); fi
	@$(PY) -c 'import PIL, yaml, numpy' 2>/dev/null || $(VENV_DIR)/bin/pip install -q "pillow>=10" "pyyaml>=6" "numpy>=1.26"

clean: ## Remove __pycache__ (never touches data/)
	find . -path ./.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} +

# ── Development ──────────────────────────────────────────────────────────────

check: install ## Byte-compile the Python modules
	@$(PY) -m py_compile *.py && echo "check ok"

test: install ## Run the unit tests (no GPU, no network)
	$(PY) -m unittest discover -s . -p 'test_*.py'
```

- [ ] **Step 2: Create the environment**

Run: `make install && .venv/bin/python -c 'import PIL, yaml, numpy; print("ok")'`
Expected: `ok`.

- [ ] **Step 3: Write the test kit's source builders**

`testkit.py`:

```python
"""Shared test support: a miniature atlantis-textures output, a rooms.yaml
writer, the ComfyUI and vLLM patch stacks, a fake window renderer and a
CLI-capture helper.

The real source tree is atlantis-textures' `out/`: indexed/rooms/room_NNN.png
in P mode at native size, and manifest.json whose assets[] carry room, file,
width, height, role and sha256.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


# Indices 2-13 lie far apart (RGB distance over 64), so de-dithering keeps
# every block edge; index 0 is the margin colour.
BASE = [(0, 0, 0), (255, 255, 255), (200, 40, 40), (40, 200, 40), (40, 40, 200),
        (200, 200, 40), (200, 40, 200), (40, 200, 200), (120, 60, 20), (20, 120, 60),
        (60, 20, 120), (230, 140, 60), (60, 140, 230), (140, 230, 60)]
PALETTE = BASE + [(i, i, i) for i in range(len(BASE), 256)]


def room(number, width, height, *, seed=None, wrap=None, right_margin=0, flat=None):
    """A room for make_source: random 16-pixel blocks of indices 2-13 (seeded by
    `seed`, default the room number); `wrap=(period, span)` copies columns
    [0, span) onto [period, period + span); `right_margin` columns of index 0;
    `flat=I` makes the whole room index I."""
    return {"room": number, "width": width, "height": height,
            "seed": number if seed is None else seed, "wrap": wrap,
            "right_margin": right_margin, "flat": flat}


DEFAULT_ROOMS = (
    room(1, 320, 144),                                          # one window
    room(2, 568, 144),                                          # two windows
    room(3, 1152, 144, wrap=(840, 224), right_margin=88),       # room 58's shape
    room(4, 16, 200, flat=0),                                   # a placeholder
)


def room_pixels(spec):
    """The room's palette indices, a (height, width) uint8 array."""
    h, w = spec["height"], spec["width"]
    if spec["flat"] is not None:
        return np.full((h, w), spec["flat"], np.uint8)
    rng = np.random.default_rng(spec["seed"])
    blocks = rng.integers(2, len(BASE), size=(-(-h // 16), -(-w // 16)), dtype=np.uint8)
    pixels = np.kron(blocks, np.ones((16, 16), np.uint8))[:h, :w].copy()
    if spec["wrap"]:
        period, span = spec["wrap"]
        pixels[:, period:period + span] = pixels[:, :span]
    if spec["right_margin"]:
        pixels[:, w - spec["right_margin"]:] = 0
    return pixels


def indexed_image(pixels, palette=PALETTE):
    """A P-mode image of `pixels` with `palette`."""
    h, w = pixels.shape
    image = Image.frombytes("P", (w, h), np.ascontiguousarray(pixels, np.uint8).tobytes())
    image.putpalette([c for rgb in palette for c in rgb])
    return image


def make_source(root, rooms=DEFAULT_ROOMS):
    """Write <root>/out like atlantis-textures' `make extract` and return it."""
    src = Path(root) / "out"
    assets = []
    for spec in rooms:
        rel = f"indexed/rooms/room_{spec['room']:03d}.png"
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        indexed_image(room_pixels(spec)).save(path)
        assets.append({"room": spec["room"], "name": None, "role": "background",
                       "width": spec["width"], "height": spec["height"], "file": rel,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "transparent_index": 5, "anomalies": []})
    (src / "manifest.json").write_text(json.dumps(
        {"assets": assets, "game": {"dir": "/game"}, "summary": {}}, indent=1))
    return src


def rewrite_manifest(src, change):
    """Load <src>/manifest.json, let change(assets) edit it in place, save it."""
    path = Path(src) / "manifest.json"
    doc = json.loads(path.read_text())
    change(doc["assets"])
    path.write_text(json.dumps(doc, indent=1))
```

- [ ] **Step 4: Write the failing tests**

`test_source_tree.py`:

```python
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import source_tree
import testkit
from source_tree import SourceError


class SourceTreeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = testkit.make_source(self.tmp)

    def test_loads_background_rooms_by_number(self):
        source = source_tree.load(self.src)
        self.assertEqual([r.number for r in source.rooms], [1, 2, 3, 4])
        room = source.rooms[2]
        self.assertEqual((room.key, room.out_name), ("room_003", "room_003.png"))
        self.assertEqual(((room.width, room.height), room.out_size), ((1152, 144), (4608, 576)))
        self.assertEqual(room.rel, Path("indexed/rooms/room_003.png"))

    def test_ignores_other_roles(self):
        testkit.rewrite_manifest(self.src, lambda assets: assets.append(
            {"room": 9, "role": "object", "file": "nope.png"}))
        self.assertEqual(len(source_tree.load(self.src).rooms), 4)

    def test_refuses_a_manifest_that_disagrees_with_its_files(self):
        def edit(field, value, index=0):
            def change(assets):
                assets[index][field] = value
            return change
        cases = {
            "missing file": (edit("file", "indexed/rooms/room_999.png"), "file not found"),
            "size": (edit("width", 336), "the manifest says 336x144"),
            "strips": (edit("height", 150), "positive multiple of 8"),
            "sha256": (edit("sha256", "0" * 64), "sha256 differs"),
            "escaping path": (edit("file", "../x.png"), "relative path inside"),
            "room number": (edit("room", "1"), "non-negative integer"),
            "duplicate": (edit("room", 1, index=1), "duplicate room 1"),
        }
        for name, (change, message) in cases.items():
            with self.subTest(name):
                src = testkit.make_source(self.tmp / name)
                testkit.rewrite_manifest(src, change)
                with self.assertRaisesRegex(SourceError, message):
                    source_tree.load(src)

    def test_refuses_an_rgb_file(self):
        Image.new("RGB", (320, 144)).save(self.src / "indexed/rooms/room_001.png")
        with self.assertRaisesRegex(SourceError, "mode RGB, expected P"):
            source_tree.load(self.src)

    def test_refuses_an_unreadable_file(self):
        (self.src / "indexed/rooms/room_001.png").write_bytes(b"not a png")
        with self.assertRaisesRegex(SourceError, "not a readable image"):
            source_tree.load(self.src)

    def test_refuses_a_broken_or_missing_manifest(self):
        (self.src / "manifest.json").write_text("{")
        with self.assertRaisesRegex(SourceError, "invalid JSON"):
            source_tree.load(self.src)
        (self.src / "manifest.json").unlink()
        with self.assertRaisesRegex(SourceError, "run make extract"):
            source_tree.load(self.src)

    def test_refuses_a_manifest_without_rooms(self):
        testkit.rewrite_manifest(self.src, lambda assets: assets.clear())
        with self.assertRaisesRegex(SourceError, "no background rooms"):
            source_tree.load(self.src)

    def test_select(self):
        source = source_tree.load(self.src)
        self.assertEqual(len(source_tree.select(source)), 4)
        self.assertEqual([r.number for r in source_tree.select(source, [3, 1, 3])], [1, 3])
        with self.assertRaisesRegex(SourceError, "room 34, 99"):
            source_tree.select(source, [99, 1, 34])

    def test_open_indexed_keeps_the_palette(self):
        source = source_tree.load(self.src)
        image = source_tree.open_indexed(self.src, source.rooms[0])
        self.assertEqual(image.mode, "P")
        self.assertEqual(tuple(image.getpalette()[6:9]), testkit.PALETTE[2])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_source_tree -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'source_tree'`.

- [ ] **Step 6: Write `source_tree.py`**

```python
"""Read and validate the extractor's manifest.json: which rooms exist, their
native sizes and their files.

The source tree is atlantis-textures' output (`make extract` there):
indexed/rooms/room_NNN.png in P mode at native size, and manifest.json whose
assets[] records carry room, file, width, height, role and sha256. This module
is its only reader. It never writes: ATL_SRC is read in place.
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

SCALE = 4               # every output is exactly 4x its room's native size
ROLE = "background"     # the manifest role of a room background


class SourceError(ValueError):
    """The source tree disagrees with its manifest, or a selection is not in it."""


@dataclass(frozen=True)
class Room:
    number: int
    rel: Path           # the indexed PNG, relative to the source root
    width: int          # native size
    height: int
    sha256: str

    @property
    def key(self):
        """The rooms.yaml and reviews.yaml key, audit folder and output name stem."""
        return f"room_{self.number:03d}"

    @property
    def out_name(self):
        return f"{self.key}.png"

    @property
    def out_size(self):
        return (self.width * SCALE, self.height * SCALE)


@dataclass(frozen=True)
class Source:
    root: Path
    rooms: tuple        # of Room, by number


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _room(root, record, where):
    number = record.get("room")
    rel = record.get("file")
    width, height = record.get("width"), record.get("height")
    digest = record.get("sha256")
    if type(number) is not int or number < 0:
        raise SourceError(f'{where}: "room" must be a non-negative integer, got {number!r}')
    if (not isinstance(rel, str) or not rel or rel.startswith("/")
            or ".." in Path(rel).parts):
        raise SourceError(f'{where}: "file" must be a relative path inside the source tree')
    for name, value in (("width", width), ("height", height)):
        # SMAP images are built from 8-pixel strips; every window size relies on it.
        if type(value) is not int or value <= 0 or value % 8:
            raise SourceError(f'{where}: "{name}" must be a positive multiple of 8, got {value!r}')
    if not isinstance(digest, str) or len(digest) != 64:
        raise SourceError(f'{where}: "sha256" must be 64 hex digits')
    path = root / rel
    label = f"room {number} ({rel})"
    if not path.is_file():
        raise SourceError(f"{label}: file not found")
    try:
        with Image.open(path) as im:
            mode, size = im.mode, im.size
    except OSError as error:
        raise SourceError(f"{label}: not a readable image: {error}") from error
    if mode != "P":
        raise SourceError(f"{label}: mode {mode}, expected P (indexed)")
    if size != (width, height):
        raise SourceError(f"{label}: is {size[0]}x{size[1]}, the manifest says {width}x{height}")
    if file_sha256(path) != digest:
        raise SourceError(f"{label}: sha256 differs from the manifest - re-run make extract")
    return Room(number, Path(rel), width, height, digest)


def load(root):
    """Every background room the manifest lists, each checked against its file."""
    root = Path(root)
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise SourceError(f"{manifest}: not found - run make extract in atlantis-textures")
    try:
        doc = json.loads(manifest.read_text())
    except ValueError as error:
        raise SourceError(f"{manifest}: invalid JSON: {error}") from error
    assets = doc.get("assets") if isinstance(doc, dict) else None
    if not isinstance(assets, list):
        raise SourceError(f'{manifest}: expected a mapping with an "assets" list')
    rooms = {}
    for i, record in enumerate(assets):
        if not isinstance(record, dict) or record.get("role") != ROLE:
            continue
        room = _room(root, record, f"{manifest}: assets[{i}]")
        if room.number in rooms:
            raise SourceError(f"{manifest}: assets[{i}]: duplicate room {room.number}")
        rooms[room.number] = room
    if not rooms:
        raise SourceError(f"{manifest}: lists no background rooms")
    return Source(root, tuple(rooms[n] for n in sorted(rooms)))


def select(source, numbers=None):
    """The rooms `numbers` names, by number; every room when it is empty or None."""
    if not numbers:
        return list(source.rooms)
    by_number = {room.number: room for room in source.rooms}
    unknown = sorted({n for n in numbers if n not in by_number})
    if unknown:
        raise SourceError("not in the manifest: room " + ", ".join(map(str, unknown)))
    return [by_number[n] for n in sorted(set(numbers))]


def open_indexed(root, room):
    """The room's image, loaded: P mode with the game's palette."""
    with Image.open(Path(root) / room.rel) as im:
        im.load()
        return im.copy()
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m unittest test_source_tree -v`
Expected: `OK`.

- [ ] **Step 8: Commit**

```bash
git add .gitignore pyproject.toml Makefile testkit.py test_source_tree.py source_tree.py
git commit -m "feat: scaffold and the atlantis-textures manifest reader"
```

---

### Task 2: `rooms.yaml` and `reviews.yaml`

**Files:**
- Create: `test_rooms_file.py`, `rooms_file.py`, `rooms.yaml`

**Interfaces:**
- Consumes: `source_tree.load`, `Room.key` (Task 1), to write the shipped `rooms.yaml`.
- Produces: `KINDS = ("scene", "insert", "skip")`; `REVIEW_SOURCES = ("review", "geometry")`; `RoomsFileError(ValueError)`; `RoomEntry(kind: str, caption: str = "")`; `Review(attempt: int, accepted: bool, issues: tuple, source: str = "review")`; `normalize_text(text) -> str`; `load_rooms(path) -> dict[str, RoomEntry]`; `save_rooms(path, rooms)`; `check_coverage(rooms, keys, path="rooms.yaml")`; `load_reviews(path, optional=False) -> dict[str, Review]`; `save_reviews(path, reviews)`. Both files are mappings keyed `room_NNN` (spec §6).

- [ ] **Step 1: Write the failing tests**

`test_rooms_file.py`:

```python
import tempfile
import unittest
from pathlib import Path

import rooms_file as rf
from rooms_file import Review, RoomEntry, RoomsFileError

REPO = Path(__file__).resolve().parent


class RoomsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "rooms.yaml"

    def test_round_trip_normalizes_captions(self):
        rooms = {"room_002": RoomEntry("insert", "SCENE: a newspaper.  \n"
                                                 "TEXT: German Wizard Splits Atom\n\n"),
                 "room_001": RoomEntry("scene", "one line"),
                 "room_020": RoomEntry("skip")}
        rf.save_rooms(self.path, rooms)
        loaded = rf.load_rooms(self.path)
        self.assertEqual(list(loaded), ["room_001", "room_002", "room_020"])
        self.assertEqual(loaded["room_002"], RoomEntry(
            "insert", "SCENE: a newspaper.\nTEXT: German Wizard Splits Atom"))
        self.assertEqual(loaded["room_020"], RoomEntry("skip", ""))
        self.assertIn("caption: >", self.path.read_text())
        self.assertFalse((self.dir / "rooms.yaml.tmp").exists())

    def test_missing_or_null_caption_is_blank(self):
        self.path.write_text("room_001:\n  kind: scene\nroom_002:\n  kind: skip\n  caption:\n")
        self.assertEqual(rf.load_rooms(self.path),
                         {"room_001": RoomEntry("scene"), "room_002": RoomEntry("skip")})

    def test_rejects_bad_entries(self):
        cases = {
            "kind": ("room_001:\n  kind: scenery\n",
                     "room_001: \"kind\" must be one of scene, insert, skip, got 'scenery'"),
            "field": ("room_001:\n  kind: scene\n  kidn: x\n", r"unknown field\(s\) kidn"),
            "key": ("room_1:\n  kind: scene\n", "'room_1' is not a room key"),
            "caption": ("room_001:\n  kind: scene\n  caption: [a]\n", '"caption" must be a string'),
            "shape": ("- room_001\n", "expected a mapping of room_NNN entries"),
            "entry": ("room_001: scene\n", "room_001: expected a mapping"),
            "yaml": ("room_001: [\n", "invalid YAML"),
        }
        for name, (text, message) in cases.items():
            with self.subTest(name):
                self.path.write_text(text)
                with self.assertRaisesRegex(RoomsFileError, message):
                    rf.load_rooms(self.path)

    def test_missing_file_is_an_error(self):
        with self.assertRaisesRegex(RoomsFileError, "file not found"):
            rf.load_rooms(self.path)

    def test_check_coverage(self):
        rooms = {"room_001": RoomEntry("scene"), "room_009": RoomEntry("scene")}
        rf.check_coverage(rooms, ["room_001", "room_009"])
        with self.assertRaisesRegex(RoomsFileError, "no entry for room_002; entries for "
                                                    "rooms not in the manifest: room_009"):
            rf.check_coverage(rooms, ["room_001", "room_002"])

    def test_shipped_rooms_file_covers_the_corpus(self):
        rooms = rf.load_rooms(REPO / "rooms.yaml")
        self.assertEqual(len(rooms), 96)
        kinds = {kind: sorted(int(key[5:]) for key, entry in rooms.items() if entry.kind == kind)
                 for kind in rf.KINDS}
        self.assertEqual(kinds["skip"], [20, 68, 89, 90, 98])
        self.assertEqual(kinds["insert"], [8, 9, 47, 70, 75, 83, 84, 85, 86, 87, 88])


class ReviewsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "reviews.yaml"

    def test_round_trip(self):
        reviews = {"room_058": Review(2, False, ("geometry: window 2 is shifted +1.3,+0.0 px",),
                                      "geometry"),
                   "room_001": Review(1, True, ())}
        rf.save_reviews(self.path, reviews)
        self.assertEqual(rf.load_reviews(self.path), reviews)

    def test_source_defaults_to_review(self):
        self.path.write_text("room_001:\n  attempt: 1\n  accepted: true\n  issues: []\n")
        self.assertEqual(rf.load_reviews(self.path)["room_001"].source, "review")

    def test_missing_file(self):
        self.assertEqual(rf.load_reviews(self.path, optional=True), {})
        with self.assertRaisesRegex(RoomsFileError, "file not found"):
            rf.load_reviews(self.path)

    def test_rejects_bad_verdicts(self):
        cases = {
            "attempt": ("attempt: -1\n  accepted: true\n  issues: []",
                        '"attempt" must be a non-negative integer'),
            "accepted": ("attempt: 1\n  accepted: yes please\n  issues: []",
                         '"accepted" must be true or false'),
            "issues": ('attempt: 1\n  accepted: false\n  issues: [""]',
                       '"issues" must be a list of non-empty strings'),
            "contradiction": ("attempt: 1\n  accepted: true\n  issues: [moved]",
                              '"accepted" contradicts "issues"'),
            "source": ("attempt: 1\n  accepted: true\n  issues: []\n  source: human",
                       '"source" must be one of review, geometry'),
        }
        for name, (body, message) in cases.items():
            with self.subTest(name):
                self.path.write_text("room_001:\n  " + body + "\n")
                with self.assertRaisesRegex(RoomsFileError, message):
                    rf.load_reviews(self.path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_rooms_file -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'rooms_file'`.

- [ ] **Step 3: Write `rooms_file.py`**

```python
"""Read and write rooms.yaml and reviews.yaml.

rooms.yaml is hand-owned: one entry per manifest room, keyed room_NNN, with a
`kind` (scene, insert or skip) and a `caption` that `make caption` fills and
the user edits. reviews.yaml is machine-written: one verdict per room on its
latest judged attempt, from the VLM review (`source: review`) or from batch's
geometry gate (`source: geometry`).

Multi-line strings are written in folded (`>`) style. PyYAML writes a blank
line for every embedded line break so the text reloads byte-for-byte; the file
looks airier than a hand-written folded block, which is accepted. Every save
goes to <file>.tmp and is renamed into place.
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

KINDS = ("scene", "insert", "skip")
REVIEW_SOURCES = ("review", "geometry")
_KEY = re.compile(r"^room_\d{3}$")


class RoomsFileError(ValueError):
    """A YAML file does not have the shape this kit expects."""


@dataclass(frozen=True)
class RoomEntry:
    kind: str
    caption: str = ""


@dataclass(frozen=True)
class Review:
    attempt: int
    accepted: bool
    issues: tuple
    source: str = "review"


def normalize_text(text):
    """Strip trailing whitespace on each line and trailing blank lines.

    PyYAML refuses block style for text with a space before a line break and
    falls back to a double-quoted scalar; VLM output often has such spaces.
    """
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper, data):
    style = ">" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def _dump(mapping, path):
    path = Path(path)
    text = yaml.dump(mapping, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     width=1_000_000)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_mapping(path, optional):
    """The file's top-level mapping of room keys; {} for a missing file when optional."""
    path = Path(path)
    if not path.exists():
        if optional:
            return {}
        raise RoomsFileError(f"{path}: file not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise RoomsFileError(f"{path}: invalid YAML: {error}") from error
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise RoomsFileError(f"{path}: expected a mapping of room_NNN entries")
    for key in data:
        if not isinstance(key, str) or not _KEY.match(key):
            raise RoomsFileError(f"{path}: {key!r} is not a room key (room_NNN)")
    return data


def load_rooms(path):
    """{room_NNN: RoomEntry}. A missing or blank caption loads as ""."""
    result = {}
    for key, entry in _read_mapping(path, optional=False).items():
        where = f"{Path(path)}: {key}"
        if not isinstance(entry, dict):
            raise RoomsFileError(f"{where}: expected a mapping")
        unknown = sorted(set(entry) - {"kind", "caption"})
        if unknown:
            raise RoomsFileError(f"{where}: unknown field(s) {', '.join(unknown)}")
        kind = entry.get("kind")
        if kind not in KINDS:
            raise RoomsFileError(f'{where}: "kind" must be one of {", ".join(KINDS)}, '
                                 f"got {kind!r}")
        caption = entry.get("caption")
        if caption is None:
            caption = ""
        if not isinstance(caption, str):
            raise RoomsFileError(f'{where}: "caption" must be a string')
        result[key] = RoomEntry(kind, caption)
    return result


def save_rooms(path, rooms):
    _dump({key: {"kind": rooms[key].kind, "caption": normalize_text(rooms[key].caption)}
           for key in sorted(rooms)}, path)


def check_coverage(rooms, keys, path="rooms.yaml"):
    """Raise unless `rooms` has exactly one entry per key in `keys`."""
    missing = sorted(set(keys) - set(rooms))
    extra = sorted(set(rooms) - set(keys))
    problems = []
    if missing:
        problems.append("no entry for " + ", ".join(missing))
    if extra:
        problems.append("entries for rooms not in the manifest: " + ", ".join(extra))
    if problems:
        raise RoomsFileError(f"{path}: " + "; ".join(problems))


def load_reviews(path, optional=False):
    """{room_NNN: Review}. A missing file is {} when optional, else an error."""
    result = {}
    for key, entry in _read_mapping(path, optional).items():
        where = f"{Path(path)}: {key}"
        if not isinstance(entry, dict):
            raise RoomsFileError(f"{where}: expected a mapping")
        attempt, accepted = entry.get("attempt"), entry.get("accepted")
        issues, source = entry.get("issues"), entry.get("source", "review")
        if type(attempt) is not int or attempt < 0:
            raise RoomsFileError(f'{where}: "attempt" must be a non-negative integer')
        if type(accepted) is not bool:
            raise RoomsFileError(f'{where}: "accepted" must be true or false')
        if (not isinstance(issues, list)
                or any(not isinstance(x, str) or not x.strip() for x in issues)):
            raise RoomsFileError(f'{where}: "issues" must be a list of non-empty strings')
        if accepted != (not issues):
            raise RoomsFileError(f'{where}: "accepted" contradicts "issues"')
        if source not in REVIEW_SOURCES:
            raise RoomsFileError(f'{where}: "source" must be one of {", ".join(REVIEW_SOURCES)}')
        result[key] = Review(attempt, accepted, tuple(issues), source)
    return result


def save_reviews(path, reviews):
    _dump({key: {"attempt": r.attempt, "accepted": r.accepted,
                 "issues": [normalize_text(x) for x in r.issues], "source": r.source}
           for key, r in sorted(reviews.items())}, path)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_rooms_file -v`
Expected: every test passes except `test_shipped_rooms_file_covers_the_corpus`, which fails with `rooms.yaml: file not found`.

- [ ] **Step 5: Write the shipped `rooms.yaml`**

The kinds come from the spec §6 (the placeholders were confirmed single-colour from their pixels):

```bash
.venv/bin/python - <<'EOF'
import source_tree
from rooms_file import RoomEntry, save_rooms

SKIP = {20, 68, 89, 90, 98}
INSERT = {8, 9, 47, 70, 75, 83, 84, 85, 86, 87, 88}
source = source_tree.load("../atlantis-textures/out")
rooms = {room.key: RoomEntry("skip" if room.number in SKIP else
                             "insert" if room.number in INSERT else "scene")
         for room in source.rooms}
save_rooms("rooms.yaml", rooms)
print(len(rooms), sum(e.kind == "skip" for e in rooms.values()),
      sum(e.kind == "insert" for e in rooms.values()))
EOF
```

Expected output: `96 5 11`.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m unittest test_rooms_file -v`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add test_rooms_file.py rooms_file.py rooms.yaml
git commit -m "feat: rooms.yaml and reviews.yaml, with the kinds of all 96 rooms"
```

---

### Task 3: The guide image

**Files:**
- Create: `test_room_geometry.py`, `room_geometry.py`

**Interfaces:**
- Consumes: `testkit.DEFAULT_ROOMS`, `room_pixels`, `indexed_image`, `PALETTE` (Task 1). The test file's header also names `source_tree` and `REAL_SRC`, which Task 5's tests use.
- Produces: the constants `SCALE`, `WINDOW_WIDTH`, `WINDOW_OVERLAP`, `DEDITHER_METHODS`, `DEDITHER_METHOD`, `DEDITHER_THRESHOLD`, `MIN_WRAP_PERIOD`, `MIN_WRAP_SPAN`, `WRAP_MATCH`; `indices(indexed) -> np.ndarray`; `to_rgb(indexed) -> Image`; `dedither(rgb, method=DEDITHER_METHOD, threshold=DEDITHER_THRESHOLD) -> Image` (raises `ValueError` for an unknown method); `Guide(native: Image, full: Image)`; `build_guide(indexed, method=DEDITHER_METHOD) -> Guide` (spec §9.1).

- [ ] **Step 1: Write the failing tests**

`test_room_geometry.py` (Tasks 4–6 add classes above the `if __name__` line):

```python
import os
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import room_geometry as rg
import source_tree
import testkit

REAL_SRC = Path(os.environ.get("ATL_SRC")
                or Path(__file__).resolve().parent.parent / "atlantis-textures" / "out")
SKIP_ROOMS = (20, 68, 89, 90, 98)


def checkerboard(a, b, size=(32, 32)):
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w]
    arr = np.where(((xs + ys) % 2 == 0)[..., None], np.array(a, np.uint8), np.array(b, np.uint8))
    return Image.fromarray(arr.astype(np.uint8))


def fixture_room(number):
    spec = next(s for s in testkit.DEFAULT_ROOMS if s["room"] == number)
    return testkit.indexed_image(testkit.room_pixels(spec))


def noise(size, seed=0):
    w, h = size
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8))


def spans(windows):
    return [(w.x0, w.x1) for w in windows]


class GuideTests(unittest.TestCase):
    def test_to_rgb_uses_the_exact_palette(self):
        index = int(testkit.room_pixels(testkit.DEFAULT_ROOMS[0])[0, 0])
        self.assertEqual(rg.to_rgb(fixture_room(1)).getpixel((0, 0)), testkit.PALETTE[index])

    def test_palette_smooth_melts_near_dithering(self):
        board = checkerboard((100, 100, 100), (130, 130, 130))
        out = np.asarray(rg.dedither(board, "palette-smooth"), dtype=float)
        self.assertLess(out.std(), 0.2 * np.asarray(board, dtype=float).std())

    def test_palette_smooth_keeps_edges_between_far_colours(self):
        arr = np.zeros((8, 16, 3), np.uint8)
        arr[:, :8], arr[:, 8:] = 20, 220
        image = Image.fromarray(arr)
        self.assertEqual(rg.dedither(image, "palette-smooth").tobytes(), image.tobytes())

    def test_gaussian_softens_dithering(self):
        board = checkerboard((100, 100, 100), (130, 130, 130))
        out = np.asarray(rg.dedither(board, "gaussian"), dtype=float)
        self.assertLess(out.std(), 0.5 * np.asarray(board, dtype=float).std())

    def test_unknown_method(self):
        with self.assertRaisesRegex(ValueError, "unknown de-dither method 'median'"):
            rg.dedither(checkerboard((0, 0, 0), (1, 1, 1)), "median")

    def test_build_guide_sizes(self):
        guide = rg.build_guide(fixture_room(2))
        self.assertEqual((guide.native.size, guide.full.size), ((568, 144), (2272, 576)))
        self.assertEqual((guide.native.mode, guide.full.mode), ("RGB", "RGB"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'room_geometry'`.

- [ ] **Step 3: Write `room_geometry.py`**

```python
"""Room geometry: the guide image, margins, wraparound, the window plan, each
window's composite and mask, the stitch, the wrap seam and the fix-ups.

Pure image maths on Pillow images and numpy arrays; talks to no service and
knows no file layout. Positions are native room columns unless a comment says
4x; SCALE converts.
"""
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

SCALE = 4
WINDOW_WIDTH = 320          # Wt: the widest window, native columns (the spike tunes it)
WINDOW_OVERLAP = 64         # Ov: the least overlap between neighbouring windows
DEDITHER_METHODS = ("palette-smooth", "gaussian")
DEDITHER_METHOD = "palette-smooth"
DEDITHER_THRESHOLD = 64.0   # palette-smooth: the RGB distance of a neighbour still averaged in
MIN_WRAP_PERIOD = 320       # a wraparound repeats at least one screen later ...
MIN_WRAP_SPAN = 64          # ... over at least this many columns ...
WRAP_MATCH = 0.999          # ... in at least this fraction of their pixels


# ---- guide ------------------------------------------------------------------

def indices(indexed):
    """The palette indices of a P-mode image, a (height, width) uint8 array."""
    return np.asarray(indexed, dtype=np.uint8)


def to_rgb(indexed):
    return indexed.convert("RGB")


def dedither(rgb, method=DEDITHER_METHOD, threshold=DEDITHER_THRESHOLD):
    """`rgb` with its dithering smoothed away, at its own size.

    palette-smooth: each pixel becomes the mean of itself and those of its 3x3
    neighbours within `threshold` RGB distance of it, so a checkerboard of near
    colours melts while an edge between distant colours stays sharp.
    gaussian: a Gaussian blur of radius 1. (A 3x3 median is no candidate: on a
    50% checkerboard each pixel is its neighbourhood's majority.)
    """
    if method == "gaussian":
        return rgb.convert("RGB").filter(ImageFilter.GaussianBlur(1))
    if method != "palette-smooth":
        raise ValueError(f"unknown de-dither method {method!r}; choose one of "
                         + ", ".join(DEDITHER_METHODS))
    a = np.asarray(rgb.convert("RGB"), dtype=np.float32)
    h, w, _ = a.shape
    padded = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode="edge")
    total = np.zeros_like(a)
    count = np.zeros((h, w, 1), np.float32)
    for dy in range(3):
        for dx in range(3):
            n = padded[dy:dy + h, dx:dx + w]
            near = np.sqrt(((n - a) ** 2).sum(axis=2, keepdims=True)) <= threshold
            near = near.astype(np.float32)
            total += n * near
            count += near
    return Image.fromarray(np.round(total / count).astype(np.uint8))


@dataclass(frozen=True)
class Guide:
    native: Image.Image     # de-dithered at native size: what the geometry check compares with
    full: Image.Image       # native upscaled 4x (Lanczos): reference, Canny input, img2img start


def build_guide(indexed, method=DEDITHER_METHOD):
    native = dedither(to_rgb(indexed), method)
    full = native.resize((native.width * SCALE, native.height * SCALE),
                         Image.Resampling.LANCZOS)
    return Guide(native, full)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add test_room_geometry.py room_geometry.py
git commit -m "feat: the guide image, de-dithered at native size and upscaled 4x"
```

---

### Task 4: Margins and wraparound detection

**Files:**
- Modify: `room_geometry.py` (append), `test_room_geometry.py` (add classes above `if __name__`)

**Interfaces:**
- Consumes: `testkit.room`, `room_pixels`, `DEFAULT_ROOMS`.
- Produces: `Margins(left, right, top, bottom)`; `blank_margins(pixels: np.ndarray) -> Margins`; `Wrap(period, span)`; `find_wrap(pixels, content_end) -> Wrap | None` (spec §9.2).

- [ ] **Step 1: Write the failing tests**

Add to `test_room_geometry.py`, above `if __name__ == "__main__":`:

```python
class MarginTests(unittest.TestCase):
    def test_right_margin_of_the_wraparound_fixture(self):
        pixels = testkit.room_pixels(testkit.DEFAULT_ROOMS[2])
        self.assertEqual(rg.blank_margins(pixels), rg.Margins(0, 88, 0, 0))

    def test_margins_on_every_side(self):
        pixels = np.zeros((10, 20), np.uint8)       # a black frame ...
        pixels[3:8, 2:16] = 5                       # ... around content of index 5 ...
        pixels[4:6, 6:10] = 7                       # ... with some detail
        self.assertEqual(rg.blank_margins(pixels), rg.Margins(2, 4, 3, 2))

    def test_a_run_needs_one_index_throughout(self):
        pixels = np.full((4, 8), 3, np.uint8)
        pixels[:, 0], pixels[:, 1] = 1, 2           # two flat columns of different indices
        pixels[1, 4] = 9
        self.assertEqual(rg.blank_margins(pixels).left, 1)


class WrapTests(unittest.TestCase):
    def setUp(self):
        self.pixels = testkit.room_pixels(testkit.DEFAULT_ROOMS[2])   # wrap (840, 224), 88 margin
        self.end = 1152 - 88

    def test_finds_the_repeat(self):
        self.assertEqual(rg.find_wrap(self.pixels, self.end), rg.Wrap(840, 224))

    def test_tolerates_a_few_differences(self):
        self.pixels[:4, 900:904] = 1                # 16 of 32256 pixels: a 99.95% match
        self.assertEqual(rg.find_wrap(self.pixels, self.end), rg.Wrap(840, 224))

    def test_needs_nearly_every_pixel(self):
        self.pixels[:13, 900:905] = 1               # 65 of 32256 pixels: a 99.8% match
        self.assertIsNone(rg.find_wrap(self.pixels, self.end))

    def test_no_repeat(self):
        pixels = testkit.room_pixels(testkit.room(9, 1152, 144, right_margin=88))
        self.assertIsNone(rg.find_wrap(pixels, self.end))

    def test_ignores_a_repeat_closer_than_one_screen(self):
        pixels = testkit.room_pixels(testkit.room(9, 400, 144, wrap=(200, 200)))
        self.assertIsNone(rg.find_wrap(pixels, 400))
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: ERROR, `AttributeError: module 'room_geometry' has no attribute 'blank_margins'` (and `find_wrap`, `Margins`).

- [ ] **Step 3: Append the margin and wraparound code to `room_geometry.py`**

```python
# ---- margins and wraparound -------------------------------------------------

@dataclass(frozen=True)
class Margins:
    left: int               # columns (left, right) or rows (top, bottom) at each edge
    right: int              # that are all one palette index, the same one throughout
    top: int
    bottom: int


def _flat_run(lines):
    """How many leading lines are each one palette index, the same index throughout."""
    count, value = 0, None
    for line in lines:
        if (line != line[0]).any():
            break
        if value is None:
            value = line[0]
        elif line[0] != value:
            break
        count += 1
    return count


def blank_margins(pixels):
    h, w = pixels.shape
    return Margins(left=_flat_run(pixels[:, x] for x in range(w)),
                   right=_flat_run(pixels[:, x] for x in range(w - 1, -1, -1)),
                   top=_flat_run(pixels[y, :] for y in range(h)),
                   bottom=_flat_run(pixels[y, :] for y in range(h - 1, -1, -1)))


@dataclass(frozen=True)
class Wrap:
    period: int             # columns [period, period + span) repeat columns [0, span)
    span: int


def find_wrap(pixels, content_end):
    """The room's wraparound, or None.

    The smallest period from MIN_WRAP_PERIOD at which columns
    [period, content_end) repeat columns [0, content_end - period) in at least
    WRAP_MATCH of their pixels, over at least MIN_WRAP_SPAN columns.
    """
    for period in range(MIN_WRAP_PERIOD, content_end - MIN_WRAP_SPAN + 1):
        span = content_end - period
        if (pixels[:, period:content_end] == pixels[:, :span]).mean() >= WRAP_MATCH:
            return Wrap(period, span)
    return None
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add test_room_geometry.py room_geometry.py
git commit -m "feat: detect flat margins and a wraparound's repeated span"
```

---

### Task 5: The window plan and the room plan

**Files:**
- Modify: `room_geometry.py` (append), `test_room_geometry.py` (add classes above `if __name__`)

**Interfaces:**
- Consumes: Task 4's `blank_margins`, `find_wrap`; `source_tree.load`, `open_indexed` for the real-corpus test.
- Produces: `Window(x0, x1)` with property `width`; `plan_windows(start, end, width=WINDOW_WIDTH, overlap=WINDOW_OVERLAP) -> tuple[Window, ...]`; `RoomPlan(width, height, margins, wrap, span, windows)`; `plan_room(indexed, width=WINDOW_WIDTH, overlap=WINDOW_OVERLAP) -> RoomPlan` (raises `ValueError` containing `set kind: skip` for a flat room); `stitch_from(window, previous) -> int` (native column); `stitch_boundaries(plan, width=WINDOW_WIDTH) -> list[int]` (4x columns) (spec §9.3).

- [ ] **Step 1: Write the failing tests**

Add to `test_room_geometry.py`, above `if __name__ == "__main__":`:

```python
class WindowPlanTests(unittest.TestCase):
    def test_known_plans(self):
        cases = {
            (0, 320): [(0, 320)],
            (0, 176): [(0, 176)],
            (64, 240): [(64, 240)],
            (0, 568): [(0, 320), (248, 568)],
            (0, 840): [(0, 320), (168, 488), (344, 664), (520, 840)],
            (0, 1280): [(0, 320), (240, 560), (480, 800), (720, 1040), (960, 1280)],
        }
        for (start, end), expected in cases.items():
            with self.subTest(span=(start, end)):
                self.assertEqual(spans(rg.plan_windows(start, end)), expected)

    def test_rules_hold_for_every_corpus_width(self):
        for end in range(328, 1288, 8):
            with self.subTest(end=end):
                windows = rg.plan_windows(0, end)
                self.assertEqual((windows[0].x0, windows[-1].x1), (0, end))
                for win in windows:
                    self.assertLessEqual(win.width, rg.WINDOW_WIDTH)
                    self.assertEqual(win.x0 % 8, 0)
                for left, right in zip(windows, windows[1:]):
                    self.assertGreaterEqual(left.x1 - right.x0, rg.WINDOW_OVERLAP)
                    self.assertLess(left.x0, right.x0)


class RoomPlanTests(unittest.TestCase):
    def test_fixture_rooms(self):
        one = rg.plan_room(fixture_room(1))
        self.assertEqual((spans(one.windows), one.wrap, one.span), ([(0, 320)], None, (0, 320)))
        two = rg.plan_room(fixture_room(2))
        self.assertEqual(spans(two.windows), [(0, 320), (248, 568)])
        wrap = rg.plan_room(fixture_room(3))
        self.assertEqual((wrap.wrap, wrap.span, wrap.margins),
                         (rg.Wrap(840, 224), (0, 840), rg.Margins(0, 88, 0, 0)))
        self.assertEqual(len(wrap.windows), 4)

    def test_margins_round_the_span_out_to_8_columns(self):
        pixels = testkit.room_pixels(testkit.room(9, 320, 200))
        pixels[:, :66], pixels[:, 239:] = 0, 0      # the labyrinth pieces' side margins
        plan = rg.plan_room(testkit.indexed_image(pixels))
        self.assertEqual((plan.margins.left, plan.margins.right), (66, 81))
        self.assertEqual((plan.span, spans(plan.windows)), ((64, 240), [(64, 240)]))

    def test_a_flat_room_has_nothing_to_render(self):
        with self.assertRaisesRegex(ValueError, "set kind: skip"):
            rg.plan_room(fixture_room(4))

    def test_stitch_boundaries(self):
        self.assertEqual(rg.stitch_boundaries(rg.plan_room(fixture_room(1))), [])
        self.assertEqual(rg.stitch_boundaries(rg.plan_room(fixture_room(2))), [1136])
        self.assertEqual(rg.stitch_boundaries(rg.plan_room(fixture_room(3))),
                         [320, 976, 1664, 2368, 3040, 3360])


@unittest.skipUnless((REAL_SRC / "manifest.json").is_file(),
                     "the real atlantis-textures output is not present")
class RealCorpusTests(unittest.TestCase):
    """The measured facts the design rests on (spec section 4)."""

    @classmethod
    def setUpClass(cls):
        source = source_tree.load(REAL_SRC)
        cls.plans = {room.number: rg.plan_room(source_tree.open_indexed(REAL_SRC, room))
                     for room in source.rooms if room.number not in SKIP_ROOMS}

    def test_every_scene_and_insert_plans(self):
        self.assertEqual(len(self.plans), 91)
        for number, plan in self.plans.items():
            with self.subTest(room=number):
                for win in plan.windows:
                    self.assertEqual(win.width % 8, 0)
                    self.assertLessEqual(win.width, rg.WINDOW_WIDTH)

    def test_only_room_58_wraps(self):
        self.assertEqual({n: p.wrap for n, p in self.plans.items() if p.wrap},
                         {58: rg.Wrap(840, 224)})
        self.assertEqual(self.plans[58].margins, rg.Margins(0, 88, 28, 26))

    def test_labyrinth_margins(self):
        self.assertEqual((self.plans[85].margins.left, self.plans[85].span), (66, (64, 320)))
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: ERROR, `AttributeError: module 'room_geometry' has no attribute 'plan_room'` (and `plan_windows`, `stitch_boundaries`).

- [ ] **Step 3: Append the window code to `room_geometry.py`**

```python
# ---- windows ----------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    x0: int                 # native columns [x0, x1), full height
    x1: int

    @property
    def width(self):
        return self.x1 - self.x0


def plan_windows(start, end, width=WINDOW_WIDTH, overlap=WINDOW_OVERLAP):
    """Windows over columns [start, end): at most `width` wide, neighbours
    overlapping by at least `overlap`, each start `start` plus a multiple of 8,
    the first at `start` and the last flush with `end`."""
    span = end - start
    if span <= width:
        return (Window(start, end),)
    n = math.ceil((span - overlap) / (width - overlap))
    while True:
        step = (span - width) / (n - 1)
        starts = [start + 8 * math.floor(i * step / 8) for i in range(n - 1)] + [end - width]
        if all(a + width - b >= overlap for a, b in zip(starts, starts[1:])):
            return tuple(Window(s, s + width) for s in starts)
        n += 1


@dataclass(frozen=True)
class RoomPlan:
    width: int              # the room's native size
    height: int
    margins: Margins
    wrap: Wrap | None
    span: tuple             # (start, end): the native columns the windows cover
    windows: tuple          # of Window, left to right


def plan_room(indexed, width=WINDOW_WIDTH, overlap=WINDOW_OVERLAP):
    """Margins, wraparound and windows of one room.

    The span skips whole-column margins, rounded out to 8 columns so every
    window's 4x width is a multiple of 32; a wraparound room's span ends at its
    period. Raises ValueError for a room with nothing to render.
    """
    pixels = indices(indexed)
    h, w = pixels.shape
    margins = blank_margins(pixels)
    if margins.left >= w:
        raise ValueError("the room is one flat colour: nothing to render (set kind: skip)")
    content_end = w - margins.right
    wrap = find_wrap(pixels, content_end)
    if wrap and wrap.period < width:
        raise ValueError(f"the wraparound period {wrap.period} is narrower than one "
                         f"window ({width}); lower WINDOW_WIDTH")
    start = 8 * (margins.left // 8)
    end = wrap.period if wrap else min(w, 8 * math.ceil(content_end / 8))
    windows = plan_windows(start, end, width, overlap)
    if any(win.width % 8 for win in windows):
        raise ValueError(f"window widths must be multiples of 8 native columns: {windows}")
    return RoomPlan(w, h, margins, wrap, (start, end), windows)


def stitch_from(window, previous):
    """The native column from which `window`'s render replaces the stitch: the
    middle of its overlap with `previous`, or its start when it is the first."""
    return window.x0 if previous is None else window.x0 + (previous.x1 - window.x0) // 2


def stitch_boundaries(plan, width=WINDOW_WIDTH):
    """The 4x columns where the stitched image switches from one render to another."""
    xs = {stitch_from(win, prev) * SCALE for prev, win in zip(plan.windows, plan.windows[1:])}
    if plan.wrap:
        q, period = width // 4, plan.wrap.period
        xs |= {(period - q) * SCALE, q * SCALE, period * SCALE}
    return sorted(xs)
```

- [ ] **Step 4: Run the tests, the real corpus included**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: `OK`, and `RealCorpusTests` shows three passing tests, not `skipped`. These tests pin spec §4's measurements: only room 58 wraps, at (840, 224), with margins (0, 88, 28, 26).

- [ ] **Step 5: Commit**

```bash
git add test_room_geometry.py room_geometry.py
git commit -m "feat: plan each room's windows, span and wraparound"
```

---

### Task 6: Composites, masks, the stitch, the seam and the fix-ups

**Files:**
- Modify: `room_geometry.py` (append), `test_room_geometry.py` (add classes above `if __name__`)

**Interfaces:**
- Consumes: Task 5's `plan_room`, `stitch_from`, `RoomPlan`; Task 3's `to_rgb`.
- Produces: `window_inputs(guide, canvas, window, previous) -> (crop, composite, mask)` (all 4x; the mask is mode L, 255 paints, 0 keeps); `paste_window(canvas, window, previous, rendered)`; `seam_inputs(guide, canvas, plan, width=WINDOW_WIDTH) -> (strip, composite, mask)`; `apply_seam(canvas, plan, rendered, width=WINDOW_WIDTH)`; `apply_fixups(image, plan, indexed) -> Image` (spec §9.4).

- [ ] **Step 1: Write the failing tests**

Add to `test_room_geometry.py`, above `if __name__ == "__main__":`:

```python
class WindowInputTests(unittest.TestCase):
    def setUp(self):
        self.plan = rg.plan_room(fixture_room(2))           # windows (0, 320), (248, 568)
        self.guide = noise((2272, 576), seed=1)
        self.canvas = noise((2272, 576), seed=2)

    def test_a_first_window_is_painted_whole(self):
        crop, composite, mask = rg.window_inputs(self.guide, self.canvas, self.plan.windows[0], None)
        self.assertEqual(crop.size, (1280, 576))
        self.assertEqual(composite.tobytes(), crop.tobytes())
        self.assertEqual((mask.mode, set(np.asarray(mask).ravel())), ("L", {255}))

    def test_a_later_window_holds_the_outer_half_of_its_overlap(self):
        first, second = self.plan.windows
        crop, composite, mask = rg.window_inputs(self.guide, self.canvas, second, first)
        m = np.asarray(mask)
        self.assertTrue((m[:, :144] == 0).all())                # 36 native columns held
        ramp = m[0, 144:288]
        self.assertTrue(((ramp > 0) & (ramp < 255)).all())
        self.assertTrue((np.diff(ramp.astype(int)) >= 0).all())
        self.assertTrue((m[:, 288:] == 255).all())
        c = np.asarray(composite)
        self.assertTrue((c[:, :288] == np.asarray(self.canvas)[:, 992:1280]).all())
        self.assertTrue((c[:, 288:] == np.asarray(crop)[:, 288:]).all())

    def test_paste_window_starts_mid_overlap(self):
        first, second = self.plan.windows
        rendered = noise((1280, 576), seed=3)
        before = np.asarray(self.canvas).copy()
        rg.paste_window(self.canvas, second, first, rendered)
        after = np.asarray(self.canvas)
        self.assertTrue((after[:, :1136] == before[:, :1136]).all())
        self.assertTrue((after[:, 1136:] == np.asarray(rendered)[:, 144:]).all())


class SeamTests(unittest.TestCase):
    def setUp(self):
        self.plan = rg.plan_room(fixture_room(3))           # wrap (840, 224)
        self.guide = noise((4608, 576), seed=4)
        self.canvas = noise((4608, 576), seed=5)

    def test_seam_inputs_roll_the_join_into_the_middle(self):
        strip, composite, mask = rg.seam_inputs(self.guide, self.canvas, self.plan)
        self.assertEqual(strip.size, (1280, 576))
        c, canvas = np.asarray(composite), np.asarray(self.canvas)
        self.assertTrue((c[:, :640] == canvas[:, 2720:3360]).all())
        self.assertTrue((c[:, 640:] == canvas[:, :640]).all())
        m = np.asarray(mask)[0]
        self.assertTrue((m[:320] == 0).all() and (m[960:] == 0).all())
        self.assertTrue((m[480:800] == 255).all())
        self.assertTrue(((m[320:480] > 0) & (m[320:480] < 255)).all())

    def test_apply_seam_writes_both_ends(self):
        rendered = noise((1280, 576), seed=6)
        before = np.asarray(self.canvas).copy()
        rg.apply_seam(self.canvas, self.plan, rendered)
        after, r = np.asarray(self.canvas), np.asarray(rendered)
        self.assertTrue((after[:, 3040:3360] == r[:, 320:640]).all())
        self.assertTrue((after[:, :320] == r[:, 640:960]).all())
        self.assertTrue((after[:, 320:3040] == before[:, 320:3040]).all())
        self.assertTrue((after[:, 3360:] == before[:, 3360:]).all())


class FixupTests(unittest.TestCase):
    def test_wrap_copy_and_margin(self):
        indexed = fixture_room(3)
        out = np.asarray(rg.apply_fixups(noise((4608, 576), seed=7), rg.plan_room(indexed), indexed))
        self.assertTrue((out[:, 3360:4256] == out[:, :896]).all())
        self.assertTrue((out[:, 4256:] == 0).all())

    def test_top_and_bottom_margins(self):
        pixels = testkit.room_pixels(testkit.room(9, 320, 144))
        pixels[:28], pixels[-26:] = 0, 0            # room 58's letterbox rows
        indexed = testkit.indexed_image(pixels)
        out = np.asarray(rg.apply_fixups(noise((1280, 576), seed=8), rg.plan_room(indexed), indexed))
        self.assertTrue((out[:112] == 0).all() and (out[-104:] == 0).all())
        self.assertFalse((out[112:-104] == 0).all())

    def test_nothing_to_fix(self):
        indexed = fixture_room(1)
        image = noise((1280, 576), seed=9)
        self.assertEqual(rg.apply_fixups(image, rg.plan_room(indexed), indexed).tobytes(),
                         image.tobytes())
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: ERROR, `AttributeError: module 'room_geometry' has no attribute 'apply_fixups'` (and `window_inputs`, `paste_window`, `seam_inputs`, `apply_seam`).

- [ ] **Step 3: Append the composite, stitch, seam and fix-up code to `room_geometry.py`**

```python
# ---- composites, stitch, seam, fix-ups --------------------------------------

def _mask_row(width_4x, zero_until, full_from):
    """A 4x mask row: 0 before `zero_until`, a ramp strictly between 0 and 255
    up to `full_from`, 255 from there."""
    row = np.full(width_4x, 255, np.uint8)
    row[:zero_until] = 0
    n = full_from - zero_until
    if n > 0:
        row[zero_until:full_from] = np.round(np.arange(1, n + 1) * 255 / (n + 1))
    return row


def _mask(row, height):
    return Image.fromarray(np.tile(row, (height, 1)))


def window_inputs(guide, canvas, window, previous):
    """(guide crop, composite, mask) for rendering `window`, all 4x.

    `guide` is the 4x guide and `canvas` the stitch so far. The composite is the
    guide crop with its overlap with `previous` taken from the canvas. The mask
    (255 paints, 0 keeps) holds the overlap's outer half, ramps across its inner
    half and frees the rest; a first window is painted whole.
    """
    h = guide.height
    crop = guide.crop((window.x0 * SCALE, 0, window.x1 * SCALE, h))
    composite = crop.copy()
    if previous is None:
        return crop, composite, _mask(np.full(crop.width, 255, np.uint8), h)
    overlap = previous.x1 - window.x0
    composite.paste(canvas.crop((window.x0 * SCALE, 0, previous.x1 * SCALE, h)), (0, 0))
    row = _mask_row(crop.width, (overlap // 2) * SCALE, overlap * SCALE)
    return crop, composite, _mask(row, h)


def paste_window(canvas, window, previous, rendered):
    """Stitch `rendered`, the window's 4x render, into `canvas` from stitch_from on."""
    x = stitch_from(window, previous)
    offset = (x - window.x0) * SCALE
    canvas.paste(rendered.crop((offset, 0, rendered.width, rendered.height)), (x * SCALE, 0))


def _rolled(image, period, half):
    """The 4x columns of native [period - half, period) followed by [0, half)."""
    h = image.height
    strip = Image.new("RGB", (2 * half * SCALE, h))
    strip.paste(image.crop(((period - half) * SCALE, 0, period * SCALE, h)), (0, 0))
    strip.paste(image.crop((0, 0, half * SCALE, h)), (half * SCALE, 0))
    return strip


def seam_inputs(guide, canvas, plan, width=WINDOW_WIDTH):
    """(guide strip, composite, mask) for the seam window across a wraparound's join.

    The strip is the span's last width/2 columns followed by its first width/2.
    The mask holds the outer quarters, ramps across the next eighths and paints
    the middle quarter fully.
    """
    period, half, q, e = plan.wrap.period, width // 2, width // 4, width // 8
    up = _mask_row(width * SCALE, q * SCALE, (q + e) * SCALE)
    row = np.minimum(up, up[::-1])
    return _rolled(guide, period, half), _rolled(canvas, period, half), _mask(row, guide.height)


def apply_seam(canvas, plan, rendered, width=WINDOW_WIDTH):
    """Write the seam render's middle half back to both ends of `canvas`."""
    period, half, q = plan.wrap.period, width // 2, width // 4
    h = canvas.height
    canvas.paste(rendered.crop((q * SCALE, 0, half * SCALE, h)), ((period - q) * SCALE, 0))
    canvas.paste(rendered.crop((half * SCALE, 0, (half + q) * SCALE, h)), (0, 0))


def apply_fixups(image, plan, indexed):
    """A copy of the 4x `image` with the wraparound's repeat copied from the
    room's start, and the margins set to the source's flat colours."""
    out = image.copy()
    h = out.height
    if plan.wrap:
        period, span = plan.wrap.period, plan.wrap.span
        out.paste(out.crop((0, 0, span * SCALE, h)), (period * SCALE, 0))
    m = plan.margins
    if m.left or m.right or m.top or m.bottom:
        flat = to_rgb(indexed).resize(out.size, Image.Resampling.NEAREST)
        w, rows = plan.width, plan.height
        for x0, y0, x1, y1 in ((0, 0, m.left, rows), (w - m.right, 0, w, rows),
                               (0, 0, w, m.top), (0, rows - m.bottom, w, rows)):
            if x1 > x0 and y1 > y0:
                box = (x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE)
                out.paste(flat.crop(box), box[:2])
    return out
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add test_room_geometry.py room_geometry.py
git commit -m "feat: window composites and masks, the stitch, the wrap seam and the fix-ups"
```

---

### Task 7: The geometry check

**Files:**
- Create: `test_geometry_check.py`, `geometry_check.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (numpy and Pillow only; windows are `(x0, x1)` tuples).
- Produces: `MAX_SHIFT`, `EDGE_THRESHOLD`, `MIN_EDGE_AGREEMENT`, `SEAM_WARN`, `SEAM_BAND`, `SEAM_CAP`; `GeometryResult(shift, window_shifts, edge_agreement, seam_ratios, issues)` with property `passed` and method `as_dict() -> dict`; `luminance(image) -> np.ndarray`; `phase_shift(a, b) -> (dx, dy)`; `sobel(lum) -> np.ndarray`; `edge_agreement(source, render, threshold=EDGE_THRESHOLD) -> float`; `seam_ratio(image, x, band=SEAM_BAND) -> float`; `check(render, source, windows=(), boundaries=(), reference=None) -> GeometryResult`. Issue strings start with `geometry:` (spec §10).

A measured fact the tests encode: on the real art, phase correlation reads a 2-pixel shift as exactly 2.0, while edge agreement barely drops (it stays between 0.81 and 0.99 across rooms 1, 29, 47, 52, 58, 85 and 14). So the shift catches slides and edge agreement catches lost structure; neither replaces the other.

One refinement over spec §10.3: a seam ratio is divided by the guide's own ratio at the same column (`reference`), so a stitch boundary that falls on a real edge of the source is not called a seam. Pre-flight validation of this plan found the undivided ratio flagging every boundary that landed on a block edge.

- [ ] **Step 1: Write the failing tests**

`test_geometry_check.py`:

```python
import json
import unittest

import numpy as np
from PIL import Image

import geometry_check as gc


def blocks(width, height, seed=0, size=8):
    rng = np.random.default_rng(seed)
    grid = rng.integers(0, 256, size=(-(-height // size), -(-width // size), 3), dtype=np.uint8)
    return Image.fromarray(np.kron(grid, np.ones((size, size, 1), np.uint8))[:height, :width])


def up(image):
    return image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST)


def shifted(image, dx):
    out = Image.new("RGB", image.size)
    out.paste(image, (dx, 0))
    return out


class PhaseShiftTests(unittest.TestCase):
    def test_measures_a_known_displacement(self):
        a = gc.luminance(blocks(96, 64))
        for dx, dy in ((2, 0), (0, 3), (-1, 0)):
            with self.subTest(dx=dx, dy=dy):
                sx, sy = gc.phase_shift(a, np.roll(np.roll(a, dy, axis=0), dx, axis=1))
                self.assertAlmostEqual(sx, dx, delta=0.25)
                self.assertAlmostEqual(sy, dy, delta=0.25)

    def test_identical_is_zero(self):
        a = gc.luminance(blocks(96, 64))
        self.assertEqual(gc.phase_shift(a, a), (0.0, 0.0))

    def test_flat_reads_as_zero(self):
        # Review Focus: a window of flat black (the labyrinth pieces) has no position.
        self.assertEqual(gc.phase_shift(np.zeros((64, 96)), gc.luminance(blocks(96, 64))),
                         (0.0, 0.0))


class EdgeAgreementTests(unittest.TestCase):
    def setUp(self):
        self.source = gc.luminance(blocks(96, 64, size=16))

    def test_identical(self):
        self.assertEqual(gc.edge_agreement(self.source, self.source), 1.0)

    def test_added_fine_texture_keeps_the_edges(self):
        rng = np.random.default_rng(1)
        render = self.source + rng.normal(0, 6, self.source.shape)
        self.assertGreaterEqual(gc.edge_agreement(self.source, render), 0.95)

    def test_a_removed_region_loses_its_edges(self):
        render = self.source.copy()
        render[:, :60] = render[:, :60].mean()
        self.assertLess(gc.edge_agreement(self.source, render), gc.MIN_EDGE_AGREEMENT)

    def test_no_source_edges(self):
        self.assertEqual(gc.edge_agreement(np.zeros((8, 8)), np.ones((8, 8))), 1.0)


class SeamRatioTests(unittest.TestCase):
    def test_a_hard_step_stands_out(self):
        rng = np.random.default_rng(2)
        arr = rng.normal(128, 4, (32, 256, 3))
        arr[:, 128:] += 60
        image = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        self.assertGreater(gc.seam_ratio(image, 128), gc.SEAM_WARN)

    def test_texture_without_a_step_does_not(self):
        self.assertLess(gc.seam_ratio(blocks(256, 32, seed=3, size=1), 128), gc.SEAM_WARN)

    def test_a_flat_image(self):
        self.assertEqual(gc.seam_ratio(Image.new("RGB", (64, 8)), 32), 0.0)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.source = blocks(128, 64, seed=4)

    def test_an_aligned_render_passes(self):
        result = gc.check(up(self.source), self.source, windows=[(0, 64), (64, 128)],
                          boundaries=[256])
        self.assertTrue(result.passed, result.issues)
        self.assertEqual((len(result.window_shifts), len(result.seam_ratios)), (2, 1))
        json.dumps(result.as_dict())

    def test_a_shifted_render_fails(self):
        result = gc.check(shifted(up(self.source), 8), self.source)
        self.assertFalse(result.passed)
        self.assertIn("the room is shifted +2.0", result.issues[0])

    def test_a_shift_inside_one_window_is_named(self):
        render = up(self.source)
        render.paste(shifted(render.crop((256, 0, 512, 256)), 8), (256, 0))
        result = gc.check(render, self.source, windows=[(0, 64), (64, 128)])
        self.assertTrue(any("window 2 is shifted" in issue for issue in result.issues),
                        result.issues)
        self.assertFalse(any("window 1" in issue for issue in result.issues))

    def test_a_boundary_on_a_source_edge_is_not_a_seam(self):
        arr = np.full((64, 128, 3), 40, np.uint8)
        arr[:, 64:] = 200                           # the source's own edge at column 64
        source = Image.fromarray(arr)
        alone = gc.check(up(source), source, boundaries=[256])
        against = gc.check(up(source), source, boundaries=[256], reference=up(source))
        self.assertGreater(alone.seam_ratios[0], gc.SEAM_WARN)
        self.assertLessEqual(against.seam_ratios[0], 1.0)

    def test_a_flat_window_passes(self):
        # Review Focus: the labyrinth pieces are half flat black.
        arr = np.asarray(self.source).copy()
        arr[:, :64] = 0
        source = Image.fromarray(arr)
        result = gc.check(up(source), source, windows=[(0, 64), (64, 128)])
        self.assertTrue(result.passed, result.issues)
        self.assertEqual(result.window_shifts[0], (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_geometry_check -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'geometry_check'`.

- [ ] **Step 3: Write `geometry_check.py`**

```python
"""The deterministic geometry check of a 4x render against its native source.

The re-import-safe gate: a render whose content slid, or that lost the
source's edges, is not promoted. Numpy maths on Pillow images; knows no files,
rooms or audit tree. Windows are native (x0, x1) column pairs; seam boundaries
are 4x columns.

Each measure has one job. Phase correlation finds a slid room or window (a
2-pixel shift reads as 2.0). Edge agreement finds lost or moved structure: on
the real art a 2-pixel shift still keeps most edges within 1 pixel, so it is
no shift detector.
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image

MAX_SHIFT = 0.5             # native px, whole room and per window
EDGE_THRESHOLD = 80.0       # Sobel magnitude on 0-255 luminance that counts as an edge
MIN_EDGE_AGREEMENT = 0.80   # the least fraction of source edges the render keeps within 1 px
SEAM_WARN = 3.0             # the step across a stitch boundary against the local column steps
SEAM_BAND = 64              # 4x columns either side of a boundary that set the local step
SEAM_CAP = 999.0            # a step where there is no local variation at all reads as this


@dataclass(frozen=True)
class GeometryResult:
    shift: tuple            # (dx, dy) of the whole room, native px
    window_shifts: tuple    # ((dx, dy), ...) per window
    edge_agreement: float
    seam_ratios: tuple      # per stitch boundary; warnings only
    issues: tuple           # why the render fails; empty when it passes

    @property
    def passed(self):
        return not self.issues

    def as_dict(self):
        return {"passed": self.passed, "shift": list(self.shift),
                "window_shifts": [list(s) for s in self.window_shifts],
                "edge_agreement": self.edge_agreement,
                "seam_ratios": list(self.seam_ratios), "issues": list(self.issues)}


def luminance(image):
    return np.asarray(image.convert("L"), dtype=np.float64)


def phase_shift(a, b):
    """(dx, dy) by which luminance array `b` is displaced from `a`, sub-pixel.

    Phase correlation under a Hann window, refined by a parabola through the
    peak. A flat array has no position to measure and reads as (0, 0).
    """
    if a.std() < 1 or b.std() < 1:
        return (0.0, 0.0)
    h, w = a.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    fa = np.fft.fft2((a - a.mean()) * window)
    fb = np.fft.fft2((b - b.mean()) * window)
    cross = fb * np.conj(fa)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.ifft2(cross).real
    py, px = np.unravel_index(np.argmax(corr), corr.shape)

    def refine(before, peak, after):
        denominator = before - 2 * peak + after
        return 0.0 if denominator == 0 else 0.5 * (before - after) / denominator

    dy = py + refine(corr[(py - 1) % h, px], corr[py, px], corr[(py + 1) % h, px])
    dx = px + refine(corr[py, (px - 1) % w], corr[py, px], corr[py, (px + 1) % w])
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return (round(float(dx), 3) + 0.0, round(float(dy), 3) + 0.0)


def sobel(lum):
    p = np.pad(lum, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy)


def _grow(mask):
    """`mask` grown by one pixel in every direction."""
    p = np.pad(mask, 1)
    out = np.zeros_like(mask)
    for dy in range(3):
        for dx in range(3):
            out |= p[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return out


def edge_agreement(source, render, threshold=EDGE_THRESHOLD):
    """The fraction of the source's edge pixels with a render edge within 1 px;
    1.0 when the source has no edges. Arrays are native-size luminance."""
    edges = sobel(source) > threshold
    if not edges.any():
        return 1.0
    kept = edges & _grow(sobel(render) > threshold)
    return float(kept.sum() / edges.sum())


def seam_ratio(image, x, band=SEAM_BAND):
    """The colour step between 4x columns x-1 and x, over the median step
    between neighbouring columns within `band` on either side."""
    lo, hi = max(0, x - band - 1), min(image.width, x + band + 1)
    a = np.asarray(image.crop((lo, 0, hi, image.height)).convert("RGB"), dtype=np.float64)
    steps = np.abs(np.diff(a, axis=1)).mean(axis=(0, 2))    # steps[i]: column i to i + 1
    at = x - 1 - lo
    around = np.concatenate([steps[:at], steps[at + 1:]])
    base = float(np.median(around)) if around.size else 0.0
    step = float(steps[at])
    if base == 0:
        return 0.0 if step == 0 else SEAM_CAP
    return round(min(step / base, SEAM_CAP), 3)


def check(render, source, windows=(), boundaries=(), reference=None):
    """Compare the 4x `render` with its de-dithered native `source` (both RGB).

    A seam ratio is the render's step at a boundary over its local steps; with a
    4x `reference` (the guide) it is divided by the reference's own ratio there,
    so a boundary that falls on a real edge of the source is not called a seam.
    """
    small = luminance(render.resize(source.size, Image.Resampling.BOX))
    base = luminance(source)
    issues = []
    shift = phase_shift(base, small)
    if max(abs(shift[0]), abs(shift[1])) >= MAX_SHIFT:
        issues.append(f"geometry: the room is shifted {shift[0]:+.1f},{shift[1]:+.1f} px")
    window_shifts = []
    for k, (x0, x1) in enumerate(windows, 1):
        ws = phase_shift(base[:, x0:x1], small[:, x0:x1])
        window_shifts.append(ws)
        if max(abs(ws[0]), abs(ws[1])) >= MAX_SHIFT:
            issues.append(f"geometry: window {k} is shifted {ws[0]:+.1f},{ws[1]:+.1f} px")
    agreement = round(edge_agreement(base, small), 4)
    if agreement < MIN_EDGE_AGREEMENT:
        issues.append(f"geometry: edge agreement {agreement:.2f}, needs "
                      f"{MIN_EDGE_AGREEMENT:.2f}")
    ratios = []
    for x in boundaries:
        ratio = seam_ratio(render, x)
        if reference is not None:
            ratio = round(ratio / max(1.0, seam_ratio(reference, x)), 3)
        ratios.append(ratio)
    return GeometryResult(shift, tuple(window_shifts), agreement, tuple(ratios), tuple(issues))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_geometry_check -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add test_geometry_check.py geometry_check.py
git commit -m "feat: the geometry gate: shift, edge agreement and seam ratio"
```

---

### Task 8: The colour match

**Files:**
- Create: `test_colour_match.py`, `colour_match.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `RULE = "source-relative"`; `lab_stats(image) -> (means, stds)`; `match(render, guide, strength=1.0) -> Image` (spec §9.7).

- [ ] **Step 1: Write the failing tests**

`test_colour_match.py`:

```python
import unittest

import numpy as np
from PIL import Image

import colour_match as cm


class MatchTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.guide = Image.fromarray(rng.integers(60, 200, (64, 96, 3), dtype=np.uint8))
        render = rng.integers(0, 120, (64, 96, 3))
        render[..., 0] += 100                           # a red cast
        self.render = Image.fromarray(render.astype(np.uint8))

    def test_strength_zero_keeps_the_raw_pixels(self):
        self.assertEqual(cm.match(self.render, self.guide, 0).tobytes(), self.render.tobytes())

    def test_full_strength_takes_the_guide_statistics(self):
        (gm, gs), (om, os_) = cm.lab_stats(self.guide), cm.lab_stats(
            cm.match(self.render, self.guide, 1.0))
        for band in range(3):
            with self.subTest(band=band):
                self.assertAlmostEqual(om[band], gm[band], delta=2.5)
                self.assertAlmostEqual(os_[band], gs[band], delta=3.5)

    def test_half_strength_lands_between(self):
        raw, guide = cm.lab_stats(self.render)[0][0], cm.lab_stats(self.guide)[0][0]
        half = cm.lab_stats(cm.match(self.render, self.guide, 0.5))[0][0]
        self.assertAlmostEqual(half, (raw + guide) / 2, delta=4)

    def test_a_flat_render(self):
        out = cm.match(Image.new("RGB", (32, 16), (90, 90, 90)), self.guide, 1.0)
        self.assertEqual((out.size, out.mode), ((32, 16), "RGB"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_colour_match -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'colour_match'`.

- [ ] **Step 3: Write `colour_match.py`**

```python
"""Pull a render's colours toward its own source guide.

Rule "source-relative": the render's per-band Lab mean and spread move toward
the guide's (the de-dithered source, upscaled), blended by strength. There are
no anchors: the painted look keeps the game's colours, and the rooms of one
location already share the game's palette. Pure image maths on Pillow's 8-bit
LAB mode (littlecms); knows no rooms or files. The Lab helpers come from the
AITD kit's colour_match.py.
"""
from PIL import Image, ImageCms, ImageStat

RULE = "source-relative"

_SRGB = ImageCms.createProfile("sRGB")
_LAB = ImageCms.createProfile("LAB")
_TO_LAB = ImageCms.buildTransformFromOpenProfiles(_SRGB, _LAB, "RGB", "LAB")
_TO_RGB = ImageCms.buildTransformFromOpenProfiles(_LAB, _SRGB, "LAB", "RGB")


def _to_lab(image):
    return ImageCms.applyTransform(image.convert("RGB"), _TO_LAB)


def lab_stats(image):
    """(means, stds): three floats each, over Pillow's 8-bit L, A, B bands."""
    stat = ImageStat.Stat(_to_lab(image))
    return tuple(stat.mean), tuple(stat.stddev)


def _clamp(value):
    return min(255, max(0, round(value)))


def match(render, guide, strength=1.0):
    """The render shifted and scaled per Lab band toward `guide`'s mean and
    spread, blended by `strength`. Returns a new RGB image of the render's size;
    strength 0 returns the raw pixels unchanged (no Lab round trip)."""
    if strength == 0:
        return render.convert("RGB").copy()
    lab = _to_lab(render)
    stat = ImageStat.Stat(lab)
    target_means, target_stds = lab_stats(guide)
    bands = []
    for band, mean, std, tmean, tstd in zip(lab.split(), stat.mean, stat.stddev,
                                            target_means, target_stds):
        gain = tstd / std if std else 1.0
        table = [_clamp(v + strength * ((v - mean) * gain + tmean - v)) for v in range(256)]
        bands.append(band.point(table))
    return ImageCms.applyTransform(Image.merge("LAB", bands), _TO_RGB)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_colour_match -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add test_colour_match.py colour_match.py
git commit -m "feat: colour-match a render toward its own source guide"
```

---

### Task 9: Prompts and VLM requests

**Files:**
- Create: `test_prompts.py`, `prompts.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `CAPTION_TIMEOUT`, `REVIEW_TIMEOUT`, `VLM_MAX_SIDE`, `CAPTION_QUESTION`, `SECTION_LABELS`, `DEFAULT_REFERENCE`, `PAINTED_RULES`, `INSERT_RULES`, `INSERT_LETTERING`, `SEAM_NOTE`, `PAINTED_NEGATIVE`, `REVIEW_QUESTION`; `text_section(caption) -> str | None`; `window_note(x0, x1, start, end) -> str`; `render_prompt(caption, kind, corrections=(), note="", reference=DEFAULT_REFERENCE) -> str`; `caption_room(images, http, base_url, model, key) -> str`; `parse_review(text) -> {"accepted": bool, "issues": [str]}`; `review_room(pairs, overview, kind, caption, http, base_url, model, key) -> dict`; `vlm_is_serving(base_url, model, http, key="") -> bool`. Images may be paths or Pillow images (spec §8 step 1, §9.6, §10.4).

- [ ] **Step 1: Write the failing tests**

`test_prompts.py`:

```python
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import prompts as p

CAPTION = ("SCENE: a newspaper page.\nVIEW: flat, frontal.\n"
           "**TEXT:** German Wizard Splits Atom (headline, top)\n"
           "**INVARIANTS:** the photograph sits below the headline.")


class FakeVLM:
    """Answers /chat/completions with `content`, recording each request."""

    def __init__(self, content, finish="stop"):
        self.content, self.finish, self.calls = content, finish, []

    def __call__(self, url, data=None, timeout=60, token=None):
        self.calls.append((url, json.loads(data), timeout, token))
        return {"choices": [{"finish_reason": self.finish,
                             "message": {"content": self.content}}]}


def decoded_size(part):
    data = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
    with Image.open(io.BytesIO(data)) as im:
        return im.size


class TextSectionTests(unittest.TestCase):
    def test_extracts_until_the_next_label(self):
        self.assertEqual(p.text_section(CAPTION), "German Wizard Splits Atom (headline, top)")

    def test_none_or_absent(self):
        self.assertIsNone(p.text_section("SCENE: a cave.\nTEXT: none.\nINVARIANTS: x"))
        self.assertIsNone(p.text_section("SCENE: a cave."))

    def test_multi_line(self):
        self.assertEqual(p.text_section("TEXT: ARTIFACTS (sign)\nAPOTHECARY (door)\nPALETTE: ochre"),
                         "ARTIFACTS (sign)\nAPOTHECARY (door)")


class RenderPromptTests(unittest.TestCase):
    def test_scene(self):
        text = p.render_prompt("SCENE: a study.", "scene", reference="<image1>")
        self.assertTrue(text.startswith("Repaint <image1> as a high-definition hand-painted"))
        self.assertIn("REFERENCE OBSERVATIONS:\nSCENE: a study.", text)
        self.assertNotIn("LETTERING", text)
        self.assertNotIn("CORRECT THESE", text)

    def test_insert_carries_its_lettering(self):
        self.assertIn("LETTERING:\nGerman Wizard Splits Atom (headline, top)",
                      p.render_prompt(CAPTION, "insert"))

    def test_insert_without_a_text_section(self):
        # Review Focus: a hand-edited insert caption with no TEXT section.
        text = p.render_prompt("SCENE: a stone tablet.", "insert")
        self.assertIn(p.INSERT_RULES, text)
        self.assertNotIn("LETTERING:", text)

    def test_window_note_and_corrections(self):
        note = p.window_note(248, 568, 0, 568)
        self.assertIn("from 44% to 100%", note)
        text = p.render_prompt("SCENE: a street.", "scene", ["the awning moved left"], note)
        self.assertIn(note, text)
        self.assertIn("CORRECT THESE PROBLEMS FROM THE PREVIOUS ATTEMPT WHILE KEEPING THE "
                      "REFERENCE LAYOUT:\nthe awning moved left", text)


class RequestTests(unittest.TestCase):
    def test_caption_sends_every_image(self):
        vlm = FakeVLM("SCENE: x")
        images = [Image.new("RGB", (640, 144)), Image.new("RGB", (1280, 576))]
        self.assertEqual(p.caption_room(images, vlm, "http://h/v1/", "m", "k"), "SCENE: x")
        url, payload, timeout, token = vlm.calls[0]
        self.assertEqual((url, timeout, token), ("http://h/v1/chat/completions",
                                                 p.CAPTION_TIMEOUT, "k"))
        parts = payload["messages"][1]["content"]
        self.assertEqual((parts[0]["text"], len(parts)), (p.CAPTION_QUESTION, 3))
        self.assertNotIn("response_format", payload)

    def test_images_are_scaled_to_the_longer_side(self):
        self.assertEqual(decoded_size(p._image(Image.new("RGB", (320, 144)))), (1280, 576))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "room.png"
            Image.new("RGB", (2560, 400)).save(path)
            self.assertEqual(decoded_size(p._image(path)), (1280, 200))

    def test_a_truncated_answer_is_refused(self):
        with self.assertRaisesRegex(ValueError, "truncated"):
            p.caption_room([Image.new("RGB", (8, 8))], FakeVLM("x", "length"), "http://h/v1",
                           "m", "")

    def test_review_sends_pairs_then_the_overview(self):
        vlm = FakeVLM('{"accepted": false, "issues": ["window 2: the awning moved; move it back"]}')
        pairs = [(Image.new("RGB", (64, 32)), Image.new("RGB", (64, 32)))] * 2
        verdict = p.review_room(pairs, Image.new("RGB", (128, 32)), "insert", CAPTION, vlm,
                                "http://h/v1", "m", "")
        self.assertEqual(verdict, {"accepted": False,
                                   "issues": ["window 2: the awning moved; move it back"]})
        payload = vlm.calls[0][1]
        content = payload["messages"][1]["content"]
        self.assertIn("This room has 2 window(s). Kind: insert. Expected lettering: "
                      "German Wizard Splits Atom (headline, top).", content[0]["text"])
        self.assertEqual(len(content), 1 + 5)
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_vlm_is_serving(self):
        self.assertTrue(p.vlm_is_serving("http://h/v1", "m",
                                         lambda url, **kw: {"data": [{"id": "m"}]}))
        self.assertFalse(p.vlm_is_serving("http://h/v1", "m",
                                          lambda url, **kw: {"data": [{"id": "other"}]}))

        def down(url, **kw):
            raise OSError("connection refused")
        self.assertFalse(p.vlm_is_serving("http://h/v1", "m", down))


class ParseReviewTests(unittest.TestCase):
    def test_plain_fenced_and_wrapped_json(self):
        for text in ('{"accepted": true, "issues": []}',
                     '```json\n{"accepted": true, "issues": []}\n```',
                     'Verdict: {"accepted": true, "issues": []} done'):
            with self.subTest(text=text):
                self.assertEqual(p.parse_review(text), {"accepted": True, "issues": []})

    def test_malformed_verdicts(self):
        for text, message in (('{"accepted": "yes", "issues": []}', "boolean accepted"),
                              ('{"accepted": false, "issues": [""]}', "nonempty issue strings"),
                              ('{"accepted": true, "issues": ["moved"]}', "contradicts")):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, message):
                    p.parse_review(text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_prompts -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'prompts'`.

- [ ] **Step 3: Write `prompts.py`**

```python
"""Prompts and VLM requests: the caption question, the painted render prompt,
the review question and its parser.

Knows no files or make targets: the driver hands it images (paths or Pillow
images) and text. The VLM plumbing (_image, _ask, parse_review,
vlm_is_serving) comes from the AITD kit's recreation_quality.py.
"""
import base64
import io
import json
import re
from pathlib import Path

from PIL import Image

CAPTION_TIMEOUT = 900   # a caption is up to 1600 tokens; about 4 tok/s on this host
REVIEW_TIMEOUT = 600    # a review is up to 1200 tokens
VLM_MAX_SIDE = 1280     # every image is scaled so its longer side is this

CAPTION_QUESTION = '''Image 1 is a background from Indiana Jones and the Fate of Atlantis (LucasArts, 1992), a hand-painted 256-colour point-and-click adventure game. Any further images are consecutive windows of the same room from left to right. Describe it for an artist who will repaint it in high definition with exactly the same composition. Report only what the images show; this is observation, not creative writing.
Use these short labelled sections:
SCENE: the kind of place (interior, exterior, close-up insert, map), its architecture and atmosphere.
VIEW: viewpoint, framing and perspective.
LAYOUT: the major objects and surfaces from left to right, each with its horizontal position as a fraction of the room's width (0 is the left edge, 1 the right edge) and its vertical position (0 top, 1 bottom), relative size and occlusion. Cover foreground, middle and background.
OBJECTS: doors, windows, openings, furniture and props, with their open or closed states; say absent if there are none.
LIGHTING: light sources, their direction, the exposure and the shadows. Dark areas stay dark.
PALETTE: the dominant colours of each major area.
TEXT: every piece of lettering that is legible, transcribed verbatim with its position; write none if there is none. Do not guess at illegible text.
INVARIANTS: the composition and object relationships that must survive repainting. Mark ambiguity instead of inventing detail.
The game draws its characters separately, so say "no people" unless people are painted into the background itself. Do not prescribe a style, lens or colour grade. Keep under 600 words.'''

SECTION_LABELS = ("SCENE", "VIEW", "LAYOUT", "OBJECTS", "LIGHTING", "PALETTE", "TEXT",
                  "INVARIANTS")

DEFAULT_REFERENCE = "the provided reference image"   # how the 2511 prompt names the window

PAINTED_RULES = '''Repaint {reference} as a high-definition hand-painted background for a classic point-and-click adventure game, in the manner of the painted backgrounds of early-1990s LucasArts adventures: confident painterly brushwork, rich but faithful colour, soft painted light and shadow, crisp readable shapes.
Keep the exact composition. Every object, edge, opening and horizon stays where the reference puts it, at the same size and in the same perspective; nothing is moved, added, removed or resized. Add no people, creatures or characters that the reference does not show.
Keep the reference's colours, time of day, light sources and shadow pattern. Dark areas stay dark and flat black areas stay flat black.
Replace the dithering and blocky pixels with painted texture and fine detail that suit each material: wood grain, stone, cloth, foliage, metal, water, sky. No photograph, no 3D render, no pixel art, no border or frame.'''

INSERT_RULES = '''This is a full-screen close-up insert, not a room. Keep any lettering exactly as the reference shows it, in the same place and style; illegible small print stays illegible texture.'''

INSERT_LETTERING = INSERT_RULES + '''
Reproduce this lettering exactly, spelled as written, in the same place and style, legible where the reference is legible:
LETTERING:
{text}'''

SEAM_NOTE = '''This image straddles the join of a wraparound panorama: its left half is the room's right end and its right half is the room's left end. Paint one continuous scene across the middle, with no seam.'''

PAINTED_NEGATIVE = ("photograph, photorealistic, 3D render, CGI, pixel art, dithering, jpeg "
                    "artifacts, blurry, noisy, people, characters, figures, extra objects, "
                    "changed text, extra text, watermark, signature, frame, border")

REVIEW_QUESTION = '''The images come in pairs. In each pair the first image is one window of the authoritative original background of a 1992 hand-painted adventure game (smoothed and enlarged), and the second is the same window of a high-definition repaint. The last image is the whole repaint, downscaled. Judge fidelity first, then style. Painted texture and fine detail replacing the original's pixels is the goal and is never a reason to reject.
Reject when:
1. layout: an object, edge, opening or horizon is added, dropped, moved or resized, the perspective or framing changed, or a person, creature or character appears that the original lacks;
2. style: the repaint looks like a photograph or a 3D render, or keeps the original's flat, dithered pixels instead of painted detail;
3. lettering (close-up inserts only): legible lettering differs from the expected lettering below, or became illegible;
4. seams: a visible vertical seam, a doubled object or repeated detail where windows meet, or a jump in colour or texture between neighbouring windows in the whole repaint.
Return ONLY JSON: {"accepted": true or false, "issues": ["one specific problem: its window number, its screen position and a concrete correction"]}. Accept only if there are no significant problems; use an empty issues list when accepted. At most six issues.'''

_NONE = ("none", "no text", "absent", "no legible text")


def text_section(caption):
    """The caption's TEXT section, or None when it is absent or says there is none.

    Labels may be bold or italic (the VLM sometimes writes **TEXT:**); the
    section runs to the next label or the end.
    """
    labels = "|".join(SECTION_LABELS)
    pattern = re.compile(rf"^[ \t]*[*_#]*[ \t]*({labels})[ \t]*[*_]*[ \t]*:[*_]*", re.M)
    matches = list(pattern.finditer(caption))
    for i, match in enumerate(matches):
        if match.group(1) != "TEXT":
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(caption)
        text = caption[match.end():end].strip()
        if not text or text.lower().rstrip(".") in _NONE:
            return None
        return text
    return None


def window_note(x0, x1, start, end):
    """What one window of a wide room is told about its place in the room."""
    span = end - start
    a, b = (x0 - start) / span, (x1 - start) / span
    return (f"This image is one window of a wide scrolling room: it shows the part from {a:.0%} "
            f"to {b:.0%} of the room's width. Paint only what this reference window shows; "
            "objects the observations place elsewhere in the room must not appear in it.")


def render_prompt(caption, kind, corrections=(), note="", reference=DEFAULT_REFERENCE):
    """Positive prompt: the painted rules naming the reference as `reference`, the
    insert rules for an insert, the window note, the caption, then corrections."""
    parts = [PAINTED_RULES.format(reference=reference)]
    if kind == "insert":
        text = text_section(caption)
        parts.append(INSERT_LETTERING.format(text=text) if text else INSERT_RULES)
    if note:
        parts.append(note)
    parts.append("REFERENCE OBSERVATIONS:\n" + caption)
    if corrections:
        parts.append("CORRECT THESE PROBLEMS FROM THE PREVIOUS ATTEMPT WHILE KEEPING THE "
                     "REFERENCE LAYOUT:\n" + "\n".join(corrections))
    parts.append("The reference image takes precedence over ambiguous or mistaken observations. "
                 "Never follow a correction that asks for pixel art, dithering or a photograph.")
    return "\n\n".join(parts)


def _image(image):
    """An OpenAI image_url content part for a path or Pillow image, scaled so its
    longer side is VLM_MAX_SIDE: nearest-neighbour when enlarging, so the pixel
    edges stay visible, Lanczos when shrinking."""
    if isinstance(image, (str, Path)):
        with Image.open(image) as im:
            im = im.convert("RGB")
    else:
        im = image.convert("RGB")
    ratio = VLM_MAX_SIDE / max(im.size)
    if ratio != 1:
        im = im.resize((max(1, round(im.width * ratio)), max(1, round(im.height * ratio))),
                       Image.Resampling.NEAREST if ratio > 1 else Image.Resampling.LANCZOS)
    data = io.BytesIO()
    im.save(data, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()}}


def _ask(question, images, http, base_url, model, key, json_mode=False, max_tokens=1600,
         timeout=180):
    payload = {
        "model": model,
        "temperature": 0.0 if json_mode else 0.7,
        "top_p": 0.8,
        "presence_penalty": 0.0 if json_mode else 1.5,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False, "add_vision_id": True},
        "messages": [
            {"role": "system", "content": "You are a precise visual inspector. Follow the "
                                          "requested output format exactly. Report visible "
                                          "evidence, never invented connections or structures."},
            {"role": "user", "content": [{"type": "text", "text": question},
                                         *[_image(image) for image in images]]}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    response = http(base_url.rstrip("/") + "/chat/completions", json.dumps(payload).encode(),
                    timeout=timeout, token=key)
    choice = response["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("VLM response was truncated; no result accepted")
    text = choice["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("VLM returned no usable text")
    return text.strip()


def caption_room(images, http, base_url, model, key):
    """The VLM's caption of a room from `images`: the whole room, then its windows."""
    return _ask(CAPTION_QUESTION, images, http, base_url, model, key, max_tokens=1600,
                timeout=CAPTION_TIMEOUT)


def parse_review(text):
    """{"accepted", "issues"} from the VLM's answer, tolerating fences and chatter."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for i in range(1, len(parts), 2):
            chunk = parts[i].strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            try:
                value = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(value, dict) and "accepted" in value:
                text = chunk
                break
    elif not text.startswith("{") and "{" in text and "}" in text:
        text = text[text.find("{"):text.rfind("}") + 1].strip()
    value = json.loads(text)
    if not isinstance(value, dict) or type(value.get("accepted")) is not bool:
        raise ValueError("VLM review must contain a boolean accepted verdict")
    issues = value.get("issues")
    if not isinstance(issues, list) or any(not isinstance(x, str) or not x.strip() for x in issues):
        raise ValueError("VLM review must contain a list of nonempty issue strings")
    if value["accepted"] != (not issues):
        raise ValueError("VLM review verdict contradicts its issues")
    return {"accepted": value["accepted"], "issues": issues}


def review_room(pairs, overview, kind, caption, http, base_url, model, key):
    """The VLM's verdict on a room: (source guide, render) per window, then the
    whole render; an insert's expected lettering comes from its caption."""
    lettering = text_section(caption) if kind == "insert" else None
    question = (REVIEW_QUESTION + f"\nThis room has {len(pairs)} window(s). Kind: {kind}. "
                f"Expected lettering: {lettering or 'none'}.")
    images = [image for pair in pairs for image in pair] + [overview]
    return parse_review(_ask(question, images, http, base_url, model, key, json_mode=True,
                             max_tokens=1200, timeout=REVIEW_TIMEOUT))


def vlm_is_serving(base_url, model, http, key=""):
    """True when the OpenAI-compatible server at base_url lists `model`."""
    try:
        models = http(base_url.rstrip("/") + "/models", timeout=5, token=key)["data"]
        return any(m.get("id") == model for m in models)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError):
        return False
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_prompts -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add test_prompts.py prompts.py
git commit -m "feat: painted-HD caption, render and review prompts and the VLM requests"
```

---

### Task 10: The ComfyUI client and the two graphs

**Files:**
- Create: `test_comfy_client.py`, `comfy_client.py`, `recreation_qwen2511_canny.json`, `recreation_qwen21_i2i.json`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `HISTORY_TIMEOUT`, `POLL_SECONDS`, `OUTPUT_PREFIX = "atl"`; `Workflow` (namedtuple: `name template guide composite mask reference_inputs positive negative seed save model_files node_classes reference`); `WORKFLOWS` (`"qwen-edit-2511-canny"`, `"qwen-image-2.1-i2i"`); `DEFAULT_WORKFLOW`; `REFERENCES = ("guide", "composite")`; `load_template(workflow) -> dict`; `http_json(url, data=None, timeout=60, token=None)`; `is_up(url, http=http_json) -> bool`; `free_models(url, http=http_json)`; `missing_model_files(workflow, comfy_dir) -> list[str]`; `missing_nodes(workflow, url, http=http_json) -> list[str]`; `render_window(workflow, *, guide, composite, mask, reference, positive, negative, seed, name, url, comfy_dir, http=http_json, timeout=HISTORY_TIMEOUT, sleep=time.sleep) -> Path`; `sweep_outputs(room_key, comfy_dir) -> int` (spec §9.5).

The graphs use these node signatures, checked against `~/ComfyUI` (c194dd0): `SetLatentNoiseMask(samples, mask)` (the mask's 1 means "denoise here"), `DifferentialDiffusion(model, strength)`, `LoadImageMask(image, channel)`, `VAEEncode(pixels, vae)`. Their tunables (the ControlNet's `strength` in node 33, the 2.1 sampler's `denoise` in node 13) live in the JSON, not in code, as in the AITD kit.

- [ ] **Step 1: Write the failing tests**

`test_comfy_client.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import comfy_client


class FakeComfy:
    """Answers /prompt, /history and /interrupt like ComfyUI, saving one render."""

    def __init__(self, comfy_dir, status="success", history=True):
        self.comfy_dir, self.status, self.history, self.calls = comfy_dir, status, history, []

    def __call__(self, url, data=None, timeout=60, token=None):
        self.calls.append((url, json.loads(data) if data else None))
        if url.endswith("/prompt"):
            return {"prompt_id": "p1"}
        if url.endswith("/interrupt"):
            return {}
        if "/history/" in url:
            if not self.history:
                return {}
            prefix = self.calls[0][1]["prompt"]["15"]["inputs"]["filename_prefix"]
            folder, stem = prefix.split("/")
            out = self.comfy_dir / "output" / folder
            out.mkdir(parents=True, exist_ok=True)
            name = f"{stem}_00001_.png"
            Image.new("RGB", (32, 32)).save(out / name)
            return {"p1": {"status": {"status_str": self.status, "messages": ["boom"]},
                           "outputs": {"15": {"images": [{"filename": name, "subfolder": folder,
                                                          "type": "output"}]}}}}
        raise AssertionError(f"unexpected request {url}")


class TemplateTests(unittest.TestCase):
    def test_each_record_matches_its_template(self):
        for name, wf in comfy_client.WORKFLOWS.items():
            with self.subTest(name):
                prompt = comfy_client.load_template(wf)
                classes = {node["class_type"] for node in prompt.values()}
                self.assertEqual(prompt[wf.guide[0]]["class_type"], "LoadImage")
                self.assertEqual(prompt[wf.composite[0]]["class_type"], "LoadImage")
                self.assertEqual(prompt[wf.mask[0]]["class_type"], "LoadImageMask")
                self.assertEqual(prompt[wf.mask[0]]["inputs"]["channel"], "red")
                for node, key in (wf.guide, wf.composite, wf.mask, wf.positive, wf.negative,
                                  wf.seed, *wf.reference_inputs):
                    self.assertIn(key, prompt[node]["inputs"])
                for _folder, node, key in wf.model_files:
                    self.assertIn(key, prompt[node]["inputs"])
                for cls in wf.node_classes:
                    self.assertIn(cls, classes)
                self.assertEqual(prompt[wf.save]["class_type"], "SaveImage")
                sampler = prompt[wf.seed[0]]
                self.assertEqual(sampler["class_type"], "KSampler")
                self.assertEqual(prompt[sampler["inputs"]["model"][0]]["class_type"],
                                 "DifferentialDiffusion")
                latent = prompt[sampler["inputs"]["latent_image"][0]]
                self.assertEqual(latent["class_type"], "SetLatentNoiseMask")
                self.assertEqual(latent["inputs"]["mask"], [wf.mask[0], 0])
                encode = prompt[latent["inputs"]["samples"][0]]
                self.assertEqual(encode["class_type"], "VAEEncode")
                self.assertEqual(encode["inputs"]["pixels"], [wf.composite[0], 0])
                for node_id, node in prompt.items():
                    for value in node["inputs"].values():
                        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                            self.assertIn(value[0], prompt, f"node {node_id} links to {value[0]}")

    def test_2511_controlnet_reads_canny_of_the_guide(self):
        wf = comfy_client.WORKFLOWS["qwen-edit-2511-canny"]
        prompt = comfy_client.load_template(wf)
        apply = next(n for n in prompt.values() if n["class_type"] == "ControlNetApplyAdvanced")
        canny = prompt[apply["inputs"]["image"][0]]
        self.assertEqual((canny["class_type"], canny["inputs"]["image"]), ("Canny", [wf.guide[0], 0]))

    def test_qwen21_reference_uses_the_autogrow_container_path(self):
        # AITD's live check: a flat "image_1" key arrives as an unexpected keyword
        # and kills the render; ComfyUI rebuilds the dict from "images.image_1".
        wf = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        inputs = comfy_client.load_template(wf)["9"]["inputs"]
        self.assertIn("images.image_1", inputs)
        self.assertNotIn("image_1", inputs)
        self.assertEqual(wf.reference_inputs, (("9", "images.image_1"),))

    def test_default_workflow_is_registered(self):
        self.assertIn(comfy_client.DEFAULT_WORKFLOW, comfy_client.WORKFLOWS)


class RenderWindowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.comfy_dir = Path(tmp.name) / "comfy"
        self.inputs = Path(tmp.name) / "in"
        self.inputs.mkdir()
        for part in ("guide", "composite", "mask"):
            Image.new("RGB", (32, 32)).save(self.inputs / f"{part}.png")

    def render(self, workflow, reference="guide", http=None, timeout=60):
        http = http or FakeComfy(self.comfy_dir)
        path = comfy_client.render_window(
            comfy_client.WORKFLOWS[workflow], guide=self.inputs / "guide.png",
            composite=self.inputs / "composite.png", mask=self.inputs / "mask.png",
            reference=reference, positive="paint it", negative="no photo", seed=43,
            name="room_001_window-1", url="http://c", comfy_dir=self.comfy_dir, http=http,
            timeout=timeout, sleep=lambda s: None)
        return path, http

    def test_fills_the_2511_graph(self):
        path, http = self.render("qwen-edit-2511-canny")
        self.assertEqual(path, self.comfy_dir / "output" / "atl" / "room_001_window-1_00001_.png")
        prompt = http.calls[0][1]["prompt"]
        for node, part in (("1", "guide"), ("2", "composite"), ("3", "mask")):
            staged = f"__atl_room_001_window-1_{part}.png"
            self.assertEqual(prompt[node]["inputs"]["image"], staged)
            self.assertTrue((self.comfy_dir / "input" / staged).is_file())
        self.assertEqual((prompt["9"]["inputs"]["prompt"], prompt["10"]["inputs"]["prompt"]),
                         ("paint it", "no photo"))
        self.assertEqual(prompt["13"]["inputs"]["seed"], 43)
        self.assertEqual((prompt["9"]["inputs"]["image1"], prompt["10"]["inputs"]["image1"]),
                         (["1", 0], ["1", 0]))
        self.assertEqual(prompt["15"]["inputs"]["filename_prefix"], "atl/room_001_window-1")

    def test_the_reference_can_be_the_composite(self):
        _, http = self.render("qwen-image-2.1-i2i", reference="composite")
        inputs = http.calls[0][1]["prompt"]["9"]["inputs"]
        self.assertEqual(inputs["images.image_1"], ["2", 0])
        self.assertEqual((inputs["prompt"], inputs["negative_prompt"]), ("paint it", "no photo"))

    def test_an_unknown_reference(self):
        with self.assertRaisesRegex(ValueError, "reference must be one of guide, composite"):
            self.render("qwen-image-2.1-i2i", reference="both")

    def test_a_failed_execution(self):
        with self.assertRaisesRegex(RuntimeError, "ComfyUI execution failed"):
            self.render("qwen-image-2.1-i2i", http=FakeComfy(self.comfy_dir, status="error"))

    def test_a_timeout_interrupts_the_prompt(self):
        http = FakeComfy(self.comfy_dir, history=False)
        with self.assertRaises(TimeoutError):
            self.render("qwen-image-2.1-i2i", http=http, timeout=0)
        self.assertEqual(http.calls[-1], ("http://c/interrupt", {"prompt_id": "p1"}))


class PreflightTests(unittest.TestCase):
    def test_missing_model_files(self):
        wf = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        with tempfile.TemporaryDirectory() as tmp:
            missing = comfy_client.missing_model_files(wf, tmp)
            self.assertEqual(missing, ["models/diffusion_models/qwen_image_2.1_bf16.safetensors",
                                       "models/text_encoders/qwen3vl_8b_bf16.safetensors",
                                       "models/vae/qwen_image_2.1_vae_bf16.safetensors"])
            for rel in missing:
                path = Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertEqual(comfy_client.missing_model_files(wf, tmp), [])

    def test_missing_nodes(self):
        wf = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        known = {"TextEncodeQwenImage21", "DifferentialDiffusion", "SetLatentNoiseMask"}

        def http(url, timeout=60):
            cls = url.rsplit("/", 1)[1]
            if cls == "SetLatentNoiseMask":
                raise RuntimeError("HTTP 500")
            return {cls: {}} if cls in known else {}
        self.assertEqual(comfy_client.missing_nodes(wf, "http://c", http),
                         ["LoadImageMask", "SetLatentNoiseMask"])

    def test_is_up_and_free(self):
        calls = []

        def http(url, data=None, timeout=60):
            calls.append((url, data))
            return {}
        self.assertTrue(comfy_client.is_up("http://c", http))
        comfy_client.free_models("http://c", http)
        self.assertEqual(calls[-1], ("http://c/free",
                                     b'{"unload_models": true, "free_memory": true}'))

        def down(url, timeout=60):
            raise OSError("refused")
        self.assertFalse(comfy_client.is_up("http://c", down))


class SweepTests(unittest.TestCase):
    def test_removes_only_the_rooms_own_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output" / "atl"
            out.mkdir(parents=True)
            for name in ("room_001_window-1_00001_.png", "room_001_seam_00003_.png",
                         "room_002_window-1_00001_.png", "room_001_window-1_00001_.png.txt"):
                (out / name).touch()
            self.assertEqual(comfy_client.sweep_outputs("room_001", tmp), 2)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["room_001_window-1_00001_.png.txt", "room_002_window-1_00001_.png"])

    def test_no_output_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(comfy_client.sweep_outputs("room_001", tmp), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_comfy_client -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'comfy_client'`.

- [ ] **Step 3: Write the two graphs**

`recreation_qwen2511_canny.json`:

```json
{
 "prompt": {
  "1": {"class_type": "LoadImage", "inputs": {"image": "guide.png"}},
  "2": {"class_type": "LoadImage", "inputs": {"image": "composite.png"}},
  "3": {"class_type": "LoadImageMask", "inputs": {"image": "mask.png", "channel": "red"}},
  "4": {"class_type": "CLIPLoader", "inputs": {
    "clip_name": "qwen_2.5_vl_7b_uncensored_comfy_ready_bf16.safetensors", "type": "qwen_image"}},
  "5": {"class_type": "UNETLoader", "inputs": {
    "unet_name": "qwen_image_edit_2511_fp8mixed.safetensors", "weight_dtype": "default"}},
  "6": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
  "7": {"class_type": "DifferentialDiffusion", "inputs": {"model": ["23", 0], "strength": 1.0}},
  "9": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
    "clip": ["4", 0], "prompt": "", "image1": ["1", 0], "vae": ["6", 0]}},
  "10": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
    "clip": ["4", 0], "prompt": "", "image1": ["1", 0], "vae": ["6", 0]}},
  "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["6", 0]}},
  "12": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["11", 0], "mask": ["3", 0]}},
  "13": {"class_type": "KSampler", "inputs": {
    "model": ["7", 0], "seed": 42, "steps": 40, "cfg": 3.0, "sampler_name": "euler",
    "scheduler": "simple", "positive": ["33", 0], "negative": ["33", 1],
    "latent_image": ["12", 0], "denoise": 1.0}},
  "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["6", 0]}},
  "15": {"class_type": "SaveImage", "inputs": {"images": ["14", 0], "filename_prefix": "atl"}},
  "22": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["5", 0], "shift": 3.1}},
  "23": {"class_type": "CFGNorm", "inputs": {"model": ["22", 0], "strength": 1.0}},
  "30": {"class_type": "Canny", "inputs": {
    "image": ["1", 0], "low_threshold": 0.4, "high_threshold": 0.8}},
  "31": {"class_type": "ControlNetLoader", "inputs": {
    "control_net_name": "Qwen-Image-InstantX-ControlNet-Union.safetensors"}},
  "32": {"class_type": "SetUnionControlNetType", "inputs": {
    "control_net": ["31", 0], "type": "canny/lineart/anime_lineart/mlsd"}},
  "33": {"class_type": "ControlNetApplyAdvanced", "inputs": {
    "positive": ["9", 0], "negative": ["10", 0], "control_net": ["32", 0], "image": ["30", 0],
    "vae": ["6", 0], "strength": 0.7, "start_percent": 0.0, "end_percent": 0.65}}
 }
}
```

`recreation_qwen21_i2i.json`:

```json
{
 "prompt": {
  "1": {"class_type": "LoadImage", "inputs": {"image": "guide.png"}},
  "2": {"class_type": "LoadImage", "inputs": {"image": "composite.png"}},
  "3": {"class_type": "LoadImageMask", "inputs": {"image": "mask.png", "channel": "red"}},
  "4": {"class_type": "CLIPLoader", "inputs": {
    "clip_name": "qwen3vl_8b_bf16.safetensors", "type": "qwen_image"}},
  "5": {"class_type": "UNETLoader", "inputs": {
    "unet_name": "qwen_image_2.1_bf16.safetensors", "weight_dtype": "default"}},
  "6": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
  "7": {"class_type": "DifferentialDiffusion", "inputs": {"model": ["5", 0], "strength": 1.0}},
  "9": {"class_type": "TextEncodeQwenImage21", "inputs": {
    "clip": ["4", 0], "vae": ["6", 0], "prompt": "", "negative_prompt": "", "resolution": 0,
    "images.image_1": ["1", 0]}},
  "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["6", 0]}},
  "12": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["11", 0], "mask": ["3", 0]}},
  "13": {"class_type": "KSampler", "inputs": {
    "model": ["7", 0], "seed": 42, "steps": 40, "cfg": 1.0, "sampler_name": "euler",
    "scheduler": "simple", "positive": ["9", 0], "negative": ["9", 1],
    "latent_image": ["12", 0], "denoise": 0.6}},
  "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["6", 0]}},
  "15": {"class_type": "SaveImage", "inputs": {"images": ["14", 0], "filename_prefix": "atl"}}
 }
}
```

- [ ] **Step 4: Write `comfy_client.py`**

```python
"""Thin client for the local ComfyUI HTTP API.

The only module that knows workflow node ids. WORKFLOWS records, per render
workflow, the template file and where the driver's values go:
  guide       LoadImage: the window of the 4x guide (the 2511 graph's Canny input)
  composite   LoadImage: the guide window with the held overlap from the stitch,
              VAE-encoded as the latent the sampler starts from
  mask        LoadImageMask (red channel): 255 paints, 0 keeps (SetLatentNoiseMask)
  reference_inputs  the encoder inputs that receive the reference image, which
              the driver points at the guide or the composite
  positive, negative, seed, save  as named
The HTTP plumbing (http_json, is_up, free_models, missing_model_files,
missing_nodes, wait_history, stage_input, execute, output_path) comes from the
AITD kit's comfy_client.py.
"""
import json
import re
import shutil
import time
import urllib.error
import urllib.request
from collections import namedtuple
from pathlib import Path

HISTORY_TIMEOUT = 1800
POLL_SECONDS = 2
OUTPUT_PREFIX = "atl"
REPO_DIR = Path(__file__).resolve().parent

# name:        registry key, also written into attempt-N.prompt.txt and attempt-N.json
# template:    workflow file, relative to the repository (absolute paths work too)
# guide, composite, mask: (node id, input key) that receive the three staged images
# reference_inputs: (node id, input key) pairs linked to the reference image
# positive, negative, seed: (node id, input key)
# save:        SaveImage node id
# model_files: (models subfolder, node id, input key) ComfyUI must have on disk
# node_classes: class_type values the ComfyUI build must know
# reference:   how the positive prompt names the window
Workflow = namedtuple("Workflow", "name template guide composite mask reference_inputs "
                                  "positive negative seed save model_files node_classes "
                                  "reference")

MASK_CLASSES = ("LoadImageMask", "SetLatentNoiseMask", "DifferentialDiffusion")

WORKFLOWS = {
    "qwen-edit-2511-canny": Workflow(
        name="qwen-edit-2511-canny",
        template="recreation_qwen2511_canny.json",
        guide=("1", "image"), composite=("2", "image"), mask=("3", "image"),
        reference_inputs=(("9", "image1"), ("10", "image1")),
        positive=("9", "prompt"), negative=("10", "prompt"), seed=("13", "seed"), save="15",
        model_files=(("diffusion_models", "5", "unet_name"),
                     ("text_encoders", "4", "clip_name"),
                     ("vae", "6", "vae_name"),
                     ("controlnet", "31", "control_net_name")),
        node_classes=("TextEncodeQwenImageEditPlus", "ControlNetApplyAdvanced",
                      "SetUnionControlNetType", "Canny") + MASK_CLASSES,
        reference="the provided reference image"),
    "qwen-image-2.1-i2i": Workflow(
        name="qwen-image-2.1-i2i",
        template="recreation_qwen21_i2i.json",
        guide=("1", "image"), composite=("2", "image"), mask=("3", "image"),
        reference_inputs=(("9", "images.image_1"),),
        positive=("9", "prompt"), negative=("9", "negative_prompt"), seed=("13", "seed"),
        save="15",
        model_files=(("diffusion_models", "5", "unet_name"),
                     ("text_encoders", "4", "clip_name"),
                     ("vae", "6", "vae_name")),
        node_classes=("TextEncodeQwenImage21",) + MASK_CLASSES,
        reference="<image1>"),
}
DEFAULT_WORKFLOW = "qwen-edit-2511-canny"   # the spike (plan Task 18) confirms or replaces it
REFERENCES = ("guide", "composite")


def load_template(workflow):
    """The `prompt` graph of the workflow's template file, read fresh."""
    path = Path(workflow.template)
    if not path.is_absolute():
        path = REPO_DIR / path
    return json.loads(path.read_text())["prompt"]


def http_json(url, data=None, timeout=60, token=None):
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode(errors="replace")[:2000]
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {e.code} {e.reason} for {url}: {detail}") from e


def is_up(url, http=http_json):
    try:
        http(f"{url}/queue", timeout=5)
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def free_models(url, http=http_json):
    http(f"{url}/free", json.dumps({"unload_models": True, "free_memory": True}).encode(),
         timeout=60)


def missing_model_files(workflow, comfy_dir):
    """Workflow model files absent from <comfy_dir>/models, as relative paths."""
    prompt = load_template(workflow)
    missing = []
    for folder, node, key in workflow.model_files:
        name = prompt[node]["inputs"][key]
        if not (Path(comfy_dir) / "models" / folder / name).is_file():
            missing.append(f"models/{folder}/{name}")
    return missing


def missing_nodes(workflow, url, http=http_json):
    """Node classes of the workflow that the running ComfyUI does not describe.

    GET /object_info/<class> answers {} for an unknown class; an HTTP error
    counts as unknown too, so an old checkout fails the preflight, not the render.
    """
    missing = []
    for cls in workflow.node_classes:
        try:
            info = http(f"{url}/object_info/{cls}", timeout=30)
        except (OSError, ValueError, RuntimeError):
            info = {}
        if not isinstance(info, dict) or cls not in info:
            missing.append(cls)
    return missing


def wait_history(url, prompt_id, http=http_json, timeout=HISTORY_TIMEOUT, sleep=time.sleep):
    deadline = time.monotonic() + timeout
    while True:
        hist = http(f"{url}/history/{prompt_id}")
        if prompt_id in hist:
            return hist[prompt_id]
        if time.monotonic() >= deadline:
            raise TimeoutError(f"no history for {prompt_id} within {timeout}s")
        sleep(POLL_SECONDS)


def stage_input(source, stage_name, comfy_dir):
    """Copy `source` into ComfyUI's input folder as `stage_name`."""
    input_dir = Path(comfy_dir) / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, input_dir / stage_name)


def execute(prompt, url, http, timeout, sleep, interrupt_on_timeout=False):
    """Queue `prompt` and return its history entry once it succeeded.

    Raises RuntimeError when ComfyUI reports a failed execution and
    TimeoutError when the history never appears; with `interrupt_on_timeout`
    it first asks ComfyUI to stop the prompt (best effort: a failed interrupt
    must not hide the timeout).
    """
    resp = http(f"{url}/prompt", json.dumps({"prompt": prompt}).encode())
    try:
        entry = wait_history(url, resp["prompt_id"], http, timeout, sleep)
    except TimeoutError:
        if interrupt_on_timeout:
            try:
                http(f"{url}/interrupt", json.dumps({"prompt_id": resp["prompt_id"]}).encode())
            except Exception:
                pass
        raise
    status = entry.get("status", {})
    if status.get("status_str") != "success":
        raise RuntimeError(f"ComfyUI execution failed: {status.get('messages', status)}")
    return entry


def output_path(comfy_dir, img):
    """Where ComfyUI saved the output image `img` (a history `images[]` entry)."""
    return Path(comfy_dir) / "output" / (img.get("subfolder") or "") / img["filename"]


def render_window(workflow, *, guide, composite, mask, reference, positive, negative, seed,
                  name, url, comfy_dir, http=http_json, timeout=HISTORY_TIMEOUT,
                  sleep=time.sleep):
    """Queue one window render and return the path of the image ComfyUI saved.

    `guide`, `composite` and `mask` are local PNG paths, staged into ComfyUI's
    input folder as __atl_<name>_<part>.png. `reference` ("guide" or
    "composite") picks the image the encoder sees. The render lands in
    output/atl/ as <name>_NNNNN_.png; the caller moves it away and checks its
    size. Raises RuntimeError when ComfyUI reports a failed execution, and
    TimeoutError, after asking ComfyUI to interrupt the prompt, when no history
    appears in time.
    """
    if reference not in REFERENCES:
        raise ValueError(f"reference must be one of {', '.join(REFERENCES)}, got {reference!r}")
    comfy_dir = Path(comfy_dir)
    prompt = load_template(workflow)
    for (node, key), path, part in ((workflow.guide, guide, "guide"),
                                    (workflow.composite, composite, "composite"),
                                    (workflow.mask, mask, "mask")):
        staged = f"__atl_{name}_{part}.png"
        stage_input(path, staged, comfy_dir)
        prompt[node]["inputs"][key] = staged
    source = (workflow.guide if reference == "guide" else workflow.composite)[0]
    for node, key in workflow.reference_inputs:
        prompt[node]["inputs"][key] = [source, 0]
    for (node, key), value in ((workflow.positive, positive), (workflow.negative, negative),
                               (workflow.seed, seed)):
        prompt[node]["inputs"][key] = value
    prompt[workflow.save]["inputs"]["filename_prefix"] = f"{OUTPUT_PREFIX}/{name}"
    # A timed-out render is still running in ComfyUI; interrupt it so it does not
    # hold the queue and write a file nobody collects.
    entry = execute(prompt, url, http, timeout, sleep, interrupt_on_timeout=True)
    return output_path(comfy_dir, entry["outputs"][workflow.save]["images"][0])


def sweep_outputs(room_key, comfy_dir):
    """Delete the room's leftover window renders under output/atl/, named as
    SaveImage names them: <room_key>_<label>_NNNNN_.png. Returns the count.

    A failed room may leave renders ComfyUI finished after the driver gave up;
    room keys are room_NNN, so one room's pattern never matches another's.
    """
    folder = Path(comfy_dir) / "output" / OUTPUT_PREFIX
    pattern = re.compile(rf"^{re.escape(room_key)}_[A-Za-z0-9-]+_\d{{5}}_\.png$")
    removed = 0
    if folder.is_dir():
        for path in folder.iterdir():
            if pattern.match(path.name):
                path.unlink(missing_ok=True)
                removed += 1
    return removed
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest test_comfy_client -v`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add test_comfy_client.py comfy_client.py recreation_qwen2511_canny.json recreation_qwen21_i2i.json
git commit -m "feat: the ComfyUI client and the window graphs for Edit 2511 + Canny and Qwen-Image 2.1"
```

---

### Task 11: The driver's core and `verify`

**Files:**
- Create: `atl_recreate.py`, `test_atl_recreate.py`
- Modify: `testkit.py` (replace the import block; append `write_rooms`, `run_cli`)

**Interfaces:**
- Consumes: `source_tree` (Task 1); `rooms_file.RoomsFileError`, `check_coverage`, `load_rooms`, `RoomEntry`, `save_rooms` (Task 2).
- Produces (`atl_recreate`): the configuration constants (`SRC_ROOT`, `DST_ROOT`, `ROOMS_FILE`, `REVIEWS_FILE`, `COMFY_URL`, `COMFY_DIR`, `VLM_*`, `MEMORY_FLOOR_GB`, `SEED`, `MAX_ATTEMPTS`, `DEFAULT_MATCH_STRENGTH`, `REFERENCE`, `SCALE`); `UsageError`; `fail(msg) -> 2`; `write_atomic(path, text)`; `save_image_atomic(image, path)`; `selection(args) -> list[Room]`; `load_entries(args) -> dict[str, RoomEntry]`; `audit_dir(dst_root, room) -> Path`; `latest_attempt(audit) -> int`; `read_record(audit, attempt) -> dict | None`; `promoted_record(audit, sha) -> dict | None`; `image_info(path) -> ((w, h), mode) | None`; `cmd_verify(args) -> int`; `build_parser()`; `main(argv=None) -> int`. The shared options are `--src`, `--dst`, `--room N` (repeatable), `--rooms-file` and `--reviews`.
- Produces (`testkit`): `write_rooms(path, kinds=None, caption="SCENE: a test room.\nTEXT: none", rooms=DEFAULT_ROOMS)` (room 4 `skip`, others `scene`); `run_cli(argv) -> (code, out, err)`.
- Produces (tests): `DriverFixture` in `test_atl_recreate.py`, which Tasks 12–15 subclass: `self.src`, `self.source`, `self.dst`, `self.rooms_file`, `self.reviews`, `self.comfy_dir`, `self.room(n)`, `self.run_cli(command, *extra)`, `self.record(n, attempt=1)`.

An attempt number is used by anything named `attempt-N.*` in a room's audit folder, so a failed attempt, which leaves only `attempt-N.tiles/`, still uses up its number (spec §12, resumability). `verify` accepts an output only when some attempt record says it promoted exactly that file (sha256).

- [ ] **Step 1: Extend the test kit**

Replace `testkit.py`'s import block (every import line between the module docstring and the `# Indices 2-13` comment, from `import hashlib` to `from PIL import Image`) with:

```python
import contextlib
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

import atl_recreate as a
from rooms_file import RoomEntry, save_rooms
```

and append:

```python
def write_rooms(path, kinds=None, caption="SCENE: a test room.\nTEXT: none", rooms=DEFAULT_ROOMS):
    """Write a rooms.yaml covering `rooms`: kind scene with `caption`, unless
    `kinds` maps a room number to another kind. Room 4 is skip by default;
    skip rooms get no caption."""
    kinds = {4: "skip", **(kinds or {})}
    entries = {}
    for spec in rooms:
        kind = kinds.get(spec["room"], "scene")
        entries[f"room_{spec['room']:03d}"] = RoomEntry(kind, "" if kind == "skip" else caption)
    save_rooms(path, entries)


def run_cli(argv):
    """Run atl_recreate.main(argv), capturing stdout and stderr: (code, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = a.main(list(argv))
    return code, out.getvalue(), err.getvalue()
```

- [ ] **Step 2: Write the failing tests**

`test_atl_recreate.py` (Tasks 12–15 add classes above the `if __name__` line):

```python
import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

import atl_recreate as a
import comfy_client
import source_tree
import testkit
from prompts import PAINTED_NEGATIVE, SEAM_NOTE
from rooms_file import Review, RoomEntry, load_reviews, load_rooms, save_reviews


class DriverFixture(unittest.TestCase):
    """A miniature source tree (rooms 1-4 of testkit.DEFAULT_ROOMS), a captioned
    rooms.yaml (room 4 skip) and empty output, reviews and ComfyUI folders."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = testkit.make_source(self.root)
        self.source = source_tree.load(self.src)
        self.dst = self.root / "dst"
        self.rooms_file = self.root / "rooms.yaml"
        self.reviews = self.root / "reviews.yaml"
        self.comfy_dir = self.root / "comfy"
        testkit.write_rooms(self.rooms_file)

    def room(self, number):
        return next(r for r in self.source.rooms if r.number == number)

    def run_cli(self, command, *extra):
        return testkit.run_cli([command, "--src", str(self.src), "--dst", str(self.dst),
                                "--rooms-file", str(self.rooms_file),
                                "--reviews", str(self.reviews), *extra])

    def record(self, number, attempt=1):
        return json.loads((self.dst / ".quality" / f"room_{number:03d}"
                           / f"attempt-{attempt}.json").read_text())


class VerifyTests(DriverFixture):
    def write_output(self, number, size=None, mode="RGB", record=True, sha=None):
        room = self.room(number)
        path = self.dst / room.out_name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new(mode, size or room.out_size).save(path)
        if record:
            audit = self.dst / ".quality" / room.key
            audit.mkdir(parents=True, exist_ok=True)
            (audit / "attempt-1.json").write_text(json.dumps(
                {"attempt": 1, "promoted": True,
                 "output_sha256": sha or source_tree.file_sha256(path)}))

    def test_everything_missing(self):
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("MISSING    room_001", out)
        self.assertIn("verify: 4 room(s), 4 problem(s)", out)

    def test_a_complete_tree_passes(self):
        for number in (1, 2, 3):
            self.write_output(number)
        self.write_output(4, record=False)          # a skip room needs no record
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 0, out)
        self.assertIn("verify: 4 room(s), 0 problem(s)", out)

    def test_problems_are_named(self):
        self.write_output(1, size=(1280, 575))
        self.write_output(2, record=False)
        self.write_output(3, mode="RGBA")
        (self.dst / "room_004.png").write_bytes(b"not a png")
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("WRONGSIZE  room_001  is 1280x575, expected 1280x576", out)
        self.assertIn("UNRECORDED room_002  no attempt record promoted this file - "
                      "run: make batch room=2 force=1", out)
        self.assertIn("WRONGMODE  room_003  is RGBA, expected RGB", out)
        self.assertIn("UNREADABLE room_004", out)

    def test_the_record_must_match_the_file(self):
        self.write_output(1, sha="0" * 64)
        code, out, _ = self.run_cli("verify", "--room", "1")
        self.assertEqual(code, 1)
        self.assertIn("UNRECORDED room_001", out)
        self.assertIn("verify: 1 room(s), 1 problem(s)", out)

    def test_an_unknown_room(self):
        code, _, err = self.run_cli("verify", "--room", "99")
        self.assertEqual(code, 2)
        self.assertIn("not in the manifest: room 99", err)

    def test_rooms_file_must_cover_the_manifest(self):
        testkit.write_rooms(self.rooms_file, rooms=testkit.DEFAULT_ROOMS[:2])
        code, _, err = self.run_cli("verify")
        self.assertEqual(code, 2)
        self.assertIn("no entry for room_003, room_004", err)

    def test_a_missing_source(self):
        code, _, err = testkit.run_cli(["verify", "--src", str(self.root / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("source is not a directory", err)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_atl_recreate -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'atl_recreate'`.

- [ ] **Step 4: Write `atl_recreate.py`**

```python
#!/usr/bin/env python3
"""Regenerate the Indiana Jones and the Fate of Atlantis room backgrounds as
painted high-definition art at exactly 4x, re-import-safe.

Human-paced stages, each a subcommand:

  caption   observe every scene and insert room with the local vLLM and write
            its caption into rooms.yaml
  batch     render every captioned room through ComfyUI window by window,
            stitch, colour-match, fix up and check its geometry; promote it into
            the output tree when the geometry holds; re-render the rooms
            reviews.yaml rejects; write skip rooms as a nearest-neighbour 4x
  review    compare every promoted room with its source through the vLLM and
            write reviews.yaml
  verify    audit the output tree against the manifest, the 4x rule and the
            attempt records

The source tree is atlantis-textures' output; its manifest.json (read by
source_tree) decides which rooms exist. Services are external: vLLM
(Qwen/Qwen3.8-27B on :8000) and ComfyUI (:8188) are started by the user; this
driver only checks that they answer.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from PIL import Image

import source_tree
from rooms_file import RoomsFileError, check_coverage, load_rooms
from source_tree import SourceError

REPO = Path(__file__).resolve().parent


def _env_path(name, default):
    return Path(os.environ.get(name) or default).expanduser()


SRC_ROOT = _env_path("ATL_SRC", REPO.parent / "atlantis-textures" / "out")
DST_ROOT = _env_path("ATL_DST", REPO / "data" / "rooms-ai")
ROOMS_FILE = _env_path("ATL_ROOMS", REPO / "rooms.yaml")
REVIEWS_FILE = _env_path("ATL_REVIEWS", REPO / "reviews.yaml")
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_DIR = _env_path("COMFY_DIR", Path.home() / "ComfyUI")
VLM_BASE_URL = os.environ.get("VLM_BASE_URL", "http://127.0.0.1:8000/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "Qwen/Qwen3.8-27B")
VLM_API_KEY = os.environ.get("VLM_API_KEY", "")
MEMORY_FLOOR_GB = 45
SEED = 42                   # attempt N of a room uses SEED + N - 1 for every window
MAX_ATTEMPTS = 4            # a room rejected this many times waits for the user
DEFAULT_MATCH_STRENGTH = 0.5
REFERENCE = "guide"         # what a window's encoder sees: "guide" or "composite"
SCALE = source_tree.SCALE
_ATTEMPT = re.compile(r"^attempt-(\d+)(\.|$)")


class UsageError(Exception):
    """Bad arguments or a precondition the user must fix; reported without a traceback."""


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    return 2


def write_atomic(path, text):
    """Write `text` to `path` through <path>.tmp and a rename."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def save_image_atomic(image, path):
    """Save `image` as a PNG at `path` through <path>.pending and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    image.save(pending, format="PNG")
    os.replace(pending, path)


def selection(args):
    return source_tree.select(args.source, args.room)


def load_entries(args):
    """rooms.yaml, checked to cover exactly the manifest's rooms."""
    entries = load_rooms(args.rooms_file)
    check_coverage(entries, [room.key for room in args.source.rooms], args.rooms_file)
    return entries


# ---- audit folder -----------------------------------------------------------

def audit_dir(dst_root, room):
    return dst_root / ".quality" / room.key


def latest_attempt(audit):
    """The highest N among the audit folder's attempt-N.* entries, 0 when none.
    A failed attempt leaves attempt-N.tiles/ behind and still uses up N."""
    if not audit.is_dir():
        return 0
    return max((int(m.group(1)) for p in audit.iterdir() if (m := _ATTEMPT.match(p.name))),
               default=0)


def read_record(audit, attempt):
    """attempt-N.json as a mapping, or None when it is missing or unreadable."""
    try:
        value = json.loads((audit / f"attempt-{attempt}.json").read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def promoted_record(audit, sha):
    """The latest attempt record that promoted an output with this sha256, or None."""
    for attempt in range(latest_attempt(audit), 0, -1):
        record = read_record(audit, attempt)
        if record and record.get("promoted") and record.get("output_sha256") == sha:
            return record
    return None


def image_info(path):
    """(size, mode) of the image at `path`, or None when it does not decode."""
    try:
        with Image.open(path) as im:
            return im.size, im.mode
    except OSError:
        return None


# ---- verify -----------------------------------------------------------------

def cmd_verify(args):
    rooms = selection(args)
    entries = load_entries(args)
    bad = 0
    for room in rooms:
        dst = args.dst / room.out_name
        info = image_info(dst) if dst.is_file() else None
        want = room.out_size
        if not dst.is_file():
            code, detail = "MISSING", ""
        elif info is None:
            code, detail = "UNREADABLE", ""
        elif info[0] != want:
            code, detail = "WRONGSIZE", f"is {info[0][0]}x{info[0][1]}, expected {want[0]}x{want[1]}"
        elif info[1] != "RGB":
            code, detail = "WRONGMODE", f"is {info[1]}, expected RGB"
        elif (entries[room.key].kind != "skip" and promoted_record(
                audit_dir(args.dst, room), source_tree.file_sha256(dst)) is None):
            code, detail = "UNRECORDED", ("no attempt record promoted this file - "
                                          f"run: make batch room={room.number} force=1")
        else:
            continue
        bad += 1
        print(f"{code:10} {room.key}" + (f"  {detail}" if detail else ""))
    print(f"verify: {len(rooms)} room(s), {bad} problem(s)")
    return 1 if bad else 0


# ---- command line -----------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--src", type=Path, default=SRC_ROOT,
                       help="atlantis-textures output: manifest.json and indexed/ "
                            "(default: %(default)s, or ATL_SRC)")
        p.add_argument("--dst", type=Path, default=DST_ROOT,
                       help="output tree (default: %(default)s, or ATL_DST)")
        p.add_argument("--room", type=int, action="append", metavar="N",
                       help="process room N only (repeatable)")
        p.add_argument("--rooms-file", type=Path, default=ROOMS_FILE,
                       help="rooms file (default: %(default)s, or ATL_ROOMS)")
        p.add_argument("--reviews", type=Path, default=REVIEWS_FILE,
                       help="reviews file (default: %(default)s, or ATL_REVIEWS)")

    verify = sub.add_parser("verify", help="audit the output tree against the manifest, the 4x "
                                           "rule and the attempt records")
    common(verify)
    verify.set_defaults(func=cmd_verify)
    return ap


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        if not args.src.is_dir():
            return fail(f"source is not a directory: {args.src} - set ATL_SRC or pass --src")
        args.source = source_tree.load(args.src)
        return args.func(args)
    except (UsageError, RoomsFileError, SourceError) as error:
        return fail(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the whole suite**

Run: `make test`
Expected: `OK`. Every earlier module still passes, now that `testkit` imports the driver.

- [ ] **Step 6: Commit**

```bash
git add testkit.py test_atl_recreate.py atl_recreate.py
git commit -m "feat: the driver's core, audit records and verify"
```

---

### Task 12: The `caption` stage

**Files:**
- Modify: `atl_recreate.py`, `testkit.py`, `test_atl_recreate.py`

**Interfaces:**
- Consumes: `room_geometry.plan_room` (Task 5); `prompts.caption_room`, `vlm_is_serving` (Task 9); `comfy_client.http_json` (Task 10); `rooms_file.RoomEntry`, `save_rooms`.
- Produces (`atl_recreate`): `caption_images(src, room) -> list[Image]` (the room at 2x, then each window at 4x when there are several); `cmd_caption(args) -> int`; the `caption` subcommand with `--force`.
- Produces (`testkit`): `vlm_stub(*, serving=True, caption=None, review=None, free=_UNSET)`, yielding mocks `serving`, `caption`, `review`, `freed`.

- [ ] **Step 1: Extend the test kit**

Replace `testkit.py`'s import block (every import line between the module docstring and the `# Indices 2-13` comment) with:

```python
import contextlib
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

import atl_recreate as a
from rooms_file import RoomEntry, save_rooms
```

and append:

```python
_UNSET = object()


@contextlib.contextmanager
def vlm_stub(*, serving=True, caption=None, review=None, free=_UNSET):
    """Patch the vLLM side of `caption` and `review`: atl_recreate.vlm_is_serving
    and, when given, a side_effect callable for atl_recreate.caption_room or
    review_room. Pass `free` (a side_effect, or None for a plain stub) to also
    patch comfy_client.free_models, which only `review` calls.

    Yields the mocks: serving, and caption, review and freed when requested.
    """
    with contextlib.ExitStack() as stack:
        mocks = SimpleNamespace(
            serving=stack.enter_context(patch.object(a, "vlm_is_serving", return_value=serving)))
        if caption is not None:
            mocks.caption = stack.enter_context(patch.object(a, "caption_room", side_effect=caption))
        if review is not None:
            mocks.review = stack.enter_context(patch.object(a, "review_room", side_effect=review))
        if free is not _UNSET:
            mocks.freed = stack.enter_context(
                patch.object(comfy_client, "free_models", side_effect=free))
        yield mocks
```

- [ ] **Step 2: Write the failing tests**

Add to `test_atl_recreate.py`, above `if __name__ == "__main__":`:

```python
class CaptionTests(DriverFixture):
    def setUp(self):
        super().setUp()
        testkit.write_rooms(self.rooms_file, caption="")

    def test_captions_scene_rooms_and_skips_skip_rooms(self):
        with testkit.vlm_stub(caption=lambda images, *a: f"SCENE: {len(images)} image(s)") as vlm:
            code, out, err = self.run_cli("caption")
        self.assertEqual(code, 0, err)
        rooms = load_rooms(self.rooms_file)
        self.assertEqual([rooms[f"room_00{n}"].caption for n in (1, 2, 3)],
                         ["SCENE: 1 image(s)", "SCENE: 3 image(s)", "SCENE: 5 image(s)"])
        self.assertEqual(rooms["room_004"], RoomEntry("skip", ""))
        self.assertEqual(vlm.caption.call_count, 3)
        self.assertIn("done: captioned=3 skipped=1 failed=0", out)

    def test_the_room_at_2x_then_its_windows_at_4x(self):
        with testkit.vlm_stub(caption=lambda images, *a: "SCENE: x") as vlm:
            self.run_cli("caption", "--room", "2")
        images = vlm.caption.call_args.args[0]
        self.assertEqual([im.size for im in images], [(1136, 288), (1280, 576), (1280, 576)])

    def test_keeps_existing_captions_unless_forced(self):
        testkit.write_rooms(self.rooms_file)
        with testkit.vlm_stub(caption=lambda images, *a: "SCENE: new") as vlm:
            code, _, _ = self.run_cli("caption")
        self.assertEqual((code, vlm.caption.call_count), (0, 0))
        with testkit.vlm_stub(caption=lambda images, *a: "SCENE: new"):
            self.run_cli("caption", "--force", "--room", "1")
        self.assertEqual(load_rooms(self.rooms_file)["room_001"].caption, "SCENE: new")

    def test_keeps_the_kind(self):
        testkit.write_rooms(self.rooms_file, kinds={2: "insert"}, caption="")
        with testkit.vlm_stub(caption=lambda images, *a: "SCENE: a page"):
            self.run_cli("caption", "--room", "2")
        self.assertEqual(load_rooms(self.rooms_file)["room_002"], RoomEntry("insert", "SCENE: a page"))

    def test_refuses_without_vllm(self):
        with testkit.vlm_stub(serving=False, caption=lambda *a: "x") as vlm:
            code, _, err = self.run_cli("caption")
        self.assertEqual(code, 2)
        self.assertIn("vLLM is not serving", err)
        vlm.caption.assert_not_called()

    def test_a_failed_caption_does_not_stop_the_others(self):
        def caption(images, *a):
            if len(images) == 3:
                raise ValueError("VLM response was truncated; no result accepted")
            return "SCENE: ok"
        with testkit.vlm_stub(caption=caption):
            code, _, err = self.run_cli("caption")
        self.assertEqual(code, 1)
        self.assertIn("ERROR captioning room_002", err)
        rooms = load_rooms(self.rooms_file)
        self.assertEqual((rooms["room_001"].caption, rooms["room_002"].caption), ("SCENE: ok", ""))
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_atl_recreate.CaptionTests -v`
Expected: ERROR in every test, `AttributeError: <module 'atl_recreate' ...> does not have the attribute 'vlm_is_serving'` (raised by `vlm_stub`'s patch).

- [ ] **Step 4: Implement the stage**

In `atl_recreate.py`, replace the import block (from `import argparse` to `from source_tree import SourceError`) with:

```python
import argparse
import json
import os
import re
import sys
from pathlib import Path

from PIL import Image

import comfy_client
import room_geometry
import source_tree
from prompts import caption_room, vlm_is_serving
from rooms_file import RoomEntry, RoomsFileError, check_coverage, load_rooms, save_rooms
from source_tree import SourceError
```

Insert this section directly above the `# ---- command line` line:

```python
# ---- caption ----------------------------------------------------------------

def caption_images(src, room):
    """What the VLM sees: the room at 2x, then each window at 4x when there are several."""
    indexed = source_tree.open_indexed(src, room)
    rgb = indexed.convert("RGB")
    images = [rgb.resize((rgb.width * 2, rgb.height * 2), Image.Resampling.NEAREST)]
    plan = room_geometry.plan_room(indexed)
    if len(plan.windows) > 1:
        for win in plan.windows:
            crop = rgb.crop((win.x0, 0, win.x1, rgb.height))
            images.append(crop.resize((crop.width * SCALE, crop.height * SCALE),
                                      Image.Resampling.NEAREST))
    return images


def cmd_caption(args):
    rooms = selection(args)
    entries = load_entries(args)
    if not vlm_is_serving(VLM_BASE_URL, VLM_MODEL, comfy_client.http_json, VLM_API_KEY):
        return fail(f"vLLM is not serving {VLM_MODEL} at {VLM_BASE_URL} - start it first")
    done = skipped = failed = 0
    for i, room in enumerate(rooms, 1):
        entry = entries[room.key]
        if entry.kind == "skip" or (entry.caption.strip() and not args.force):
            skipped += 1
            continue
        print(f"[{i}/{len(rooms)}] caption {room.key} ({entry.kind})", flush=True)
        try:
            caption = caption_room(caption_images(args.src, room), comfy_client.http_json,
                                   VLM_BASE_URL, VLM_MODEL, VLM_API_KEY)
        except Exception as error:
            failed += 1
            print(f"  ERROR captioning {room.key}: {error}", file=sys.stderr, flush=True)
            continue
        entries[room.key] = RoomEntry(entry.kind, caption)
        save_rooms(args.rooms_file, entries)
        done += 1
    print(f"done: captioned={done} skipped={skipped} failed={failed} -> {args.rooms_file}")
    return 1 if failed else 0
```

In `build_parser`, insert this block directly above the line `    verify = sub.add_parser(`:

```python
    caption = sub.add_parser("caption", help="write captions into rooms.yaml with the local vLLM")
    common(caption)
    caption.add_argument("--force", action="store_true",
                         help="re-caption rooms that already have a caption")
    caption.set_defaults(func=cmd_caption)
```

- [ ] **Step 5: Run the tests**

Run: `make test`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add atl_recreate.py testkit.py test_atl_recreate.py
git commit -m "feat: caption stage writes VLM captions into rooms.yaml"
```

---

### Task 13: Render one room

**Files:**
- Modify: `atl_recreate.py`, `testkit.py`, `test_atl_recreate.py`

**Interfaces:**
- Consumes: `room_geometry.build_guide`, `plan_room`, `window_inputs`, `paste_window`, `seam_inputs`, `apply_seam`, `apply_fixups`, `stitch_boundaries`, `DEDITHER_METHOD`, `WINDOW_WIDTH`, `WINDOW_OVERLAP` (Tasks 3–6); `geometry_check.check`, `SEAM_WARN` (Task 7); `colour_match.match`, `RULE` (Task 8); `prompts.render_prompt`, `window_note`, `SEAM_NOTE`, `PAINTED_NEGATIVE` (Task 9); `comfy_client.render_window` (Task 10).
- Produces (`atl_recreate`): `render_room(args, workflow, room, entry, corrections) -> (attempt, GeometryResult)`. `args` needs `src`, `dst` and `match_strength`. It writes `attempt-N.tiles/{label}.{guide,composite,mask}.png` and `{label}.png` for each window (labels `window-K` and `seam`), plus `attempt-N.prompt.txt`, `attempt-N.png` (the raw stitch) and `attempt-N.json`, whose keys are `attempt workflow seed reference dedither window_width window_overlap windows wrap margins match geometry promoted output_sha256 seconds`. On a pass it promotes `room_NNN.png`. It raises `RuntimeError` when a window comes back the wrong size.

Spec §10.2 lists the fix-ups (a wraparound's repeat byte-identical, flat margins) among the gates. They hold by construction: `apply_fixups` runs last, just before the geometry check. So the gate does not re-measure them; `FixupTests` (Task 6) and `test_a_wraparound_room` below pin them.
- Produces (`testkit`): `shift_right(image, pixels=8)`; `fake_render(transform=None)` (a `render_window` side effect that saves the window's composite where ComfyUI would); `comfy_stub(*, up=True, mem=100.0, missing=(), nodes=(), comfy_dir=None, render=None, free=None, swept=0)`, yielding mocks `is_up`, `freed`, `missing_model_files`, `missing_nodes`, `sweep`, `memory_available_gb` and `render`. It patches `atl_recreate.memory_available_gb`, which Task 14 adds; `patch.object` needs the attribute, so Step 4 adds it here.

- [ ] **Step 1: Extend the test kit**

Replace `testkit.py`'s import block (every import line between the module docstring and the `# Indices 2-13` comment) with:

```python
import contextlib
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

import atl_recreate as a
import comfy_client
from rooms_file import RoomEntry, save_rooms
```

and append:

```python
def shift_right(image, pixels=8):
    """`image` moved `pixels` to the right over black: a render that slid 2 native px."""
    out = Image.new("RGB", image.size)
    out.paste(image, (pixels, 0))
    return out


def fake_render(transform=None):
    """A comfy_client.render_window stand-in that 'renders' a window by saving
    its composite (through `transform`, when given) where ComfyUI would."""
    def render(workflow, **kw):
        with Image.open(kw["composite"]) as im:
            image = im.convert("RGB")
        if transform is not None:
            image = transform(image)
        folder = Path(kw["comfy_dir"]) / "output" / comfy_client.OUTPUT_PREFIX
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{kw['name']}_00001_.png"
        image.save(path)
        return path
    return render


@contextlib.contextmanager
def comfy_stub(*, up=True, mem=100.0, missing=(), nodes=(), comfy_dir=None, render=None,
               free=None, swept=0):
    """Patch the ComfyUI side of `batch`: comfy_client.is_up, free_models,
    missing_model_files, missing_nodes, sweep_outputs, atl_recreate's
    memory_available_gb and (when given) COMFY_DIR and comfy_client.render_window
    (`render`, a side_effect callable such as fake_render()).

    Yields the mocks: is_up, freed, missing_model_files, missing_nodes, sweep,
    memory_available_gb, and render when requested.
    """
    with contextlib.ExitStack() as stack:
        mocks = SimpleNamespace(
            is_up=stack.enter_context(patch.object(comfy_client, "is_up", return_value=up)),
            freed=stack.enter_context(patch.object(comfy_client, "free_models", side_effect=free)),
            missing_model_files=stack.enter_context(
                patch.object(comfy_client, "missing_model_files", return_value=list(missing))),
            missing_nodes=stack.enter_context(
                patch.object(comfy_client, "missing_nodes", return_value=list(nodes))),
            sweep=stack.enter_context(
                patch.object(comfy_client, "sweep_outputs", return_value=swept)),
            memory_available_gb=stack.enter_context(
                patch.object(a, "memory_available_gb", return_value=mem)))
        if comfy_dir is not None:
            stack.enter_context(patch.object(a, "COMFY_DIR", comfy_dir))
        if render is not None:
            mocks.render = stack.enter_context(
                patch.object(comfy_client, "render_window", side_effect=render))
        yield mocks
```

- [ ] **Step 2: Write the failing tests**

Add to `test_atl_recreate.py`, above `if __name__ == "__main__":`:

```python
class RenderRoomTests(DriverFixture):
    def setUp(self):
        super().setUp()
        self.entries = load_rooms(self.rooms_file)
        self.workflow = comfy_client.WORKFLOWS["qwen-edit-2511-canny"]

    def render(self, number, transform=None, corrections=()):
        room = self.room(number)
        args = argparse.Namespace(src=self.src, dst=self.dst, match_strength=0.5)
        with testkit.comfy_stub(comfy_dir=self.comfy_dir,
                                render=testkit.fake_render(transform)) as stub:
            result = a.render_room(args, self.workflow, room, self.entries[room.key],
                                   list(corrections))
        return result, stub

    def test_a_one_window_room(self):
        (attempt, result), stub = self.render(1)
        self.assertEqual(attempt, 1)
        self.assertTrue(result.passed, result.issues)
        with Image.open(self.dst / "room_001.png") as im:
            self.assertEqual((im.size, im.mode), ((1280, 576), "RGB"))
        record = self.record(1)
        self.assertEqual((record["promoted"], record["seed"], record["windows"], record["wrap"],
                          record["workflow"], record["reference"]),
                         (True, 42, [[0, 320]], None, "qwen-edit-2511-canny", "guide"))
        self.assertEqual(record["output_sha256"], source_tree.file_sha256(self.dst / "room_001.png"))
        audit = self.dst / ".quality" / "room_001"
        self.assertTrue((audit / "attempt-1.png").is_file())
        self.assertTrue((audit / "attempt-1.prompt.txt").read_text().startswith(
            "workflow: qwen-edit-2511-canny\n"))
        for name in ("window-1.guide.png", "window-1.composite.png", "window-1.mask.png",
                     "window-1.png"):
            self.assertTrue((audit / "attempt-1.tiles" / name).is_file(), name)
        kw = stub.render.call_args.kwargs
        self.assertEqual((kw["seed"], kw["reference"], kw["name"], kw["negative"]),
                         (42, "guide", "room_001_window-1", PAINTED_NEGATIVE))
        self.assertNotIn("one window of a wide scrolling room", kw["positive"])
        self.assertEqual(list((self.comfy_dir / "output" / "atl").iterdir()), [])

    def test_a_second_window_continues_the_first(self):
        (_, result), stub = self.render(2)
        self.assertTrue(result.passed, result.issues)
        calls = [c.kwargs for c in stub.render.call_args_list]
        self.assertEqual([c["name"] for c in calls], ["room_002_window-1", "room_002_window-2"])
        self.assertIn("from 44% to 100%", calls[1]["positive"])
        with Image.open(calls[1]["mask"]) as mask:
            self.assertEqual((mask.getpixel((0, 0)), mask.getpixel((400, 0))), (0, 255))
        self.assertEqual(len(self.record(2)["geometry"]["seam_ratios"]), 1)

    def test_a_wraparound_room(self):
        (_, result), stub = self.render(3)
        self.assertTrue(result.passed, result.issues)
        calls = [c.kwargs for c in stub.render.call_args_list]
        self.assertEqual([c["name"] for c in calls],
                         [f"room_003_window-{k}" for k in (1, 2, 3, 4)] + ["room_003_seam"])
        self.assertIn(SEAM_NOTE, calls[-1]["positive"])
        with Image.open(self.dst / "room_003.png") as im:
            out = np.asarray(im.convert("RGB"))
        self.assertTrue((out[:, 3360:4256] == out[:, :896]).all())
        self.assertTrue((out[:, 4256:] == 0).all())
        self.assertEqual(self.record(3)["wrap"], [840, 224])

    def test_a_shifted_render_is_not_promoted(self):
        (_, result), _ = self.render(1, transform=testkit.shift_right)
        self.assertFalse(result.passed)
        self.assertIn("the room is shifted", result.issues[0])
        self.assertFalse((self.dst / "room_001.png").exists())
        self.assertEqual((self.record(1)["promoted"], self.record(1)["output_sha256"]),
                         (False, None))

    def test_a_wrong_size_render_fails_the_room(self):
        # Review Focus: ComfyUI hands back a size other than the window's.
        def shrink(image):
            return image.resize((image.width - 32, image.height))
        with self.assertRaisesRegex(RuntimeError, "window-1 came back 1248x576, expected 1280x576"):
            self.render(1, transform=shrink)
        self.assertFalse((self.dst / "room_001.png").exists())
        self.assertEqual(a.latest_attempt(self.dst / ".quality" / "room_001"), 1)

    def test_attempts_continue_with_the_next_seed_and_carry_corrections(self):
        self.render(1)
        (attempt, _), stub = self.render(1, corrections=["the lamp moved"])
        self.assertEqual((attempt, stub.render.call_args.kwargs["seed"]), (2, 43))
        self.assertIn("the lamp moved", stub.render.call_args.kwargs["positive"])
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_atl_recreate.RenderRoomTests -v`
Expected: ERROR, `AttributeError: <module 'atl_recreate' ...> does not have the attribute 'memory_available_gb'`.

- [ ] **Step 4: Implement it**

In `atl_recreate.py`, replace the import block (from `import argparse` to `from source_tree import SourceError`) with:

```python
import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from PIL import Image

import colour_match
import comfy_client
import geometry_check
import room_geometry
import source_tree
from prompts import (PAINTED_NEGATIVE, SEAM_NOTE, caption_room, render_prompt, vlm_is_serving,
                     window_note)
from rooms_file import RoomEntry, RoomsFileError, check_coverage, load_rooms, save_rooms
from source_tree import SourceError
```

Insert this section directly above the `# ---- command line` line:

```python
# ---- render one room --------------------------------------------------------

def render_room(args, workflow, room, entry, corrections):
    """Render one room window by window, stitch it, colour-match it, fix it up
    and check its geometry; promote it into the output tree when that holds.

    Returns (attempt, GeometryResult). Raises when a window fails to render or
    comes back the wrong size: the windows rendered so far stay in the
    attempt's tiles folder, and the attempt number stays used.
    """
    audit = audit_dir(args.dst, room)
    audit.mkdir(parents=True, exist_ok=True)
    attempt = latest_attempt(audit) + 1
    tiles = audit / f"attempt-{attempt}.tiles"
    tiles.mkdir()
    seed = SEED + attempt - 1
    started = time.monotonic()
    indexed = source_tree.open_indexed(args.src, room)
    guide = room_geometry.build_guide(indexed)
    plan = room_geometry.plan_room(indexed)
    canvas = guide.full.copy()
    prompt_log = []

    def render(label, guide_image, composite, mask, note):
        positive = render_prompt(entry.caption, entry.kind, corrections, note, workflow.reference)
        prompt_log.append(f"--- {label} ---\n{positive}")
        paths = {}
        for part, image in (("guide", guide_image), ("composite", composite), ("mask", mask)):
            paths[part] = tiles / f"{label}.{part}.png"
            image.save(paths[part])
        saved = comfy_client.render_window(
            workflow, guide=paths["guide"], composite=paths["composite"], mask=paths["mask"],
            reference=REFERENCE, positive=positive, negative=PAINTED_NEGATIVE, seed=seed,
            name=f"{room.key}_{label}", url=COMFY_URL, comfy_dir=COMFY_DIR)
        out = tiles / f"{label}.png"
        shutil.move(saved, out)
        with Image.open(out) as im:
            rendered = im.convert("RGB")
        if rendered.size != guide_image.size:
            raise RuntimeError(f"{label} came back {rendered.width}x{rendered.height}, "
                               f"expected {guide_image.width}x{guide_image.height}")
        return rendered

    start, end = plan.span
    previous = None
    for k, window in enumerate(plan.windows, 1):
        crop, composite, mask = room_geometry.window_inputs(guide.full, canvas, window, previous)
        note = window_note(window.x0, window.x1, start, end) if len(plan.windows) > 1 else ""
        rendered = render(f"window-{k}", crop, composite, mask, note)
        room_geometry.paste_window(canvas, window, previous, rendered)
        previous = window
    if plan.wrap:
        strip, composite, mask = room_geometry.seam_inputs(guide.full, canvas, plan)
        room_geometry.apply_seam(canvas, plan, render("seam", strip, composite, mask, SEAM_NOTE))

    write_atomic(audit / f"attempt-{attempt}.prompt.txt",
                 f"workflow: {workflow.name}\n\n" + "\n\n".join(prompt_log)
                 + f"\n\n--- negative ---\n{PAINTED_NEGATIVE}\n")
    canvas.save(audit / f"attempt-{attempt}.png")
    matched = colour_match.match(canvas, guide.full, args.match_strength)
    final = room_geometry.apply_fixups(matched, plan, indexed)
    if final.size != room.out_size:
        raise RuntimeError(f"the stitched room is {final.width}x{final.height}, "
                           f"expected {room.out_size[0]}x{room.out_size[1]}")
    boundaries = room_geometry.stitch_boundaries(plan)
    result = geometry_check.check(final, guide.native, [(w.x0, w.x1) for w in plan.windows],
                                  boundaries, reference=guide.full)
    for x, ratio in zip(boundaries, result.seam_ratios):
        if ratio > geometry_check.SEAM_WARN:
            print(f"  warning: {room.key} seam at 4x column {x}: step {ratio:.1f}x the local "
                  "texture", flush=True)
    sha = None
    if result.passed:
        dst = args.dst / room.out_name
        save_image_atomic(final, dst)
        sha = source_tree.file_sha256(dst)
    m = plan.margins
    record = {
        "attempt": attempt, "workflow": workflow.name, "seed": seed, "reference": REFERENCE,
        "dedither": room_geometry.DEDITHER_METHOD,
        "window_width": room_geometry.WINDOW_WIDTH, "window_overlap": room_geometry.WINDOW_OVERLAP,
        "windows": [[w.x0, w.x1] for w in plan.windows],
        "wrap": [plan.wrap.period, plan.wrap.span] if plan.wrap else None,
        "margins": {"left": m.left, "right": m.right, "top": m.top, "bottom": m.bottom},
        "match": {"rule": colour_match.RULE, "strength": args.match_strength},
        "geometry": result.as_dict(), "promoted": result.passed, "output_sha256": sha,
        "seconds": round(time.monotonic() - started, 1),
    }
    write_atomic(audit / f"attempt-{attempt}.json", json.dumps(record, indent=2))
    return attempt, result
```

and, below it, the memory probe (Task 14's section will sit under it):

```python
# ---- batch ------------------------------------------------------------------

def memory_available_gb(meminfo=Path("/proc/meminfo")):
    """MemAvailable in GiB. On this unified-memory host it is the GPU budget too."""
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2 ** 20
    raise RuntimeError(f"MemAvailable not found in {meminfo}")
```

- [ ] **Step 5: Run the tests**

Run: `make test`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add atl_recreate.py testkit.py test_atl_recreate.py
git commit -m "feat: render a room window by window, stitch, match, fix up and gate it"
```

---

### Task 14: The `batch` stage

**Files:**
- Modify: `atl_recreate.py`, `test_atl_recreate.py`

**Interfaces:**
- Consumes: `render_room` and `memory_available_gb` (Task 13); `comfy_client.WORKFLOWS`, `DEFAULT_WORKFLOW`, `is_up`, `missing_model_files`, `missing_nodes`, `free_models`, `sweep_outputs` (Task 10); `rooms_file.Review`, `load_reviews`, `save_reviews` (Task 2).
- Produces (`atl_recreate`): `comfy_preflight(workflow, no_memory_check) -> int | None`; `room_status(args, room, reviews) -> (status, attempt)`, where status is one of `new`, `failed`, `rejected`, `missing`, `done`; `write_nearest(args, room)`; `plan_line(args, room, entry, corrections) -> str`; `stuck_line(room) -> str`; `cmd_batch(args) -> int`; `default_workflow(environ=os.environ)`, `match_strength(text)`, `default_match_strength(environ=os.environ)`; the `batch` subcommand with `--dry-run`, `--no-memory-check`, `--force`, `--match-strength X` and `--workflow NAME`.

Batch exit codes: 0 when nothing failed and nothing is stuck (a geometry rejection this run is not a failure: the next batch retries it), 1 when a room failed or is stuck, 2 for a usage or preflight error. `--dry-run` always exits 0 for a valid selection and never contacts ComfyUI.

- [ ] **Step 1: Write the failing tests**

Add to `test_atl_recreate.py`, above `if __name__ == "__main__":`:

```python
class BatchTests(DriverFixture):
    def batch(self, *extra, render=None, **stub):
        with testkit.comfy_stub(comfy_dir=self.comfy_dir, render=render or testkit.fake_render(),
                                **stub) as mocks:
            code, out, err = self.run_cli("batch", *extra)
        return code, out, err, mocks

    def test_dry_run_plans_without_comfyui(self):
        code, out, _, mocks = self.batch("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("render  room_002 scene  -> 2272x576  windows 0-320 248-568", out)
        self.assertIn("wrap 840+224 (seam window); margins L0 R88 T0 B0", out)
        self.assertIn("copy    room_004 skip   -> 64x800 nearest", out)
        mocks.is_up.assert_not_called()
        mocks.render.assert_not_called()
        self.assertFalse(self.dst.exists())

    def test_renders_copies_and_verifies(self):
        code, out, err, mocks = self.batch()
        self.assertEqual(code, 0, err)
        self.assertIn("done: promoted=3 rejected=0 failed=0 copied=1", out)
        mocks.freed.assert_called_once()
        self.assertEqual(self.run_cli("verify")[0], 0)

    def test_a_second_run_has_nothing_to_do(self):
        self.batch()
        code, out, _, mocks = self.batch()
        self.assertEqual(code, 0)
        mocks.render.assert_not_called()
        mocks.is_up.assert_not_called()
        self.assertIn("render 0, copy 0 (kind skip), done 4", out)

    def test_uncaptioned_rooms_stop_the_batch(self):
        testkit.write_rooms(self.rooms_file, caption="")
        code, _, err, mocks = self.batch()
        self.assertEqual(code, 2)
        self.assertIn("run: make caption", err)
        mocks.render.assert_not_called()
        code, out, _, _ = self.batch("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("NOCAPTION room_001", out)

    def test_preflight(self):
        cases = {"down": ({"up": False}, "ComfyUI is not answering"),
                 "models": ({"missing": ["models/vae/x.safetensors"]}, "models/vae/x.safetensors"),
                 "nodes": ({"nodes": ["DifferentialDiffusion"]}, "does not know DifferentialDiffusion"),
                 "memory": ({"mem": 20.0}, "stop vLLM first")}
        for name, (stub, message) in cases.items():
            with self.subTest(name):
                code, _, err, mocks = self.batch("--room", "1", **stub)
                self.assertEqual(code, 2)
                self.assertIn(message, err)
                mocks.render.assert_not_called()
        code, _, _, _ = self.batch("--room", "1", "--no-memory-check", mem=20.0)
        self.assertEqual(code, 0)

    def test_a_geometry_rejection_is_retried_with_its_issues(self):
        code, out, _, _ = self.batch("--room", "1", render=testkit.fake_render(testkit.shift_right))
        self.assertEqual(code, 0)
        self.assertIn("rejected attempt 1: geometry: the room is shifted", out)
        review = load_reviews(self.reviews)["room_001"]
        self.assertEqual((review.attempt, review.accepted, review.source), (1, False, "geometry"))
        code, out, _, mocks = self.batch("--room", "1")
        self.assertEqual(code, 0)
        self.assertIn("promoted attempt 2", out)
        self.assertIn("geometry: the room is shifted", mocks.render.call_args.kwargs["positive"])

    def test_a_review_rejection_is_retried(self):
        self.batch()
        save_reviews(self.reviews, {"room_002": Review(1, False, ("window 2: the awning moved; "
                                                                  "move it back",))})
        _, _, _, mocks = self.batch()
        self.assertEqual({c.kwargs["name"] for c in mocks.render.call_args_list},
                         {"room_002_window-1", "room_002_window-2"})
        self.assertIn("the awning moved", mocks.render.call_args.kwargs["positive"])

    def test_a_room_rejected_max_attempts_times_waits(self):
        for _ in range(a.MAX_ATTEMPTS):
            self.batch("--room", "1", render=testkit.fake_render(testkit.shift_right))
        code, _, err, mocks = self.batch("--room", "1")
        self.assertEqual(code, 1)
        mocks.render.assert_not_called()
        self.assertIn("STUCK   room_001: rejected 4 times", err)
        code, out, _, _ = self.batch("--room", "1", "--force")
        self.assertEqual(code, 0)
        self.assertIn("promoted attempt 5", out)

    def test_a_failed_room_does_not_stop_the_others(self):
        good = testkit.fake_render()

        def render(workflow, **kw):
            if kw["name"].startswith("room_001"):
                raise RuntimeError("ComfyUI execution failed: boom")
            return good(workflow, **kw)
        code, _, err, mocks = self.batch(render=render, swept=2)
        self.assertEqual(code, 1)
        self.assertIn("ERROR rendering room_001: ComfyUI execution failed: boom "
                      "(removed 2 stray output file(s))", err)
        mocks.sweep.assert_called_once_with("room_001", self.comfy_dir)
        self.assertTrue((self.dst / "room_002.png").is_file())
        mocks.freed.assert_called_once()

    def test_an_interrupted_room_starts_over_as_a_new_attempt(self):
        # Review Focus: a crash or timeout mid-room, then a rerun.
        good = testkit.fake_render()

        def render(workflow, **kw):
            if kw["name"] == "room_002_window-2":
                raise TimeoutError("no history for p1 within 1800s")
            return good(workflow, **kw)
        self.batch("--room", "2", render=render)
        audit = self.dst / ".quality" / "room_002"
        self.assertTrue((audit / "attempt-1.tiles" / "window-1.png").is_file())
        self.assertFalse((audit / "attempt-1.json").exists())
        code, out, _, _ = self.batch("--room", "2")
        self.assertEqual(code, 0)
        self.assertIn("promoted attempt 2", out)
        self.assertEqual(self.run_cli("verify", "--room", "2")[0], 0)

    def test_a_flat_room_marked_scene_fails_cleanly(self):
        # Review Focus: a hand edit gives a placeholder a scene kind.
        testkit.write_rooms(self.rooms_file, kinds={4: "scene"})
        code, _, err, _ = self.batch("--room", "4")
        self.assertEqual(code, 1)
        self.assertIn("ERROR rendering room_004: the room is one flat colour", err)

    def test_skip_rooms_are_written_once(self):
        path = self.dst / "room_004.png"
        self.batch("--room", "4")
        with Image.open(path) as im:
            self.assertEqual((im.size, im.getpixel((0, 0))), ((64, 800), (0, 0, 0)))
        Image.new("RGB", (64, 800), "red").save(path)
        self.batch("--room", "4")
        with Image.open(path) as im:
            self.assertEqual(im.getpixel((0, 0)), (255, 0, 0))
        self.batch("--room", "4", "--force")
        with Image.open(path) as im:
            self.assertEqual(im.getpixel((0, 0)), (0, 0, 0))

    def test_a_deleted_output_is_rendered_again(self):
        self.batch("--room", "1")
        (self.dst / "room_001.png").unlink()
        _, out, _, _ = self.batch("--room", "1")
        self.assertIn("promoted attempt 2", out)

    def test_workflow_and_strength_are_recorded(self):
        self.batch("--room", "1", "--workflow", "qwen-image-2.1-i2i", "--match-strength", "0")
        record = self.record(1)
        self.assertEqual((record["workflow"], record["match"]["strength"]),
                         ("qwen-image-2.1-i2i", 0.0))
        with self.assertRaises(SystemExit):
            self.batch("--match-strength", "1.5")

    def test_a_bad_environment_default(self):
        for name, value, message in (("ATL_WORKFLOW", "nope", "ATL_WORKFLOW='nope' is not a workflow"),
                                     ("ATL_MATCH_STRENGTH", "2", "ATL_MATCH_STRENGTH: 2 is not")):
            with self.subTest(name), patch.dict(os.environ, {name: value}):
                code, _, err, _ = self.batch("--dry-run")
                self.assertEqual(code, 2)
                self.assertIn(message, err)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_atl_recreate.BatchTests -v`
Expected: ERROR, `SystemExit: 2`: argparse rejects `invalid choice: 'batch'`.

- [ ] **Step 3: Implement the stage**

In `atl_recreate.py`, replace the import block (from `import argparse` to `from source_tree import SourceError`) with:

```python
import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from PIL import Image

import colour_match
import comfy_client
import geometry_check
import room_geometry
import source_tree
from prompts import (PAINTED_NEGATIVE, SEAM_NOTE, caption_room, render_prompt, vlm_is_serving,
                     window_note)
from rooms_file import (Review, RoomEntry, RoomsFileError, check_coverage, load_reviews,
                        load_rooms, save_reviews, save_rooms)
from source_tree import SourceError
```

Insert this section directly below the `memory_available_gb` function (above the `# ---- command line` line):

```python
def comfy_preflight(workflow, no_memory_check):
    """None when ComfyUI answers, has the model files, knows the node classes
    and there is memory to render; else fail(...)'s exit code."""
    if not comfy_client.is_up(COMFY_URL):
        return fail(f"ComfyUI is not answering at {COMFY_URL} - start it first (make server)")
    missing = comfy_client.missing_model_files(workflow, COMFY_DIR)
    if missing:
        return fail(f"ComfyUI is missing model files under {COMFY_DIR}:\n  " + "\n  ".join(missing))
    unknown = comfy_client.missing_nodes(workflow, COMFY_URL)
    if unknown:
        return fail(f"ComfyUI at {COMFY_URL} does not know {', '.join(unknown)} - update the "
                    f"checkout (git -C {COMFY_DIR} pull) and restart it")
    if not no_memory_check:
        available = memory_available_gb()
        if available < MEMORY_FLOOR_GB:
            return fail(f"only {available:.0f} GB of memory available, a render needs about "
                        f"{MEMORY_FLOOR_GB} GB: stop vLLM first (or pass --no-memory-check)")
    return None


def room_status(args, room, reviews):
    """(status, latest attempt) of a scene or insert room:
    new       never attempted
    failed    the latest attempt never finished (it has no record)
    rejected  the latest attempt failed the geometry gate, or its review rejected it
    missing   promoted and not rejected, but the output file is gone
    done      promoted and not rejected (reviewed, or waiting for review)
    """
    audit = audit_dir(args.dst, room)
    attempt = latest_attempt(audit)
    if attempt == 0:
        return "new", 0
    record = read_record(audit, attempt)
    if record is None:
        return "failed", attempt
    review = reviews.get(room.key)
    if not record.get("promoted") or (review is not None and not review.accepted
                                      and review.attempt >= attempt):
        return "rejected", attempt
    if not (args.dst / room.out_name).is_file():
        return "missing", attempt
    return "done", attempt


def write_nearest(args, room):
    """A skip room's output: its source enlarged 4x, nearest neighbour."""
    indexed = source_tree.open_indexed(args.src, room)
    save_image_atomic(indexed.convert("RGB").resize(room.out_size, Image.Resampling.NEAREST),
                      args.dst / room.out_name)


def plan_line(args, room, entry, corrections):
    """One dry-run line: the room's size, windows, wraparound, margins and corrections."""
    plan = room_geometry.plan_room(source_tree.open_indexed(args.src, room))
    w, h = room.out_size
    line = (f"  render  {room.key} {entry.kind:6} -> {w}x{h}  windows "
            + " ".join(f"{win.x0}-{win.x1}" for win in plan.windows))
    extras = []
    if plan.wrap:
        extras.append(f"wrap {plan.wrap.period}+{plan.wrap.span} (seam window)")
    m = plan.margins
    if m.left or m.right or m.top or m.bottom:
        extras.append(f"margins L{m.left} R{m.right} T{m.top} B{m.bottom}")
    if corrections:
        extras.append(f"{len(corrections)} correction(s)")
    return line + ("  " + "; ".join(extras) if extras else "")


def stuck_line(room):
    return (f"  STUCK   {room.key}: rejected {MAX_ATTEMPTS} times - fix its caption in "
            f"rooms.yaml, then: make batch room={room.number} force=1")


def cmd_batch(args):
    workflow = comfy_client.WORKFLOWS[args.workflow]
    rooms = selection(args)
    entries = load_entries(args)
    reviews = load_reviews(args.reviews, optional=True)
    copies, work, stuck, uncaptioned = [], [], [], []
    done = 0
    for room in rooms:
        entry = entries[room.key]
        if entry.kind == "skip":
            if args.force or not (args.dst / room.out_name).is_file():
                copies.append(room)
            else:
                done += 1
            continue
        status, attempt = room_status(args, room, reviews)
        if not args.force and status == "done":
            done += 1
            continue
        if not args.force and status == "rejected" and attempt >= MAX_ATTEMPTS:
            stuck.append(room)
            continue
        if not entry.caption.strip():
            uncaptioned.append(room.key)
            continue
        review = reviews.get(room.key)
        rejected = status == "rejected" and review is not None and not review.accepted
        work.append((room, entry, list(review.issues) if rejected else []))

    print(f"workflow: {workflow.name}  match strength: {args.match_strength}")
    print(f"{len(rooms)} room(s): render {len(work)}, copy {len(copies)} (kind skip), "
          f"done {done}, stuck {len(stuck)}")
    if args.dry_run:
        for room in copies:
            w, h = room.out_size
            print(f"  copy    {room.key} skip   -> {w}x{h} nearest")
        for room, entry, corrections in work:
            try:
                print(plan_line(args, room, entry, corrections))
            except ValueError as error:
                print(f"  ERROR   {room.key}: {error}")
        for key in uncaptioned:
            print(f"  NOCAPTION {key} - run: make caption")
        for room in stuck:
            print(stuck_line(room))
        return 0
    if uncaptioned:
        return fail(f"{len(uncaptioned)} selected room(s) have no caption in {args.rooms_file} "
                    "- run: make caption\n  " + "\n  ".join(uncaptioned))
    for room in copies:
        write_nearest(args, room)
        print(f"  copy    {room.key} (nearest 4x)")
    if not work:
        for room in stuck:
            print(stuck_line(room), file=sys.stderr)
        return 1 if stuck else 0

    code = comfy_preflight(workflow, args.no_memory_check)
    if code is not None:
        return code
    # ComfyUI keeps its models loaded after rendering (~40 GB); free them on the
    # way out, even after a failure, so vLLM has room to start for `make review`.
    try:
        promoted = rejected = failed = 0
        for i, (room, entry, corrections) in enumerate(work, 1):
            note = f" with {len(corrections)} correction(s)" if corrections else ""
            print(f"[{i}/{len(work)}] render {room.key} ({entry.kind}){note}", flush=True)
            try:
                attempt, result = render_room(args, workflow, room, entry, corrections)
            except Exception as error:
                failed += 1
                swept = comfy_client.sweep_outputs(room.key, COMFY_DIR)
                extra = f" (removed {swept} stray output file(s))" if swept else ""
                print(f"  ERROR rendering {room.key}: {error}{extra}", file=sys.stderr, flush=True)
                continue
            if result.passed:
                promoted += 1
                print(f"  promoted attempt {attempt}", flush=True)
                continue
            rejected += 1
            reviews[room.key] = Review(attempt, False, result.issues, "geometry")
            save_reviews(args.reviews, reviews)
            print(f"  rejected attempt {attempt}: " + "; ".join(result.issues), flush=True)
            if attempt >= MAX_ATTEMPTS:
                stuck.append(room)
        for room in stuck:
            print(stuck_line(room), file=sys.stderr)
        print(f"done: promoted={promoted} rejected={rejected} failed={failed} "
              f"copied={len(copies)} done={done} stuck={len(stuck)}")
        return 1 if failed or stuck else 0
    finally:
        try:
            comfy_client.free_models(COMFY_URL)
        except Exception as error:
            print(f"warning: failed to free ComfyUI's models: {error}", file=sys.stderr)
```

Insert these three functions directly below the `# ---- command line` line:

```python
def default_workflow(environ=os.environ):
    """--workflow when the flag is absent: ATL_WORKFLOW or comfy_client.DEFAULT_WORKFLOW."""
    name = environ.get("ATL_WORKFLOW") or comfy_client.DEFAULT_WORKFLOW
    if name not in comfy_client.WORKFLOWS:
        raise UsageError(f"ATL_WORKFLOW={name!r} is not a workflow; choose one of "
                         + ", ".join(sorted(comfy_client.WORKFLOWS)))
    return name


def match_strength(text):
    """argparse type for --match-strength: a number from 0 to 1."""
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError(f"{text} is not a number from 0 to 1")
    return value


def default_match_strength(environ=os.environ):
    """--match-strength when the flag is absent: ATL_MATCH_STRENGTH or DEFAULT_MATCH_STRENGTH."""
    text = environ.get("ATL_MATCH_STRENGTH")
    if not text:
        return DEFAULT_MATCH_STRENGTH
    try:
        return match_strength(text)
    except argparse.ArgumentTypeError as error:
        raise UsageError(f"ATL_MATCH_STRENGTH: {error}") from error
```

In `build_parser`, insert this block directly above the line `    verify = sub.add_parser(`:

```python
    batch = sub.add_parser("batch", help="render captioned rooms through ComfyUI")
    common(batch)
    batch.add_argument("--dry-run", action="store_true",
                       help="print the plan without contacting ComfyUI or writing files")
    batch.add_argument("--no-memory-check", action="store_true",
                       help=f"skip the {MEMORY_FLOOR_GB} GB available-memory guard")
    batch.add_argument("--force", action="store_true",
                       help="render the selected rooms again, even when done or stuck")
    batch.add_argument("--match-strength", type=match_strength, default=default_match_strength(),
                       metavar="X",
                       help="how far each render moves toward its source's colours, 0 to 1 "
                            "(default: %(default)s, or ATL_MATCH_STRENGTH)")
    batch.add_argument("--workflow", choices=sorted(comfy_client.WORKFLOWS),
                       default=default_workflow(), metavar="NAME",
                       help="render workflow: " + ", ".join(sorted(comfy_client.WORKFLOWS))
                            + " (default: %(default)s, or ATL_WORKFLOW)")
    batch.set_defaults(func=cmd_batch)
```

- [ ] **Step 4: Run the tests**

Run: `make test`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add atl_recreate.py test_atl_recreate.py
git commit -m "feat: batch stage with retries, max attempts, skip copies and dry-run"
```

---

### Task 15: The `review` stage

**Files:**
- Modify: `atl_recreate.py`, `test_atl_recreate.py`

**Interfaces:**
- Consumes: `prompts.review_room` (Task 9); `room_geometry.build_guide`, `plan_room`; Task 11's audit helpers.
- Produces (`atl_recreate`): `review_images(src, room, output) -> (pairs, render)`; `cmd_review(args) -> int`; the `review` subcommand with `--force`. It reviews only a promoted latest attempt; each verdict goes to `reviews.yaml` (`source: review`) and `attempt-N.review.json`, and a failure goes to `attempt-N.review-error.txt`.

- [ ] **Step 1: Write the failing tests**

Add to `test_atl_recreate.py`, above `if __name__ == "__main__":`:

```python
class ReviewTests(DriverFixture):
    def setUp(self):
        super().setUp()
        with testkit.comfy_stub(comfy_dir=self.comfy_dir, render=testkit.fake_render()):
            self.run_cli("batch")

    def review(self, *extra, verdict=None, **stub):
        verdict = verdict or (lambda pairs, overview, kind, caption, *a:
                              {"accepted": True, "issues": []})
        with testkit.vlm_stub(review=verdict, free=None, **stub) as vlm:
            code, out, err = self.run_cli("review", *extra)
        return code, out, err, vlm

    def test_reviews_every_promoted_room(self):
        code, _, err, vlm = self.review()
        self.assertEqual(code, 0, err)
        reviews = load_reviews(self.reviews)
        self.assertEqual(sorted(reviews), ["room_001", "room_002", "room_003"])
        self.assertTrue(all(r.accepted and r.attempt == 1 and r.source == "review"
                            for r in reviews.values()))
        self.assertEqual([len(c.args[0]) for c in vlm.review.call_args_list], [1, 2, 4])
        self.assertEqual(vlm.review.call_args_list[2].args[1].size, (4608, 576))
        vlm.freed.assert_called_once()
        self.assertTrue((self.dst / ".quality/room_001/attempt-1.review.json").is_file())

    def test_skips_reviewed_rooms_unless_forced(self):
        self.review()
        _, out, _, vlm = self.review()
        vlm.review.assert_not_called()
        self.assertIn("skipped=4", out)
        _, _, _, vlm = self.review("--force", "--room", "1")
        self.assertEqual(vlm.review.call_count, 1)

    def test_a_rejection_sends_the_room_back_to_batch(self):
        def verdict(pairs, *a):
            if len(pairs) == 2:
                return {"accepted": False, "issues": ["window 2: the awning moved; move it back"]}
            return {"accepted": True, "issues": []}
        self.review(verdict=verdict)
        with testkit.comfy_stub(comfy_dir=self.comfy_dir, render=testkit.fake_render()) as mocks:
            self.run_cli("batch")
        self.assertEqual({c.kwargs["name"] for c in mocks.render.call_args_list},
                         {"room_002_window-1", "room_002_window-2"})

    def test_a_geometry_rejected_attempt_is_not_reviewed(self):
        # Review Focus: review must not judge an output older than the latest attempt.
        with testkit.comfy_stub(comfy_dir=self.comfy_dir,
                                render=testkit.fake_render(testkit.shift_right)):
            self.run_cli("batch", "--room", "1", "--force")
        _, _, _, vlm = self.review("--room", "1")
        vlm.review.assert_not_called()
        self.assertEqual(load_reviews(self.reviews)["room_001"].source, "geometry")

    def test_refuses_without_vllm(self):
        code, _, err, vlm = self.review(serving=False)
        self.assertEqual(code, 2)
        self.assertIn("vLLM is not serving", err)
        vlm.review.assert_not_called()

    def test_a_failed_review_is_recorded(self):
        def boom(*a):
            raise ValueError("VLM review verdict contradicts its issues")
        code, _, _, _ = self.review("--room", "1", verdict=boom)
        self.assertEqual(code, 1)
        self.assertIn("contradicts", (self.dst / ".quality/room_001/attempt-1.review-error.txt")
                      .read_text())

    def test_a_down_comfyui_does_not_stop_the_review(self):
        with testkit.vlm_stub(review=lambda *a: {"accepted": True, "issues": []},
                              free=RuntimeError("connection refused")):
            code, _, _ = self.run_cli("review", "--room", "1")
        self.assertEqual(code, 0)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest test_atl_recreate.ReviewTests -v`
Expected: ERROR, `AttributeError: <module 'atl_recreate' ...> does not have the attribute 'review_room'`.

- [ ] **Step 3: Implement the stage**

In `atl_recreate.py`, replace the import block (from `import argparse` to `from source_tree import SourceError`) with:

```python
import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from PIL import Image

import colour_match
import comfy_client
import geometry_check
import room_geometry
import source_tree
from prompts import (PAINTED_NEGATIVE, SEAM_NOTE, caption_room, render_prompt, review_room,
                     vlm_is_serving, window_note)
from rooms_file import (Review, RoomEntry, RoomsFileError, check_coverage, load_reviews,
                        load_rooms, save_reviews, save_rooms)
from source_tree import SourceError
```

Insert this section directly above the `# ---- command line` line:

```python
# ---- review -----------------------------------------------------------------

def review_images(src, room, output):
    """([(guide window, render window), ...], whole render) for the VLM."""
    indexed = source_tree.open_indexed(src, room)
    guide = room_geometry.build_guide(indexed)
    plan = room_geometry.plan_room(indexed)
    with Image.open(output) as im:
        render = im.convert("RGB")
    pairs = []
    for win in plan.windows:
        box = (win.x0 * SCALE, 0, win.x1 * SCALE, render.height)
        pairs.append((guide.full.crop(box), render.crop(box)))
    return pairs, render


def cmd_review(args):
    rooms = selection(args)
    entries = load_entries(args)
    if not vlm_is_serving(VLM_BASE_URL, VLM_MODEL, comfy_client.http_json, VLM_API_KEY):
        return fail(f"vLLM is not serving {VLM_MODEL} at {VLM_BASE_URL} - start it first")
    try:
        comfy_client.free_models(COMFY_URL)     # give the VLM room; ComfyUI may be down
    except Exception:
        pass
    reviews = load_reviews(args.reviews, optional=True)
    accepted = rejected = skipped = failed = 0
    for i, room in enumerate(rooms, 1):
        entry = entries[room.key]
        audit = audit_dir(args.dst, room)
        attempt = latest_attempt(audit)
        record = read_record(audit, attempt) if attempt else None
        dst = args.dst / room.out_name
        review = reviews.get(room.key)
        # Only a promoted latest attempt is judged: a geometry rejection already
        # has its verdict, and a failed attempt has nothing to show.
        if (entry.kind == "skip" or record is None or not record.get("promoted")
                or not dst.is_file()
                or (review is not None and review.attempt >= attempt and not args.force)):
            skipped += 1
            continue
        print(f"[{i}/{len(rooms)}] review {room.key} (attempt {attempt})", flush=True)
        try:
            pairs, overview = review_images(args.src, room, dst)
            verdict = review_room(pairs, overview, entry.kind, entry.caption,
                                  comfy_client.http_json, VLM_BASE_URL, VLM_MODEL, VLM_API_KEY)
        except Exception as error:
            failed += 1
            write_atomic(audit / f"attempt-{attempt}.review-error.txt", str(error))
            print(f"  ERROR reviewing {room.key}: {error}", file=sys.stderr, flush=True)
            continue
        write_atomic(audit / f"attempt-{attempt}.review.json", json.dumps(verdict, indent=2))
        reviews[room.key] = Review(attempt, verdict["accepted"], tuple(verdict["issues"]), "review")
        save_reviews(args.reviews, reviews)
        if verdict["accepted"]:
            accepted += 1
            print("  accepted")
        else:
            rejected += 1
            print("  rejected: " + "; ".join(verdict["issues"]))
    print(f"done: accepted={accepted} rejected={rejected} skipped={skipped} failed={failed} "
          f"-> {args.reviews}")
    return 1 if failed else 0
```

In `build_parser`, insert this block directly above the line `    verify = sub.add_parser(`:

```python
    review = sub.add_parser("review", help="compare promoted rooms with their sources through "
                                           "the local vLLM")
    common(review)
    review.add_argument("--force", action="store_true",
                        help="review rooms whose latest attempt was already reviewed")
    review.set_defaults(func=cmd_review)
```

- [ ] **Step 4: Run the tests**

Run: `make test`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add atl_recreate.py test_atl_recreate.py
git commit -m "feat: review stage judges promoted rooms against their sources"
```

---

### Task 16: Make targets, wrappers and documentation

**Files:**
- Modify: `Makefile` (replace)
- Create: `run_batch.sh`, `run_server.sh`, `test_scripts.py`, `README.md`, `AGENTS.md`, `CLAUDE.md` (a symlink to `AGENTS.md`)

**Interfaces:**
- Consumes: the four subcommands (Tasks 11–15).
- Produces: `make caption|dry-run|batch|review|verify|server`, taking `room="1 58"`, `src=`, `dst=`, `force=1`, and for `batch` and `dry-run` also `workflow=`, `strength=` and `memcheck=0` (spec §8).

- [ ] **Step 1: Write the failing test**

`test_scripts.py`:

```python
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent


def dry_make(*args):
    """The ./run_* command lines `make -n` would run, whitespace collapsed."""
    out = subprocess.run(["make", "-n", "-s", *args], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout
    return [" ".join(line.split()) for line in out.splitlines() if line.startswith("./run_")]


class MakeTests(unittest.TestCase):
    def test_targets_forward_their_arguments(self):
        cases = {
            ("caption", "room=1 58", "force=1"): "./run_batch.sh caption --room 1 --room 58 --force",
            ("dry-run", "workflow=qwen-image-2.1-i2i", "strength=0.5"):
                "./run_batch.sh batch --dry-run --match-strength 0.5 --workflow qwen-image-2.1-i2i",
            ("batch", "room=58", "memcheck=0", "force=1", "dst=data/spike"):
                './run_batch.sh batch --room 58 --dst "data/spike" --no-memory-check --force',
            ("review", "force=1"): "./run_batch.sh review --force",
            ("verify", "src=/x"): './run_batch.sh verify --src "/x"',
            ("server",): "./run_server.sh",
        }
        for args, expected in cases.items():
            with self.subTest(args=args):
                self.assertEqual(dry_make(*args), [expected])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m unittest test_scripts -v`
Expected: ERROR, `CalledProcessError`: `make -n caption` fails with `No rule to make target 'caption'`.

- [ ] **Step 3: Write the wrappers and the full Makefile**

`run_batch.sh`:

```bash
#!/bin/bash
# Run the Atlantis regeneration driver: forwards every argument to atl_recreate.py
# (caption | batch | review | verify, plus their options). Prefers the project
# venv (.venv, made by make install), then PYTHON, then python3; the interpreter
# needs Pillow, PyYAML and numpy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PY="$SCRIPT_DIR/.venv/bin/python"
fi
PY="${PY:-${PYTHON:-python3}}"

"$PY" -c 'import PIL, yaml, numpy' 2>/dev/null || {
  echo "error: $PY lacks Pillow, PyYAML or numpy - run: make install" >&2
  exit 1
}

exec "$PY" "$SCRIPT_DIR/atl_recreate.py" "$@"
```

`run_server.sh`:

```bash
#!/bin/bash
# Start ComfyUI from its own checkout and venv (default ~/ComfyUI), listening on :8188.
set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
PY="$COMFY_DIR/venv/bin/python"

[ -f "$COMFY_DIR/main.py" ] || { echo "error: $COMFY_DIR/main.py not found - set COMFY_DIR" >&2; exit 1; }
[ -x "$PY" ] || { echo "error: $PY not found - create the ComfyUI venv first" >&2; exit 1; }

cd "$COMFY_DIR"
exec "$PY" main.py --listen 0.0.0.0 --port 8188 "$@"
```

`Makefile` (replace the whole file; recipe lines start with a real tab):

```make
# Makefile for the Atlantis background regeneration kit
# Pipeline: caption -> (edit rooms.yaml) -> batch -> review -> batch ... -> verify
SERVICE = Atlantis Background Regen

VENV_DIR = .venv
PY = $(VENV_DIR)/bin/python

# Arguments, e.g. make batch room="1 58" workflow=qwen-image-2.1-i2i force=1
room ?=
src ?=
dst ?=
force ?=
memcheck ?= 1
strength ?=
workflow ?=
ARGS = $(foreach r,$(room),--room $(r)) $(if $(src),--src "$(src)") $(if $(dst),--dst "$(dst)")
BATCH_ARGS = $(if $(filter 0,$(memcheck)),--no-memory-check) $(if $(strength),--match-strength $(strength)) \
             $(if $(workflow),--workflow $(workflow)) $(if $(force),--force)

.PHONY: help install server caption dry-run batch review verify check test clean

help: ## Print this help message
	@printf '\033[01;32m${SERVICE}\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

# ── Environment ──────────────────────────────────────────────────────────────

install: ## Create .venv with Pillow, PyYAML and numpy (re-running is safe)
	@if [ ! -x "$(PY)" ]; then python3 -m venv $(VENV_DIR); fi
	@$(PY) -c 'import PIL, yaml, numpy' 2>/dev/null || $(VENV_DIR)/bin/pip install -q "pillow>=10" "pyyaml>=6" "numpy>=1.26"

server: ## Start ComfyUI on :8188 from ~/ComfyUI (override COMFY_DIR)
	./run_server.sh

clean: ## Remove __pycache__ (never touches data/)
	find . -path ./.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} +

# ── Pipeline ─────────────────────────────────────────────────────────────────

caption: install ## [STEP 1] Caption scene and insert rooms with vLLM into rooms.yaml (room=, force=1)
	./run_batch.sh caption $(ARGS) $(if $(force),--force)

dry-run: install ## [STEP 2a] Show what batch would render, without touching ComfyUI (room=, workflow=, strength=, force=1)
	./run_batch.sh batch --dry-run $(ARGS) $(BATCH_ARGS)

batch: install ## [STEP 2] Render rooms through ComfyUI into data/rooms-ai; stop vLLM first (room=, workflow=, strength=, memcheck=0, force=1)
	./run_batch.sh batch $(ARGS) $(BATCH_ARGS)

review: install ## [STEP 3] Review promoted rooms with vLLM into reviews.yaml (room=, force=1)
	./run_batch.sh review $(ARGS) $(if $(force),--force)

verify: install ## [STEP 4] Audit data/rooms-ai against the manifest, the 4x rule and the attempt records (room=)
	./run_batch.sh verify $(ARGS)

# ── Development ──────────────────────────────────────────────────────────────

check: install ## Byte-compile the Python modules
	@$(PY) -m py_compile *.py && echo "check ok"

test: install ## Run the unit tests (no GPU, no network)
	$(PY) -m unittest discover -s . -p 'test_*.py'
```

Then: `chmod +x run_batch.sh run_server.sh`

- [ ] **Step 4: Run the tests and try the targets**

Run: `make test && make check && make dry-run room="1 58"`
Expected: the tests pass and `check ok` is printed. The dry run reads the real corpus and exits 0. It prints `NOCAPTION room_001` and `NOCAPTION room_058`, because the captions come in Task 17; a dry run never fails on a missing caption.

- [ ] **Step 5: Write the documentation**

`README.md`:

````markdown
# Atlantis Background Regeneration

Regenerates the 96 room backgrounds of *Indiana Jones and the Fate of
Atlantis* (LucasArts, 1992) as painted high-definition art at exactly 4x
their native size, with local models:

- ComfyUI running one of two render workflows, chosen per run: Qwen-Image-Edit
  2511 with the InstantX Canny ControlNet (`qwen-edit-2511-canny`, the
  default), or Qwen-Image 2.1 img2img (`qwen-image-2.1-i2i`).
- vLLM serving `Qwen/Qwen3.8-27B`, which captions each room before rendering
  and reviews each render afterwards.

Input: `../atlantis-textures/out/` (override with `ATL_SRC`), the output of
`make extract` in atlantis-textures: indexed room PNGs and `manifest.json`.
Output: `data/rooms-ai/room_NNN.png` (override with `ATL_DST`).

**Personal use only.** The extracted and regenerated art is LucasArts/Disney
copyright. Do not redistribute it. `data/` is gitignored; never commit art.

## Pipeline

```
ATL_SRC ──[make caption]──▶ rooms.yaml ──(you edit)──┐
            vLLM up                                   ▼
data/rooms-ai/ ◀──[make batch]── rooms.yaml + reviews.yaml (rejects only)
   │               ComfyUI up, vLLM stopped
   └──[make review]──▶ reviews.yaml   (vLLM up)
```

1. **`make caption`** (vLLM up) describes every `scene` and `insert` room
   whose caption is blank and writes it into `rooms.yaml`, saving after each
   room. `force=1` redoes all; blanking one caption redoes that room.
2. **Edit `rooms.yaml`.** The caption becomes the REFERENCE OBSERVATIONS
   block of every window's prompt; an insert's `TEXT:` section becomes the
   lettering its render must reproduce.
3. **`make batch`** (ComfyUI up, vLLM stopped) renders every captioned room
   whose output is missing or whose latest attempt was rejected (see Checks),
   and writes each `skip` room as a nearest-neighbour 4x. On exit, even after
   a failure, it frees ComfyUI's models so vLLM can start.
4. **`make review`** (vLLM up) judges every promoted room whose latest attempt
   is unreviewed and writes `reviews.yaml`.
5. **`make batch` again** redoes only the rejected rooms, with the next seed
   and the issues as corrections. Repeat 4 and 5.
6. **`make verify`** audits `data/rooms-ai/`.

`make dry-run` prints what `batch` would do (windows, wraparound, margins,
corrections) without touching ComfyUI.

## Swapping the services on this host

vLLM (about 73 GB) and a render (about 45 GB) do not fit together in the
GB10's 121 GB of unified memory.

| Service | Start | Stop |
|---|---|---|
| vLLM | `docker start lmcache-server vllm-server` | `docker stop vllm-server lmcache-server` |
| ComfyUI | `make server` (foreground) or `sudo systemctl start comfyui` | Ctrl-C, or `sudo systemctl stop comfyui` |

`make batch` refuses to start with less than 45 GB free (`memcheck=0` skips
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

A room wider than 320 columns renders as overlapping windows, each at most 320
native columns wide (1280 px at 4x), overlapping by at least 64. Windows
render left to right with one seed. Each later window holds the outer half of
its overlap with the already-painted stitch and ramps across the inner half,
so the brushwork continues instead of meeting at a seam.

Room 58 wraps around: its columns 840–1063 repeat columns 0–223, and its last
88 columns and its top 28 and bottom 26 rows are flat black. The kit detects
this from the pixels. It renders the 840-column panorama, then one more seam
window across the join. It then copies the repeated span over and fills the
flat margins with the source colour, so the output repeats exactly where the
game's art does.

## Checks

Before a render is promoted, `make batch` checks it:

- **Size:** exactly 4x native, RGB.
- **Geometry:** the render, box-downscaled to native size, must not be shifted
  by 0.5 px or more against the de-dithered source (over the room and within
  each window), and must keep at least 80% of the source's strong edges
  within 1 px. A failure is written to `reviews.yaml` as `source: geometry`,
  and the next batch retries the room.
- **Seams:** a window boundary whose colour step is 3 times the local texture
  (measured relative to the source's own step there) is printed as a warning.

A room rejected 4 times is **STUCK**: batch reports it and leaves it alone.
Fix its caption, then run `make batch room=N force=1`.

## Outputs and the audit folder

```
data/rooms-ai/room_NNN.png            the promoted render
data/rooms-ai/.quality/room_NNN/
  attempt-N.png                       the raw stitch, before the colour match
  attempt-N.tiles/                    window-K.{guide,composite,mask}.png, window-K.png, seam.*
  attempt-N.prompt.txt                starts "workflow: NAME"; every window's prompt
  attempt-N.json                      seed, windows, wrap, margins, match, geometry, promoted, sha256, seconds
  attempt-N.review.json               the VLM verdict
```

## Commands

| Target | What it does |
|---|---|
| `make caption [room=] [force=1]` | Write captions into `rooms.yaml` |
| `make dry-run [room=] [workflow=] [strength=] [force=1]` | Show what `batch` would render |
| `make batch [room=] [workflow=] [strength=] [memcheck=0] [force=1]` | Render and promote into `data/rooms-ai/` |
| `make review [room=] [force=1]` | Write `reviews.yaml` |
| `make verify [room=]` | Audit `data/rooms-ai/` |
| `make server` | Start ComfyUI from `~/ComfyUI` on :8188 |
| `make install` / `make check` / `make test` / `make clean` | venv / byte-compile / unit tests / caches |

`room="1 29 58"` selects rooms by number; every stage target also takes
`src=DIR` and `dst=DIR`. Environment overrides: `ATL_SRC`, `ATL_DST`,
`ATL_ROOMS`, `ATL_REVIEWS`, `ATL_WORKFLOW`, `ATL_MATCH_STRENGTH`, `COMFY_URL`,
`COMFY_DIR`, `VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY`.

## Setup

- `make install` creates `.venv` with Pillow, PyYAML and numpy.
- ComfyUI at `~/ComfyUI` (override with `COMFY_DIR`), at or after commit
  c194dd0 (2026-09-20), with these files under `models/`:
  - `qwen-edit-2511-canny`: `diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors`,
    `text_encoders/qwen_2.5_vl_7b_uncensored_comfy_ready_bf16.safetensors`,
    `vae/qwen_image_vae.safetensors`,
    `controlnet/Qwen-Image-InstantX-ControlNet-Union.safetensors`;
  - `qwen-image-2.1-i2i`: `diffusion_models/qwen_image_2.1_bf16.safetensors`,
    `text_encoders/qwen3vl_8b_bf16.safetensors`,
    `vae/qwen_image_2.1_vae_bf16.safetensors`.

  `make batch` checks the files and the node classes before rendering.
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
| `Makefile`, `run_batch.sh`, `run_server.sh` | Targets and wrappers |
| `testkit.py`, `test_*.py` | Test support and unit tests (no GPU, no network) |
| `docs/superpowers/` | The design spec and the implementation plan |
````

`AGENTS.md`:

````markdown
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
````

Then: `ln -s AGENTS.md CLAUDE.md`

- [ ] **Step 6: Commit**

```bash
git add Makefile run_batch.sh run_server.sh test_scripts.py README.md AGENTS.md CLAUDE.md
git commit -m "feat: make targets, wrappers, README and AGENTS"
```

---

### Task 17: Live check — one room through each graph

This task runs services on this host. It proves each graph renders, which the template tests cannot. It also produces the six spike captions.

**Files:**
- Modify: `rooms.yaml` (six captions), `AGENTS.md` (section 6); possibly a graph JSON and `test_comfy_client.py`, if a graph needs fixing.

- [ ] **Step 1: Start vLLM and caption the spike rooms**

Check that nothing else holds memory (`free -g`: about 115 GB available), then:

```bash
docker start lmcache-server vllm-server
until curl -sf http://127.0.0.1:8000/v1/models | grep -q Qwen3.8-27B; do sleep 10; done
make caption room="1 29 47 52 58 85"
```

Expected: `done: captioned=6 skipped=0 failed=0`. The model load takes several minutes, and each caption takes up to about 7 minutes.

- [ ] **Step 2: Read and correct the six captions**

Open `rooms.yaml` and compare each caption with its room (`../atlantis-textures/out/indexed/rooms/room_NNN.png`; the Read tool shows images). Room 47's TEXT must contain the headline `German Wizard Splits Atom`. Rewrite by hand any section that misreads the room: the AITD kit's full run found that a room which keeps failing on layout is usually a caption problem first.

- [ ] **Step 3: Swap vLLM for ComfyUI**

```bash
docker stop vllm-server lmcache-server
make server > data/comfyui.log 2>&1 &      # or: sudo systemctl start comfyui
until curl -sf http://127.0.0.1:8188/queue > /dev/null; do sleep 5; done
```

(`mkdir -p data` first if it does not exist.)

- [ ] **Step 4: Render room 1 through each graph**

```bash
make batch room=1 workflow=qwen-edit-2511-canny dst=data/smoke/qwen-edit-2511-canny
make batch room=1 workflow=qwen-image-2.1-i2i dst=data/smoke/qwen-image-2.1-i2i
```

Expected: each ends with `done: promoted=1` or with `rejected attempt 1: geometry: ...`. Either outcome proves the graph runs. A ComfyUI validation error (`Prompt outputs failed validation`, `Required input is missing`, `unexpected keyword argument`) means the graph is wrong. Fix the JSON, add a test to `test_comfy_client.TemplateTests` that names the error it guards (like `test_qwen21_reference_uses_the_autogrow_container_path`), run `make test`, and render again.

- [ ] **Step 5: Render a two-window room**

```bash
make batch room=29 workflow=qwen-image-2.1-i2i dst=data/smoke/qwen-image-2.1-i2i
```

This exercises the continuation mask (`SetLatentNoiseMask` with a `DifferentialDiffusion` ramp) on a real room. Look at `data/smoke/qwen-image-2.1-i2i/room_029.png` and its two tiles in `.quality/room_029/attempt-1.tiles/`. The overlap must continue the first window's painting, not restart it.

- [ ] **Step 6: Record the live check**

In `AGENTS.md` section 6, replace "Not run yet. …" with a `**Live check (<today's date>, GB10).**` paragraph, using the date you ran it. It records, per workflow: seconds per window (the record's `seconds` divided by its windows), the geometry numbers from each `attempt-1.json`, whether room 29's overlap continued, and any graph fix with its error message. Keep the final sentence about Task 18.

- [ ] **Step 7: Commit**

```bash
git add rooms.yaml AGENTS.md
git add -u        # a graph fix and its test, if Step 4 needed one
git commit -m "chore: captions for the six spike rooms; live check of both graphs"
```

---

### Task 18: The spike — choose the defaults (human checkpoint)

Spec §14. ComfyUI stays up from Task 17 and vLLM stays stopped. Each Edit 2511 variant renders 11 windows across rooms 1, 29, 47, 52, 58 and 85 (about 50 minutes); each 2.1 variant takes about 10 minutes. The variants are made by editing a JSON tunable or a constant for one run and restoring it with `git checkout` afterwards. Nothing but the decisions in Step 8 is committed.

**Files:**
- Modify (decisions only): `comfy_client.py` (`DEFAULT_WORKFLOW`), one graph JSON's tunable, `room_geometry.py` (`DEDITHER_METHOD`; `WINDOW_WIDTH`/`WINDOW_OVERLAP` only if Step 3 shows it), `atl_recreate.py` (`REFERENCE`, `DEFAULT_MATCH_STRENGTH`), `geometry_check.py` (`MIN_EDGE_AGREEMENT`), `AGENTS.md`, `README.md`.
- Create (throwaway, under the gitignored `data/spike/`): `sheet.py`, `strength.py`, `table.py`.

- [ ] **Step 1: Render the four model variants**

Rooms 1, 29, 47, 52, 58 and 85 cover one window, two windows, the newspaper insert, dark stone, the wraparound and a half-black labyrinth piece. Room 85 is not in spec §14's table; it is there to watch spec §15's first risk, that the model paints texture into flat black. If it does, record it in Step 8 as a follow-up (a flat-region preserve rule), not as a fix inside this plan. Sample free memory while they run, to confirm the 45 GB floor:

```bash
rooms="1 29 47 52 58 85"
( while sleep 5; do awk '/MemAvailable/ {print $2}' /proc/meminfo; done ) > data/spike-memory.log &
make batch room="$rooms" workflow=qwen-edit-2511-canny dst=data/spike/2511-cn0.7
sed -i 's/"strength": 0.7, "start_percent"/"strength": 0.9, "start_percent"/' recreation_qwen2511_canny.json
make batch room="$rooms" workflow=qwen-edit-2511-canny dst=data/spike/2511-cn0.9
git checkout recreation_qwen2511_canny.json
make batch room="$rooms" workflow=qwen-image-2.1-i2i dst=data/spike/21-d0.6
sed -i 's/"denoise": 0.6}/"denoise": 0.75}/' recreation_qwen21_i2i.json
make batch room="$rooms" workflow=qwen-image-2.1-i2i dst=data/spike/21-d0.75
git checkout recreation_qwen21_i2i.json
kill %1
sort -n data/spike-memory.log | head -1       # the lowest MemAvailable, in kB
```

Expected: each run ends `done: promoted=… rejected=… failed=0 …`. A geometry rejection is data here: do not retry it. After each `sed`, confirm with `git diff` that exactly one value changed.

- [ ] **Step 2: Build the comparison sheets**

`data/spike/sheet.py`:

```python
"""Throwaway: one labelled row per variant for each spike room (data/spike/sheet_room_NNN.png)."""
import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path("data/spike")
SRC = Path("../atlantis-textures/out/indexed/rooms")


def raw_attempts(folder):
    found = [(int(m.group(1)), p) for p in folder.glob("attempt-*.png")
             if (m := re.match(r"attempt-(\d+)\.png$", p.name))]
    return [p for _, p in sorted(found)]


for number in (1, 29, 47, 52, 58, 85):
    key = f"room_{number:03d}"
    with Image.open(SRC / f"{key}.png") as im:
        source = im.convert("RGB")
    rows = [("source (nearest 4x)",
             source.resize((source.width * 4, source.height * 4), Image.Resampling.NEAREST))]
    for variant in sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name != "strength"):
        output, raw = variant / f"{key}.png", raw_attempts(variant / ".quality" / key)
        if output.is_file():
            path, label = output, variant.name
        elif raw:
            path, label = raw[-1], f"{variant.name} (REJECTED by geometry; raw stitch)"
        else:
            continue
        with Image.open(path) as im:
            rows.append((label, im.convert("RGB")))
    sheet = Image.new("RGB", (max(image.width for _, image in rows),
                              sum(image.height + 24 for _, image in rows)), "white")
    draw = ImageDraw.Draw(sheet)
    y = 0
    for label, image in rows:
        draw.text((6, y + 6), label, fill="black")
        sheet.paste(image, (0, y + 24))
        y += image.height + 24
    sheet.save(ROOT / f"sheet_{key}.png")
    print(ROOT / f"sheet_{key}.png")
```

Run: `.venv/bin/python data/spike/sheet.py`
Expected: six paths `data/spike/sheet_room_NNN.png`.

- [ ] **Step 3: Render the second-order variants on the best-looking model variant**

Pick the variant whose sheets look most like painted HD with the layout intact; call it `$best` (for example `21-d0.6`) and its workflow `$wf`. Then:

```bash
sed -i 's/^DEDITHER_METHOD = "palette-smooth"/DEDITHER_METHOD = "gaussian"/' room_geometry.py
make batch room="1 52 85" workflow=$wf dst=data/spike/$best-gaussian
git checkout room_geometry.py
sed -i 's/^REFERENCE = "guide"/REFERENCE = "composite"/' atl_recreate.py
make batch room="29 58" workflow=$wf dst=data/spike/$best-composite
git checkout atl_recreate.py
sed -i 's/^WINDOW_WIDTH = 320 /WINDOW_WIDTH = 256 /' room_geometry.py
make batch room="29 58" workflow=$wf dst=data/spike/$best-wt256
git checkout room_geometry.py
.venv/bin/python data/spike/sheet.py
```

If `$best` is one of the `…-0.9` or `…-0.75` variants, apply its `sed` from Step 1 before these runs, and `git checkout` its JSON afterwards.

`data/spike/strength.py`, which re-matches `$best`'s raw stitches at three strengths without re-rendering:

```python
"""Throwaway: one variant's raw stitches re-matched at three strengths (data/spike/strength/)."""
import sys
from pathlib import Path

from PIL import Image

import colour_match
import room_geometry
import source_tree

variant = Path(sys.argv[1])
src = Path("../atlantis-textures/out")
out = Path("data/spike/strength")
out.mkdir(parents=True, exist_ok=True)
source = source_tree.load(src)
for room in source_tree.select(source, [1, 29, 47, 52, 58, 85]):
    raw = variant / ".quality" / room.key / "attempt-1.png"
    if not raw.is_file():
        continue
    indexed = source_tree.open_indexed(src, room)
    guide = room_geometry.build_guide(indexed)
    plan = room_geometry.plan_room(indexed)
    with Image.open(raw) as im:
        stitch = im.convert("RGB")
    for strength in (0.0, 0.5, 1.0):
        matched = colour_match.match(stitch, guide.full, strength)
        room_geometry.apply_fixups(matched, plan, indexed).save(out / f"{room.key}_s{strength}.png")
    print(room.key)
```

Run: `PYTHONPATH=. .venv/bin/python data/spike/strength.py data/spike/$best`
Expected: six room keys. The images land in `data/spike/strength/room_NNN_s{0.0,0.5,1.0}.png`.

- [ ] **Step 4: Tabulate the geometry numbers**

`data/spike/table.py`:

```python
"""Throwaway: every spike render's geometry numbers, to calibrate MIN_EDGE_AGREEMENT."""
import json
from pathlib import Path

for path in sorted(Path("data/spike").glob("*/.quality/room_*/attempt-*.json")):
    record = json.loads(path.read_text())
    geometry = record["geometry"]
    windows = len(record["windows"]) + (1 if record["wrap"] else 0)
    print(f"{path.parts[2]:28} {path.parts[4]}  edge {geometry['edge_agreement']:.3f}  "
          f"shift {geometry['shift']}  promoted {record['promoted']!s:5}  "
          f"{record['seconds'] / windows:6.1f} s/window")
```

Run: `.venv/bin/python data/spike/table.py`

- [ ] **Step 5: CHECKPOINT: stop and ask your human partner**

Do not choose the defaults yourself. Hand over:
- the paths of the sheets and the strength images;
- the table from Step 4;
- the lowest MemAvailable from Step 1.

Ask them to:
1. mark each render in the sheets good or bad for layout fidelity;
2. pick the look: the workflow and its strength or denoise;
3. pick palette-smooth or gaussian;
4. pick guide or composite as the continuation reference;
5. keep 320 or take 256 as the window width;
6. pick the colour-match strength.

Wait for their answers.

- [ ] **Step 6: Calibrate `MIN_EDGE_AGREEMENT`**

From the table and their good or bad marks: if every render marked good has a higher edge agreement than every render marked bad, set `MIN_EDGE_AGREEMENT` just below the lowest good one, rounded down to 0.01. Otherwise keep 0.80 and record the overlap in Step 8. `EDGE_THRESHOLD` stays 80 unless they judged the gate wrong on a render whose numbers show why.

- [ ] **Step 7: Apply the decisions**

- `comfy_client.DEFAULT_WORKFLOW` = the chosen workflow; replace its comment with `# chosen by the spike on <its date>: <one-line reason>`.
- The chosen graph's tunable: node 33 `strength` (2511) or node 13 `denoise` (2.1).
- `room_geometry.DEDITHER_METHOD`, `atl_recreate.REFERENCE`, `atl_recreate.DEFAULT_MATCH_STRENGTH`, `geometry_check.MIN_EDGE_AGREEMENT`.
- If the window width changed: `room_geometry.WINDOW_WIDTH` (and `WINDOW_OVERLAP` if it was chosen too). Then update `test_room_geometry.WindowPlanTests.test_known_plans` and the `test_stitch_boundaries` expectations to the new plans (compute them with `rg.plan_windows` and `rg.stitch_boundaries`, and check each by hand against the rules in spec §9.3). Also update `MIN_WRAP_PERIOD` if the new width exceeds 320.

Run: `make test && make check`
Expected: `OK`, `check ok`.

- [ ] **Step 8: Record the spike**

In `AGENTS.md` section 6, add a `**Spike (<today's date>, GB10).**` paragraph and table: variant × room with seconds per window, shift, edge agreement, promoted, and your partner's good or bad mark. Add the lowest MemAvailable during rendering, each decision with the reason they gave, and the edge-agreement calibration (or the overlap that kept 0.80). If the default workflow changed, update the README's first list to name it as the default.

- [ ] **Step 9: Commit**

```bash
git add comfy_client.py recreation_qwen2511_canny.json recreation_qwen21_i2i.json room_geometry.py atl_recreate.py geometry_check.py test_room_geometry.py AGENTS.md README.md
git commit -m "chore: the spike's defaults: workflow, de-dither, reference, match strength, edge gate"
```

The kit is then ready for the full corpus run: `make caption`, then edit `rooms.yaml`, then alternate `make batch` and `make review`, and finish with `make verify` (README, Pipeline).
