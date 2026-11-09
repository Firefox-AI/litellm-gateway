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

## Schema check

`python -m litellm_gateway.schema_check` runs as an init container. It waits until
the database has every migration this image ships, so a pod can't start against a
schema that the migrations Job hasn't caught up yet. It reads `DATABASE_USERNAME`,
`DATABASE_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT` and `DATABASE_NAME`, and gives
up after `MIGRATION_CHECK_TIMEOUT_S` (default 300) seconds.

## Publishing

After CI passes, pushes to `main` publish the gateway image.

Images are tagged with the commit SHA, `latest`, and the upstream LiteLLM version.
Use the commit SHA to pin a deployment; the other tags move with new builds.
