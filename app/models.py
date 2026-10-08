from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DraftRequest(BaseModel):
    notes: str = Field(min_length=3, max_length=2000, description="Seller's rough notes about the item")
    category_group: Literal["shoes", "phones", "video_games"] | None = Field(
        default=None, description="Optional override; otherwise detected from the notes"
    )

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("notes must be at least 3 characters")
        return v


class Example(BaseModel):
    title: str
    price: float | None = None
    currency: str | None = None
    sold_quantity: int | None = None
    item_url: str | None = None
    score: float | None = None


class Category(BaseModel):
    id: str | None = None
    name: str | None = None
    group: str


class Question(BaseModel):
    """A follow-up the seller can answer with one tap instead of writing more notes."""

    field: str
    question: str
    options: list[str]  # empty -> free-text answer
    required: bool  # an eBay-required aspect, not just a buyer question


class TitleCheck(BaseModel):
    aspect: str
    value: str | None  # None -> still unknown
    in_title: bool


class DraftResponse(BaseModel):
    draft_id: str
    title: str
    item_specifics: dict[str, str]
    description: str
    category: Category
    condition: str | None
    missing_required: list[str]
    missing_info: list[str]
    questions: list[Question] = []
    title_checks: list[TitleCheck] = []
    examples: list[Example]
    retrieval_source: Literal["vector_search", "live_search", "none"]
    warnings: list[str]
    timings_ms: dict[str, float]
    cache: dict[str, dict[str, int]] = {}


class MarketResponse(BaseModel):
    draft_id: str
    price: dict
    plan: dict = {}  # fast / recommended / max list prices; empty with too few listings
    evidence: list[Example]
    note: str = "Units sold are from current multi-quantity listings, not sold-price history."
