"""GeeTest V3 local solvers and async orchestration."""

from importlib.metadata import PackageNotFoundError, version

from ._native import ClickResult, SlideResult, Solver, click_w, slide_w, solve_slide
from .client import BILIBILI_REGISTER_URL, Challenge, Client, Validation
from .exceptions import (
    GtlvError,
    ProtocolError,
    SolverRequiredError,
    UnsupportedCaptchaTypeError,
    VerificationError,
)

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
    "UnsupportedCaptchaTypeError",
    "Validation",
    "VerificationError",
    "click_w",
    "slide_w",
    "solve_slide",
]
