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


# ---- batch ------------------------------------------------------------------

def memory_available_gb(meminfo=Path("/proc/meminfo")):
    """MemAvailable in GiB. On this unified-memory host it is the GPU budget too."""
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2 ** 20
    raise RuntimeError(f"MemAvailable not found in {meminfo}")


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


# ---- command line -----------------------------------------------------------

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
