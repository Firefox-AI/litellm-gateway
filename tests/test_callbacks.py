"""Flat-rate billing behavior, using the same LiteLLM runtime as deployment."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from support import loopback_only

from litellm_gateway.custom_callbacks import proxy_handler_instance as handler


class CallbackTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(loopback_only())

    async def test_workload_groups_distinct_keys_using_authenticated_metadata(self):
        for alias in ("evals-nightly-key-1", "evals-manual-key-2"):
            for response in (None, SimpleNamespace()):
                with self.subTest(alias=alias, failure=response is None):
                    headers = await handler.async_post_call_response_headers_hook(
                        data={"metadata": {"workload": "load_test"}},
                        user_api_key_dict=SimpleNamespace(
                            key_alias=alias,
                            api_key="sk-secret-must-not-leak",
                            metadata={"workload": "eval", "private": "must-not-leak"},
                        ),
                        response=response,
                        request_headers={"x-mlpa-workload": "load_test"},
                    )
                    self.assertEqual(headers, {"x-mlpa-workload": "eval"})

    async def test_workload_values_are_bounded(self):
        for workload in ("eval", "load_test"):
            with self.subTest(workload=workload):
                headers = await handler.async_post_call_response_headers_hook(
                    {}, {"metadata": {"workload": workload}}, None
                )
                self.assertEqual(headers, {"x-mlpa-workload": workload})
        for metadata in (
            None,
            {},
            [],
            '{"workload":"eval"}',
            *(
                {"workload": value}
                for value in (
                    None,
                    "",
                    "other",
                    "eval-run-123",
                    "load test",
                    "EVAL",
                    " eval ",
                    "bad\r\nheader",
                    "\ud800",
                    [],
                    {},
                    1,
                )
            ),
        ):
            with self.subTest(metadata=repr(metadata)):
                self.assertEqual(
                    await handler.async_post_call_response_headers_hook(
                        {"metadata": {"workload": "eval"}},
                        SimpleNamespace(key_alias="eval", metadata=metadata),
                        None,
                        request_headers={"x-mlpa-workload": "eval"},
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
