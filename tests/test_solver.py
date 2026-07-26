import unittest

from gtlv import Solver
from gtlv.exceptions import UnsolvableImageError


class EmbeddedModelTests(unittest.TestCase):
    def test_embedded_models_load_and_reject_non_images(self):
        solver = Solver()
        with self.assertRaises(UnsolvableImageError):
            solver.solve(b"not an image")


if __name__ == "__main__":
    unittest.main()
