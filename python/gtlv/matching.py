"""将提示词各字指派到答案格。

实现 gtlv-core 的 ``docs/matching.md`` 所定契约。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence

__all__ = ["Match", "assign", "euclidean"]


@dataclass(frozen=True)
class Match:
    """一条指派。其在返回列表中的位置即点击顺序。"""

    answer_index: int
    distance: float


def euclidean(a: Sequence[float], b: Sequence[float]) -> float:
    """欧氏距离；维度不一致时返回无穷大。

    契约要求按双精度累加：512 个平方项若以单精度累加，可能选中不同的答案格。
    Python 的 float 即双精度。
    """

    if len(a) != len(b):
        return math.inf
    return math.sqrt(sum((x - y) * (x - y) for x, y in zip(a, b)))


def assign(
    prompt_features: Sequence[Sequence[float]],
    answer_features: Sequence[Sequence[float]],
) -> List[Match]:
    """为每个提示字指派一个互不相同的答案格，使总距离最小。

    指派是单射而非双射：剩余的答案格为干扰字，不得点击。提示字至多 4 个、答案格至多 8 个，
    故采用穷举并以当前最优代价剪枝。

    返回的匹配按提示字位置排序，即提交顺序；答案格少于提示字时返回空列表。
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
