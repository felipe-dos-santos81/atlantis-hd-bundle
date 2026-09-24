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

import comfy_client
import room_geometry
import source_tree
from prompts import caption_room, vlm_is_serving
from rooms_file import RoomEntry, RoomsFileError, check_coverage, load_rooms, save_rooms
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

    caption = sub.add_parser("caption", help="write captions into rooms.yaml with the local vLLM")
    common(caption)
    caption.add_argument("--force", action="store_true",
                         help="re-caption rooms that already have a caption")
    caption.set_defaults(func=cmd_caption)

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
