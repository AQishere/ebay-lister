import httpx
import pytest

from app.cache import Cache, make_key, normalise
from app.ebay_client import EbayClient, normalise_item
from app.llm import LLMError, parse_json, provider_config
from app.pricing import condition_bucket, price_summary, weighted_median
from app.retrieval import rerank_by_sales
from app.title_format import build_title_messages, title_specifics
from app.validators import clean_title
from tests.conftest import ITEM, SUMMARY, FakeCollection

# ---------- title validation ----------


def test_clean_title_trims_to_80_on_word_boundary():
    raw = "Nike Air Max 90 White Black Mens US Size 10 Running Shoes Trainers Sneakers Classic Retro OG"
    title, warnings = clean_title(raw)
    assert len(title) <= 80
    assert raw.startswith(title)
    assert not title.endswith(" ")
    assert any("trimmed" in w for w in warnings)


def test_clean_title_strips_prefix_quotes_and_spam():
    title, warnings = clean_title('Title: "L@@K Nike Dunk Low Panda Size 9!!"')
    assert title == "Nike Dunk Low Panda Size 9"
    assert warnings


@pytest.mark.parametrize(
    "title, support, expected, removed",
    [
        # copied from similar listings, not in the notes -> removed
        ("Apple iPhone 13 Unlocked Smartphone", "iphone 13", "Apple iPhone 13 Smartphone", ["Unlocked"]),
        ("Apple iPhone 13 128GB - Very Good Condition | AT&T", "iphone 13",
         "Apple iPhone 13", ["128GB", "Very", "Good", "Condition", "AT&T"]),
        ("Mario Kart 8 Deluxe Nintendo Switch Pre-owned Game", "mario kart 8 deluxe switch, cartridge and case",
         "Mario Kart 8 Deluxe Nintendo Switch Game", ["Pre-owned"]),
        ("Samsung Galaxy S23 (Unlocked) T-Mobile", "samsung s23", "Samsung Galaxy S23", ["Unlocked", "T-Mobile"]),
        # supported by the notes or the seller's answers -> kept
        ("Apple iPhone 13 128GB Unlocked Midnight", "iphone 13\nStorage Capacity: 128 GB\nNetwork: Unlocked",
         "Apple iPhone 13 128GB Unlocked Midnight", []),
        ("Jordan 1 Retro High OG Chicago US10 Used Like New", "jordan 1 chicago size 10 Used - Like New",
         "Jordan 1 Retro High OG Chicago US10 Used Like New", []),
        ("New Balance 550 White Green", "new balance 550 white green", "New Balance 550 White Green", []),
    ],
)
def test_strip_unsupported_claims(title, support, expected, removed):
    from app.validators import strip_unsupported_claims

    assert strip_unsupported_claims(title, support) == (expected, removed)


# ---------- cache ----------


def test_cache_key_normalises_whitespace_and_case():
    assert normalise("  Nike   AIR max ") == "nike air max"
    assert make_key("x", "Nike  Air Max") == make_key("x", "nike air max")
    assert make_key("x", {"a": 1, "b": 2}) == make_key("x", {"b": 2, "a": 1})


async def test_cache_hit_miss_and_expiry():
    cache = Cache(FakeCollection())
    assert await cache.get("k") is None
    await cache.set("k", {"v": 1}, ttl_seconds=60)
    assert await cache.get("k") == {"v": 1}
    await cache.set("old", 1, ttl_seconds=-1)
    assert await cache.get("old") is None
    assert (cache.hits, cache.misses) == (1, 2)


async def test_cache_disabled_without_db():
    cache = Cache(None)
    await cache.set("k", 1, 60)
    assert await cache.get("k") is None


# ---------- eBay parsing ----------


def test_normalise_item_extracts_aspects_and_sold_counts():
    item = normalise_item(ITEM)
    assert item["aspects"]["Model"] == "Air Max 90"
    assert item["sold_quantity"] == 42
    assert item["available_quantity"] == 3
    assert item["price"] == 85.0
    assert item["category_id"] == "15709"


def test_normalise_item_without_availability_has_no_sold_count():
    item = normalise_item({**ITEM, "estimatedAvailabilities": []})
    assert item["sold_quantity"] is None


def _listing(title, price, sold=0, cid="3000", aspects=None):
    return {"title": title, "price": price, "currency": "USD", "sold_quantity": sold, "condition_id": cid,
            "aspects": aspects or {}}


