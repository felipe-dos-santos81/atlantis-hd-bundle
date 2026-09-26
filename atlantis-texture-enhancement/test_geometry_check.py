import json
import operator
import unittest

import numpy as np
from PIL import Image

import geometry_check as gc
import testkit


def blocks(width, height, seed=0, size=8):
    rng = np.random.default_rng(seed)
    grid = rng.integers(0, 256, size=(-(-height // size), -(-width // size), 3), dtype=np.uint8)
    return Image.fromarray(np.kron(grid, np.ones((size, size, 1), np.uint8))[:height, :width])


def up(image):
    return image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST)


class PhaseShiftTests(unittest.TestCase):
    def test_measures_a_known_displacement(self):
        a = gc.luminance(blocks(96, 64))
        for dx, dy in ((0, 0), (2, 0), (0, 3), (-1, 0)):
            with self.subTest(dx=dx, dy=dy):
                rolled = np.roll(np.roll(a, dy, axis=0), dx, axis=1)
                if (dx, dy) == (0, 0):
                    self.assertEqual(gc.phase_shift(a, rolled), (0.0, 0.0))
                    continue
                sx, sy = gc.phase_shift(a, rolled)
                self.assertAlmostEqual(sx, dx, delta=0.25)
                self.assertAlmostEqual(sy, dy, delta=0.25)

    def test_flat_reads_as_zero(self):
        # Review Focus: a window of flat black (the labyrinth pieces) has no position.
        self.assertEqual(gc.phase_shift(np.zeros((64, 96)), gc.luminance(blocks(96, 64))),
                         (0.0, 0.0))


class EdgeAgreementTests(unittest.TestCase):
    def setUp(self):
        self.source = gc.luminance(blocks(96, 64, size=16))

    def test_edge_agreement(self):
        rng = np.random.default_rng(1)
        textured = self.source + rng.normal(0, 6, self.source.shape)
        removed = self.source.copy()
        removed[:, :60] = removed[:, :60].mean()
        cases = {
            "identical": (self.source, self.source, operator.eq, 1.0),
            "added fine texture keeps the edges": (self.source, textured, operator.ge, 0.95),
            "a removed region loses its edges": (self.source, removed, operator.lt,
                                                 gc.MIN_EDGE_AGREEMENT),
            "no source edges": (np.zeros((8, 8)), np.ones((8, 8)), operator.eq, 1.0),
        }
        for name, (source, render, op, expected) in cases.items():
            with self.subTest(name):
                agreement = gc.edge_agreement(source, render)
                self.assertTrue(op(agreement, expected),
                                f"{agreement} {op.__name__} {expected}")

    def test_a_render_edge_counts_down_to_the_render_threshold(self):
        # Regression: resampling weakened room 95's marginal sea edges under the one shared
        # threshold, so even its own guide failed. A step of d reads 4d on the Sobel.
        source = np.zeros((16, 16))
        source[:, 8:] = 30                                          # 120: a strong edge
        for step, kept in ((17, 1.0), (14, 0.0)):                   # 68 is kept, 56 is not
            with self.subTest(step=step):
                render = np.zeros((16, 16))
                render[:, 8:] = step
                self.assertEqual(gc.edge_agreement(source, render), kept)


class SeamRatioTests(unittest.TestCase):
    def test_seam_ratio(self):
        rng = np.random.default_rng(2)
        arr = rng.normal(128, 4, (32, 256, 3))
        arr[:, 128:] += 60
        stepped = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        cases = {
            "a hard step stands out": (stepped, 128, operator.gt, gc.SEAM_WARN),
            "texture without a step does not": (blocks(256, 32, seed=3, size=1), 128,
                                                 operator.lt, gc.SEAM_WARN),
            "a flat image": (Image.new("RGB", (64, 8)), 32, operator.eq, 0.0),
        }
        for name, (image, boundary, op, expected) in cases.items():
            with self.subTest(name):
                ratio = gc.seam_ratio(image, boundary)
                self.assertTrue(op(ratio, expected), f"{ratio} {op.__name__} {expected}")


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.source = blocks(128, 64, seed=4)

    def test_check_passes(self):
        with self.subTest("aligned render"):
            result = gc.check(up(self.source), self.source, windows=[(0, 64), (64, 128)],
                              boundaries=[256])
            self.assertTrue(result.passed, result.issues)
            self.assertEqual((len(result.window_shifts), len(result.seam_ratios)), (2, 1))
            json.dumps(result.as_dict())
        with self.subTest("a window too sparse to judge passes"):
            arr = np.asarray(self.source).copy()
            arr[:, :72] = 0                            # window 1 is black ...
            arr[8:16, 16:24] = 255                     # ... but for a square under MIN_WINDOW_EDGES
            source = Image.fromarray(arr)
            render = up(source)
            render.paste((0, 0, 0), (0, 0, 256, 256))  # ... that the render loses
            result = gc.check(render, source, windows=[(0, 64), (64, 128)])
            self.assertLess(np.count_nonzero(gc.sobel(gc.luminance(source)[:, :64])
                                             > gc.EDGE_THRESHOLD), gc.MIN_WINDOW_EDGES)
            self.assertTrue(result.passed, result.issues)
            self.assertEqual(result.window_agreements[0], 1.0)

    def test_check_flags_a_shift(self):
        with self.subTest("whole room"):
            result = gc.check(testkit.shift_right(up(self.source)), self.source)
            self.assertFalse(result.passed)
            self.assertIn("the room is shifted +2.0", result.issues[0])
        with self.subTest("one window"):
            render = up(self.source)
            render.paste(testkit.shift_right(render.crop((256, 0, 512, 256))), (256, 0))
            result = gc.check(render, self.source, windows=[(0, 64), (64, 128)])
            self.assertTrue(any("window 2 is shifted" in issue for issue in result.issues),
                            result.issues)
            self.assertFalse(any("window 1" in issue for issue in result.issues))

    def test_a_boundary_on_a_source_edge_is_not_a_seam(self):
        arr = np.full((64, 128, 3), 40, np.uint8)
        arr[:, 64:] = 200                           # the source's own edge at column 64
        source = Image.fromarray(arr)
        alone = gc.check(up(source), source, boundaries=[256])
        against = gc.check(up(source), source, boundaries=[256], reference=up(source))
        self.assertGreater(alone.seam_ratios[0], gc.SEAM_WARN)
        self.assertLessEqual(against.seam_ratios[0], 1.0)

    def test_a_flat_window_passes(self):
        # Review Focus: the labyrinth pieces are half flat black.
        arr = np.asarray(self.source).copy()
        arr[:, :64] = 0
        source = Image.fromarray(arr)
        result = gc.check(up(source), source, windows=[(0, 64), (64, 128)])
        self.assertTrue(result.passed, result.issues)
        self.assertEqual(result.window_shifts[0], (0.0, 0.0))
        self.assertEqual(result.window_agreements[0], 1.0)

    def test_one_ruined_window_fails_the_room(self):
        # Regression: spec 7, "every window passes"; a window painted to mush left the
        # whole-room agreement above the bar.
        source = blocks(512, 64, seed=5)
        windows = [(x, x + 64) for x in range(0, 512, 64)]
        render = up(source)
        render.paste((128, 128, 128), (448 * 4, 0, 512 * 4, 256))
        result = gc.check(render, source, windows=windows)
        self.assertGreaterEqual(result.edge_agreement, gc.MIN_EDGE_AGREEMENT)
        self.assertEqual(len(result.window_agreements), 8)
        self.assertEqual(len(result.issues), 1, result.issues)
        self.assertRegex(result.issues[0],
                         r"^geometry: window 8 edge agreement 0\.\d\d, needs 0\.80$")
        self.assertEqual(result.as_dict()["window_agreements"], list(result.window_agreements))


if __name__ == "__main__":
    unittest.main()
