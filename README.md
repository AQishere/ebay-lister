# eBay Lister

Rough seller notes in → a ready-to-copy eBay listing out: **title, item specifics, description and a recommended price**, grounded in real eBay listings. Even "iphone 13" is enough to start; the app asks a few tap-to-answer questions for the rest.

Categories: **shoes, phones, video games**. Marketplace: EBAY_US (EBAY_GB via one setting).

**Live app:** https://ebay-lister-iota.vercel.app ([health](https://ebay-lister-iota.vercel.app/api/health))

**Stack:** FastAPI + Vite/React/TypeScript on Vercel · MongoDB Atlas (cache, drafts, Atlas Vector Search, rate limits) · Voyage AI embeddings · Groq `gpt-oss-120b` · eBay Browse + Taxonomy APIs

## What the seller gets

- **Follow-up questions** for what the notes didn't say (storage, size, colour, condition…), with answers taken from eBay's allowed values or the most common values among similar listings. Answers regenerate the draft.
- **Your price:** sell fast / recommended / max list prices from comparable listings in the same condition, with how many of the units sold were priced at or below the recommendation.
- **Title** (≤ 80 chars) with a **"Buyers search by"** checklist: which details buyers filter by are in the title, a tap to add a confirmed one, and which are still unknown.
- **Item specifics** filtered to the category's official aspects, and a **description** that only states what is known.
- **Market:** median asking price, the middle-half price range and similar current listings with units sold.

## How it works

```
POST /api/drafts {notes}
  1. Extract (Groq, JSON)   notes -> category group, search query, condition, stated attributes, follow-up questions
  2. In parallel:
       Taxonomy API          leaf category + official item aspects (required / recommended)
       Retrieval             embed (Voyage AI) -> Atlas Vector Search over the ingested corpus,
                             re-ranked by units sold; falls back to live Browse search
  3. In parallel (Groq):     title  ||  item specifics + description, constrained to the aspect list
  4. Check and save          title cleaned to <= 80 chars; claim words the notes don't support
                             (Unlocked, 128GB, Mint...) removed; specifics filtered to valid aspects;
                             questions and title checklist built; draft saved
GET /api/drafts/{id}/market   live listings -> sold counts + asking-price range + price plan
```

Every eBay and LLM response is cached in MongoDB with TTL indexes. Each draft response includes per-step `timings_ms` and cache hit counts.

**Data honesty:** the Browse API only sees *active* listings. Prices are **asking prices of current listings**, and sold numbers are **units sold on current multi-quantity listings**, never sold-price history.

**Protection:** API keys live only in server env vars (never in the frontend bundle or git). The API refuses cross-origin browser calls (`CORS_ORIGINS` empty), hides `/api/docs` unless `EXPOSE_DOCS=true`, returns generic messages for upstream errors (details go to the server log), and rate-limits per client and site-wide with counters in MongoDB (see `RATE_*` in `.env.example`). If MongoDB is unreachable the limiter allows requests rather than taking the app down.

## Layout

| Path | What |
|---|---|
| `app/` | FastAPI app and all logic (`pipeline.py` is the request path, `insights.py` the price plan and title checklist, `validators.py` the title checks, `ratelimit.py` the limits) |
| `api/index.py` | Vercel entry point |
| `frontend/` | Vite + React + TypeScript UI, served at `/` (the API keeps `/api/*`) |
| `scripts/verify_ebay.py` | Checks eBay access and fields with real calls |
| `scripts/create_indexes.py` | TTL, unique and Atlas Vector Search indexes |
| `scripts/ingest.py` | Builds the listing corpus for vector search (resumable, call-budgeted) |
| `scripts/check_llm.py`, `scripts/check_embeddings.py` | Check the Groq and Voyage keys |
| `tests/` | Pipeline end to end with eBay, Groq and Mongo mocked, plus unit tests |

## Setup and run order

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows; source .venv/bin/activate elsewhere
pip install -r requirements-dev.txt
cp .env.example .env                                  # fill in keys
pytest -q                                             # works without any keys
```

1. **Accounts:** eBay Developer (production keyset with OAuth enabled and the Marketplace Account Deletion exemption), MongoDB Atlas M0 (Network Access: `0.0.0.0/0`), Groq, Voyage AI, Vercel.
2. **Verify eBay:** `python -m scripts.verify_ebay` (≈20 calls).
3. **Indexes:** `python -m scripts.create_indexes`
4. **Keys:** `python -m scripts.check_embeddings` (Voyage) and `python -m scripts.check_llm` (Groq).
5. **Run the API:** `uvicorn app.main:app --reload`, then open http://localhost:8000/api/docs (set `EXPOSE_DOCS=true` in `.env` locally). With an empty corpus it falls back to live search; this shows up in `warnings`.
   **Frontend:** `cd frontend && npm install && npm run dev`, then open http://localhost:5173 (it proxies `/api` to `localhost:8000`; set `VITE_API_TARGET=https://<app>.vercel.app` to use the live API instead).
6. **Ingest:** `python -m scripts.ingest --per-query 10 --max-calls 300`. Resumable; each listing costs one eBay call (the batch endpoint is restricted), so spread it over days to stay under the ~5,000/day quota.
7. **Deploy:** import the repo in Vercel with the **Services** preset (`vercel.json` defines the `api` and `web` services), add the `.env` values as environment variables.

Local dev without Groq: `LLM_PROVIDER=ollama` with `ollama pull qwen2.5:7b`.

## Limitations

- **Asking prices, not sold prices.** eBay's sold-price data (Marketplace Insights API) is limited to approved partners, so prices come from current listings.
- **Three categories, US marketplace.** Shoes, phones and video games on EBAY_US; EBAY_GB is configurable but less tested.
- **Draft only.** The seller copies the listing into eBay; nothing is posted automatically.
- **Colour names:** a colourway name can land in `Color` ("Chicago" for a Jordan 1).
