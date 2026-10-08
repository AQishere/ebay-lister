"""MongoDB access. One client per process so warm serverless invocations reuse it."""

import asyncio

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.operations import SearchIndexModel

from app.config import get_settings

VECTOR_INDEX = "listing_vector_index"

_client: AsyncMongoClient | None = None


def get_db() -> AsyncDatabase:
    global _client
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not set")
    if _client is None:
        _client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000)
    return _client[settings.mongodb_db]


def vector_index_definition(dim: int) -> dict:
    return {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": dim, "similarity": "cosine"},
            {"type": "filter", "path": "category_group"},
            {"type": "filter", "path": "marketplace"},
        ]
    }


async def _search_indexes(db: AsyncDatabase) -> dict[str, dict]:
    return {ix["name"]: ix async for ix in await db.listings.list_search_indexes()}


async def ensure_indexes(db: AsyncDatabase) -> list[str]:
    """Idempotent. Run via scripts/create_indexes.py. Returns what it did."""
    done = []
    for name in ("ebay_cache", "llm_cache", "rate_limits"):
        await db[name].create_index("expires_at", expireAfterSeconds=0)
    await db.listings.create_index("item_id", unique=True)
    await db.listings.create_index([("category_group", ASCENDING), ("marketplace", ASCENDING)])
    await db.drafts.create_index("created_at")
    done.append("regular indexes ok")

    dim = get_settings().embed_dim
    existing = (await _search_indexes(db)).get(VECTOR_INDEX)
    if existing:
        fields = (existing.get("latestDefinition") or existing.get("definition") or {}).get("fields", [])
        current_dim = next((f.get("numDimensions") for f in fields if f.get("type") == "vector"), None)
        if current_dim == dim:
            done.append(f"vector index ok ({dim} dims)")
            return done
        if await db.listings.count_documents({"embedding": {"$exists": True}}):
            raise RuntimeError(
                f"vector index is {current_dim} dims but EMBED_DIM={dim}, and listings already have embeddings. "
                "Delete the listings (or keep the old model) before changing dimensions."
            )
        await db.listings.drop_search_index(VECTOR_INDEX)
        for _ in range(60):  # Atlas deletes search indexes asynchronously
            if VECTOR_INDEX not in await _search_indexes(db):
                break
            await asyncio.sleep(2)
        done.append(f"dropped old vector index ({current_dim} dims)")

    await db.listings.create_search_index(
        SearchIndexModel(name=VECTOR_INDEX, type="vectorSearch", definition=vector_index_definition(dim))
    )
    done.append(f"created vector index ({dim} dims)")
    return done
