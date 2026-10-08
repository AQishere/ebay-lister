"""Check Voyage embeddings work, and show what they do: similar meaning -> high similarity.

    python -m scripts.check_embeddings
"""

import asyncio
import time

import numpy as np

from app.cache import Cache
from app.config import get_settings
from app.embeddings import Embedder, EmbeddingError

QUERY = "nike air max 90 white mens size 10"
LISTINGS = [
    "NIKE AM90 Triple White Men's US10 Trainers",
    "Nike Air Max 90 Essential White Sneakers Size 10",
    "Adidas Samba OG White Black Mens UK 9",
    "Apple iPhone 13 128GB Blue Unlocked",
    "Mario Kart 8 Deluxe Nintendo Switch",
]


async def main() -> None:
    s = get_settings()
    print(f"Model: {s.voyage_model} | dimensions: {s.embed_dim}\n")
    emb = Embedder(Cache(None), s)
    try:
        start = time.perf_counter()
        q = np.array(await emb.embed_query(QUERY))
        docs = np.array(await emb.embed(LISTINGS, "document"))
        ms = (time.perf_counter() - start) * 1000
    except EmbeddingError as e:
        print(f"[XX ] {e}")
        return
    finally:
        await emb.aclose()

    print(f"[OK ] got {len(docs) + 1} vectors of {len(q)} numbers each in {ms:.0f} ms")
    print(f"      first 5 numbers of the query vector: {np.round(q[:5], 3).tolist()}\n")
    sims = docs @ q / (np.linalg.norm(docs, axis=1) * np.linalg.norm(q))
    print(f'Query: "{QUERY}"\nCosine similarity to each listing (higher = closer in meaning):')
    for sim, text in sorted(zip(sims, LISTINGS), reverse=True):
        print(f"  {sim:.3f}  {'#' * int(max(sim, 0) * 40):40}  {text}")


if __name__ == "__main__":
    asyncio.run(main())
