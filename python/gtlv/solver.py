"""点选求解：推理与指派。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from . import matching
from ._native import Detector
from .exceptions import UnsolvableImageError

__all__ = ["ClickResult", "Solver"]

# 提示词字数的合法范围。
MIN_PROMPT_CHARS = 2
MAX_PROMPT_CHARS = 4


@dataclass(frozen=True)
class ClickResult:
    """按提交顺序排列的点击坐标。"""

    coords: List[Tuple[float, float]]
    confidences: List[float]
    k: int
    """提示词字数。"""
    m: int
    """答案格数量，含干扰字，可大于 k。"""


class Solver:
    """点选求解器：进程内构造一次、反复调用 :meth:`solve`。

    构造需加载模型，耗时数百毫秒。:meth:`solve` 可从多个线程调用，底层推理以互斥串行化。
    """

    def __init__(self) -> None:
        self._detector = Detector()

    def solve(self, image: bytes, conf_threshold: float = 0.5) -> ClickResult:
        """求解一张点选验证码图（PNG/JPEG 字节）。

        图像无法求解时抛出 :class:`~gtlv.exceptions.UnsolvableImageError`，
        调用方应更换图像重试。
        """

        try:
            result = self._detector.detect(image, conf_threshold)
        except RuntimeError as exc:  # 图像无法解码或推理失败
            raise UnsolvableImageError(str(exc)) from exc

        m = len(result.detections)
        k = len(result.prompt_features)
        if result.prompt_box is None:
            raise UnsolvableImageError("no prompt box detected")
        if m == 0:
            raise UnsolvableImageError("no answer boxes detected")
        if not MIN_PROMPT_CHARS <= k <= MAX_PROMPT_CHARS:
            raise UnsolvableImageError("prompt char count out of range: k={}".format(k))
        if m < k:
            raise UnsolvableImageError(
                "detection missed targets: {} tiles < {} targets".format(m, k)
            )
        if len(result.answer_features) != m:
            raise UnsolvableImageError(
                "feature count mismatch: {} features for {} detections".format(
                    len(result.answer_features), m
                )
            )

        matches = matching.assign(result.prompt_features, result.answer_features)
        if not matches:
            raise UnsolvableImageError("assignment produced no matches")

        coords: List[Tuple[float, float]] = []
        confidences: List[float] = []
        for match in matches:
            x_min, y_min, x_max, y_max = result.detections[match.answer_index].bbox
            coords.append(((x_min + x_max) / 2, (y_min + y_max) / 2))
            confidences.append(1.0 / (1.0 + match.distance))

        return ClickResult(coords=coords, confidences=confidences, k=k, m=m)
