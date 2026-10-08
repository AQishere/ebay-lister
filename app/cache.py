"""TTL cache on top of a MongoDB collection.

Documents look like {_id: <key>, value: ..., expires_at: <datetime>}. A TTL
index on expires_at lets Atlas delete them; the read path also checks expiry
because the TTL monitor only runs about once a minute.
"""

import hashlib
import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.asynchronous.collection import AsyncCollection


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def make_key(namespace: str, payload: Any) -> str:
    if isinstance(payload, str):
        payload = normalise(payload)
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return f"{namespace}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


class Cache:
    def __init__(self, collection: AsyncCollection | None):
        self.col = collection
        self.hits = 0
        self.misses = 0

    async def get(self, key: str) -> Any | None:
        if self.col is None:
            return None
        doc = await self.col.find_one({"_id": key})
        if doc and doc["expires_at"].replace(tzinfo=UTC) > datetime.now(UTC):
            self.hits += 1
            return doc["value"]
        self.misses += 1
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if self.col is None:
            return
        expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        await self.col.replace_one({"_id": key}, {"_id": key, "value": value, "expires_at": expires}, upsert=True)


class Timer:
    """Collects per-step latency for the response and the README numbers."""

    def __init__(self) -> None:
        self.steps: dict[str, float] = {}

    def step(self, name: str) -> "_Step":
        return _Step(self, name)


class _Step:
    def __init__(self, timer: Timer, name: str):
        self.timer, self.name = timer, name

    def __enter__(self) -> None:
        self.start = time.perf_counter()

    def __exit__(self, *exc: object) -> None:
        self.timer.steps[self.name] = round((time.perf_counter() - self.start) * 1000)
