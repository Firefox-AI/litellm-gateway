# Match the explicitly versioned upstream image currently used by MLPA.
# Pin the upstream digest so builds use the reviewed artifact.
FROM ghcr.io/berriai/litellm:v1.105.1@sha256:b7b9e2c306343721802253d0dd9436b9634a2eb4e14da7c7cf06c5c7b7530802

# Keep upstream's entrypoint and command. Tenant configuration is supplied at deployment.
WORKDIR /app
COPY src/litellm_gateway/ /app/litellm_gateway/
