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


if __name__ == "__main__":
    unittest.main()
