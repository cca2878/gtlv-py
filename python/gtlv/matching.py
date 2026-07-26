"""Assign prompt glyphs to answer tiles.

Implements the contract in gtlv-core's ``docs/matching.md``. The core returns
features; turning them into a click order is pure arithmetic and belongs here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence

__all__ = ["Match", "assign", "euclidean"]


@dataclass(frozen=True)
class Match:
    """One assignment. The position in the returned list is the click order."""

    answer_index: int
    distance: float


def euclidean(a: Sequence[float], b: Sequence[float]) -> float:
    """Euclidean distance, or infinity for mismatched dimensions.

    Python floats are doubles, which the contract requires: accumulating the
    512 squared terms at single precision can select a different tile.
    """

    if len(a) != len(b):
        return math.inf
    return math.sqrt(sum((x - y) * (x - y) for x, y in zip(a, b)))


def assign(
    prompt_features: Sequence[Sequence[float]],
    answer_features: Sequence[Sequence[float]],
) -> List[Match]:
    """Assign each prompt glyph a distinct tile, minimising total distance.

    The assignment is injective rather than bijective: the tiles left over are
    distractors and must not be clicked. With at most 4 prompts and 8 tiles an
    exhaustive search with best-cost pruning is well under a millisecond.

    Returns matches ordered by prompt position, which is the submission order,
    or an empty list when there are fewer tiles than prompts.
    """

    k = len(prompt_features)
    m = len(answer_features)
    if k == 0 or m < k:
        return []

    cost = [[euclidean(prompt, answer) for answer in answer_features] for prompt in prompt_features]

    best = math.inf
    best_columns = [0] * k
    used = [False] * m
    current = [0] * k

    def search(row: int, accumulated: float) -> None:
        nonlocal best
        if accumulated >= best:
            return
        if row == k:
            best = accumulated
            best_columns[:] = current
            return
        for column in range(m):
            if used[column]:
                continue
            used[column] = True
            current[row] = column
            search(row + 1, accumulated + cost[row][column])
            used[column] = False

    search(0, 0.0)

    return [Match(answer_index=best_columns[row], distance=cost[row][best_columns[row]]) for row in range(k)]
