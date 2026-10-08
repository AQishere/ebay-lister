"""The three category groups the app supports.

Category IDs are eBay US leaf/parent categories. Browse search on a parent ID
covers its whole subtree. GB IDs are not guaranteed to match: run
`python -m scripts.verify_ebay` on EBAY_GB before ingesting there.
"""

from typing import Literal

CategoryGroup = Literal["shoes", "phones", "video_games"]
GROUPS: tuple[CategoryGroup, ...] = ("shoes", "phones", "video_games")

CATEGORY_IDS: dict[str, dict[CategoryGroup, list[str]]] = {
    "EBAY_US": {
        "shoes": ["93427", "3034"],  # Men's Shoes, Women's Shoes
        "phones": ["9355"],  # Cell Phones & Smartphones
        "video_games": ["139973"],  # Video Games
    },
    "EBAY_GB": {
        "shoes": ["93427", "3034"],
        "phones": ["9355"],
        "video_games": ["139973"],
    },
}

# Queries used by the offline ingestion job to build the RAG corpus.
SEED_QUERIES: dict[CategoryGroup, list[str]] = {
    "shoes": [
        "nike air max", "nike air force 1", "nike dunk low", "air jordan 1", "adidas samba",
        "adidas ultraboost", "new balance 550", "new balance 990", "converse chuck taylor",
        "vans old skool", "asics gel", "dr martens 1460", "timberland boots", "ugg boots",
        "birkenstock", "hoka", "on cloud", "puma suede", "reebok club c", "salomon xt-6",
    ],
    "phones": [
        "iphone 15", "iphone 14", "iphone 13", "iphone 12", "iphone 11", "iphone se",
        "samsung galaxy s24", "samsung galaxy s23", "samsung galaxy s22", "samsung galaxy a54",
        "google pixel 8", "google pixel 7", "oneplus", "motorola moto g", "samsung galaxy z flip",
    ],
    "video_games": [
        "ps5 game", "ps4 game", "nintendo switch game", "xbox series x game", "xbox one game",
        "pokemon game", "mario kart", "zelda", "call of duty", "fifa", "gta v",
        "nintendo ds game", "gamecube game", "n64 game", "ps2 game",
    ],
}


def category_ids(marketplace: str, group: CategoryGroup) -> list[str]:
    return CATEGORY_IDS[marketplace][group]
