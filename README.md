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

Give each key a unique `key_alias`, and register shared workload metadata to
group keys for cost attribution. For example, two keys with aliases
`eval-nightly-key-1` and `eval-manual-key-2` can both have
`metadata: {"workload": "eval"}`. Performance keys use
`metadata: {"workload": "load_test"}`. Aliases identify keys; workload values
identify accounting buckets and do not have to be unique.

The registered callback sends `x-mlpa-workload` on upstream responses so MLPA
can label its cost/usage metrics and structured logs. It reads only
`metadata.workload` on LiteLLM's authenticated key record, never client-supplied
headers or request metadata. Only `eval` and `load_test` are supported; missing
or unsupported values omit the header. MLPA records those responses as
`unknown`, including unclassified shared default keys. Independently, the callback
returns the authenticated `key_alias` in `x-mlpa-key-alias`, percent-encoded for
HTTP headers. Missing or invalid workload metadata does not suppress the alias,
and an invalid alias does not suppress a valid workload. Key secrets and other
metadata are not emitted. MLPA consumes both headers internally without
forwarding them to clients. Adding a new bucket requires updating both
the gateway allowlist and MLPA's consumer.

LiteLLM already stores spend against the key; join spend records to
`LiteLLM_VerificationToken` for its alias and `metadata.workload`. No new key
registration endpoint or database schema is required.

Deploy this gateway callback before or alongside the MLPA consumer. Older MLPA
versions ignore the header; newer consumers report `unknown` for responses from
gateways without it. Spend-log reporting does not depend on this header.

## Publishing

After CI passes, pushes to `main` publish the gateway image.

Images are tagged with the commit SHA, `latest`, and the upstream LiteLLM version.
Use the commit SHA to pin a deployment; the other tags move with new builds.
