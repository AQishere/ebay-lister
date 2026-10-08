"""The title prompt: category, condition and the title-relevant specifics, plus a
few similar titles as style examples. Used by app/pipeline.py."""

SYSTEM = (
    "You write eBay listing titles. Use at most 80 characters. Put the most searched "
    "keywords first (brand, model, key specifics). Use only facts given in Condition and Specifics; "
    "similar titles show style only, so never copy their storage, size, colour or condition. "
    "If condition is not specified, leave it out. "
    "No emojis, no ALL CAPS words except brand/model codes, no filler like 'L@@K' or 'WOW'. "
    "Reply with the title only."
)

# Aspects worth putting in a title, in priority order. US and GB spellings both listed.
TITLE_ASPECTS: dict[str, list[str]] = {
    "shoes": [
        "Brand", "Product Line", "Model", "Style", "Style Code", "Department",
        "US Shoe Size", "UK Shoe Size", "EU Shoe Size", "Color", "Colour", "Type", "Upper Material",
    ],
    "phones": [
        "Brand", "Model", "Storage Capacity", "Color", "Colour", "Network", "Lock Status",
        "Carrier", "RAM", "Connectivity",
    ],
    "video_games": [
        "Game Name", "Platform", "Edition", "Region Code", "Publisher", "Release Year", "Rating", "Genre",
    ],
}
MAX_EXAMPLES = 3


def title_specifics(group: str, aspects: dict[str, str]) -> dict[str, str]:
    """Keep only title-relevant aspects, in priority order, skipping empty/'Does not apply'."""
    out = {}
    for name in TITLE_ASPECTS.get(group, []):
        value = aspects.get(name)
        if value and str(value).strip().lower() not in {"does not apply", "n/a", "unbranded", "-"}:
            out[name] = str(value).strip()
    return out


def build_title_messages(
    group: str,
    category_name: str | None,
    condition: str | None,
    specifics: dict[str, str],
    examples: list[str],
) -> list[dict[str, str]]:
    lines = [f"Category: {category_name or group}", f"Condition: {condition or 'Not specified'}", "Specifics:"]
    lines += [f"- {k}: {v}" for k, v in title_specifics(group, specifics).items()] or ["- (none)"]
    if examples:
        lines.append("Titles of similar listings that sell:")
        lines += [f"- {t}" for t in examples[:MAX_EXAMPLES]]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]
