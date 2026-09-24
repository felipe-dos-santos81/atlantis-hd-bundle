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


if __name__ == "__main__":
    unittest.main()
