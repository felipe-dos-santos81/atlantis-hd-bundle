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

    def test_loads_background_rooms_by_number_and_ignores_other_roles(self):
        source = source_tree.load(self.src)
        self.assertEqual([r.number for r in source.rooms], [1, 2, 3, 4])
        room = source.rooms[2]
        self.assertEqual((room.key, room.out_name), ("room_003", "room_003.png"))
        self.assertEqual(((room.width, room.height), room.out_size), ((1152, 144), (4608, 576)))
        self.assertEqual(room.rel, Path("indexed/rooms/room_003.png"))
        testkit.rewrite_manifest(self.src, lambda assets: assets.append(
            {"room": 9, "role": "object", "file": "nope.png"}))
        self.assertEqual(len(source_tree.load(self.src).rooms), 4, msg="ignores other roles")

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
            "no rooms": (lambda assets: assets.clear(), "no background rooms"),
        }
        for name, (change, message) in cases.items():
            with self.subTest(name):
                src = testkit.make_source(self.tmp / name)
                testkit.rewrite_manifest(src, change)
                with self.assertRaisesRegex(SourceError, message):
                    source_tree.load(src)

    def test_refuses_a_bad_image_file(self):
        with self.subTest("wrong mode"):
            Image.new("RGB", (320, 144)).save(self.src / "indexed/rooms/room_001.png")
            with self.assertRaisesRegex(SourceError, "mode RGB, expected P"):
                source_tree.load(self.src)
        with self.subTest("unreadable"):
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
