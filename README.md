# LiteLLM Gateway

Custom LiteLLM image for Mozilla AI Platform, including Exa and Liner providers and
Exa/Liner flat-rate billing callback in `src/litellm_gateway/`.

## Build and test

```bash
docker build --platform linux/amd64 -t litellm-gateway:local .
docker run --rm --platform linux/amd64 --network none --entrypoint python \
  -v "$PWD/tests:/tmp/tests:ro" \
  -e LITELLM_LOCAL_MODEL_COST_MAP=True -e DO_NOT_TRACK=True \
  litellm-gateway:local -m unittest discover -s /tmp/tests -v
```

Tests use Python's built-in `unittest` and run directly in the gateway image.
They use synthetic responses and a local fake Exa server, with external networking
disabled. [CI](.github/workflows/ci.yml) also checks lint, formatting, and configuration
loading.

## Configuration

Mount your configuration at `/etc/litellm/config.yaml` and start LiteLLM with
`--config /app/config.yaml` so it can find the packaged handlers. Register them
alongside your model settings:

```yaml
litellm_settings:
  callbacks: litellm_gateway.custom_callbacks.proxy_handler_instance
  custom_provider_map:
    - provider: liner
      custom_handler: litellm_gateway.liner_handler.liner_llm
    - provider: exa_citations
      custom_handler: litellm_gateway.exa_handler.exa_llm
```

## Virtual-key cost attribution

Register keys with a stable, unique `key_alias` such as `evals-stage` or
`performance-stage`. LiteLLM already stores spend against the key; join spend
records to `LiteLLM_VerificationToken` for its alias and metadata.

The registered callback also sends `x-mlpa-key-alias` on upstream responses so
MLPA can label its cost/usage metrics and structured logs. The value comes only
from LiteLLM's authenticated key record, never from client-supplied headers or
metadata. It identifies the actual key, including MLPA's default key when a
custom key was not used. The value is UTF-8 percent-encoded for HTTP transport;
missing or invalid aliases omit the header. No key secret or key metadata is
included. MLPA consumes this header internally without forwarding it to clients.

Deploy this gateway callback before or alongside the MLPA consumer. Older MLPA
versions ignore the header; newer consumers report `unknown` for responses from
gateways without it. Spend-log reporting does not depend on this header.

## Publishing

After CI passes, pushes to `main` publish the gateway image.

Images are tagged with the commit SHA, `latest`, and the upstream LiteLLM version.
Use the commit SHA to pin a deployment; the other tags move with new builds.
