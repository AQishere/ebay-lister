"""Fixed-window rate limits stored in MongoDB.

Vercel runs many short-lived instances, so in-memory counters would not be
shared; one small document per (key, window) is. A TTL index on expires_at
deletes old windows. Clients are identified by a hash of their IP, never the
raw address.
"""

import hashlib
import logging
import math
import time
from datetime import UTC, datetime

from fastapi import Request
from pymongo import ReturnDocument

log = logging.getLogger(__name__)

MINUTE = 60
DAY = 24 * 60 * 60


class RateLimited(Exception):
    def __init__(self, retry_after: int, scope: str):
        super().__init__(f"rate limit reached ({scope})")
        self.retry_after = retry_after
        self.scope = scope


def client_id(request: Request) -> str:
    """Hashed client IP. On Vercel, x-forwarded-for is set by the platform."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or request.headers.get("x-real-ip") or (request.client.host if request.client else "")
    return hashlib.sha256(ip.encode()).hexdigest()[:24]


async def hit(collection, key: str, limit: int, window: int, now: float | None = None) -> int | None:
    """Count one request; return seconds until the window resets if over the limit."""
    now = time.time() if now is None else now
    start = int(now // window) * window
    doc = await collection.find_one_and_update(
        {"_id": f"{key}:{window}:{start}"},
        {"$inc": {"n": 1}, "$setOnInsert": {"expires_at": datetime.fromtimestamp(start + window + 60, UTC)}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if doc["n"] > limit:
        return max(1, math.ceil(start + window - now))
    return None


async def enforce(collection, checks: list[tuple[str, int, int, str]]) -> None:
    """checks: (key, limit, window_seconds, scope). Raises RateLimited on the first
    exceeded one. Fails open if MongoDB is unreachable, so a database hiccup never
    takes the app down."""
    if collection is None:
        return
    for key, limit, window, scope in checks:
        try:
            retry_after = await hit(collection, key, limit, window)
        except Exception:  # noqa: BLE001 - availability beats strictness here
            log.exception("rate limiter unavailable; allowing request")
            return
        if retry_after is not None:
            raise RateLimited(retry_after, scope)
