"""Check eBay API access and the fields the app relies on, with real API calls.

    python -m scripts.verify_ebay

Checks: OAuth, Browse search, getItem's estimatedSoldQuantity, getItems batch
support, Taxonomy category IDs + aspects for each group. Uses no cache and ~15 calls.
"""

import asyncio
import json

from app.cache import Cache
from app.categories import GROUPS, SEED_QUERIES, category_ids
from app.config import get_settings
from app.ebay_client import EbayClient, EbayError


def show(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK ' if ok else 'XX '}] {label}" + (f"  -> {detail}" if detail else ""))


async def main() -> None:
    s = get_settings()
    ebay = EbayClient(Cache(None), s)
    print(f"Marketplace {s.ebay_marketplace}, env {s.ebay_env}\n")

    try:
        await ebay._get_token()
        show("OAuth client-credentials token", True)
    except EbayError as e:
        show("OAuth client-credentials token", False, str(e))
        return

    # Search + sold counts on multi-quantity fixed-price listings
    raw = await ebay._get(
        "/buy/browse/v1/item_summary/search",
        {"q": "iphone 13 case", "limit": 10, "filter": "buyingOptions:{FIXED_PRICE}"},
    )
    summaries = raw.get("itemSummaries", [])
    show("Browse search", bool(summaries), f"{raw.get('total')} total results")
    ids = [x["itemId"] for x in summaries[:5]]

    sold_found = 0
    for iid in ids:
        item = await ebay._get(f"/buy/browse/v1/item/{iid}")
        est = item.get("estimatedAvailabilities", [])
        if any("estimatedSoldQuantity" in e for e in est):
            sold_found += 1
        if iid == ids[0]:
            print("    sample estimatedAvailabilities:", json.dumps(est)[:300])
            print("    sample localizedAspects:", [a["name"] for a in item.get("localizedAspects", [])][:12])
    show("getItem returns estimatedSoldQuantity", sold_found > 0, f"{sold_found}/{len(ids)} items had it")

    try:
        batch = await ebay._get("/buy/browse/v1/item/", {"item_ids": ",".join(ids)})
        items = batch.get("items", [])
        has_sold = sum(any("estimatedSoldQuantity" in e for e in i.get("estimatedAvailabilities", [])) for i in items)
        show("getItems batch endpoint", bool(items), f"{len(items)} items, {has_sold} with sold counts")
    except EbayError as e:
        show("getItems batch endpoint", False, f"{e} (client falls back to parallel getItem)")

    # Taxonomy
    tree = await ebay.category_tree_id()
    show("Taxonomy category tree", True, f"tree id {tree}")
    for group in GROUPS:
        expected = set(category_ids(s.ebay_marketplace, group))
        sugg = await ebay.category_suggestions(SEED_QUERIES[group][0])
        if not sugg:
            show(f"{group}: category suggestions", False, "none returned")
            continue
        top = sugg[0]
        inside = top["category_id"] in expected or bool(expected & set(top["ancestor_ids"]))
        show(
            f"{group}: top suggestion inside configured IDs {sorted(expected)}",
            inside,
            f"{top['name']} ({top['category_id']}), ancestors {top['ancestor_ids']}",
        )
        aspects = await ebay.item_aspects(top["category_id"])
        req = [a["name"] for a in aspects if a["required"]]
        show(f"{group}: item aspects", bool(aspects), f"{len(aspects)} aspects, required: {req}")

    print(f"\nUsed {ebay.calls} API calls.")
    await ebay.aclose()


if __name__ == "__main__":
    asyncio.run(main())
