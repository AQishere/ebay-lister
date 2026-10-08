"""Offline ingestion: build the listing corpus used for RAG (vector search).

    python -m scripts.ingest --groups shoes phones video_games --max-calls 3000

For each seed query: Browse search -> item details (aspects + sold counts) ->
embed -> upsert into `listings`. Resumable: items already stored with details
are skipped, so you can run it on several days to stay under the daily quota.
"""

import argparse
import asyncio
from datetime import UTC, datetime

from pymongo import UpdateOne

from app.cache import Cache
from app.categories import GROUPS, SEED_QUERIES, category_ids
from app.config import get_settings
from app.db import get_db
from app.ebay_client import EbayClient, EbayRateLimited
from app.embeddings import Embedder
from app.retrieval import embed_text


async def ingest_query(ebay: EbayClient, db, embed: Embedder, group: str, query: str, per_query: int, m: str) -> int:
    summaries = await ebay.search(query, category_ids(m, group), limit=per_query)
    ids = [s["item_id"] for s in summaries]
    have = {d["item_id"] async for d in db.listings.find({"item_id": {"$in": ids}}, {"item_id": 1})}
    new_ids = [i for i in ids if i not in have]
    if not new_ids:
        return 0

    items = await ebay.get_items(new_ids)
    texts = [embed_text(group, it["title"], it.get("aspects") or {}) for it in items]
    vectors = await embed.embed(texts, "document")
    now = datetime.now(UTC)
    ops = [
        UpdateOne(
            {"item_id": it["item_id"]},
            {"$set": {**it, "marketplace": m, "category_group": group, "seed_query": query,
                      "embed_text": text, "embedding": vec, "fetched_at": now}},
            upsert=True,
        )
        for it, text, vec in zip(items, texts, vectors)
    ]
    if ops:
        await db.listings.bulk_write(ops, ordered=False)
    return len(ops)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", nargs="+", default=list(GROUPS), choices=GROUPS)
    ap.add_argument("--max-calls", type=int, default=3000, help="eBay API call budget for this run")
    ap.add_argument("--per-query", type=int, default=200, help="search results per seed query (max 200)")
    args = ap.parse_args()

    s = get_settings()
    db = get_db()
    ebay = EbayClient(Cache(db.ebay_cache), s)
    embed = Embedder(Cache(None), s)

    total = 0
    try:
        for group in args.groups:
            for query in SEED_QUERIES[group]:
                if ebay.calls >= args.max_calls:
                    print(f"Call budget {args.max_calls} reached; re-run later to continue.")
                    return
                n = await ingest_query(ebay, db, embed, group, query, args.per_query, s.ebay_marketplace)
                total += n
                print(f"{group:12} {query:28} +{n:4} new   (calls used: {ebay.calls})")
    except EbayRateLimited:
        print("eBay daily limit reached; re-run tomorrow, progress is saved.")
    finally:
        count = await db.listings.count_documents({})
        print(f"\nAdded {total} listings this run. Corpus size: {count}. eBay calls: {ebay.calls}")
        await ebay.aclose()


if __name__ == "__main__":
    asyncio.run(main())
