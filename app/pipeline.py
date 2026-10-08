"""The request path: notes -> extraction -> category + retrieval -> (title || specifics) -> draft.

Market evidence (sold counts, price range) is a separate call so it never
slows down the draft.
"""

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.cache import Cache, Timer
from app.categories import GROUPS, category_ids
from app.config import Settings
from app.ebay_client import EbayClient
from app.llm import LLM
from app.models import DraftRequest
from app.insights import price_plan, title_checks
from app.pricing import price_summary
from app.prompts import extract_messages, listing_messages
from app.retrieval import embed_text, vector_search
from app.embeddings import Embedder, EmbeddingError
from app.title_format import build_title_messages
from app.validators import clean_title, strip_unsupported_claims

MIN_CORPUS_HITS = 3
EVIDENCE_ITEMS = 10


class UnsupportedCategory(Exception):
    pass


@dataclass
class Deps:
    settings: Settings
    db: AsyncDatabase | None
    ebay: EbayClient
    llm: LLM
    embedder: Embedder
    ebay_cache: Cache
    llm_cache: Cache


async def pick_category(ebay: EbayClient, group: str, query: str, marketplace: str) -> tuple[str | None, str | None]:
    """Best Taxonomy suggestion that sits inside the group's category subtree."""
    allowed = set(category_ids(marketplace, group))
    for s in await ebay.category_suggestions(query):
        if s["category_id"] in allowed or allowed & set(s["ancestor_ids"]):
            return s["category_id"], s["name"]
    return None, None


async def retrieve(deps: Deps, group: str, query_text: str, search_query: str) -> tuple[list[dict], str, list[str]]:
    """Corpus vector search first; live Browse search if the corpus is empty or embeddings fail."""
    warnings: list[str] = []
    m = deps.settings.ebay_marketplace
    if deps.db is not None:
        try:
            vector = await deps.embedder.embed_query(query_text)
            docs = await vector_search(deps.db, vector, group, m)
            if len(docs) >= MIN_CORPUS_HITS:
                return docs, "vector_search", warnings
            warnings.append("few corpus matches; used live eBay search")
        except EmbeddingError as e:
            warnings.append(f"embedding unavailable ({e}); used live eBay search")

    live = await deps.ebay.search(search_query, category_ids(m, group), limit=20)
    if not live:
        return [], "none", warnings
    # Summaries lack item specifics; fetch details for the few we show the LLM.
    detailed = await deps.ebay.get_items([x["item_id"] for x in live[:5]])
    return detailed or live[:5], "live_search", warnings


MAX_QUESTIONS = 4
MAX_OPTIONS = 12


def _parse_follow_ups(follow_ups: object) -> list[tuple[str, str, list[str]]]:
    """(field, question, options) from the LLM; malformed items are dropped."""
    out = []
    for f in follow_ups if isinstance(follow_ups, list) else []:
        if not isinstance(f, dict):
            continue
        question = str(f.get("question") or "").strip()
        options = [str(o).strip() for o in f.get("options") or [] if str(o).strip()][:5]
        if question and len(options) >= 2:
            out.append((question.rstrip("?").strip(), question, options))
    return out


def _aspect_options(name: str, allowed: list[str], examples: list[dict], llm_options: list[str] | None) -> list[str]:
    """Tappable answers for a required aspect. eBay's allowed list is only useful when
    short (it is not sorted by popularity: storage starts at '1 KB'), so otherwise use
    the values similar listings actually have, then the LLM's suggestions."""
    if allowed and len(allowed) <= MAX_OPTIONS:
        return allowed
    seen = Counter(str(v).strip() for e in examples if (v := (e.get("aspects") or {}).get(name)))
    common, keys = [], set()
    for v, _ in seen.most_common():
        key = v.lower().replace(" ", "")  # '128 GB' and '128GB' are one option
        if key not in keys:
            keys.add(key)
            common.append(v)
    common = common[:MAX_OPTIONS]
    if len(common) >= 2:
        return common
    return llm_options or []  # empty -> free-text answer


def build_questions(aspects: list[dict], missing_required: list[str], follow_ups: object, examples: list[dict]) -> list[dict]:
    """Missing eBay-required aspects first, then the LLM's questions for other gaps."""
    allowed = {a["name"]: a["values"] for a in aspects}
    llm = _parse_follow_ups(follow_ups)
    llm_by_field = {field.lower(): options for field, _, options in llm}
    questions = [
        {
            "field": name,
            "question": f"{name}?",
            "options": _aspect_options(name, allowed.get(name, []), examples, llm_by_field.get(name.lower())),
            "required": True,
        }
        for name in missing_required
    ]
    asked = {name.lower() for name in missing_required}
    for field, question, options in llm:
        if field.lower() not in asked:
            asked.add(field.lower())
            questions.append({"field": field, "question": question, "options": options, "required": False})
    return questions[:MAX_QUESTIONS]


