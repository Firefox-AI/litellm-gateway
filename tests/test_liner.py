"""Exercise Liner requests and responses without a live provider."""

import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from litellm.types.utils import ModelResponse

from litellm_gateway.liner_handler import liner_llm


class LinerTests(IsolatedAsyncioTestCase):
    async def test_sync_and_async_json_and_streaming(self):
        for asynchronous in (False, True):
            for streaming in (False, True):
                with self.subTest(asynchronous=asynchronous, streaming=streaming):
                    references = [{"url": "https://example.org", "faviconUrl": "icon"}]
                    raw = {
                        "choices": [{"message": {"content": "Answer"}}],
                        "references": references,
                    }
                    lines = [
                        "data: "
                        + json.dumps({"choices": [{"delta": {"content": "Answer"}}]}),
                        "data: "
                        + json.dumps(
                            {
                                "choices": [{"delta": {}, "finish_reason": "stop"}],
                                "references": references,
                            }
                        ),
                        "data: [DONE]",
                    ]
                    response = Mock()
                    response.json.return_value = raw
                    response.iter_lines.return_value = iter(lines)

                    async def async_lines():
                        for line in lines:
                            yield line

                    response.aiter_lines = async_lines
                    client = Mock()
                    client.post = (
                        AsyncMock(return_value=response)
                        if asynchronous
                        else Mock(return_value=response)
                    )
                    params = dict(
                        model="quick-answer",
                        messages=[
                            {"role": "system", "content": "Be brief"},
                            {"role": "user", "content": "Hello"},
                            {"role": "tool", "content": "unsupported"},
                        ],
                        api_base="https://provider.invalid/quick-answer/",
                        api_key="offline-test-key",
                        custom_prompt_dict={},
                        model_response=ModelResponse(),
                        print_verbose=None,
                        encoding=None,
                        logging_obj=None,
                        optional_params={},
                        client=client,
                    )
                    if streaming:
                        if asynchronous:
                            chunks = [
                                chunk async for chunk in liner_llm.astreaming(**params)
                            ]
                        else:
                            chunks = list(liner_llm.streaming(**params))
                        self.assertEqual(
                            "".join(chunk["text"] for chunk in chunks), "Answer"
                        )
                        self.assertTrue(chunks[-1]["is_finished"])
                        self.assertEqual(chunks[-1]["usage"]["total_tokens"], 2)
                        fields = chunks[-1]["provider_specific_fields"]
                    else:
                        result = (
                            await liner_llm.acompletion(**params)
                            if asynchronous
                            else liner_llm.completion(**params)
                        )
                        self.assertEqual(result.choices[0].message.content, "Answer")
                        self.assertEqual(result._hidden_params["response_cost"], 0.003)
                        fields = result.choices[0].message.provider_specific_fields
                    self.assertEqual(fields["citations"][0]["favicon"], "icon")
                    self.assertEqual(fields["dropped"][0]["reason"], "unsupported_role")
                    request = client.post.call_args.kwargs
                    self.assertEqual(
                        request["url"], "https://provider.invalid/quick-answer"
                    )
                    self.assertEqual(
                        request["headers"]["x-api-key"], "offline-test-key"
                    )
                    self.assertEqual(request["json"]["stream"], streaming)
                    self.assertEqual(
                        request["json"]["messages"],
                        [
                            {"role": "user", "content": "Be brief"},
                            {"role": "user", "content": "Hello"},
                        ],
                    )
