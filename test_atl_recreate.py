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
import room_geometry
import source_tree
import testkit
from prompts import GEOMETRY_CORRECTION, PAINTED_NEGATIVE, SEAM_NOTE
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
                         (42, "guide", "room_001_a1-window-1", PAINTED_NEGATIVE))
        self.assertNotIn("one window of a wide scrolling room", kw["positive"])
        self.assertEqual(list((self.comfy_dir / "output" / "atl").iterdir()), [])

    def test_a_second_window_continues_the_first(self):
        (_, result), stub = self.render(2)
        self.assertTrue(result.passed, result.issues)
        calls = [c.kwargs for c in stub.render.call_args_list]
        self.assertEqual([c["name"] for c in calls],
                         ["room_002_a1-window-1", "room_002_a1-window-2"])
        self.assertIn("from 44% to 100%", calls[1]["positive"])
        with Image.open(calls[1]["mask"]) as mask:
            self.assertEqual((mask.getpixel((0, 0)), mask.getpixel((400, 0))), (0, 255))
        self.assertEqual(len(self.record(2)["geometry"]["seam_ratios"]), 1)

    def test_a_wraparound_room(self):
        (_, result), stub = self.render(3)
        self.assertTrue(result.passed, result.issues)
        calls = [c.kwargs for c in stub.render.call_args_list]
        self.assertEqual([c["name"] for c in calls],
                         [f"room_003_a1-window-{k}" for k in (1, 2, 3, 4)] + ["room_003_a1-seam"])
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

    def test_a_failed_attempt_records_its_error(self):
        # Regression: a failed attempt left no audit of what went wrong.
        good = testkit.fake_render()

        def render(workflow, **kw):
            if kw["name"].endswith("window-2"):
                raise TimeoutError("no history for p1 within 1800s")
            return good(workflow, **kw)
        room = self.room(2)
        args = argparse.Namespace(src=self.src, dst=self.dst, match_strength=0.5)
        with testkit.comfy_stub(comfy_dir=self.comfy_dir, render=render):
            with self.assertRaises(TimeoutError):
                a.render_room(args, self.workflow, room, self.entries[room.key], [])
        audit = self.dst / ".quality" / "room_002"
        text = (audit / "attempt-1.error.txt").read_text()
        for line in ("workflow: qwen-edit-2511-canny", "seed: 42", "window: window-2",
                     "error: TimeoutError: no history for p1 within 1800s"):
            self.assertIn(line + "\n", text)
        self.assertRegex(text, r"seconds: \d+\.\d\n")
        self.assertFalse((audit / "attempt-1.json").exists())
        self.assertEqual(a.room_status(args, room, {}), ("failed", 1))

    def test_attempts_continue_with_the_next_seed_and_carry_corrections(self):
        self.render(1)
        (attempt, _), stub = self.render(1, corrections=["the lamp moved"])
        kw = stub.render.call_args.kwargs
        self.assertEqual((attempt, kw["seed"]), (2, 43))
        self.assertIn("the lamp moved", kw["positive"])
        # Regression: the same name and seed across runs could hit ComfyUI's cache.
        self.assertEqual(kw["name"], "room_001_a2-window-1")
        self.assertTrue((self.dst / ".quality/room_001/attempt-2.tiles/window-1.png").is_file())


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

    def test_a_geometry_rejection_is_retried_with_the_layout_correction(self):
        # Regression: the gate's own strings ("geometry: edge agreement 0.71, needs 0.80")
        # went into the diffusion prompt, where they mean nothing and invite lettering.
        code, out, _, _ = self.batch("--room", "1", render=testkit.fake_render(testkit.shift_right))
        self.assertEqual(code, 0)
        self.assertIn("rejected attempt 1: geometry: the room is shifted", out)
        review = load_reviews(self.reviews)["room_001"]
        self.assertEqual((review.attempt, review.accepted, review.source), (1, False, "geometry"))
        self.assertIn("geometry: the room is shifted", review.issues[0])
        code, out, _, mocks = self.batch("--room", "1")
        self.assertEqual(code, 0)
        self.assertIn("promoted attempt 2", out)
        positive = mocks.render.call_args.kwargs["positive"]
        self.assertIn(GEOMETRY_CORRECTION, positive)
        self.assertNotIn("geometry:", positive)

    def test_a_review_rejection_is_retried(self):
        self.batch()
        save_reviews(self.reviews, {"room_002": Review(1, False, ("window 2: the awning moved; "
                                                                  "move it back",))})
        _, _, _, mocks = self.batch()
        self.assertEqual({c.kwargs["name"] for c in mocks.render.call_args_list},
                         {"room_002_a2-window-1", "room_002_a2-window-2"})
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

    def test_a_failed_attempt_keeps_the_review_corrections(self):
        # Regression: a review rejected attempt 1, attempt 2 timed out, and attempt 3
        # rendered without the corrections and was promoted.
        self.batch("--room", "1")
        save_reviews(self.reviews, {"room_001": Review(1, False, ("the lamp moved",))})

        def timeout(workflow, **kw):
            raise TimeoutError("no history for p1 within 1800s")
        code, _, _, _ = self.batch("--room", "1", render=timeout)
        self.assertEqual(code, 1)
        code, out, _, mocks = self.batch("--room", "1")
        self.assertEqual(code, 0)
        self.assertIn("promoted attempt 3", out)
        self.assertIn("the lamp moved", mocks.render.call_args.kwargs["positive"])
        _, _, _, mocks = self.batch("--room", "1", "--force")
        self.assertNotIn("the lamp moved", mocks.render.call_args.kwargs["positive"])

    def test_failed_attempts_do_not_count_toward_stuck(self):
        # Regression: three ComfyUI failures and one geometry rejection made the room
        # STUCK as "rejected 4 times".
        def boom(workflow, **kw):
            raise RuntimeError("ComfyUI execution failed: boom")
        for _ in range(a.MAX_ATTEMPTS - 1):
            self.assertEqual(self.batch("--room", "1", render=boom)[0], 1)
        code, _, err, _ = self.batch("--room", "1", render=testkit.fake_render(testkit.shift_right))
        self.assertEqual(code, 0)
        self.assertNotIn("STUCK", err)
        code, out, err, _ = self.batch("--room", "1")
        self.assertEqual(code, 0, err)
        self.assertIn(f"promoted attempt {a.MAX_ATTEMPTS + 1}", out)

    def test_a_stale_review_is_ignored(self):
        # Regression: after the audit folder is cleared, a reviews.yaml entry for a later
        # attempt made every new attempt read as rejected and carry its corrections.
        save_reviews(self.reviews, {"room_001": Review(3, False, ("the lamp moved",))})
        code, out, _, mocks = self.batch("--room", "1")
        self.assertEqual(code, 0)
        self.assertIn("promoted attempt 1", out)
        self.assertNotIn("the lamp moved", mocks.render.call_args.kwargs["positive"])
        _, out, _, mocks = self.batch("--room", "1")
        mocks.render.assert_not_called()
        self.assertIn("done 1", out)

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

    def test_ctrl_c_sweeps_the_room_and_frees_the_models(self):
        # Regression: KeyboardInterrupt skipped the sweep of the room's stray outputs.
        def ctrl_c(workflow, **kw):
            raise KeyboardInterrupt
        with testkit.comfy_stub(comfy_dir=self.comfy_dir, render=ctrl_c) as mocks:
            with self.assertRaises(KeyboardInterrupt):
                self.run_cli("batch", "--room", "1")
        mocks.sweep.assert_called_once_with("room_001", self.comfy_dir)
        mocks.freed.assert_called_once()

    def test_an_interrupted_room_starts_over_as_a_new_attempt(self):
        # Review Focus: a crash or timeout mid-room, then a rerun.
        good = testkit.fake_render()

        def render(workflow, **kw):
            if kw["name"] == "room_002_a1-window-2":
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
                         {"room_002_a2-window-1", "room_002_a2-window-2"})

    def test_a_geometry_rejected_attempt_is_not_reviewed(self):
        # Review Focus: review must not judge an output older than the latest attempt.
        with testkit.comfy_stub(comfy_dir=self.comfy_dir,
                                render=testkit.fake_render(testkit.shift_right)):
            self.run_cli("batch", "--room", "1", "--force")
        _, _, _, vlm = self.review("--room", "1")
        vlm.review.assert_not_called()
        self.assertEqual(load_reviews(self.reviews)["room_001"].source, "geometry")

    def test_a_stale_review_does_not_count_as_reviewed(self):
        # Regression: a reviews.yaml entry for a later attempt, left after the audit
        # folder was cleared, read as a verdict on the new attempt.
        save_reviews(self.reviews, {"room_001": Review(3, True, ())})
        _, _, _, vlm = self.review("--room", "1")
        self.assertEqual(vlm.review.call_count, 1)
        self.assertEqual(load_reviews(self.reviews)["room_001"].attempt, 1)

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


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_a_perfect_render_of_every_room_passes_the_gate(self):
        # Regression: room 95's marginal edges failed its own guide (agreement 0.27), so no
        # render of it could ever be promoted. Each room's guide, as the stitch, must pass.
        rooms = testkit.real_rooms()
        self.assertEqual(len(rooms), 91)
        for room in rooms:
            with self.subTest(room.key):
                indexed = source_tree.open_indexed(testkit.REAL_SRC, room)
                guide = room_geometry.build_guide(indexed)
                plan = room_geometry.plan_room(indexed)
                _, result, _ = a.finish_room(guide.full.copy(), guide, plan, indexed,
                                             a.DEFAULT_MATCH_STRENGTH)
                self.assertTrue(result.passed, result.issues)


if __name__ == "__main__":
    unittest.main()
