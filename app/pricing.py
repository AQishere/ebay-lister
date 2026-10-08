"""Price range from current listings.

These are ASKING prices of active listings, not sold prices: the Browse API
has no sold history. Label them that way everywhere.
"""

from statistics import quantiles


def condition_bucket(condition_id: str | int | None) -> str | None:
    """eBay condition IDs: 1000-1999 new, 2000-2999 refurbished, 3000-6999 used, 7000 for parts."""
    try:
        cid = int(condition_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if cid < 2000:
        return "NEW"
    if cid < 3000:
        return "REFURBISHED"
    if cid < 7000:
        return "USED"
    return "PARTS"


def weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    half = sum(weights) / 2
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def comparable_items(items: list[dict], condition: str | None) -> list[dict]:
    """Priced listings in the same condition bucket (all conditions if fewer than 3
    match) and the most common currency."""
    same = [i for i in items if i.get("price") and (not condition or condition_bucket(i.get("condition_id")) == condition)]
    if len(same) < 3:  # too few to filter by condition; use everything rather than nothing
        same = [i for i in items if i.get("price")]
    if not same:
        return []
    currencies = {i.get("currency") for i in same}
    currency = max(currencies, key=lambda c: sum(i.get("currency") == c for i in same))
    return [i for i in same if i.get("currency") == currency]


def price_summary(items: list[dict], condition: str | None) -> dict:
    """items: normalised eBay items (with optional sold_quantity)."""
    same = comparable_items(items, condition)
    if not same:
        return {"count": 0, "label": "No comparable listings found"}

    currency = same[0].get("currency")
    prices = [i["price"] for i in same]
    if len(prices) >= 4:
        p25, median, p75 = quantiles(prices, n=4)
    else:
        p25, median, p75 = min(prices), sorted(prices)[len(prices) // 2], max(prices)
    weights = [1 + (i.get("sold_quantity") or 0) for i in same]

    return {
        "count": len(prices),
        "currency": currency,
        "p25": round(p25, 2),
        "median": round(median, 2),
        "p75": round(p75, 2),
        "sales_weighted_median": round(weighted_median(prices, weights), 2),
        "condition": condition,
        "label": "Asking prices of current listings (not sold prices)",
    }
