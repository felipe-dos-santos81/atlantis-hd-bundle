import unittest

import numpy as np
from PIL import Image

import colour_match as cm


class MatchTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.guide = Image.fromarray(rng.integers(60, 200, (64, 96, 3), dtype=np.uint8))
        render = rng.integers(0, 120, (64, 96, 3))
        render[..., 0] += 100                           # a red cast
        self.render = Image.fromarray(render.astype(np.uint8))

    def test_strength_zero_keeps_the_raw_pixels(self):
        self.assertEqual(cm.match(self.render, self.guide, 0).tobytes(), self.render.tobytes())

    def test_full_strength_takes_the_guide_statistics(self):
        (gm, gs), (om, os_) = cm.lab_stats(self.guide), cm.lab_stats(
            cm.match(self.render, self.guide, 1.0))
        for band in range(3):
            with self.subTest(band=band):
                self.assertAlmostEqual(om[band], gm[band], delta=1.5)
                self.assertAlmostEqual(os_[band], gs[band], delta=2.0)

    def test_half_strength_lands_between(self):
        raw, guide = cm.lab_stats(self.render)[0][0], cm.lab_stats(self.guide)[0][0]
        half = cm.lab_stats(cm.match(self.render, self.guide, 0.5))[0][0]
        self.assertAlmostEqual(half, (raw + guide) / 2, delta=1.5)

    def test_matching_statistics_leave_saturated_colours_alone(self):
        # Regression: Pillow's 8-bit Lab round trip moved (0, 250, 210) to (38, 250, 209).
        rng = np.random.default_rng(3)
        colours = np.array([(0, 250, 210), (255, 0, 0), (0, 0, 255), (250, 0, 250),
                            (0, 255, 0), (255, 220, 0), (10, 10, 10), (240, 240, 240)], np.uint8)
        render = colours[rng.integers(0, len(colours), (48, 64))]
        guide = Image.fromarray(render[::-1, ::-1].copy())     # the same pixels and statistics
        out = np.asarray(cm.match(Image.fromarray(render), guide, 1.0), dtype=int)
        self.assertLessEqual(np.abs(out - render.astype(int)).max(), 1)

    def test_a_flat_render(self):
        out = cm.match(Image.new("RGB", (32, 16), (90, 90, 90)), self.guide, 1.0)
        self.assertEqual((out.size, out.mode), ((32, 16), "RGB"))


if __name__ == "__main__":
    unittest.main()
