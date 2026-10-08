"""End-to-end pipeline with every external service mocked (no keys, no network)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cache import Cache
from app.ebay_client import EbayClient
from app.llm import LLM
from app.main import app
from app.models import DraftRequest
from app.pipeline import Deps, UnsupportedCategory, generate_draft
from app.embeddings import Embedder
from tests.conftest import FakeCollection, ebay_and_llm_handler


def make_deps(settings, calls):
    http = httpx.AsyncClient(transport=httpx.MockTransport(ebay_and_llm_handler(calls)))
    ebay_cache, llm_cache = Cache(FakeCollection()), Cache(FakeCollection())
    return Deps(
        settings=settings, db=None,
        ebay=EbayClient(ebay_cache, settings, http), llm=LLM(llm_cache, settings, http),
        embedder=Embedder(llm_cache, settings, http),
        ebay_cache=ebay_cache, llm_cache=llm_cache,
    )


async def test_generate_draft_end_to_end(settings):
    calls: list[str] = []
    deps = make_deps(settings, calls)
    draft = await generate_draft(DraftRequest(notes="nike air max 90 white size 10 worn twice"), deps)

    assert draft["title"].startswith("Nike Air Max 90")
    assert len(draft["title"]) <= 80
    assert draft["category"] == {"id": "15709", "name": "Athletic Shoes", "group": "shoes"}
    assert "Made Up Aspect" not in draft["item_specifics"]  # filtered by the Taxonomy aspect list
    assert draft["missing_required"] == ["Department"]
    # Required aspect first, then the valid LLM follow-up; duplicates and malformed items dropped.
    assert [(q["field"], q["required"]) for q in draft["questions"]] == [("Department", True), ("Original box included", False)]
    assert draft["questions"][1]["options"] == ["Yes", "No"]
    assert draft["retrieval_source"] == "live_search"
    assert draft["examples"][0]["sold_quantity"] == 42
    assert set(draft["timings_ms"]) >= {"extract", "taxonomy", "retrieval", "title", "specifics_description"}

    # Second identical request is served from cache: no new eBay or LLM calls.
    n = len(calls)
    deps2 = make_deps(settings, calls)
    deps2.ebay_cache, deps2.llm_cache = deps.ebay_cache, deps.llm_cache
    deps2.ebay.cache, deps2.llm.cache = deps.ebay_cache, deps.llm_cache
    await generate_draft(DraftRequest(notes="nike air max 90 white size 10 worn twice"), deps2)
    assert [c for c in calls[n:] if not c.endswith("/oauth2/token")] == []


async def test_unsupported_category(settings):
    deps = make_deps(settings, [])

    async def fake_extract(*a, **k):
        return {"category_group": "other"}

    deps.llm.chat_json = fake_extract
    with pytest.raises(UnsupportedCategory):
        await generate_draft(DraftRequest(notes="a red ceramic teapot, never used"), deps)


def test_api_rejects_short_notes(settings):
    from app.main import get_deps

    async def fake_deps():
        yield make_deps(settings, [])

    app.dependency_overrides[get_deps] = fake_deps  # don't read the developer's .env
    client = TestClient(app)
    r = client.post("/api/drafts", json={"notes": "   hi  "})
    assert r.status_code == 422
    app.dependency_overrides.clear()


class _FakeDB:
    def __init__(self) -> None:
        self.rate_limits = FakeCollection()


def _client_with_limits(settings, **limits):
    from app.main import get_deps

    deps = make_deps(settings.model_copy(update=limits), [])
    deps.db = _FakeDB()

    async def fake_deps():
        yield deps

    app.dependency_overrides[get_deps] = fake_deps
    return TestClient(app)


def test_drafts_are_rate_limited_per_client(settings):
    client = _client_with_limits(settings, rate_drafts_per_minute=0)
    r = client.post("/api/drafts", json={"notes": "nike air max 90"}, headers={"x-forwarded-for": "1.2.3.4"})
    app.dependency_overrides.clear()
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert "try again" in r.json()["detail"]


def test_site_wide_daily_cap_has_its_own_message(settings):
    client = _client_with_limits(settings, rate_global_drafts_per_day=0)
    r = client.post("/api/drafts", json={"notes": "nike air max 90"})
    app.dependency_overrides.clear()
    assert r.status_code == 429 and "tomorrow" in r.json()["detail"]


def test_market_reads_are_rate_limited(settings):
    client = _client_with_limits(settings, rate_market_per_minute=0)
    r = client.get("/api/drafts/000000000000000000000000/market")
    app.dependency_overrides.clear()
    assert r.status_code == 429


def test_no_cors_for_other_sites_and_docs_hidden(settings):
    client = _client_with_limits(settings)
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    docs = client.get("/api/docs")
    app.dependency_overrides.clear()
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
    assert docs.status_code == 404


def test_upstream_errors_are_not_leaked(settings):
    from app.llm import LLMError
    from app.main import upstream_error

    import asyncio

    resp = asyncio.run(upstream_error(None, LLMError("groq error (401): invalid key gsk_secret")))  # type: ignore[arg-type]
    assert resp.status_code == 502 and b"gsk_secret" not in resp.body and b"401" not in resp.body
