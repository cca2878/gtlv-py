"""GeeTest V3 local solvers and optional async orchestration."""

from ._native import ClickResult, SlideResult, Solver, click_w, slide_w, solve_slide
from .client import BILIBILI_REGISTER_URL, Challenge, Client, V3Client, Validation
from .exceptions import (
    GtlvError,
    ProtocolError,
    SolverRequiredError,
    UnsupportedCaptchaTypeError,
    VerificationError,
)

__version__ = "0.1.0"

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
    "V3Client",
    "Validation",
    "VerificationError",
    "click_w",
    "slide_w",
    "solve_slide",
]
