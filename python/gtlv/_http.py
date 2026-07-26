"""Minimal async HTTP GET over the standard library only.

The wheel deliberately ships with **no third-party Python dependencies**: a solve
needs a handful of plain GETs, which ``urllib`` already does. Blocking calls run
in a worker thread so the event loop keeps turning.

Anything exposing ``async get(url, params=...) -> response`` can still be injected
into :class:`gtlv.Client` (httpx, aiohttp, a test double); this is only the default.
"""

from __future__ import annotations

import asyncio
import json as _json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Mapping, Optional

# Bilibili's captcha registration endpoint answers 412 to unknown clients, and
# urllib's default "Python-urllib/3.x" is one of them. Present as a browser.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class Response:
    """The subset of the httpx response surface that :class:`gtlv.Client` uses."""

    def __init__(self, status_code: int, content: bytes, url: str) -> None:
        self.status_code = status_code
        self.content = content
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self) -> Any:
        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise OSError(
                "HTTP {} for {}".format(self.status_code, self.url)
            )


class HttpClient:
    """Default async GET client backed by ``urllib``."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.timeout = timeout
        self.headers: Dict[str, str] = {"User-Agent": DEFAULT_USER_AGENT}
        if headers:
            self.headers.update(headers)

    async def get(
        self, url: str, params: Optional[Mapping[str, Any]] = None
    ) -> Response:
        return await asyncio.to_thread(self._get, url, params)

    def _get(self, url: str, params: Optional[Mapping[str, Any]]) -> Response:
        if params:
            separator = "&" if urllib.parse.urlparse(url).query else "?"
            url = url + separator + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return Response(response.status, response.read(), url)
        except urllib.error.HTTPError as error:
            # Surface the status instead of raising, so raise_for_status decides.
            return Response(error.code, error.read(), url)

    async def aclose(self) -> None:
        """No pooled state to release; present for interface parity."""
