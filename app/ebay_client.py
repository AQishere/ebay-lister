"""eBay Browse + Taxonomy API client.

- OAuth client-credentials token, kept in memory until shortly before expiry.
- Every response is cached in MongoDB (see app/cache.py) to stay inside the
  ~5,000 calls/day Browse quota.
- Items are normalised to plain dicts so the rest of the app never touches
  eBay's raw JSON shape.
"""

import asyncio
import base64
import time
from itertools import zip_longest
from typing import Any

import httpx

from app.cache import Cache, make_key
from app.config import Settings, get_settings

SCOPE = "https://api.ebay.com/oauth/api_scope"
DETAIL_CONCURRENCY = 8
BATCH_SIZE = 20  # getItems maximum


class EbayError(Exception):
    pass


class EbayRateLimited(EbayError):
    pass


class EbayClient:
    def __init__(self, cache: Cache, settings: Settings | None = None, http: httpx.AsyncClient | None = None):
        self.s = settings or get_settings()
        self.cache = cache
        self.http = http or httpx.AsyncClient(timeout=self.s.http_timeout)
        self._token: str | None = None
        self._token_expiry = 0.0
        self._token_lock = asyncio.Lock()
        self._batch_supported: bool | None = None  # learned on first getItems call
        self.calls = 0  # real (uncached) API calls, used by the ingestion budget

    # ---------- auth ----------

    async def _get_token(self) -> str:
        async with self._token_lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token
            if not (self.s.ebay_client_id and self.s.ebay_client_secret):
                raise EbayError("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET are not set")
            basic = base64.b64encode(f"{self.s.ebay_client_id}:{self.s.ebay_client_secret}".encode()).decode()
            resp = await self.http.post(
                f"{self.s.ebay_api_base}/identity/v1/oauth2/token",
                headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "scope": SCOPE},
            )
            if resp.status_code != 200:
                raise EbayError(f"OAuth failed ({resp.status_code}): {resp.text[:300]}")
            body = resp.json()
            self._token = body["access_token"]
            self._token_expiry = time.time() + int(body.get("expires_in", 7200))
            return self._token

    async def _get(self, path: str, params: dict[str, Any] | None = None, *, allow_404: bool = False) -> dict | None:
        token = await self._get_token()
        self.calls += 1
        resp = await self.http.get(
            f"{self.s.ebay_api_base}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": self.s.ebay_marketplace},
        )
        if resp.status_code == 429:
            raise EbayRateLimited("eBay API daily/rate limit reached")
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code >= 400:
            raise EbayError(f"GET {path} failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()

    # ---------- Browse ----------

    async def search(
        self,
        query: str,
        category_ids: list[str] | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
        fixed_price_only: bool = False,
        condition: str | None = None,  # "NEW" | "USED"
    ) -> list[dict]:
        if category_ids and len(category_ids) > 1:
            # Browse search accepts one category per request; search each and interleave.
            kw = {"limit": limit, "offset": offset, "fixed_price_only": fixed_price_only, "condition": condition}
            per_cat = await asyncio.gather(*(self.search(query, [c], **kw) for c in category_ids))
            merged, seen = [], set()
            for row in zip_longest(*per_cat):
                for item in row:
                    if item and item["item_id"] not in seen:
                        seen.add(item["item_id"])
                        merged.append(item)
            return merged[:limit]

        filters = []
        if fixed_price_only:
            filters.append("buyingOptions:{FIXED_PRICE}")
        if condition:
            filters.append(f"conditions:{{{condition}}}")
        params: dict[str, Any] = {"q": query, "limit": min(limit, 200), "offset": offset}
        if category_ids:
            params["category_ids"] = ",".join(category_ids)
        if filters:
            params["filter"] = ",".join(filters)

        key = make_key("search", {"m": self.s.ebay_marketplace, **params})
        if (hit := await self.cache.get(key)) is not None:
            return hit
        body = await self._get("/buy/browse/v1/item_summary/search", params) or {}
        items = [normalise_summary(x) for x in body.get("itemSummaries", [])]
        await self.cache.set(key, items, self.s.ttl_ebay_search)
        return items

    async def get_items(self, item_ids: list[str]) -> list[dict]:
        """Full item details (aspects, sold counts). Cached per item; uses the
        getItems batch endpoint when available, else parallel getItem calls."""
        results: dict[str, dict] = {}
        missing = []
        for iid in item_ids:
            hit = await self.cache.get(make_key("item", {"m": self.s.ebay_marketplace, "id": iid}))
            if hit is not None:
                results[iid] = hit
            else:
                missing.append(iid)

        fetched: list[dict] = []
        if missing and self._batch_supported is not False:
            try:
                for i in range(0, len(missing), BATCH_SIZE):
                    chunk = missing[i : i + BATCH_SIZE]
                    body = await self._get("/buy/browse/v1/item/", {"item_ids": ",".join(chunk)}) or {}
                    fetched += [normalise_item(x) for x in body.get("items", [])]
                self._batch_supported = True
            except EbayRateLimited:
                raise
            except EbayError:
                self._batch_supported = False  # not enabled for this keyset; fall back
                fetched = []

        if missing and self._batch_supported is False:
            sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

            async def one(iid: str) -> dict | None:
                async with sem:
                    body = await self._get(f"/buy/browse/v1/item/{iid}", allow_404=True)
                    return normalise_item(body) if body else None

            fetched = [x for x in await asyncio.gather(*(one(i) for i in missing)) if x]

        for item in fetched:
            results[item["item_id"]] = item
            await self.cache.set(
                make_key("item", {"m": self.s.ebay_marketplace, "id": item["item_id"]}), item, self.s.ttl_ebay_item
            )
        return [results[i] for i in item_ids if i in results]

    # ---------- Taxonomy ----------

    async def category_tree_id(self) -> str:
        key = make_key("tree", self.s.ebay_marketplace)
        if (hit := await self.cache.get(key)) is not None:
            return hit
        body = await self._get(
            "/commerce/taxonomy/v1/get_default_category_tree_id", {"marketplace_id": self.s.ebay_marketplace}
        )
        tree_id = body["categoryTreeId"]
        await self.cache.set(key, tree_id, self.s.ttl_taxonomy)
        return tree_id

    async def category_suggestions(self, query: str) -> list[dict]:
        """[{category_id, name, ancestor_ids}] best first."""
        tree = await self.category_tree_id()
        key = make_key("catsuggest", {"t": tree, "q": query})
        if (hit := await self.cache.get(key)) is not None:
            return hit
        body = await self._get(f"/commerce/taxonomy/v1/category_tree/{tree}/get_category_suggestions", {"q": query})
        out = [
            {
                "category_id": s["category"]["categoryId"],
                "name": s["category"]["categoryName"],
                "ancestor_ids": [a["categoryId"] for a in s.get("categoryTreeNodeAncestors", [])],
            }
            for s in (body or {}).get("categorySuggestions", [])
        ]
        await self.cache.set(key, out, self.s.ttl_taxonomy)
        return out

    async def item_aspects(self, category_id: str) -> list[dict]:
        """Official item specifics for a leaf category: [{name, required, mode, values}]."""
        tree = await self.category_tree_id()
        key = make_key("aspects", {"t": tree, "c": category_id})
        if (hit := await self.cache.get(key)) is not None:
            return hit
        body = await self._get(
            f"/commerce/taxonomy/v1/category_tree/{tree}/get_item_aspects_for_category", {"category_id": category_id}
        )
        out = []
        for a in (body or {}).get("aspects", []):
            c = a.get("aspectConstraint", {})
            out.append(
                {
                    "name": a["localizedAspectName"],
                    "required": bool(c.get("aspectRequired")),
                    "recommended": c.get("aspectUsage") == "RECOMMENDED",
                    "mode": c.get("aspectMode", "FREE_TEXT"),
                    "values": [v["localizedValue"] for v in a.get("aspectValues", [])[:30]],
                }
            )
        await self.cache.set(key, out, self.s.ttl_taxonomy)
        return out

    async def aclose(self) -> None:
        await self.http.aclose()


# ---------- normalisation ----------


def _price(x: dict) -> tuple[float | None, str | None]:
    p = x.get("price") or {}
    try:
        return float(p["value"]), p.get("currency")
    except (KeyError, TypeError, ValueError):
        return None, None


def normalise_summary(x: dict) -> dict:
    price, currency = _price(x)
    cats = x.get("categories") or []
    return {
        "item_id": x["itemId"],
        "title": x.get("title", ""),
        "price": price,
        "currency": currency,
        "condition": x.get("condition"),
        "condition_id": x.get("conditionId"),
        "category_id": (x.get("leafCategoryIds") or [cats[0]["categoryId"] if cats else None])[0],
        "buying_options": x.get("buyingOptions", []),
        "image_url": (x.get("image") or {}).get("imageUrl"),
        "item_url": x.get("itemWebUrl"),
    }


def normalise_item(x: dict) -> dict:
    out = normalise_summary(x)
    out["category_id"] = x.get("categoryId", out["category_id"])
    out["category_path"] = x.get("categoryPath")
    out["aspects"] = {a["name"]: a["value"] for a in x.get("localizedAspects", []) if a.get("name")}
    if x.get("brand") and "Brand" not in out["aspects"]:
        out["aspects"]["Brand"] = x["brand"]
    sold = available = None
    for est in x.get("estimatedAvailabilities", []):
        if est.get("estimatedSoldQuantity") is not None:
            sold = (sold or 0) + int(est["estimatedSoldQuantity"])
        if est.get("estimatedAvailableQuantity") is not None:
            available = (available or 0) + int(est["estimatedAvailableQuantity"])
    out["sold_quantity"] = sold
    out["available_quantity"] = available
    out["short_description"] = x.get("shortDescription")
    return out