async def generate_draft(req: DraftRequest, deps: Deps) -> dict:
    timer = Timer()
    warnings: list[str] = []

    with timer.step("extract"):
        ex = await deps.llm.chat_json(extract_messages(req.notes), temperature=0.0)
    group = req.category_group or ex.get("category_group")
    if group not in GROUPS:
        raise UnsupportedCategory("Only shoes, phones and video games are supported right now.")
    attributes = {str(k): str(v) for k, v in (ex.get("attributes") or {}).items() if v not in (None, "")}
    search_query = ex.get("search_query") or req.notes[:80]
    query_text = embed_text(group, search_query, attributes)

    async def category_step() -> tuple[str | None, str | None, list[dict]]:
        with timer.step("taxonomy"):
            cid, cname = await pick_category(deps.ebay, group, search_query, deps.settings.ebay_marketplace)
            aspects = await deps.ebay.item_aspects(cid) if cid else []
        return cid, cname, aspects

    async def retrieval_step() -> tuple[list[dict], str, list[str]]:
        with timer.step("retrieval"):
            return await retrieve(deps, group, query_text, search_query)

    (cid, cname, aspects), (examples, source, rw) = await asyncio.gather(category_step(), retrieval_step())
    warnings += rw
    if not cid:
        warnings.append("could not match an eBay leaf category; specifics are unguided")

    async def title_step() -> str:
        with timer.step("title"):
            msgs = build_title_messages(
                group, cname, ex.get("condition_text"), attributes, [e["title"] for e in examples]
            )
            return await deps.llm.chat(msgs, temperature=0.2, max_tokens=60)

    async def listing_step() -> dict:
        with timer.step("specifics_description"):
            return await deps.llm.chat_json(listing_messages(req.notes, ex, cname, aspects, examples), temperature=0.3)

    raw_title, listing = await asyncio.gather(title_step(), listing_step())
    title, cw = clean_title(raw_title)
    warnings += cw
    support = " ".join([req.notes, ex.get("condition_text") or "", *attributes.values()])
    title, removed = strip_unsupported_claims(title, support)
    if removed:
        warnings.append(f"Removed from the title because your notes don't say it: {', '.join(removed)}")

    specifics = {str(k): str(v) for k, v in (listing.get("item_specifics") or {}).items() if v not in (None, "")}
    if aspects:
        allowed = {a["name"] for a in aspects}
        dropped = sorted(set(specifics) - allowed)
        specifics = {k: v for k, v in specifics.items() if k in allowed}
        if dropped:
            warnings.append(f"dropped aspects not valid for this category: {', '.join(dropped)}")
        # Facts extracted straight from the notes fill anything the specifics call left out.
        specifics = {**{k: v for k, v in attributes.items() if k in allowed}, **specifics}
    required = [a["name"] for a in aspects if a["required"]]
    missing_required = [n for n in required if n not in specifics]

    draft = {
        "title": title,
        "item_specifics": specifics,
        "description": str(listing.get("description", "")).strip(),
        "category": {"id": cid, "name": cname, "group": group},
        "condition": ex.get("condition_text"),
        "condition_bucket": ex.get("condition"),
        "search_query": search_query,
        "missing_required": missing_required,
        "missing_info": [str(x) for x in ex.get("missing_info") or []],
        "questions": build_questions(aspects, missing_required, ex.get("follow_ups"), examples),
        "title_checks": title_checks(group, title, specifics, missing_required),
        "examples": [
            {
                "title": e["title"],
                "price": e.get("price"),
                "currency": e.get("currency"),
                "sold_quantity": e.get("sold_quantity"),
                "item_url": e.get("item_url"),
                "score": round(e["rank_score"], 4) if "rank_score" in e else None,
            }
            for e in examples
        ],
        "retrieval_source": source,
        "warnings": warnings,
        "timings_ms": timer.steps,
    }

    draft_id = str(ObjectId())
    if deps.db is not None:
        await deps.db.drafts.insert_one(
            {"_id": ObjectId(draft_id), **draft, "notes": req.notes, "marketplace": deps.settings.ebay_marketplace,
             "created_at": datetime.now(UTC)}
        )
    return {"draft_id": draft_id, **draft}


async def market_evidence(draft: dict, deps: Deps) -> dict:
    """Second, slower call: live listings + sold counts + price range for a saved draft."""
    m = deps.settings.ebay_marketplace
    group = draft["category"]["group"]
    cats = [draft["category"]["id"]] if draft["category"].get("id") else category_ids(m, group)
    bucket = draft.get("condition_bucket")

    live = await deps.ebay.search(draft["search_query"], cats, limit=50)
    fixed = [x for x in live if "FIXED_PRICE" in x.get("buying_options", [])][:EVIDENCE_ITEMS]
    detailed = {d["item_id"]: d for d in await deps.ebay.get_items([x["item_id"] for x in fixed])}
    merged = [detailed.get(x["item_id"], x) for x in live]

    evidence = sorted(detailed.values(), key=lambda d: d.get("sold_quantity") or 0, reverse=True)
    return {
        "draft_id": str(draft["_id"]),
        "price": price_summary(merged, bucket),
        "plan": price_plan(merged, bucket),
        "evidence": [
            {
                "title": e["title"],
                "price": e.get("price"),
                "currency": e.get("currency"),
                "sold_quantity": e.get("sold_quantity"),
                "item_url": e.get("item_url"),
            }
            for e in evidence
        ],
    }
