# LiteLLM Gateway

Mozilla AI Platform customizations, tests, and container build workflows for our
LiteLLM gateway. Tenant-specific Python code and CI live here; infrastructure and
Helm deployment configuration remain in [mozilla/dataservices-infra](https://github.com/mozilla/dataservices-infra/).

`src/litellm_gateway/` owns the Liner quick-answer provider and the Exa/Liner
flat-rate billing callback. These are migrated from the infrastructure chart;
provider credentials and model/router settings still come from deployment.

## Build and validate

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
docker build --platform linux/amd64 -t litellm-gateway:local .
docker run --rm --platform linux/amd64 --network none --entrypoint python \
  -v "$PWD/tests:/tmp/tests:ro" \
  -e LITELLM_LOCAL_MODEL_COST_MAP=True -e DO_NOT_TRACK=True \
  litellm-gateway:local -m unittest discover -s /tmp/tests -v
docker run --rm --platform linux/amd64 --network none --entrypoint python \
  -v "$PWD/scripts/smoke_test.py:/tmp/smoke_test.py:ro" \
  -v "$PWD/tests/fixtures/config.yaml:/etc/litellm/config.yaml:ro" \
  -e LITELLM_LOCAL_MODEL_COST_MAP=True -e DO_NOT_TRACK=True \
  litellm-gateway:local /tmp/smoke_test.py
```

CI runs the tests inside the pinned upstream image, without installing another
LiteLLM version. Tests cover sync/async Liner responses and streams, citation
mapping, dropped messages, and billing eligibility. The smoke test loads a
mounted configuration through LiteLLM's proxy loader as a non-root user.

## Image publication and deployment

After CI passes, pushes to `main` publish to:

```text
us-docker.pkg.dev/moz-fx-llm-proxy-prod-b0b8/llm-proxy-prod/litellm-gateway
```

Each build publishes a full commit SHA tag, `latest`, and the upstream version
alias extracted from the Dockerfile (currently `v1.84.4`). The version alias and
`latest` move on subsequent builds; use the commit SHA for a fixed release.
Publication uses the existing `build` environment and GCP workload identity.

For the initial migration, merge this repository's changes and wait for the
publish workflow to succeed **before** merging the infrastructure changes.
In `dataservices-infra/llm-proxy/k8s/llm-proxy`, the proxy and the
`litellm-migrations` Job must use this repository and the same image tag. The
shared `litellmImageTag` supplies dev/stage; production also overrides it in
`values-prod.yaml`. Update both for a pinned release or upstream version change.
Publishing an image alone does not restart existing Kubernetes pods. Deploy a
new tag through the infrastructure repository to trigger a rollout.

The chart mounts `config.yaml` under `/etc/litellm/` and starts LiteLLM with
`--config /app/config.yaml`. The image supplies that symlink because LiteLLM
resolves custom modules relative to the provided config path. Keep the config
mount separate from `/app/litellm_gateway/` so it cannot hide the packaged code.
Use these configuration references:

```yaml
litellm_settings:
  callbacks: litellm_gateway.custom_callbacks.proxy_handler_instance
  custom_provider_map:
    - provider: liner
      custom_handler: litellm_gateway.liner_handler.liner_llm
```

For rollback, revert the infrastructure migration as a whole: an upstream image
does not contain the packaged handlers or the `/app/config.yaml` symlink.
