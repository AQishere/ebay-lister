"""Text -> vector via the Voyage AI embeddings API.

Voyage embeds documents (stored listings) and queries (seller notes) slightly
differently via `input_type`, which improves retrieval. Query vectors are
cached; document vectors are stored in MongoDB by the ingestion job.
"""

import asyncio
from typing import Literal

import httpx

from app.cache import Cache, make_key, normalise
from app.config import Settings, get_settings

BATCH_SIZE = 128
MAX_RETRIES = 5


class EmbeddingError(Exception):
    pass


class Embedder:
    def __init__(self, cache: Cache, settings: Settings | None = None, http: httpx.AsyncClient | None = None):
        self.s = settings or get_settings()
        self.cache = cache
        self.http = http or httpx.AsyncClient(timeout=30)
        self.tokens_used = 0

    async def _request(self, texts: list[str], input_type: str) -> list[list[float]]:
        payload = {
            "input": texts,
            "model": self.s.voyage_model,
            "input_type": input_type,
            "output_dimension": self.s.embed_dim,
        }
        for attempt in range(MAX_RETRIES):
            try:
                resp = await self.http.post(
                    f"{self.s.voyage_api_url.rstrip('/')}/embeddings",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.s.voyage_api_key}"},
                )
            except httpx.HTTPError as e:
                raise EmbeddingError(f"Voyage unreachable: {e}") from e
            if resp.status_code == 429 and attempt < MAX_RETRIES - 1:
                # Accounts without a payment method get ~3 requests/min; wait it out.
                await asyncio.sleep(min(60, 5 * 2**attempt))
                continue
            if resp.status_code >= 400:
                raise EmbeddingError(f"Voyage error ({resp.status_code}): {resp.text[:300]}")
            body = resp.json()
            self.tokens_used += body.get("usage", {}).get("total_tokens", 0)
            return [d["embedding"] for d in sorted(body["data"], key=lambda d: d["index"])]
        raise EmbeddingError("Voyage rate limit: retries exhausted")

    async def embed(
        self, texts: list[str], input_type: Literal["query", "document"] = "document"
    ) -> list[list[float]]:
        if not self.s.voyage_api_key:
            raise EmbeddingError("VOYAGE_API_KEY is not set")
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            out += await self._request(texts[i : i + BATCH_SIZE], input_type)
        return out

    async def embed_query(self, text: str) -> list[float]:
        key = make_key("embed", {"m": self.s.voyage_model, "d": self.s.embed_dim, "t": normalise(text)})
        if (hit := await self.cache.get(key)) is not None:
            return hit
        [vector] = await self.embed([text], "query")
        await self.cache.set(key, vector, self.s.ttl_llm)
        return vector

    async def aclose(self) -> None:
        await self.http.aclose()
