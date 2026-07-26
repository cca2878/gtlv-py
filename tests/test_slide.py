import io
import unittest

import numpy as np
from PIL import Image

from gtlv.exceptions import UnsolvableImageError
from gtlv.slide import _encode_track, _find_gap, _make_track, _restore, solve


def _png(array):
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


class SlideTests(unittest.TestCase):
    def test_restore_produces_the_expected_canvas(self):
        source = np.zeros((160, 312, 3), dtype=np.uint8)
        source[:, :, 0] = np.arange(312, dtype=np.uint8)
        restored = _restore(_png(source))
        self.assertEqual(restored.shape, (160, 260, 3))

    def test_restore_rejects_undersized_backgrounds(self):
        with self.assertRaises(UnsolvableImageError):
            _restore(_png(np.zeros((160, 300, 3), dtype=np.uint8)))

    def test_restore_rejects_undecodable_bytes(self):
        with self.assertRaises(UnsolvableImageError):
            _restore(b"not an image")

    def test_finds_a_synthetic_gap(self):
        full = np.full((160, 260, 3), 200, dtype=np.uint8)
        bg = full.copy()
        bg[:, 130:138] = 10
        self.assertEqual(_find_gap(bg, full), 130)

    def test_identical_images_have_no_gap(self):
        full = np.full((160, 260, 3), 200, dtype=np.uint8)
        self.assertEqual(_find_gap(full, full.copy()), 0)

    def test_solve_rejects_undecodable_bytes(self):
        with self.assertRaises(UnsolvableImageError):
            solve(b"bad", b"bad")

    def test_track_advances_monotonically_to_the_target(self):
        track = _make_track(120)
        self.assertEqual(track[1], (0, 0, 0))
        xs = [point[0] for point in track[1:]]
        self.assertEqual(xs, sorted(xs))
        self.assertGreaterEqual(max(xs), 108)

    def test_encoded_track_has_three_segments(self):
        self.assertEqual(_encode_track(_make_track(120)).count("!!"), 2)

    def test_encoding_matches_the_reference_implementation(self):
        # 与 Go 参考实现在相同输入上的输出逐字符比对，含 $ 进位分支。
        self.assertEqual(
            _encode_track([(0, 0, 0), (5, 0, 12), (9, 0, 25), (9, 0, 40)]),
            ".--!!(((!!568",
        )
        self.assertEqual(
            _encode_track([(0, 0, 0), (1, 0, 5), (3, 0, 9), (70, 0, 300), (70, 0, 320)]),
            "$)*$)*!!st((!!.-$-LA",
        )


if __name__ == "__main__":
    unittest.main()
