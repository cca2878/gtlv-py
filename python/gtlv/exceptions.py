"""Typed errors raised by the async GeeTest V3 client."""


class GtlvError(Exception):
    """Base class for gtlv client errors."""


class ProtocolError(GtlvError):
    """The remote endpoint returned malformed or incomplete protocol data."""


class UnsolvableImageError(GtlvError):
    """本地求解无法处理该图像；更换图像后重试可能成功。"""


class VerificationError(GtlvError):
    """GeeTest rejected a submitted answer; replacing the image may succeed."""

    def __init__(self, result: str = "", message: str = "") -> None:
        self.result = result
        self.message = message
        details = []
        if result:
            details.append("result={!r}".format(result))
        if message:
            details.append("message={!r}".format(message))
        suffix = " ({})".format(", ".join(details)) if details else " (empty validate)"
        super().__init__("verification failed{}".format(suffix))


class UnsupportedCaptchaTypeError(GtlvError):
    """GeeTest selected a captcha type other than click or slide."""

    def __init__(self, captcha_type: str) -> None:
        self.captcha_type = captcha_type
        super().__init__(
            "unsupported captcha type {!r} (want click or slide)".format(captcha_type)
        )


class SolverRequiredError(GtlvError):
    """A click captcha was selected but the client has no click solver."""
