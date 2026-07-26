"""基于 ``urllib`` 的异步 HTTP GET，阻塞调用在工作线程中执行。

:class:`gtlv.Client` 接受任何提供 ``async get(url, params=...)`` 的对象，
故本客户端可由 httpx 或 aiohttp 替换。
"""

from __future__ import annotations

import asyncio
import json as _json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Mapping, Optional

# B 站的验证码登记接口对未知客户端返回 412，urllib 默认的 "Python-urllib/3.x" 即在其列，
# 故以浏览器标识发起请求。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class Response:
    """:class:`gtlv.Client` 所用的响应接口子集，与 httpx 的形状一致。"""

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
    """基于 ``urllib`` 的默认异步 GET 客户端。"""

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
            # 交出状态码而不直接抛出，由 raise_for_status 决定。
            return Response(error.code, error.read(), url)

    async def aclose(self) -> None:
        """无连接池状态需释放；此处仅为保持接口一致。"""
