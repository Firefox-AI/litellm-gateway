# Match the explicitly versioned upstream image currently used by MLPA.
# Pin the upstream digest so builds use the reviewed artifact.
FROM ghcr.io/berriai/litellm:v1.84.4@sha256:3b1b74c5a23cc2659bf7ed8a558b36ff389e7130d081f6ff29a2143cbaaa7c29

# Keep upstream's entrypoint and command. Tenant configuration is supplied at deployment.
WORKDIR /app
COPY src/litellm_gateway/ /app/litellm_gateway/
