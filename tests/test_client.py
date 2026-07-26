import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gtlv import (
    Challenge,
    Client,
    ProtocolError,
    SolverRequiredError,
    VerificationError,
)


class FakeResponse:
    def __init__(self, *, text="", content=b"", payload=None, status=200):
        self.text = text
        self.content = content
        self._payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError("HTTP {}".format(self.status))

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON payload")
        return self._payload


class FakeHTTPClient:
    def __init__(self, captcha_type="click", verify_results=None):
        self.captcha_type = captcha_type
        self.verify_results = list(verify_results or ["success"])
        self.calls = []
        self.slide_gets = 0

    async def get(self, url, params=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if url == "https://register.test":
            return FakeResponse(
                payload={"data": {"geetest": {"gt": "GT", "challenge": "CH"}}}
            )
        if url.endswith("/get.php") and "type" not in params:
            return self._jsonp(params, {"c": [1, 2, 3, 4, 5], "s": "0a"})
        if url.endswith("/ajax.php") and "w" not in params:
            return self._jsonp(params, {"result": self.captcha_type})
        if url.endswith("/get.php") and params.get("type") == "click":
            return self._jsonp(
                params,
                {"static_servers": ["images.test/"], "pic": "/click.jpg"},
            )
        if url.endswith("/refresh.php"):
            return self._jsonp(
                params,
                {"image_servers": ["images.test/"], "pic": "/refreshed.jpg"},
            )
        if url.endswith("/get.php") and params.get("type") == "slide":
            self.slide_gets += 1
            return self._jsonp(
                params,
                {
                    "static_servers": ["images.test/"],
                    "challenge": "NEW{}zz".format(self.slide_gets),
                    "c": [1, 2, 3, 4, 5],
                    "s": "0a",
                    "fullbg": "/full.png",
                    "bg": "/bg.png",
                },
            )
        if url.startswith("https://images.test/"):
            return FakeResponse(content=b"image")
        if url.endswith("/ajax.php") and "w" in params:
            result = self.verify_results.pop(0)
            if result == "success":
                return self._jsonp(
                    params, {"result": "success", "validate": "VALIDATE"}
                )
            return self._jsonp(params, {"result": "fail"})
        raise AssertionError("unexpected request: {} {}".format(url, params))

    @staticmethod
    def _jsonp(params, data):
        callback = params["callback"]
        return FakeResponse(text=callback + "(" + json.dumps({"data": data}) + ")")


class StubSolver:
    def __init__(self, fail_first=False):
        self.fail_first = fail_first
        self.calls = 0

    def solve(self, image):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("bad image")
        return SimpleNamespace(coords=[(120.0, 80.0)])


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_click_flow_and_register(self):
        http = FakeHTTPClient("click")
        client = Client(
            click_solver=StubSolver(),
            http_client=http,
            get_base_url="https://get.test",
            visit_base_url="http://visit.test",
            verify_delay=0,
        )
        self.assertEqual(
            await client.fetch_challenge("https://register.test"),
            Challenge("GT", "CH"),
        )
        result = await client.solve("GT", "CH")
        self.assertEqual(result.gt, "GT")
        self.assertEqual(result.challenge, "CH")
        self.assertEqual(result.validate, "VALIDATE")
        self.assertEqual(result.captcha_type, "click")
        self.assertEqual(
            result.as_dict(),
            {
                "challenge": "CH",
                "validate": "VALIDATE",
                "seccode": "VALIDATE|jordan",
            },
        )

    async def test_click_solver_failure_refreshes_image(self):
        http = FakeHTTPClient("click")
        solver = StubSolver(fail_first=True)
        client = Client(
            click_solver=solver,
            http_client=http,
            get_base_url="https://get.test",
            visit_base_url="http://visit.test",
            max_attempts=2,
            verify_delay=0,
        )
        self.assertEqual((await client.solve("GT", "CH")).validate, "VALIDATE")
        self.assertEqual(solver.calls, 2)
        self.assertTrue(any(url.endswith("/refresh.php") for url, _ in http.calls))

    async def test_default_click_solver_is_created_lazily_and_reused(self):
        http = FakeHTTPClient("click", verify_results=["success", "success"])
        solver = StubSolver()
        client = Client(
            http_client=http,
            get_base_url="https://get.test",
            visit_base_url="http://visit.test",
            verify_delay=0,
        )
        with patch("gtlv.client.Solver", return_value=solver) as factory:
            await client.solve("GT", "CH1")
            await client.solve("GT", "CH2")
        factory.assert_called_once_with()
        self.assertEqual(solver.calls, 2)

    async def test_click_requires_solver(self):
        client = Client(
            click_solver=None,
            http_client=FakeHTTPClient("click"),
            get_base_url="https://get.test",
            visit_base_url="http://visit.test",
        )
        with self.assertRaises(SolverRequiredError):
            await client.solve("GT", "CH")

    async def test_slide_retries_verification_with_new_parameters(self):
        http = FakeHTTPClient("slide", verify_results=["fail", "success"])
        client = Client(
            http_client=http,
            get_base_url="https://get.test",
            visit_base_url="http://visit.test",
            max_attempts=2,
            verify_delay=0,
        )
        slide_result = SimpleNamespace(distance=120, encrypted_track="a!!b!!c")
        with patch("gtlv.client.solve_slide", return_value=slide_result):
            result = await client.solve("GT", "CH")
        self.assertEqual(result.validate, "VALIDATE")
        self.assertEqual(result.challenge, "NEW2zz")
        self.assertEqual(result.captcha_type, "slide")
        self.assertEqual(http.slide_gets, 2)

    async def test_verification_failure_is_typed(self):
        client = Client(
            click_solver=StubSolver(),
            http_client=FakeHTTPClient("click", verify_results=["fail"]),
            get_base_url="https://get.test",
            visit_base_url="http://visit.test",
            verify_delay=0,
        )
        with self.assertRaises(VerificationError) as caught:
            await client.solve("GT", "CH")
        self.assertEqual(caught.exception.result, "fail")

    async def test_malformed_jsonp_is_rejected(self):
        class BrokenHTTP:
            async def get(self, url, params=None):
                return FakeResponse(text="not jsonp")

        client = Client(http_client=BrokenHTTP())
        with self.assertRaises(ProtocolError):
            await client.solve("GT", "CH")

    async def test_solve_registered_combines_fetch_and_solve(self):
        client = Client(
            click_solver=StubSolver(),
            http_client=FakeHTTPClient("click"),
            get_base_url="https://get.test",
            visit_base_url="http://visit.test",
            verify_delay=0,
        )
        result = await client.solve_registered("https://register.test")
        self.assertEqual((result.gt, result.challenge), ("GT", "CH"))
        self.assertEqual(result.validate, "VALIDATE")


if __name__ == "__main__":
    unittest.main()
