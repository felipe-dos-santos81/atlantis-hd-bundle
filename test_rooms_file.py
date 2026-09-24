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

    def test_load_rooms_normalizes_and_defaults_captions(self):
        with self.subTest("round trip normalizes captions"):
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
        with self.subTest("missing or null caption is blank"):
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
        with self.subTest("missing file"):
            with self.assertRaisesRegex(RoomsFileError, "file not found"):
                rf.load_rooms(self.path.parent / "nope.yaml")

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

    def test_round_trip_and_file_handling(self):
        with self.subTest("missing file"):
            self.assertEqual(rf.load_reviews(self.path, optional=True), {})
            with self.assertRaisesRegex(RoomsFileError, "file not found"):
                rf.load_reviews(self.path)
        with self.subTest("round trip"):
            reviews = {"room_058": Review(2, False, ("geometry: window 2 is shifted +1.3,+0.0 px",),
                                          "geometry"),
                       "room_001": Review(1, True, ())}
            rf.save_reviews(self.path, reviews)
            self.assertEqual(rf.load_reviews(self.path), reviews)
        with self.subTest("source defaults to review"):
            self.path.write_text("room_001:\n  attempt: 1\n  accepted: true\n  issues: []\n")
            self.assertEqual(rf.load_reviews(self.path)["room_001"].source, "review")

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
            "field": ("attempt: 1\n  accepted: true\n  issues: []\n  sorce: review",
                      r"room_001: unknown field\(s\) sorce"),
        }
        for name, (body, message) in cases.items():
            with self.subTest(name):
                self.path.write_text("room_001:\n  " + body + "\n")
                with self.assertRaisesRegex(RoomsFileError, message):
                    rf.load_reviews(self.path)


if __name__ == "__main__":
    unittest.main()
