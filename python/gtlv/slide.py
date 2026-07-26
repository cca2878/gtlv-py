"""Slide captcha solving: background restore, gap detection, track generation.

GeeTest serves the slide background as 52 shuffled slices. Restoring it and
locating the gap are array operations, so they run through numpy rather than
per-pixel Python loops.
"""

from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np
from PIL import Image, UnidentifiedImageError

from .exceptions import UnsolvableImageError

__all__ = ["SlideResult", "solve"]

# 切片在原图中的排列顺序。索引为还原后的位置，值为其在乱序图中的位置。
_OFFSETS = (
    39, 38, 48, 49, 41, 40, 46, 47, 35, 34, 50, 51, 33, 32, 28, 29, 27, 26,
    36, 37, 31, 30, 44, 45, 43, 42, 12, 13, 23, 22, 14, 15, 21, 20, 8, 9,
    25, 24, 6, 7, 3, 2, 0, 1, 11, 10, 4, 5, 19, 18, 16, 17,
)
_SLICE_WIDTH = 10
_SLICE_HEIGHT = 80
_SOURCE_STRIDE = 12
_RESTORED_WIDTH = 260
_RESTORED_HEIGHT = 160
# 单像素通道差之和低于该值视为噪声，不计入缺口判定。
_NOISE_FLOOR = 50
# 缺口不会出现在最左或最右的边缘区域。
_EDGE_MARGIN = 40


@dataclass(frozen=True)
class SlideResult:
    distance: int
    """缺口相对滑块起点的水平位移，还原后的 260px 坐标系。"""
    encrypted_track: str
    """极验编码后的拟人滑动轨迹。"""


def solve(bg: bytes, fullbg: bytes) -> SlideResult:
    """由带缺口背景与完整背景求解滑动距离，并生成轨迹。

    图像无法解码、尺寸不足或未能定位缺口时，抛出
    :class:`~gtlv.exceptions.UnsolvableImageError`，调用方应更换图像重试。
    """

    restored_bg = _restore(bg)
    restored_fullbg = _restore(fullbg)
    distance = _find_gap(restored_bg, restored_fullbg)
    if distance <= 0:
        raise UnsolvableImageError("gap not found (distance={})".format(distance))
    return SlideResult(distance=distance, encrypted_track=_encode_track(_make_track(distance)))


def _restore(data: bytes) -> np.ndarray:
    """把乱序切片重排成完整背景，返回 RGB 数组。"""

    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsolvableImageError("cannot decode background image") from exc
    source = np.asarray(image)
    height, width = source.shape[:2]
    if width < 310 or height < _RESTORED_HEIGHT:
        raise UnsolvableImageError(
            "background too small: {}x{} (need at least 310x160)".format(width, height)
        )

    restored = np.zeros((_RESTORED_HEIGHT, _RESTORED_WIDTH, 3), dtype=np.uint8)
    for index, offset in enumerate(_OFFSETS):
        source_x = (offset % 26) * _SOURCE_STRIDE
        source_y = _SLICE_HEIGHT if offset > 25 else 0
        target_x = (index % 26) * _SLICE_WIDTH
        target_y = _SLICE_HEIGHT if index > 25 else 0
        restored[target_y : target_y + _SLICE_HEIGHT, target_x : target_x + _SLICE_WIDTH] = source[
            source_y : source_y + _SLICE_HEIGHT, source_x : source_x + _SLICE_WIDTH
        ]
    return restored


def _find_gap(bg: np.ndarray, fullbg: np.ndarray) -> int:
    """返回差异最大的列，即缺口的水平位置。"""

    height = min(bg.shape[0], fullbg.shape[0])
    width = min(bg.shape[1], fullbg.shape[1])
    if width <= 2 * _EDGE_MARGIN or height == 0:
        return 0

    difference = np.abs(bg[:height, :width].astype(np.int32) - fullbg[:height, :width].astype(np.int32))
    per_pixel = difference.sum(axis=2)
    per_pixel[per_pixel <= _NOISE_FLOOR] = 0
    per_column = per_pixel.sum(axis=0)

    window = per_column[_EDGE_MARGIN : width - _EDGE_MARGIN]
    if not window.size or window.max() == 0:
        return 0
    # argmax 取首个最大值，与逐列严格大于比较的行为一致。
    return int(window.argmax()) + _EDGE_MARGIN


def _make_track(distance: int) -> List[Tuple[int, int, int]]:
    """生成拟人滑动轨迹，元素为 (x, y, 时间)。"""

    track: List[Tuple[int, int, int]] = [
        (random.randint(-50, -10), random.randint(-50, -10), 0),
        (0, 0, 0),
    ]
    count = 30 + distance // 2
    timestamp = random.randint(50, 100)
    last_x = 0
    for index in range(count):
        progress = index / count
        x = int(math.floor((1.0 - 2.0 ** (-10.0 * progress)) * distance + 0.5))
        timestamp += random.randint(10, 20)
        if x == last_x:
            continue
        track.append((x, 0, timestamp))
        last_x = x
    if track:
        track.append(track[-1])
    return track


_TRACK_ALPHABET = "()*,-./0123456789:?@ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqr"
# 常见的小位移组合各有单字符表示，省去逐个编码。
_SHORTHAND = {
    (1, 0): "s", (2, 0): "t", (1, -1): "u", (1, 1): "v", (0, 1): "w",
    (0, -1): "x", (3, 0): "y", (2, -1): "z", (2, 1): "~",
}


def _encode_value(value: int) -> str:
    base = len(_TRACK_ALPHABET)
    magnitude = abs(value)
    quotient = min(magnitude // base, base - 1)
    out = "!" if value < 0 else ""
    if quotient > 0:
        out += "$" + _TRACK_ALPHABET[quotient]
    return out + _TRACK_ALPHABET[magnitude % base]


def _encode_track(track: Sequence[Tuple[int, int, int]]) -> str:
    """把轨迹编码成极验的三段式字符串。"""

    if len(track) < 2:
        return ""

    steps: List[Tuple[int, int, int]] = []
    carried_time = 0
    for previous, current in zip(track, track[1:]):
        dx = current[0] - previous[0]
        dy = current[1] - previous[1]
        dt = current[2] - previous[2]
        if dx == 0 and dy == 0 and dt == 0:
            continue
        if dx == 0 and dy == 0:
            carried_time += dt
        else:
            steps.append((dx, dy, dt + carried_time))
            carried_time = 0
    if carried_time and steps:
        last_dx, last_dy, _ = steps[-1]
        steps.append((last_dx, last_dy, carried_time))

    horizontal: List[str] = []
    vertical: List[str] = []
    timing: List[str] = []
    for dx, dy, dt in steps:
        shorthand = _SHORTHAND.get((dx, dy))
        if shorthand is not None:
            vertical.append(shorthand)
        else:
            horizontal.append(_encode_value(dx))
            vertical.append(_encode_value(dy))
        timing.append(_encode_value(dt))

    return "{}!!{}!!{}".format("".join(horizontal), "".join(vertical), "".join(timing))
