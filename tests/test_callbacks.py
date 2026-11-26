"""Flat-rate billing behavior, using the same LiteLLM runtime as deployment."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from support import loopback_only

from litellm_gateway.custom_callbacks import proxy_handler_instance as handler


class CallbackTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(loopback_only())

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

    async def test_charge_keyed_on_resolved_deployment(self):
        # The charge must follow the deployment that served the request, not the
        # name the client typed. AIPLAT-1762: a client can address the Exa
        # deployment as "exa_citations/exa" (its litellm_params.model) instead of
        # "exa"; LiteLLM routes both to the same deployment, which the proxy
        # reports as metadata.deployment_model_name="exa".
        route = {"endpoint": "/v1/chat/completions"}
        for client_model, deployment_model_name, expected in (
            ("exa_citations/exa", "exa", 0.005),  # alias -> still charged
            ("liner/liner-quick-answer", "liner", 0.003),
            ("exa", "exa", 0.005),  # plain name unchanged
            ("exa", "some-cheap-model", 0.123),  # routed elsewhere -> not charged
        ):
            for streaming in (False, True):
                with self.subTest(
                    client_model=client_model,
                    deployment_model_name=deployment_model_name,
                    streaming=streaming,
                ):
                    response = SimpleNamespace(_hidden_params={"response_cost": 0.123})
                    data = {
                        "model": client_model,
                        "metadata": {"deployment_model_name": deployment_model_name},
                        **route,
                    }
                    if streaming:

                        async def chunks():
                            yield response

                        stream_hook = handler.async_post_call_streaming_iterator_hook
                        [_ async for _ in stream_hook(None, chunks(), data)]
                    else:
                        await handler.async_post_call_success_hook(data, None, response)
                    self.assertEqual(response._hidden_params["response_cost"], expected)
