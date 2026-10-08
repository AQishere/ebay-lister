from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_env: Literal["production", "sandbox"] = "production"
    ebay_marketplace: Literal["EBAY_US", "EBAY_GB"] = "EBAY_US"

    mongodb_uri: str = ""
    mongodb_db: str = "ebay_lister"

    llm_provider: Literal["groq", "ollama"] = "groq"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_reasoning_effort: Literal["low", "medium", "high"] = "low"  # gpt-oss only; low keeps latency down
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Embeddings (Voyage AI). Changing model or dimension means re-running
    # create_indexes and re-ingesting: vectors from different models don't mix.
    voyage_api_key: str = ""
    voyage_api_url: str = "https://api.voyageai.com/v1"
    voyage_model: str = "voyage-3.5-lite"
    embed_dim: int = 1024

    # Cache lifetimes (seconds). Kept short until eBay's license terms are checked.
    ttl_ebay_search: int = 60 * 60
    ttl_ebay_item: int = 6 * 60 * 60
    ttl_taxonomy: int = 7 * 24 * 60 * 60
    ttl_llm: int = 24 * 60 * 60

    http_timeout: float = 20.0

    # Exposure. The frontend is served from the same domain, so no CORS origins are
    # needed; list extra ones comma-separated. API docs are off unless enabled.
    cors_origins: str = ""
    expose_docs: bool = False

    # Rate limits (counted in MongoDB so every serverless instance shares them).
    # A draft plus its market check costs roughly 10-20 eBay calls (5,000/day quota).
    rate_drafts_per_minute: int = 5
    rate_drafts_per_day: int = 60
    rate_market_per_minute: int = 15
    rate_global_drafts_per_day: int = 250

    @property
    def ebay_api_base(self) -> str:
        return "https://api.sandbox.ebay.com" if self.ebay_env == "sandbox" else "https://api.ebay.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
