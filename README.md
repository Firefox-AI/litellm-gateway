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

## Publishing

After CI passes, pushes to `main` publish the gateway image.

Publishing uses Mozilla's [shared build-and-push workflow](https://github.com/mozilla/deploy-actions/blob/20f90fab6ef13820f2231cb82cc7a272bcfcd525/.github/workflows/build-and-push.yml).
It runs lint checks before building, then configuration and handler tests against
the built image before pushing that same image.

Main builds publish a short commit tag (normally 10 characters) and `latest`.
Use the commit tag or resolved digest to pin an image. Full commit-SHA and upstream
LiteLLM version tags are no longer published. Existing deployment rules requiring
40-character tags must be updated before selecting one of these builds.

Manual runs of the publishing workflow build and test without pushing:

```bash
gh workflow run publish.yml --repo Firefox-AI/litellm-gateway --ref <branch>
```

The shared workflow authenticates using the configured Google workload identity
pool and `artifact-writer` service account. It does not use a GitHub `build`
environment; any environment protections or federation conditions must account
for that job context.
