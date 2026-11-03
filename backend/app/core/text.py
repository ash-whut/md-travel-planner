"""Small text helpers shared by schemas and the agent layer."""

import re


def normalize_name(name: str) -> str:
    """Matching key for a place or hotel name (04-backend-design §5.0).

    Case-insensitive; apostrophes are dropped, other punctuation becomes a space, whitespace
    is collapsed. "Torchy's  Tacos" matches "torchys tacos", and "Austin-Downtown/Convention
    Center" matches "Austin Downtown / Convention Center".
    """
    without_apostrophes = re.sub(r"['’]", "", name.casefold())
    spaced = re.sub(r"[^\w\s]", " ", without_apostrophes)
    return " ".join(spaced.split())
