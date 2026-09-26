import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

import testkit
from importer.rooms import load_native_rooms, validate


def remove_room_2(ai, rooms):
    (ai / "room_002.png").unlink()
    return rooms


def shrink_room_1(ai, rooms):
    Image.new("RGB", (8, 8)).save(ai / "room_001.png")
    return rooms


def room_1_with_alpha(ai, rooms):
    Image.new("RGBA", (12, 8)).save(ai / "room_001.png")
    return rooms


def room_1_with_anomalies(ai, rooms):
    return [replace(rooms[0], anomalies=2), rooms[1]]


class ValidateTests(unittest.TestCase):
    def test_a_complete_folder_is_ready(self):
        with TemporaryDirectory() as tmp:
            rooms = testkit.make_rooms()
            ai = testkit.write_ai(Path(tmp) / "ai", rooms)
            (ai / "room_999.png").write_bytes(b"not a game room")  # extra files are ignored
            (ai / ".quality").mkdir()
            self.assertEqual(validate(rooms, ai), [])

    def test_each_problem_is_reported(self):
        cases = [
            ("missing", remove_room_2, ["room_002.png: missing"]),
            ("wrong size", shrink_room_1, ["room_001.png: 8x8, expected 12x8"]),
            ("not RGB", room_1_with_alpha, ["room_001.png: mode RGBA, expected RGB"]),
            ("decoder anomalies", room_1_with_anomalies,
             ["room_001: the decoder reported 2 anomalies; its index map would be wrong"]),
        ]
        for name, mutate, expected in cases:
            with self.subTest(name), TemporaryDirectory() as tmp:
                rooms = testkit.make_rooms()
                ai = testkit.write_ai(Path(tmp) / "ai", rooms)
                self.assertEqual(validate(mutate(ai, rooms), ai), expected)

    def test_all_problems_are_reported_together(self):
        with TemporaryDirectory() as tmp:
            rooms = testkit.make_rooms()
            ai = testkit.write_ai(Path(tmp) / "ai", rooms)
            rooms = room_1_with_anomalies(ai, shrink_room_1(ai, remove_room_2(ai, rooms)))
            self.assertEqual(len(validate(rooms, ai)), 3)


@unittest.skipUnless((testkit.REAL_GAME / "ATLANTIS.001").is_file() and testkit.REAL_AI.is_dir(),
                     "needs the GOG game and the AI folder")
class RealCorpusTests(unittest.TestCase):
    def test_all_96_rooms_are_ready(self):
        rooms = load_native_rooms(testkit.REAL_GAME)
        self.assertEqual(len(rooms), 96)
        self.assertEqual(validate(rooms, testkit.REAL_AI), [])
