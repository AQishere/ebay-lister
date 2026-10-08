"""Create TTL, unique and Atlas Vector Search indexes. Safe to re-run; rebuilds the
vector index if EMBED_DIM changed (only while no listings are embedded).

    python -m scripts.create_indexes
"""

import asyncio

from app.db import ensure_indexes, get_db


async def main() -> None:
    for line in await ensure_indexes(get_db()):
        print(line)
    print("Done. A new vector index takes ~1 minute on Atlas before it shows READY.")


if __name__ == "__main__":
    asyncio.run(main())
