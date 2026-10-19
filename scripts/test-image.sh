#!/usr/bin/env bash
set -euo pipefail

# Mozilla's build action loads the image under this local tag before calling us.
image="${1:-litellm-gateway:latest}"
architecture=$(docker image inspect "$image" --format '{{.Architecture}}')
if [[ "$architecture" != amd64 ]]; then
  echo "Expected an amd64 gateway image, got $architecture" >&2
  exit 1
fi

docker run --rm --platform linux/amd64 --network none --entrypoint python \
  --volume "$PWD/scripts/smoke_test.py:/tmp/smoke_test.py:ro" \
  --volume "$PWD/tests/fixtures/config.yaml:/etc/litellm/config.yaml:ro" \
  --env LITELLM_LOCAL_MODEL_COST_MAP=True \
  --env DO_NOT_TRACK=True \
  "$image" /tmp/smoke_test.py

docker run --rm --platform linux/amd64 --network none --entrypoint python \
  --volume "$PWD/tests:/tmp/tests:ro" \
  --env LITELLM_LOCAL_MODEL_COST_MAP=True \
  --env DO_NOT_TRACK=True \
  "$image" -m unittest discover -s /tmp/tests -v
