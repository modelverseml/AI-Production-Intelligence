"""Azure OpenAI client (v1 API) and token cost estimates."""
from functools import lru_cache

from openai import OpenAI

from app.config import settings

# USD per 1M tokens (input, cached input, output). List-price estimates; check your Azure pricing.
PRICES = {
    "gpt-4.1-mini" : (0.40, 0.10, 1.60),
    "gpt-4.1" : (2.00, 0.50, 8.00),
    "gpt-5-mini" : (0.25, 0.025, 2.00),
    "gpt-5" : (1.25, 0.125, 10.00),
    "gpt-5.4" : (2.50, 0.25, 15.00),
}

def llm_configured():
    return bool(settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_KEY)

@lru_cache(maxsize = 1)
def get_client():
    if not llm_configured():
        raise RuntimeError("Azure OpenAI is not configured. Set AZURE_OPENAI_* in .env")
    return OpenAI(
        api_key = settings.AZURE_OPENAI_KEY,
        base_url = settings.AZURE_OPENAI_ENDPOINT.rstrip("/") + "/" + settings.AZURE_OPENAI_API_VERSION,
        max_retries = 2,
        timeout = 120,
    )

def default_deployment():
    return settings.AZURE_OPENAI_DEPLOYMENT

def estimate_cost(deployment, prompt_tokens, completion_tokens, cached_tokens = 0):
    price_in, price_cached, price_out = PRICES.get(deployment, (0.0, 0.0, 0.0))
    uncached = prompt_tokens - cached_tokens
    return round(
        (uncached * price_in + cached_tokens * price_cached + completion_tokens * price_out) / 1e6, 6
    )
