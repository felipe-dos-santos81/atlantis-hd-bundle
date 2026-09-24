"""Shared test support: a miniature atlantis-textures output, a rooms.yaml
writer, the ComfyUI and vLLM patch stacks, a fake window renderer and a
CLI-capture helper.

The real source tree is atlantis-textures' `out/`: indexed/rooms/room_NNN.png
in P mode at native size, and manifest.json whose assets[] carry room, file,
width, height, role and sha256.
"""

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