def test_price_plan_uses_selling_listings_and_charm_prices():
    from app.insights import charm, price_plan

    items = [_listing("a", p, s) for p, s in [(200, 0), (220, 50), (230, 40), (240, 5), (260, 0), (300, 0)]]
    items.append(_listing("new one", 400, 0, cid="1000"))  # other condition, ignored
    plan = price_plan(items, "USED")
    assert plan["fast"] <= plan["recommended"] <= plan["max"]
    assert plan["recommended"] == 219.99  # half of the units sold were listed at $220 or less
    assert plan["units_sold"] == 95 and plan["units_sold_at_or_below_recommended"] == 50
    assert charm(239.4) == 238.99 and charm(8.5) == 8.5
    assert price_plan(items[:2], "USED") == {}  # too few listings


def test_title_checks_match_values_loosely_and_list_unknown_required_last():
    from app.insights import title_checks

    specifics = {"Brand": "Apple", "Model": "iPhone 13", "Storage Capacity": "128 GB", "Color": "Midnight", "Network": "Unlocked"}
    checks = title_checks("phones", "Apple iPhone 13 128GB Unlocked", specifics, ["Lock Status"])
    assert [(c["aspect"], c["in_title"]) for c in checks] == [
        ("Brand", True), ("Model", True), ("Storage Capacity", True),  # '128 GB' matches '128GB'
        ("Color", False), ("Network", True), ("Lock Status", False),
    ]
    assert checks[-1]["value"] is None


def test_question_options_prefer_short_ebay_list_then_similar_listings_then_llm():
    from app.pipeline import _aspect_options

    long_list = [f"{i} KB" for i in range(30)]  # eBay's storage list starts at '1 KB'
    examples = [{"aspects": {"Storage Capacity": v}} for v in ["128 GB", "256 GB", "128 GB", "512 GB", "128GB"]]
    assert _aspect_options("Department", ["Men", "Women"], examples, None) == ["Men", "Women"]
    assert _aspect_options("Storage Capacity", long_list, examples, ["1 TB", "2 TB"]) == ["128 GB", "256 GB", "512 GB"]
    assert _aspect_options("Storage Capacity", long_list, [], ["128 GB", "256 GB"]) == ["128 GB", "256 GB"]
    assert _aspect_options("Color", long_list, [], None) == []  # free text


