"""Letter tags for places (A..Z, AA..) and hotels (H1, H2), assigned by code, never by the LLM.

v1 (Stage 1, 04-backend-design §5.0): first-time assignment only. Places are matched by
normalized name. Keeping tags stable across itinerary versions comes in a later stage.
"""

import re
import string


def normalize_name(name: str) -> str:
    """Matching key for a place: case-insensitive, punctuation dropped, whitespace collapsed.

    "Torchy's  Tacos" and "torchys tacos" are the same place.
    """
    without_punctuation = re.sub(r"[^\w\s]", "", name.casefold())
    return " ".join(without_punctuation.split())


def letter_tag(index: int) -> str:
    """0 → "A", 25 → "Z", 26 → "AA", 27 → "AB", ... (spreadsheet-column order)."""
    if index < 0:
        raise ValueError(f"tag index must be >= 0, got {index}")
    tag = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        tag = string.ascii_uppercase[rem] + tag
    return tag


def lodging_tag(index: int) -> str:
    """0 → "H1", 1 → "H2" (hotels in check-in order)."""
    return f"H{index + 1}"


def assign_place_tags(names: list[str]) -> dict[str, str]:
    """Give each distinct place the next letter, in first-appearance order.

    `names` are place names in the order they appear in the plan (days in order, items by
    start time). Returns {normalized name: tag}.
    """
    tags: dict[str, str] = {}
    for name in names:
        key = normalize_name(name)
        if key not in tags:
            tags[key] = letter_tag(len(tags))
    return tags
