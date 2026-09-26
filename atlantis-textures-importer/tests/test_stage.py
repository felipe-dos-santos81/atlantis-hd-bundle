import json
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import testkit
from importer.stage import sha256_file, source_id, stage


class StageTests(unittest.TestCase):
    def test_stage_writes_backgrounds_index_maps_and_manifest(self):
        with TemporaryDirectory() as tmp:
            rooms = testkit.make_rooms()
            ai = testkit.write_ai(Path(tmp) / "ai", rooms)
            hd = Path(tmp) / "staged/hd"
            manifest = stage(rooms, ai, hd, "abc")

            self.assertEqual(sorted(p.name for p in hd.iterdir()),
                             ["manifest.json", "room_001.idx", "room_001.png", "room_002.idx", "room_002.png"])
            self.assertEqual((hd / "room_001.png").read_bytes(), (ai / "room_001.png").read_bytes())
            idx = (hd / "room_001.idx").read_bytes()
            self.assertEqual(idx[:8], b"ATLIDX01")
            self.assertEqual(struct.unpack("<HH", idx[8:12]), (3, 2))
            self.assertEqual(idx[12:780], rooms[0].palette)
            self.assertEqual(idx[780:], rooms[0].pixels)
            self.assertEqual(json.loads((hd / "manifest.json").read_text()), manifest)
            self.assertEqual(manifest["source"], "abc")
            self.assertEqual(manifest["rooms"]["room_002"],
                             {"width": 2, "height": 2,
                              "png_sha256": sha256_file(hd / "room_002.png"),
                              "idx_sha256": sha256_file(hd / "room_002.idx")})

    def test_source_id_follows_the_engine_sources(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "patches").mkdir()
            (root / "engine/scumm").mkdir(parents=True)
            (root / "patches/scumm-hd.patch").write_text("a")
            (root / "engine/scumm/hd_compose.cpp").write_text("b")
            first = source_id(root)
            self.assertEqual(len(first), 16)
            (root / "engine/scumm/hd_compose.cpp").write_text("c")
            self.assertNotEqual(source_id(root), first)