async def test_search_sends_one_category_per_request(settings):
    """Browse search rejects more than one category_ids value (errorId 12030)."""
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        cats = request.url.params["category_ids"]
        sent.append(cats)
        if "," in cats:
            return httpx.Response(400, json={"errors": [{"errorId": 12030}]})
        ids = {"93427": ["a", "shared", "b"], "3034": ["shared", "c"]}[cats]
        return httpx.Response(200, json={"itemSummaries": [{**SUMMARY, "itemId": i} for i in ids]})

    ebay = EbayClient(Cache(None), settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    items = await ebay.search("nike", ["93427", "3034"], limit=4)
    assert sorted(sent) == ["3034", "93427"]
    assert [x["item_id"] for x in items] == ["a", "shared", "c", "b"]  # interleaved, deduped, capped


# ---------- llm.py provider switch ----------


def test_provider_switch(settings):
    url, headers, model = provider_config(settings)
    assert "groq.com" in url and headers["Authorization"] == "Bearer gk"
    local = settings.model_copy(update={"llm_provider": "ollama"})
    url, headers, model = provider_config(local)
    assert url == "http://localhost:11434/v1/chat/completions" and headers == {} and model == "qwen2.5:7b"
    with pytest.raises(LLMError):
        provider_config(settings.model_copy(update={"groq_api_key": ""}))


async def test_reasoning_model_gets_token_budget_and_effort(settings):
    import json as _json

    import httpx

    from app.llm import LLM, REASONING_TOKEN_BUDGET

    sent = {}

    def handler(request):
        sent.update(_json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Nike Air Max 90"}}]})

    s = settings.model_copy(update={"groq_model": "openai/gpt-oss-120b"})
    llm = LLM(Cache(None), s, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await llm.chat([{"role": "user", "content": "hi"}], max_tokens=60) == "Nike Air Max 90"
    assert sent["max_tokens"] == 60 + REASONING_TOKEN_BUDGET
    assert sent["reasoning_effort"] == "low"


async def test_empty_answer_raises(settings):
    import httpx

    from app.llm import LLM

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    llm = LLM(Cache(None), settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMError):
        await llm.chat([{"role": "user", "content": "hi"}])


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


# ---------- pricing + ranking ----------


def test_condition_bucket():
    assert condition_bucket("1000") == "NEW"
    assert condition_bucket(2010) == "REFURBISHED"
    assert condition_bucket("3000") == "USED"
    assert condition_bucket("7000") == "PARTS"
    assert condition_bucket(None) is None


def test_price_summary_filters_condition_and_weights_sales():
    items = [
        {"price": 100, "currency": "USD", "condition_id": "1000"},
        {"price": 50, "currency": "USD", "condition_id": "3000", "sold_quantity": 0},
        {"price": 60, "currency": "USD", "condition_id": "3000", "sold_quantity": 0},
        {"price": 70, "currency": "USD", "condition_id": "3000", "sold_quantity": 30},
        {"price": 80, "currency": "USD", "condition_id": "3000", "sold_quantity": 0},
    ]
    s = price_summary(items, "USED")
    assert s["count"] == 4
    assert s["sales_weighted_median"] == 70
    assert "not sold prices" in s["label"]
    assert weighted_median([1, 2, 3], [1, 1, 10]) == 3


def test_rerank_prefers_selling_listings_at_similar_score():
    docs = [{"title": "a", "score": 0.90, "sold_quantity": 0}, {"title": "b", "score": 0.88, "sold_quantity": 200}]
    assert rerank_by_sales(docs)[0]["title"] == "b"


# ---------- shared title format ----------


def test_title_prompt_keeps_only_title_aspects_in_order():
    spec = title_specifics("shoes", {"UPC": "123", "US Shoe Size": "10", "Brand": "Nike", "Model": "Does not apply"})
    assert list(spec) == ["Brand", "US Shoe Size"]
    msgs = build_title_messages("shoes", "Athletic Shoes", "Pre-owned", {"Brand": "Nike"}, ["a", "b", "c", "d"])
    user = msgs[1]["content"]
    assert "Category: Athletic Shoes" in user and "- Brand: Nike" in user
    assert user.count("\n- ") == 4  # 1 specific + 3 examples (capped)


# ---------- embeddings (Voyage) ----------


def _voyage_handler(sent: list, fail_first: int = 0):
    import json as _json

    import httpx

    state = {"fails": fail_first}

    def handler(request):
        if state["fails"]:
            state["fails"] -= 1
            return httpx.Response(429, json={"detail": "rate limit"})
        body = _json.loads(request.content)
        sent.append(body)
        data = [{"index": i, "embedding": [float(i), 1.0]} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 7}})

    return handler


async def test_embedder_batches_and_sends_input_type(settings):
    import httpx

    from app import embeddings
    from app.embeddings import Embedder

    sent: list = []
    emb = Embedder(Cache(None), settings, httpx.AsyncClient(transport=httpx.MockTransport(_voyage_handler(sent))))
    vecs = await emb.embed([f"t{i}" for i in range(embeddings.BATCH_SIZE + 5)], "document")
    assert len(vecs) == embeddings.BATCH_SIZE + 5
    assert [len(b["input"]) for b in sent] == [embeddings.BATCH_SIZE, 5]
    assert sent[0]["input_type"] == "document" and sent[0]["output_dimension"] == settings.embed_dim
    assert emb.tokens_used == 14


async def test_embedder_retries_rate_limit_and_caches_queries(settings, monkeypatch):
    import httpx

    from app import embeddings
    from app.embeddings import Embedder

    async def no_sleep(_):
        return None

    monkeypatch.setattr(embeddings.asyncio, "sleep", no_sleep)
    sent: list = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(_voyage_handler(sent, fail_first=2)))
    emb = Embedder(Cache(FakeCollection()), settings, http)
    assert await emb.embed_query("nike air max") == [0.0, 1.0]
    assert await emb.embed_query("Nike  Air Max") == [0.0, 1.0]  # normalised -> cache hit
    assert len(sent) == 1 and sent[0]["input_type"] == "query"


async def test_embedder_requires_key(settings):
    from app.embeddings import Embedder, EmbeddingError

    emb = Embedder(Cache(None), settings.model_copy(update={"voyage_api_key": ""}))
    with pytest.raises(EmbeddingError):
        await emb.embed(["x"])


async def test_rate_limit_window_counts_resets_and_fails_open():
    from app.ratelimit import RateLimited, enforce, hit

    col = FakeCollection()
    assert await hit(col, "k", 2, 60, now=1000.0) is None
    assert await hit(col, "k", 2, 60, now=1001.0) is None
    assert await hit(col, "k", 2, 60, now=1010.0) == 10  # 3rd in window 960-1020 -> 10 s left
    assert await hit(col, "k", 2, 60, now=1021.0) is None  # next window

    with pytest.raises(RateLimited):
        await enforce(col, [("x", 0, 60, "per minute")])
    await enforce(None, [("x", 0, 60, "per minute")])  # no database -> no limits

    class Broken:
        async def find_one_and_update(self, *a, **k):
            raise RuntimeError("mongo down")

    await enforce(Broken(), [("x", 0, 60, "per minute")])  # fails open, no crash
