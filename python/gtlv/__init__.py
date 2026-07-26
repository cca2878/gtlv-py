"""极验 V3 的本地求解与异步编排。

:class:`Client` 覆盖完整流程；:class:`Solver` 与 :func:`solve_slide` 用于求解已持有的图像。
``w`` 的生成位于 :mod:`gtlv.crypto`，其载荷含与提交时刻绑定的时延锚点，须在协议流程中使用。
"""

from importlib.metadata import PackageNotFoundError, version

from .client import BILIBILI_REGISTER_URL, Challenge, Client, Validation
from .exceptions import (
    GtlvError,
    ProtocolError,
    SolverRequiredError,
    UnsolvableImageError,
    UnsupportedCaptchaTypeError,
    VerificationError,
)
from .slide import SlideResult
from .slide import solve as solve_slide
from .solver import ClickResult, Solver

try:
    __version__ = version("gtlv")
except PackageNotFoundError:  # 源码树中未安装
    __version__ = "0.0.0.dev0"

__all__ = [
    "BILIBILI_REGISTER_URL",
    "Challenge",
    "Client",
    "ClickResult",
    "GtlvError",
    "ProtocolError",
    "SlideResult",
    "Solver",
    "SolverRequiredError",
    "UnsolvableImageError",
    "UnsupportedCaptchaTypeError",
    "Validation",
    "VerificationError",
    "solve_slide",
]
