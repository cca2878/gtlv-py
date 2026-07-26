import io
import unittest

from PIL import Image

from gtlv.exceptions import UnsolvableImageError
from gtlv.slide import _encode_track, _find_gap, _make_track, _restore, solve


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class SlideTests(unittest.TestCase):
    def test_restore_produces_the_expected_canvas(self):
        source = Image.new("RGB", (312, 160))
        for x in range(312):
            for y in range(160):
                source.putpixel((x, y), (x % 256, 0, 0))
        self.assertEqual(_restore(_png(source)).size, (260, 160))

    def test_restore_rejects_undersized_backgrounds(self):
        with self.assertRaises(UnsolvableImageError):
            _restore(_png(Image.new("RGB", (300, 160))))

    def test_restore_rejects_undecodable_bytes(self):
        with self.assertRaises(UnsolvableImageError):
            _restore(b"not an image")

    def test_finds_a_synthetic_gap(self):
        full = Image.new("RGB", (260, 160), (200, 200, 200))
        bg = full.copy()
        bg.paste(Image.new("RGB", (8, 160), (10, 10, 10)), (130, 0))
        self.assertEqual(_find_gap(bg, full), 130)

    def test_identical_images_have_no_gap(self):
        full = Image.new("RGB", (260, 160), (200, 200, 200))
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
