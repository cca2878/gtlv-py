import math
import unittest

from gtlv.matching import assign, euclidean


def vec(x):
    return [x, 0.0]


class MatchingTests(unittest.TestCase):
    def test_picks_nearest_and_skips_distractor(self):
        prompts = [vec(0.0), vec(10.0)]
        answers = [vec(9.9), vec(5.0), vec(0.1)]  # index 1 is the distractor
        matches = assign(prompts, answers)
        self.assertEqual([m.answer_index for m in matches], [2, 0])

    def test_assignment_is_injective_where_greedy_would_collide(self):
        matches = assign([vec(0.0), vec(0.1)], [vec(0.05), vec(5.0)])
        self.assertNotEqual(matches[0].answer_index, matches[1].answer_index)

    def test_returns_empty_when_fewer_tiles_than_prompts(self):
        self.assertEqual(assign([vec(0.0), vec(1.0)], [vec(0.0)]), [])

    def test_mismatched_dimensions_are_unmatchable(self):
        self.assertEqual(euclidean([1.0, 2.0], [1.0]), math.inf)

    def test_distance_accumulates_at_double_precision(self):
        # 512 个各自微小的差值，单精度累加会把结果吞掉；双精度须保留下来。
        a = [0.0] * 512
        b = [1e-4] * 512
        self.assertAlmostEqual(euclidean(a, b), math.sqrt(512 * 1e-8), places=12)

    def test_order_follows_prompt_position(self):
        # 返回顺序即点击提交顺序，与所选格子的编号无关。
        prompts = [vec(10.0), vec(0.0)]
        answers = [vec(0.0), vec(10.0)]
        self.assertEqual([m.answer_index for m in assign(prompts, answers)], [1, 0])


if __name__ == "__main__":
    unittest.main()
