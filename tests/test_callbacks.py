"""Flat-rate billing behavior, using the same LiteLLM runtime as deployment."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from urllib.parse import unquote

from support import loopback_only

from litellm_gateway.custom_callbacks import proxy_handler_instance as handler


class CallbackTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(loopback_only())

    async def test_key_alias_comes_from_authenticated_key_only(self):
        for response in (None, SimpleNamespace()):
            with self.subTest(failure=response is None):
                headers = await handler.async_post_call_response_headers_hook(
                    data={"metadata": {"key_alias": "spoofed"}},
                    user_api_key_dict=SimpleNamespace(
                        key_alias="evals-stage",
                        api_key="sk-secret-must-not-leak",
                        metadata={"private": "must-not-leak"},
                    ),
                    response=response,
                    request_headers={"x-mlpa-key-alias": "spoofed"},
                )
                self.assertEqual(headers, {"x-mlpa-key-alias": "evals-stage"})

    async def test_key_alias_is_safe_for_http_headers(self):
        alias = "evals / café 100%"
        headers = await handler.async_post_call_response_headers_hook(
            {}, SimpleNamespace(key_alias=alias), None
        )
        encoded = headers["x-mlpa-key-alias"]
        self.assertTrue(encoded.isascii())
        self.assertEqual(unquote(encoded), alias)
        for invalid in (None, "", "   ", "bad\r\nheader", "x" * 256, "\ud800"):
            with self.subTest(alias=repr(invalid)):
                self.assertEqual(
                    await handler.async_post_call_response_headers_hook(
                        {"metadata": {"key_alias": "spoofed"}},
                        SimpleNamespace(key_alias=invalid),
                        None,
                    ),
                    {},
                )

    async def test_flat_rate_billing_and_exclusions(self):
        for model, route, expected in (
            ("exa", "/v1/chat/completions", 0.005),
            ("liner", "/v1/chat/completions", 0.003),
            ("unrelated", "/v1/chat/completions", 0.123),
            ("exa", "/v1/embeddings", 0.123),
            ("exa", None, 0.123),
        ):
            for streaming in (False, True):
                with self.subTest(model=model, route=route, streaming=streaming):
                    response = SimpleNamespace(_hidden_params={"response_cost": 0.123})
                    data = {"model": model, "endpoint": route}
                    if streaming:

                        async def chunks():
                            yield response

                        stream_hook = handler.async_post_call_streaming_iterator_hook
                        results = [
                            chunk async for chunk in stream_hook(None, chunks(), data)
                        ]
                        self.assertEqual(results, [response])
                    else:
                        result = await handler.async_post_call_success_hook(
                            data, None, response
                        )
                        self.assertIs(result, response)
                    self.assertEqual(response._hidden_params["response_cost"], expected)

    async def test_proxy_route_metadata(self):
        for route_data in (
            {"metadata": {"user_api_key_request_route": "/v1/chat/completions"}},
            {
                "metadata": {
                    "user_api_key_auth": {"request_route": "/v1/chat/completions"}
                }
            },
            {"proxy_server_request": {"url": "http://proxy/v1/chat/completions"}},
        ):
            with self.subTest(route_data=route_data):
                response = SimpleNamespace(_hidden_params={})
                await handler.async_post_call_success_hook(
                    {"model": "liner", **route_data}, None, response
                )
                self.assertEqual(response._hidden_params["response_cost"], 0.003)
