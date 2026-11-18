# Use LiteLLM's non-root runtime to limit process privileges.
# Pin the digest so builds use the same reviewed base image.
FROM ghcr.io/berriai/litellm-non_root:1.110.0@sha256:825dc1814bbdb30f8800ea5f5b8f405a265747c6f3feeb765f28dbcc60049196

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
