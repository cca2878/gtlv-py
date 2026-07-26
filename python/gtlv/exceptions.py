"""异步极验 V3 客户端抛出的类型化异常。"""


class GtlvError(Exception):
    """gtlv 客户端异常的基类。"""


class ProtocolError(GtlvError):
    """远端返回的协议数据格式错误或字段缺失。"""


class UnsolvableImageError(GtlvError):
    """本地求解无法处理该图像；更换图像后重试可能成功。"""


class VerificationError(GtlvError):
    """极验拒绝了提交的答案；更换图像后重试可能成功。"""

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
    """极验下发了点选与滑动之外的验证码类型。"""

    def __init__(self, captcha_type: str) -> None:
        self.captcha_type = captcha_type
        super().__init__(
            "unsupported captcha type {!r} (want click or slide)".format(captcha_type)
        )


class SolverRequiredError(GtlvError):
    """下发了点选验证码，但客户端未配置点选求解器。"""
