"""Liner streaming charges must survive LiteLLM's response assembly."""

import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import litellm
from litellm.utils import custom_llm_setup
from support import API_KEY, MESSAGES, event, loopback_only, mock_exa, sse

from litellm_gateway.custom_callbacks import proxy_handler_instance
from litellm_gateway.liner_handler import liner_llm


class LinerBillingTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(loopback_only())
        self.enterContext(
            patch.object(
                litellm,
                "custom_provider_map",
                [{"provider": "liner", "custom_handler": liner_llm}],
            )
        )
        for name in ("provider_list", "_custom_providers"):
            self.enterContext(patch.object(litellm, name, list(getattr(litellm, name))))
        custom_llm_setup()

    async def test_streaming_charge_reaches_accounting_response(self):
        wire = sse([event({"content": "Answer"}), event({}, "stop")])
        with mock_exa(lambda _: (200, "text/event-stream", wire)) as (base, _):
            stream = await litellm.acompletion(
                model="liner/quick-answer",
                messages=MESSAGES,
                stream=True,
                api_base=base,
                api_key=API_KEY,
                timeout=10,
                num_retries=0,
            )
            # Capture the assembled response at the accounting dispatch boundary;
            # leave the provider, stream wrapper and billing hook unmocked.
            with patch.object(
                stream.logging_obj, "dispatch_success_handlers", new_callable=AsyncMock
            ) as dispatch:
                hook = proxy_handler_instance.async_post_call_streaming_iterator_hook
                billed_stream = hook(
                    None,
                    stream,
                    {"model": "liner", "endpoint": "/v1/chat/completions"},
                )
                chunks = [chunk async for chunk in billed_stream]
                # LiteLLM schedules accounting when the stream is exhausted.
                await asyncio.sleep(0)
                dispatch.assert_awaited_once()
                response = dispatch.call_args.args[0]
                self.assertEqual(response.choices[0].message.content, "Answer")
                self.assertEqual(response._hidden_params["response_cost"], 0.003)
                self.assertTrue(
                    any(chunk.choices[0].finish_reason == "stop" for chunk in chunks)
                )
