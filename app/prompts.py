"""Prompts for the Groq/Ollama calls. The title prompt lives in title_format.py."""

import json

EXTRACT_SYSTEM = """You turn a seller's rough notes about an item into structured data for an eBay listing.
Supported categories: shoes, phones, video_games. Anything else is "other".

Return a JSON object with exactly these keys:
- "category_group": one of "shoes", "phones", "video_games", "other"
- "search_query": 2-6 keywords a buyer would type to find this exact item on eBay (brand, model, key specifics). No condition words, no size.
- "condition": "NEW" or "USED", or null when the notes don't say (don't assume)
- "condition_text": short eBay-style condition, e.g. "New with box", "Pre-owned", "Used - Good", or null when not stated
- "attributes": object of item specifics stated or directly implied by the notes, using eBay aspect names
  (e.g. "Brand", "Model", "Department", "US Shoe Size", "Color", "Storage Capacity", "Network", "Platform", "Game Name").
  Department for shoes is "Men", "Women", "Unisex Adult", "Boys", "Girls" or "Unisex Kids" when the notes say so.
  All values are strings. Never guess values that are not in the notes.
- "missing_info": list of things a buyer would expect that the notes do not say (e.g. "size", "storage", "battery health")
- "follow_ups": up to 3 multiple-choice questions for the most useful missing_info items, so the seller can answer
  with one tap. Ask about condition first if the notes don't state it. Each item is
  {"question": "Battery health?", "options": ["90% or more", "80-89%", "Below 80%"]} with 2-5 short options.
  Never ask about something the notes already say. Use [] when nothing important is missing.
Notes can be very short (e.g. "iphone 13"); extract what is there and leave the rest to missing_info and follow_ups."""

LISTING_SYSTEM = """You write eBay item specifics and descriptions.

Rules:
- Facts about the item come ONLY from the seller's notes and extracted attributes.
- The similar listings are for wording, aspect names and value spelling only. Never copy facts from them
  (size, colour, storage, defects) unless the seller's notes state the same thing.
- Prefer the allowed values for an aspect when one matches.
- Description: plain text, 3-6 short lines or bullets: what it is, key specs, honest condition, what's included.
  Write it for a buyer. Describe only what is known; never mention missing, unknown or "not provided" details,
  and never invent condition, wear, accessories or included items. Shorter is fine when the notes are short.
  No shipping, returns or payment promises. No ALL CAPS, no emojis.

Return a JSON object with exactly these keys:
- "item_specifics": object of aspect name -> value
- "description": string
- "missing_required": list of required aspect names you could not fill from the notes"""


def extract_messages(notes: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": f"Seller notes:\n{notes}"}]


def listing_messages(
    notes: str,
    extracted: dict,
    category_name: str | None,
    aspects: list[dict],
    examples: list[dict],
) -> list[dict[str, str]]:
    aspect_lines = []
    for a in aspects:
        if not (a["required"] or a["recommended"]):
            continue
        tag = "REQUIRED" if a["required"] else "recommended"
        vals = f" (allowed e.g.: {', '.join(a['values'][:12])})" if a["values"] else ""
        aspect_lines.append(f"- {a['name']} [{tag}]{vals}")
    example_lines = [
        f"- {ex['title']} | " + "; ".join(f"{k}: {v}" for k, v in list((ex.get('aspects') or {}).items())[:10])
        for ex in examples[:5]
    ]
    user = "\n".join(
        [
            f"Seller notes:\n{notes}",
            "",
            f"Extracted attributes: {json.dumps(extracted.get('attributes', {}), ensure_ascii=False)}",
            f"Condition: {extracted.get('condition_text') or 'not stated (do not guess)'}",
            f"Category: {category_name or extracted.get('category_group')}",
            "",
            "Item specifics for this category:" if aspect_lines else "No official aspect list available; use common eBay aspect names.",
            *aspect_lines[:40],
            "",
            "Similar real listings (style reference only):" if example_lines else "",
            *example_lines,
        ]
    )
    return [{"role": "system", "content": LISTING_SYSTEM}, {"role": "user", "content": user}]
