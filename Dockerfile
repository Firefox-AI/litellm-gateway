# Use LiteLLM's non-root runtime to limit process privileges.
# Pin the digest so builds use the same reviewed base image.
FROM ghcr.io/berriai/litellm-non_root:v1.109.0@sha256:17b1e5041fbf95ad96cea1750ebbfb4e42e96b2c7d7a19f1016f25636c00e92a

# Keep upstream's entrypoint and command. Tenant configuration is supplied at deployment.
WORKDIR /app
COPY src/litellm_gateway/ /app/litellm_gateway/
ENV PYTHONPATH=/app

# Guard every accounting patch against the pinned upstream source. A LiteLLM
# upgrade must explicitly review/rebase these patches before it can build.
COPY scripts/patch_accounting.py /tmp/patch_accounting.py
RUN python /tmp/patch_accounting.py /app/litellm/proxy

# LiteLLM loads handlers relative to the supplied config path. Keep that path
# beside the package while Kubernetes mounts only configuration under /etc.
RUN ln -sfn /etc/litellm/config.yaml /app/config.yaml
