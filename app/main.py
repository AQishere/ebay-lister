import logging
from collections.abc import AsyncIterator

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.cache import Cache
from app.config import get_settings
from app.db import get_db
from app.embeddings import Embedder, EmbeddingError
from app.ebay_client import EbayClient, EbayError, EbayRateLimited
from app.llm import LLM, LLMError, LLMRateLimited
from app.models import DraftRequest, DraftResponse, MarketResponse
from app.pipeline import Deps, UnsupportedCategory, generate_draft, market_evidence
from app.ratelimit import DAY, MINUTE, RateLimited, client_id, enforce

log = logging.getLogger(__name__)
_settings = get_settings()

# Docs live under /api (the frontend owns every other path) and are off unless EXPOSE_DOCS=true.
app = FastAPI(
    title="eBay Lister API",
    version="0.1.0",
    docs_url="/api/docs" if _settings.expose_docs else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _settings.expose_docs else None,
)
# Same-origin frontend needs no CORS; other sites' browsers are refused unless listed.
if origins := [o.strip() for o in _settings.cors_origins.split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


async def get_deps() -> AsyncIterator[Deps]:
    s = get_settings()
    db = get_db() if s.mongodb_uri else None
    ebay_cache = Cache(db.ebay_cache if db is not None else None)
    llm_cache = Cache(db.llm_cache if db is not None else None)
    deps = Deps(
        settings=s,
        db=db,
        ebay=EbayClient(ebay_cache, s),
        llm=LLM(llm_cache, s),
        embedder=Embedder(llm_cache, s),
        ebay_cache=ebay_cache,
        llm_cache=llm_cache,
    )
    try:
        yield deps
    finally:
        await deps.ebay.aclose()
        await deps.llm.aclose()
        await deps.embedder.aclose()


async def limit_drafts(request: Request, deps: Deps = Depends(get_deps)) -> None:
    s, col = deps.settings, (deps.db.rate_limits if deps.db is not None else None)
    who = client_id(request)
    await enforce(col, [
        (f"drafts:{who}", s.rate_drafts_per_minute, MINUTE, "per minute"),
        (f"drafts:{who}", s.rate_drafts_per_day, DAY, "per day"),
        ("drafts:all", s.rate_global_drafts_per_day, DAY, "site-wide daily"),
    ])


async def limit_reads(request: Request, deps: Deps = Depends(get_deps)) -> None:
    col = deps.db.rate_limits if deps.db is not None else None
    await enforce(col, [(f"reads:{client_id(request)}", deps.settings.rate_market_per_minute, MINUTE, "per minute")])


@app.exception_handler(RateLimited)
async def too_many_requests(_: Request, exc: RateLimited) -> JSONResponse:
    message = (
        "The app has reached today's limit. Please come back tomorrow."
        if exc.scope == "site-wide daily"
        else f"Too many requests. Please try again in {exc.retry_after} seconds."
    )
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limited", "detail": message},
        headers={"Retry-After": str(exc.retry_after)},
    )


@app.exception_handler(EbayRateLimited)
@app.exception_handler(LLMRateLimited)
async def upstream_rate_limited(_: Request, exc: Exception) -> JSONResponse:
    log.warning("upstream rate limit: %s", exc)
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limited", "detail": "We're busy right now. Please try again in a minute."},
        headers={"Retry-After": "60"},
    )


# Upstream errors can include provider responses; log them, never send them to clients.
@app.exception_handler(EbayError)
@app.exception_handler(EmbeddingError)
@app.exception_handler(LLMError)
async def upstream_error(_: Request, exc: Exception) -> JSONResponse:
    log.error("upstream error: %s", exc)
    return JSONResponse(
        status_code=502,
        content={"error": "upstream_error", "detail": "A service we rely on is having trouble. Please try again shortly."},
    )


@app.exception_handler(UnsupportedCategory)
async def unsupported(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "unsupported_category", "detail": str(exc)})


@app.get("/api/health")
async def health(deps: Deps = Depends(get_deps)) -> dict:
    s = deps.settings
    return {
        "ok": True,
        "configured": {
            "ebay": bool(s.ebay_client_id and s.ebay_client_secret),
            "mongodb": bool(s.mongodb_uri),
            "groq": bool(s.groq_api_key),
            "voyage": bool(s.voyage_api_key),
        },
    }


@app.post("/api/drafts", response_model=DraftResponse, dependencies=[Depends(limit_drafts)])
async def create_draft(req: DraftRequest, deps: Deps = Depends(get_deps)) -> dict:
    draft = await generate_draft(req, deps)
    draft["cache"] = {
        "ebay": {"hits": deps.ebay_cache.hits, "misses": deps.ebay_cache.misses},
        "llm": {"hits": deps.llm_cache.hits, "misses": deps.llm_cache.misses},
    }
    return draft


async def _load_draft(draft_id: str, deps: Deps) -> dict:
    if deps.db is None:
        raise HTTPException(503, "MongoDB is not configured")
    try:
        oid = ObjectId(draft_id)
    except InvalidId:
        raise HTTPException(404, "draft not found") from None
    draft = await deps.db.drafts.find_one({"_id": oid})
    if not draft:
        raise HTTPException(404, "draft not found")
    return draft


@app.get("/api/drafts/{draft_id}", dependencies=[Depends(limit_reads)])
async def get_draft(draft_id: str, deps: Deps = Depends(get_deps)) -> dict:
    draft = await _load_draft(draft_id, deps)
    draft["draft_id"] = str(draft.pop("_id"))
    return draft


@app.get("/api/drafts/{draft_id}/market", response_model=MarketResponse, dependencies=[Depends(limit_reads)])
async def get_market(draft_id: str, deps: Deps = Depends(get_deps)) -> dict:
    return await market_evidence(await _load_draft(draft_id, deps), deps)
