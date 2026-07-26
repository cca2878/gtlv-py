"""GeeTest V3 local solvers and async orchestration.

:class:`Client` covers the whole flow. :class:`Solver` and :func:`solve_slide` are
for solving images you already hold. ``w`` generation lives in :mod:`gtlv.crypto`;
it is only meaningful inside the protocol flow, where the payload's timing has to
match when the answer is actually submitted.
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
except PackageNotFoundError:  # source tree without an install
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
