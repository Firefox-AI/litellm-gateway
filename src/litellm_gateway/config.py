"""Provider defaults: timeouts in seconds and prices in USD per completion.

API bases and timeouts can be overridden through LiteLLM request configuration.
"""

EXA_DEFAULT_API_BASE = "https://api.exa.ai"
EXA_DEFAULT_TIMEOUT = 30.0
EXA_COST_PER_REQUEST = 0.005

LINER_DEFAULT_API_BASE = "https://platform.liner.com/api/v1/agents/quick-answer"
LINER_DEFAULT_TIMEOUT = 120.0
LINER_COST_PER_REQUEST = 0.003

# Keys match model_name in the deployment's LiteLLM configuration.
PER_REQUEST_SPEND = {
    "exa": EXA_COST_PER_REQUEST,
    "liner": LINER_COST_PER_REQUEST,
}
