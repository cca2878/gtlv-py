"""Async GeeTest V3 orchestration.

Networking deliberately lives in Python. The Rust extension only performs local
inference, slide image processing, and ``w`` generation.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Literal, Mapping, Optional, Sequence
from urllib.parse import urljoin

from ._http import HttpClient
from ._native import Solver, click_w, slide_w, solve_slide
from .exceptions import (
    ProtocolError,
    SolverRequiredError,
    UnsupportedCaptchaTypeError,
    VerificationError,
)

DEFAULT_GET_BASE_URL = "https://api.geetest.com"
DEFAULT_VISIT_BASE_URL = "http://api.geevisit.com"
BILIBILI_REGISTER_URL = (
    "https://passport.bilibili.com/x/passport-login/captcha?source=main_web"
)

_DEFAULT_SOLVER = object()


@dataclass(frozen=True)
class Challenge:
    """A GeeTest challenge issued by a business registration endpoint."""

    gt: str
    challenge: str

    def __iter__(self) -> Iterator[str]:
        """Allow ``gt, challenge = await client.fetch_challenge(...)``."""

        yield self.gt
        yield self.challenge


@dataclass(frozen=True)
class Validation:
    """A solved challenge ready to submit to the calling business."""

    gt: str
    challenge: str
    validate: str
    captcha_type: Literal["click", "slide"]

    @property
    def seccode(self) -> str:
        """GeeTest V3 seccode used by Bilibili-compatible login APIs."""

        return self.validate + "|jordan"

    def as_dict(self) -> Dict[str, str]:
        """Return the common business-submission fields."""

        return {
            "challenge": self.challenge,
            "validate": self.validate,
            "seccode": self.seccode,
        }


class _RetryableSolveError(Exception):
    pass


class Client:
    """Reusable async GeeTest client supporting click and slide challenges.

    ``http_client`` must expose an async ``get(url, params=...)`` method returning a
    response with ``raise_for_status``/``text``/``content``/``json``. Omit it to use
    the bundled stdlib client — the wheel has no third-party Python dependencies —
    or inject httpx/aiohttp if you want pooling.

    Omit ``click_solver`` to lazily create and cache the bundled local solver when
    a click challenge is first encountered. Pass ``None`` to explicitly disable
    click solving, or inject a compatible solver for tests and custom runtimes.
    """

    def __init__(
        self,
        *,
        click_solver: Any = _DEFAULT_SOLVER,
        http_client: Any = None,
        get_base_url: str = DEFAULT_GET_BASE_URL,
        visit_base_url: str = DEFAULT_VISIT_BASE_URL,
        max_attempts: int = 1,
        verify_delay: float = 2.0,
        timeout: float = 15.0,
    ) -> None:
        self._click_solver: Optional[Any] = (
            None if click_solver is _DEFAULT_SOLVER else click_solver
        )
        self._lazy_click_solver = click_solver is _DEFAULT_SOLVER
        self._solver_lock = asyncio.Lock()
        self.get_base_url = get_base_url.rstrip("/")
        self.visit_base_url = visit_base_url.rstrip("/")
        self.max_attempts = max(1, int(max_attempts))
        self.verify_delay = max(0.0, float(verify_delay))
        self._owns_http_client = http_client is None
        if http_client is None:
            http_client = HttpClient(timeout=timeout)
        self._http = http_client

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the internally-created HTTP client, if any."""

        if self._owns_http_client:
            close = getattr(self._http, "aclose", None)
            if close is not None:
                await close()
            self._owns_http_client = False

    async def fetch_challenge(
        self, url: str = BILIBILI_REGISTER_URL
    ) -> Challenge:
        """Fetch a challenge from a Bilibili-shaped registration endpoint."""

        response = await self._http.get(url)
        self._raise_for_status(response)
        try:
            root = response.json()
            geetest = root["data"]["geetest"]
            gt = geetest["gt"]
            challenge = geetest["challenge"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("register response missing data.geetest.gt/challenge") from exc
        if not isinstance(gt, str) or not gt or not isinstance(challenge, str) or not challenge:
            raise ProtocolError("register response contains empty gt/challenge")
        return Challenge(gt=gt, challenge=challenge)

    async def solve_registered(
        self, url: str = BILIBILI_REGISTER_URL
    ) -> Validation:
        """Fetch and solve a challenge in one call."""

        challenge = await self.fetch_challenge(url)
        return await self.solve(challenge.gt, challenge.challenge)

    async def solve(self, gt: str, challenge: str) -> Validation:
        """Solve a V3 challenge and return business-submission fields."""

        if not gt or not challenge:
            raise ValueError("gt and challenge must not be empty")
        await self._get_cs(gt, challenge)
        captcha_type = await self._get_type(gt, challenge)
        if captcha_type == "click":
            solver = await self._get_click_solver()
            if solver is None:
                raise SolverRequiredError("click captcha requires a Solver")
            validate = await self._click_validate(gt, challenge, solver)
            return Validation(gt, challenge, validate, "click")
        if captcha_type == "slide":
            final_challenge, validate = await self._slide_validate(gt, challenge)
            return Validation(gt, final_challenge, validate, "slide")
        raise UnsupportedCaptchaTypeError(captcha_type)

    async def get_validate(self, gt: str, challenge: str) -> str:
        """Compatibility wrapper returning only ``Validation.validate``."""

        return (await self.solve(gt, challenge)).validate

    async def register(self, url: str = BILIBILI_REGISTER_URL) -> Challenge:
        """Compatibility alias for :meth:`fetch_challenge`."""

        return await self.fetch_challenge(url)

    async def _get_click_solver(self) -> Optional[Any]:
        if self._click_solver is not None or not self._lazy_click_solver:
            return self._click_solver
        async with self._solver_lock:
            if self._click_solver is None:
                self._click_solver = await asyncio.to_thread(Solver)
        return self._click_solver

    async def _get_cs(self, gt: str, challenge: str) -> tuple[bytes, str]:
        data = await self._get_jsonp(
            self.get_base_url + "/get.php", {"gt": gt, "challenge": challenge}
        )
        return self._bytes_field(data, "c"), self._str_field(data, "s")

    async def _get_type(self, gt: str, challenge: str) -> str:
        data = await self._get_jsonp(
            self.visit_base_url + "/ajax.php", {"gt": gt, "challenge": challenge}
        )
        return self._str_field(data, "result")

    async def _click_validate(self, gt: str, challenge: str, solver: Any) -> str:
        image_url = await self._get_click_image(gt, challenge)
        last_error: Optional[BaseException] = None
        for attempt in range(self.max_attempts):
            try:
                return await self._click_attempt(gt, challenge, image_url, solver)
            except (_RetryableSolveError, VerificationError) as exc:
                last_error = exc
                if attempt + 1 >= self.max_attempts:
                    if isinstance(exc, _RetryableSolveError) and exc.__cause__ is not None:
                        raise exc.__cause__
                    raise
                image_url = await self._refresh_click(gt, challenge)
        assert last_error is not None
        raise last_error

    async def _click_attempt(
        self, gt: str, challenge: str, image_url: str, solver: Any
    ) -> str:
        issued = time.monotonic()
        image = await self._download(image_url)
        try:
            result = await asyncio.to_thread(solver.solve, image)
        except (RuntimeError, ValueError) as exc:
            raise _RetryableSolveError() from exc
        coords = list(result.coords)
        if not coords:
            raise _RetryableSolveError() from RuntimeError("solver returned no matches")
        w = click_w(coords, gt, challenge)
        await self._sleep_until(issued)
        return await self._verify(gt, challenge, w)

    async def _get_click_image(self, gt: str, challenge: str) -> str:
        data = await self._get_jsonp(
            self.visit_base_url + "/get.php",
            self._image_params(gt, challenge, "click"),
        )
        return self._image_url(data, "static_servers", "pic")

    async def _refresh_click(self, gt: str, challenge: str) -> str:
        data = await self._get_jsonp(
            self.visit_base_url + "/refresh.php", {"gt": gt, "challenge": challenge}
        )
        return self._image_url(data, "image_servers", "pic")

    async def _slide_validate(self, gt: str, challenge: str) -> tuple[str, str]:
        last_error: Optional[BaseException] = None
        for attempt in range(self.max_attempts):
            params = await self._get_slide_params(gt, challenge)
            try:
                validate = await self._slide_attempt(gt, params)
                return str(params["challenge"]), validate
            except (_RetryableSolveError, VerificationError) as exc:
                last_error = exc
                if attempt + 1 >= self.max_attempts:
                    if isinstance(exc, _RetryableSolveError) and exc.__cause__ is not None:
                        raise exc.__cause__
                    raise
        assert last_error is not None
        raise last_error

    async def _get_slide_params(self, gt: str, challenge: str) -> Dict[str, Any]:
        data = await self._get_jsonp(
            self.visit_base_url + "/get.php",
            self._image_params(gt, challenge, "slide"),
        )
        return {
            "c": self._bytes_field(data, "c"),
            "s": self._str_field(data, "s"),
            "challenge": self._str_field(data, "challenge"),
            "fullbg_url": self._image_url(data, "static_servers", "fullbg"),
            "bg_url": self._image_url(data, "static_servers", "bg"),
        }

    async def _slide_attempt(self, gt: str, params: Mapping[str, Any]) -> str:
        issued = time.monotonic()
        bg, fullbg = await asyncio.gather(
            self._download(params["bg_url"]),
            self._download(params["fullbg_url"]),
        )
        try:
            result = await asyncio.to_thread(solve_slide, bg, fullbg)
        except (RuntimeError, ValueError) as exc:
            raise _RetryableSolveError() from exc
        w = slide_w(
            result.distance,
            result.encrypted_track,
            gt,
            params["challenge"],
            list(params["c"]),
            params["s"],
        )
        await self._sleep_until(issued)
        return await self._verify(gt, params["challenge"], w)

    async def _verify(self, gt: str, challenge: str, w: str) -> str:
        data = await self._get_jsonp(
            self.visit_base_url + "/ajax.php",
            {"gt": gt, "challenge": challenge, "w": w},
        )
        result = data.get("result", "")
        message = data.get("message", "")
        if result and result != "success" or message and message != "success":
            raise VerificationError(str(result), str(message))
        validate = data.get("validate", "")
        if not isinstance(validate, str) or not validate:
            raise VerificationError(str(result), str(message))
        return validate

    async def _sleep_until(self, issued: float) -> None:
        remaining = issued + self.verify_delay - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _download(self, url: str) -> bytes:
        response = await self._http.get(url)
        self._raise_for_status(response)
        return bytes(response.content)

    async def _get_jsonp(self, url: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        callback = "geetest_{}".format(time.time_ns())
        query = dict(params)
        query["callback"] = callback
        response = await self._http.get(url, params=query)
        self._raise_for_status(response)
        body = response.text.strip()
        prefix = callback + "("
        if not body.startswith(prefix) or not body.endswith(")"):
            raise ProtocolError("JSONP wrapper does not match callback")
        try:
            root = json.loads(body[len(prefix) : -1])
            data = root["data"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProtocolError("JSONP response has no data object") from exc
        if not isinstance(data, dict):
            raise ProtocolError("JSONP data is not an object")
        return data

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        try:
            response.raise_for_status()
        except Exception as exc:
            raise ProtocolError("HTTP request failed: {}".format(exc)) from exc

    @staticmethod
    def _str_field(data: Mapping[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ProtocolError("field {!r} is not a non-empty string".format(key))
        return value

    @staticmethod
    def _bytes_field(data: Mapping[str, Any], key: str) -> bytes:
        value = data.get(key)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise ProtocolError("field {!r} is not a byte array".format(key))
        try:
            numbers = [int(item) for item in value]
        except (TypeError, ValueError) as exc:
            raise ProtocolError("field {!r} contains non-numeric values".format(key)) from exc
        if any(number < 0 or number > 255 for number in numbers):
            raise ProtocolError("field {!r} contains values outside byte range".format(key))
        return bytes(numbers)

    @staticmethod
    def _image_url(data: Mapping[str, Any], servers_key: str, path_key: str) -> str:
        servers = data.get(servers_key)
        if not isinstance(servers, Sequence) or isinstance(servers, (str, bytes)) or not servers:
            raise ProtocolError("field {!r} is not a non-empty server list".format(servers_key))
        server = servers[0]
        path = data.get(path_key)
        if not isinstance(server, str) or not server or not isinstance(path, str) or not path:
            raise ProtocolError("invalid image server/path fields")
        base = server if "://" in server else "https://" + server
        return urljoin(base.rstrip("/") + "/", path.lstrip("/"))

    @staticmethod
    def _image_params(gt: str, challenge: str, captcha_type: str) -> Dict[str, str]:
        return {
            "gt": gt,
            "challenge": challenge,
            "is_next": "true",
            "offline": "false",
            "isPC": "true",
            "type": captcha_type,
        }


# Pre-0.1 compatibility: the library only implements V3, so the shorter Python
# name is preferred while existing imports keep working.
V3Client = Client
