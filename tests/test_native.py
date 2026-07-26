import unittest

from gtlv import Solver, click_w, slide_w, solve_slide


class NativePrimitivesTests(unittest.TestCase):
    def test_click_w_validates_arguments_and_returns_payload(self):
        with self.assertRaises(ValueError):
            click_w([], "gt", "challenge")
        value = click_w([(120.0, 80.0)], "gt", "challengezz")
        self.assertGreater(len(value), 256)
        self.assertTrue(all(char in "0123456789abcdef" for char in value[-256:]))

    def test_slide_w_and_bad_slide_image(self):
        value = slide_w(120, "a!!b!!c", "gt", "challengezz", [1, 2, 3, 4, 5], "0a")
        self.assertGreater(len(value), 256)
        with self.assertRaises(RuntimeError):
            solve_slide(b"bad", b"bad")

    def test_embedded_models_load(self):
        solver = Solver()
        with self.assertRaises(RuntimeError):
            solver.solve(b"not an image")


if __name__ == "__main__":
    unittest.main()
