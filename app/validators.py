"""Rule-based checks on generated titles."""

import re

MAX_TITLE = 80
SPAM_PATTERNS = re.compile(r"l@@k|!{2,}|\bwow\b|\bmust see\b|[\U0001F300-\U0001FAFF☀-➿]", re.I)


def clean_title(raw: str) -> tuple[str, list[str]]:
    """Tidy model output into a valid title. Returns (title, warnings)."""
    warnings = []
    t = raw.strip().splitlines()[0] if raw.strip() else ""
    t = re.sub(r"^(title\s*:\s*)", "", t, flags=re.I)
    t = t.strip().strip('"').strip("'").strip()
    t = re.sub(r"\s+", " ", t)
    if SPAM_PATTERNS.search(t):
        warnings.append("title contained spam patterns; removed")
        t = re.sub(r"\s+", " ", SPAM_PATTERNS.sub("", t)).strip()
    if len(t) > MAX_TITLE:
        warnings.append(f"title was {len(t)} chars; trimmed to {MAX_TITLE}")
        t = t[: MAX_TITLE + 1].rsplit(" ", 1)[0].rstrip(" ,-/|")
    if not t:
        warnings.append("empty title")
    return t, warnings


# Words that state a fact about the specific item. Similar listings use them all the
# time (8 of 8 iPhone titles say "Unlocked"), so the LLM copies them even when told not
# to. They stay in a title only if the seller's notes or answers support them.
CLAIM_WORDS = re.compile(
    r"(?<![\w&+-])("
    r"\d+(?:\.\d+)?\s?(?:gb|tb)"  # storage
    r"|unlocked|locked|verizon|at&t|att|t-mobile|tmobile|sprint|cricket|boost|metropcs|tracfone|xfinity"  # network
    r"|new|sealed|mint|excellent|pristine|flawless|perfect|refurbished|renewed|certified|used|pre-owned|preowned"
    r"|very|good|fair|nwt|nib|vnds|ds|condition"  # condition and hype
    r")(?![\w&+-])",
    re.I,
)
_SUPPORT_TOKEN = re.compile(r"[a-z0-9]+(?:[&+-][a-z0-9]+)*")
_STORAGE = re.compile(r"\d+(?:\.\d+)?\s?(?:gb|tb)")


def strip_unsupported_claims(title: str, support: str) -> tuple[str, list[str]]:
    """Remove claim words (network, storage, condition) that the support text (notes,
    the seller's answers, extracted facts) does not contain. Returns (title, removed)."""
    low = support.lower()
    tokens = set(_SUPPORT_TOKEN.findall(low))
    storage = {re.sub(r"\s", "", s) for s in _STORAGE.findall(low)}
    removed: list[str] = []

    def drop(m: re.Match) -> str:
        word = m.group(0)
        key = re.sub(r"\s", "", word.lower())
        if key in tokens or key in storage:
            return word
        removed.append(word)
        return ""

    t = CLAIM_WORDS.sub(drop, title)
    t = re.sub(r"\(\s*\)", "", t)  # "()" left behind
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(\s*[-|,/])+(?=\s*[-|,/]|\s*$)", "", t)  # separators with nothing after them
    t = re.sub(r"^\s*[-|,/]+\s*", "", t).strip()
    return t, removed
