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

    def test_strength_interpolates_the_guide_statistics(self):
        raw_mean = cm.lab_stats(self.render)[0][0]
        guide_mean, guide_std = cm.lab_stats(self.guide)
        half = cm.lab_stats(cm.match(self.render, self.guide, 0.5))[0][0]
        self.assertAlmostEqual(half, (raw_mean + guide_mean[0]) / 2, delta=1.5,
                               msg="half strength lands between")
        om, os_ = cm.lab_stats(cm.match(self.render, self.guide, 1.0))
        for band in range(3):
            with self.subTest(band=band):
                self.assertAlmostEqual(om[band], guide_mean[band], delta=1.5,
                                       msg="full strength takes the guide statistics")
                self.assertAlmostEqual(os_[band], guide_std[band], delta=2.0,
                                       msg="full strength takes the guide statistics")

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
        # Regression: a "constant" band's float Lab std is ~1e-13, not exactly
        # 0, so the old `stds > 0` guard let the gain explode.
        out = cm.match(Image.new("RGB", (32, 16), (90, 90, 90)), self.guide, 1.0)
        self.assertEqual((out.size, out.mode), ((32, 16), "RGB"))
        out_l = cm.lab_stats(out)[0][0]
        guide_l = cm.lab_stats(self.guide)[0][0]
        self.assertAlmostEqual(out_l, guide_l, delta=1.0)

    def test_a_greyscale_render_stays_grey(self):
        # Regression: the same exploding gain turned a grey render's ~0 a*/b*
        # spread into full guide-chroma noise.
        rng = np.random.default_rng(1)
        grey = rng.integers(20, 235, (64, 96), dtype=np.uint8)
        render = Image.fromarray(np.stack([grey] * 3, axis=-1))
        out_stds = cm.lab_stats(cm.match(render, self.guide, 1.0))[1]
        for band, name in ((1, "a*"), (2, "b*")):
            with self.subTest(band=name):
                self.assertAlmostEqual(out_stds[band], 0.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
