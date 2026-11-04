"""LiteLLM proxy callbacks for spend accounting and virtual-key attribution.

Exa and Liner answers are priced per query, but LiteLLM's cost calculator has no
per-request pricing for chat completions -- `input_cost_per_request` exists in the
model cost map but nothing reads it. For successful requests to the models in
`PER_REQUEST_SPEND` routed through `/v1/chat/completions`, this callback sets
`_hidden_params["response_cost"]` to that model's fixed per-request charge.
LiteLLM then uses that value when writing its normal spend records.

The streaming hook is not something a provider handler could do instead:
CustomStreamWrapper builds its own chunk objects and stamps
`"response_cost": None` onto every one of them, discarding whatever the handler
set. Mutating the chunks here works because litellm assembles the complete
streaming response from these same objects only after the iterator is exhausted.

Failed requests, other models, and calls made through other routes are ignored.
"""

from urllib.parse import urlparse

from litellm.integrations.custom_logger import CustomLogger

from litellm_gateway.config import PER_REQUEST_SPEND

CHAT_COMPLETIONS_ROUTE = "/v1/chat/completions"
WORKLOAD_HEADER = "x-mlpa-workload"
ATTRIBUTION_WORKLOADS = frozenset({"eval", "load_test"})


def _record_get(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _route_path(value):
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("/"):
        return value
    return urlparse(value).path or None


def _request_route(data):
    metadata = data.get("metadata") or {}

    route = _route_path(metadata.get("user_api_key_request_route"))
    if route:
        return route

    auth = metadata.get("user_api_key_auth")
    route = _route_path(_record_get(auth, "request_route"))
    if route:
        return route

    proxy_request = data.get("proxy_server_request") or {}
    route = _route_path(proxy_request.get("url"))
    if route:
        return route

    return _route_path(data.get("endpoint"))


class MyCustomHandler(CustomLogger):
    async def async_post_call_response_headers_hook(
        self,
        data,
        user_api_key_dict,
        response,
        request_headers=None,
        litellm_call_info=None,
    ):
        """Attribute requests using metadata on the authenticated virtual key.

        Only the resolved key record is authoritative: request metadata and
        client headers must not be able to choose the accounting workload.
        Only bounded workload names are emitted, never unique key aliases.
        """
        metadata = _record_get(user_api_key_dict, "metadata")
        if not isinstance(metadata, dict):
            return {}
        workload = metadata.get("workload")
        if not isinstance(workload, str) or workload not in ATTRIBUTION_WORKLOADS:
            return {}
        return {WORKLOAD_HEADER: workload}

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        spend = self._per_request_spend(data)
        if spend is None:
            return response
        hidden_params = getattr(response, "_hidden_params", None)
        if hidden_params is None:
            return response

        hidden_params["response_cost"] = spend
        return response

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response, request_data
    ):
        spend = self._per_request_spend(request_data)
        async for chunk in response:
            if spend is not None:
                hidden_params = getattr(chunk, "_hidden_params", None)
                if hidden_params is not None:
                    hidden_params["response_cost"] = spend

            yield chunk

    @staticmethod
    def _per_request_spend(data):
        """Flat charge for this request, or None if it is not a flat-rate call."""
        spend = PER_REQUEST_SPEND.get(data.get("model"))
        if spend is None:
            return None

        if _request_route(data) != CHAT_COMPLETIONS_ROUTE:
            return None

        return spend


proxy_handler_instance = MyCustomHandler()
