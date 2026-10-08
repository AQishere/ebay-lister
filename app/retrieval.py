"""Vector search over the offline-ingested listing corpus, re-ranked toward listings that sell."""

import math

from pymongo.asynchronous.database import AsyncDatabase

from app.db import VECTOR_INDEX
from app.title_format import title_specifics

SALES_WEIGHT = 0.15  # how much units sold boosts similarity; log-scaled so one bestseller can't dominate


def embed_text(group: str, title: str, aspects: dict[str, str]) -> str:
    """Text embedded for both corpus listings and queries, so they live in the same space."""
    spec = "; ".join(f"{k}: {v}" for k, v in title_specifics(group, aspects).items())
    return f"{title}. {spec}" if spec else title


async def vector_search(
    db: AsyncDatabase, vector: list[float], group: str, marketplace: str, k: int = 8, num_candidates: int = 200
) -> list[dict]:
    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX,
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": num_candidates,
                "limit": k * 3,  # over-fetch, then re-rank by sales
                "filter": {"category_group": group, "marketplace": marketplace},
            }
        },
        {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
    ]
    docs = [d async for d in await db.listings.aggregate(pipeline)]
    return rerank_by_sales(docs)[:k]


def rerank_by_sales(docs: list[dict]) -> list[dict]:
    for d in docs:
        sold = d.get("sold_quantity") or 0
        d["rank_score"] = d.get("score", 0.0) * (1 + SALES_WEIGHT * math.log1p(sold))
    return sorted(docs, key=lambda d: d["rank_score"], reverse=True)
