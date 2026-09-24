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
                self.assertAlmostEqual(om[band], gm[band], delta=2.5)
                self.assertAlmostEqual(os_[band], gs[band], delta=3.5)

    def test_half_strength_lands_between(self):
        raw, guide = cm.lab_stats(self.render)[0][0], cm.lab_stats(self.guide)[0][0]
        half = cm.lab_stats(cm.match(self.render, self.guide, 0.5))[0][0]
        self.assertAlmostEqual(half, (raw + guide) / 2, delta=4)

    def test_a_flat_render(self):
        out = cm.match(Image.new("RGB", (32, 16), (90, 90, 90)), self.guide, 1.0)
        self.assertEqual((out.size, out.mode), ((32, 16), "RGB"))


if __name__ == "__main__":
    unittest.main()
