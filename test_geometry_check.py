import json
import unittest

import numpy as np
from PIL import Image

import geometry_check as gc


def blocks(width, height, seed=0, size=8):
    rng = np.random.default_rng(seed)
    grid = rng.integers(0, 256, size=(-(-height // size), -(-width // size), 3), dtype=np.uint8)
    return Image.fromarray(np.kron(grid, np.ones((size, size, 1), np.uint8))[:height, :width])


def up(image):
    return image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST)


def shifted(image, dx):
    out = Image.new("RGB", image.size)
    out.paste(image, (dx, 0))
    return out


class PhaseShiftTests(unittest.TestCase):
    def test_measures_a_known_displacement(self):
        a = gc.luminance(blocks(96, 64))
        for dx, dy in ((2, 0), (0, 3), (-1, 0)):
            with self.subTest(dx=dx, dy=dy):
                sx, sy = gc.phase_shift(a, np.roll(np.roll(a, dy, axis=0), dx, axis=1))
                self.assertAlmostEqual(sx, dx, delta=0.25)
                self.assertAlmostEqual(sy, dy, delta=0.25)

    def test_identical_is_zero(self):
        a = gc.luminance(blocks(96, 64))
        self.assertEqual(gc.phase_shift(a, a), (0.0, 0.0))

    def test_flat_reads_as_zero(self):
        # Review Focus: a window of flat black (the labyrinth pieces) has no position.
        self.assertEqual(gc.phase_shift(np.zeros((64, 96)), gc.luminance(blocks(96, 64))),
                         (0.0, 0.0))


class EdgeAgreementTests(unittest.TestCase):
    def setUp(self):
        self.source = gc.luminance(blocks(96, 64, size=16))

    def test_identical(self):
        self.assertEqual(gc.edge_agreement(self.source, self.source), 1.0)

    def test_added_fine_texture_keeps_the_edges(self):
        rng = np.random.default_rng(1)
        render = self.source + rng.normal(0, 6, self.source.shape)
        self.assertGreaterEqual(gc.edge_agreement(self.source, render), 0.95)

    def test_a_removed_region_loses_its_edges(self):
        render = self.source.copy()
        render[:, :60] = render[:, :60].mean()
        self.assertLess(gc.edge_agreement(self.source, render), gc.MIN_EDGE_AGREEMENT)

    def test_no_source_edges(self):
        self.assertEqual(gc.edge_agreement(np.zeros((8, 8)), np.ones((8, 8))), 1.0)


class SeamRatioTests(unittest.TestCase):
    def test_a_hard_step_stands_out(self):
        rng = np.random.default_rng(2)
        arr = rng.normal(128, 4, (32, 256, 3))
        arr[:, 128:] += 60
        image = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        self.assertGreater(gc.seam_ratio(image, 128), gc.SEAM_WARN)

    def test_texture_without_a_step_does_not(self):
        self.assertLess(gc.seam_ratio(blocks(256, 32, seed=3, size=1), 128), gc.SEAM_WARN)

    def test_a_flat_image(self):
        self.assertEqual(gc.seam_ratio(Image.new("RGB", (64, 8)), 32), 0.0)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.source = blocks(128, 64, seed=4)

    def test_an_aligned_render_passes(self):
        result = gc.check(up(self.source), self.source, windows=[(0, 64), (64, 128)],
                          boundaries=[256])
        self.assertTrue(result.passed, result.issues)
        self.assertEqual((len(result.window_shifts), len(result.seam_ratios)), (2, 1))
        json.dumps(result.as_dict())

    def test_a_shifted_render_fails(self):
        result = gc.check(shifted(up(self.source), 8), self.source)
        self.assertFalse(result.passed)
        self.assertIn("the room is shifted +2.0", result.issues[0])

    def test_a_shift_inside_one_window_is_named(self):
        render = up(self.source)
        render.paste(shifted(render.crop((256, 0, 512, 256)), 8), (256, 0))
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


if __name__ == "__main__":
    unittest.main()
