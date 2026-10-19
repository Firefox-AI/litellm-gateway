"""Exercise real LiteLLM conversion and billing with synthetic Exa responses."""

import json
from itertools import product
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import litellm
from litellm.utils import custom_llm_setup
from support import (
    API_KEY,
    CITATIONS,
    MESSAGES,
    USAGE,
    citation_deltas,
    event,
    json_response,
    loopback_only,
    mock_exa,
    sse,
    text_from,
)

from litellm_gateway import custom_callbacks, exa_handler

REQUEST_DATA = {"model": "exa", "endpoint": "/v1/chat/completions"}
CALLBACK = custom_callbacks.proxy_handler_instance


def params(base, stream=False):
    return dict(
        model="exa_citations/exa",
        messages=MESSAGES,
        stream=stream,
        api_base=base,
        api_key=API_KEY,
        num_retries=0,
        timeout=10,
        temperature=0.25,
        extra_body={"text": True},
        **({"stream_options": {"include_usage": True}} if stream else {}),
    )


START = event({"role": "assistant", "content": ""})
TEXT = event({"content": "Answer 🔬"})
STOP = event({}, "stop")
SOURCES = event({"content": "", "citations": CITATIONS})
USAGE_EVENT = {**event({}), "choices": [], "usage": USAGE}

STREAM_CASES = (
    ("citation-only-empty-content", [TEXT, SOURCES, STOP], [CITATIONS], True),
    (
        "citation-only-null-content",
        [TEXT, event({"content": None, "citations": CITATIONS}), STOP],
        [CITATIONS],
        True,
    ),
    (
        "citations-with-text",
        [event({"content": "Answer 🔬", "citations": CITATIONS}), STOP],
        [CITATIONS],
        True,
    ),
    (
        "citations-on-finish",
        [TEXT, event({"content": "", "citations": CITATIONS}, "stop")],
        [CITATIONS],
        True,
    ),
    ("citations-after-finish", [TEXT, STOP, SOURCES], [CITATIONS], True),
    ("empty-event", [TEXT, event({"content": ""}), STOP], [], True),
    (
        "empty-citations",
        [TEXT, event({"content": "", "citations": []}), STOP],
        [[]],
        True,
    ),
    ("text-and-usage", [TEXT, STOP], [], True),
    ("no-provider-finish", [TEXT, SOURCES], [CITATIONS], False),
)


class ExaReplayTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(loopback_only())
        self.enterContext(
            patch.object(
                litellm,
                "custom_provider_map",
                [{"provider": "exa_citations", "custom_handler": exa_handler.exa_llm}],
            )
        )
        for name in ("provider_list", "_custom_providers"):
            self.enterContext(patch.object(litellm, name, list(getattr(litellm, name))))
        custom_llm_setup()

    def assert_request(self, requests, streaming):
        self.assertEqual(len(requests), 1, "Expected one request without retries")
        path, headers, body = requests[0]
        self.assertEqual(path, "/chat/completions")
        self.assertEqual(headers["authorization"], f"Bearer {API_KEY}")
        self.assertEqual(body["model"], "exa")
        self.assertIs(body["stream"], streaming)
        self.assertEqual(body["messages"], MESSAGES)
        self.assertIs(body["text"], True)
        self.assertEqual(body["temperature"], 0.25)
        self.assertNotIn("max_retries", body)

    async def test_stream(self):
        for sync, (name, events, expected, has_usage) in product(
            (False, True), STREAM_CASES
        ):
            with self.subTest(sync=sync, case=name):
                events = [START, *events, *([USAGE_EVENT] if has_usage else [])]
                with mock_exa(lambda _: (200, "text/event-stream", sse(events))) as (
                    base,
                    requests,
                ):
                    if sync:
                        chunks = [
                            chunk.model_dump()
                            for chunk in litellm.completion(**params(base, True))
                        ]
                    else:
                        stream = await litellm.acompletion(**params(base, True))
                        stream = CALLBACK.async_post_call_streaming_iterator_hook(
                            user_api_key_dict=None,
                            response=stream,
                            request_data=REQUEST_DATA,
                        )
                        chunks = []
                        async for chunk in stream:
                            self.assertEqual(
                                chunk._hidden_params["response_cost"], 0.005
                            )
                            chunks.append(chunk.model_dump())
                self.assert_request(requests, streaming=True)
                self.assertEqual(text_from(chunks), text_from(events))
                self.assertEqual(citation_deltas(chunks), expected)
                self.assertTrue(
                    any(
                        choice.get("finish_reason") == "stop"
                        for chunk in chunks
                        for choice in chunk.get("choices", [])
                    )
                )
                if has_usage:
                    usage = next(
                        chunk["usage"]
                        for chunk in reversed(chunks)
                        if chunk.get("usage")
                    )
                    self.assertEqual({key: usage[key] for key in USAGE}, USAGE)

    async def test_json(self):
        for sync, status in product((False, True), (200, 429)):
            with self.subTest(sync=sync, status=status):
                body = (
                    json_response()
                    if status == 200
                    else {"error": {"message": "Rate limited"}}
                )
                wire = json.dumps(body).encode()
                with mock_exa(lambda _: (status, "application/json", wire)) as (
                    base,
                    requests,
                ):

                    async def complete():
                        if sync:
                            return litellm.completion(**params(base))
                        return await litellm.acompletion(**params(base))

                    if status == 429:
                        with self.assertRaises(litellm.RateLimitError) as caught:
                            await complete()
                        self.assertEqual(caught.exception.status_code, 429)
                    else:
                        response = await complete()
                        response = await CALLBACK.async_post_call_success_hook(
                            data=REQUEST_DATA,
                            user_api_key_dict=None,
                            response=response,
                        )
                        self.assertEqual(
                            response._hidden_params["response_cost"], 0.005
                        )
                        result = response.model_dump()
                        message = result["choices"][0]["message"]
                        self.assertEqual(message["content"], "Answer")
                        self.assertEqual(
                            message["provider_specific_fields"]["citations"], CITATIONS
                        )
                        self.assertEqual(
                            result["usage"]["total_tokens"], USAGE["total_tokens"]
                        )
                self.assert_request(requests, streaming=False)
