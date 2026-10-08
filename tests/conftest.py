import json

import httpx
import pytest

from app.config import Settings


class FakeCollection:
    """Just enough of AsyncCollection for app.cache.Cache."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    async def find_one(self, q: dict) -> dict | None:
        return self.docs.get(q["_id"])

    async def replace_one(self, q: dict, doc: dict, upsert: bool = False) -> None:
        self.docs[q["_id"]] = doc

    async def find_one_and_update(self, q: dict, update: dict, upsert: bool = False, return_document=None) -> dict:
        """Only the {$inc, $setOnInsert} + upsert shape used by app.ratelimit."""
        doc = self.docs.get(q["_id"])
        if doc is None:
            doc = {"_id": q["_id"], **update.get("$setOnInsert", {})}
            self.docs[q["_id"]] = doc
        for field, by in update.get("$inc", {}).items():
            doc[field] = doc.get(field, 0) + by
        return doc


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        ebay_client_id="id",
        ebay_client_secret="secret",
        groq_api_key="gk",
        mongodb_uri="",
        voyage_api_key="vk",
    )


SUMMARY = {
    "itemId": "v1|111|0",
    "title": "Nike Air Max 90 White Mens Size 10 Trainers",
    "price": {"value": "85.00", "currency": "USD"},
    "condition": "Pre-owned",
    "conditionId": "3000",
    "leafCategoryIds": ["15709"],
    "buyingOptions": ["FIXED_PRICE"],
    "itemWebUrl": "https://ebay.com/itm/111",
}

ITEM = {
    **SUMMARY,
    "categoryId": "15709",
    "categoryPath": "Clothing, Shoes & Accessories|Men|Men's Shoes|Athletic Shoes",
    "localizedAspects": [
        {"type": "STRING", "name": "Brand", "value": "Nike"},
        {"type": "STRING", "name": "Model", "value": "Air Max 90"},
        {"type": "STRING", "name": "US Shoe Size", "value": "10"},
    ],
    "estimatedAvailabilities": [
        {"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 3, "estimatedSoldQuantity": 42}
    ],
}


def ebay_and_llm_handler(calls: list[str]):
    """Routes every outbound request the pipeline makes to a canned response."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        if path.endswith("/get_default_category_tree_id"):
            return httpx.Response(200, json={"categoryTreeId": "0"})
        if path.endswith("/get_category_suggestions"):
            return httpx.Response(200, json={"categorySuggestions": [
                {"category": {"categoryId": "15709", "categoryName": "Athletic Shoes"},
                 "categoryTreeNodeAncestors": [{"categoryId": "93427"}, {"categoryId": "1059"}]}]})
        if path.endswith("/get_item_aspects_for_category"):
            return httpx.Response(200, json={"aspects": [
                {"localizedAspectName": "Brand", "aspectConstraint": {"aspectRequired": True}, "aspectValues": [{"localizedValue": "Nike"}]},
                {"localizedAspectName": "US Shoe Size", "aspectConstraint": {"aspectRequired": True}},
                {"localizedAspectName": "Department", "aspectConstraint": {"aspectRequired": True}},
                {"localizedAspectName": "Color", "aspectConstraint": {"aspectUsage": "RECOMMENDED"}},
            ]})
        if path.endswith("/item_summary/search"):
            return httpx.Response(200, json={"total": 1, "itemSummaries": [SUMMARY]})
        if path.endswith("/buy/browse/v1/item/"):
            return httpx.Response(200, json={"items": [ITEM]})
        if path.endswith("/chat/completions"):
            body = json.loads(request.content)
            system = body["messages"][0]["content"]
            if "rough notes" in system:
                content = json.dumps({
                    "category_group": "shoes", "search_query": "nike air max 90",
                    "condition": "USED", "condition_text": "Pre-owned",
                    "attributes": {"Brand": "Nike", "Model": "Air Max 90", "US Shoe Size": "10", "Color": "White"},
                    "missing_info": ["box included?"],
                    "follow_ups": [
                        {"question": "Original box included?", "options": ["Yes", "No"]},
                        {"question": "Department?", "options": ["Men", "Women"]},  # duplicate of a required aspect
                        {"question": "Bad?", "options": ["only one"]},  # too few options
                        "not a dict",
                    ],
                })
            elif "item specifics and descriptions" in system:
                content = json.dumps({
                    "item_specifics": {"Brand": "Nike", "US Shoe Size": "10", "Color": "White", "Made Up Aspect": "x"},
                    "description": "Nike Air Max 90 in white, US size 10. Worn a few times.",
                    "missing_required": ["Department"],
                })
            else:  # title prompt
                content = "Title: Nike Air Max 90 White Mens US Size 10 Running Shoes Trainers Pre-owned"
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        return httpx.Response(404, json={"error": f"unmocked {path}"})

    return handler
