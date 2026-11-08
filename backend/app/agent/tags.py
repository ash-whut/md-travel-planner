"""Letter tags for stops (contracts §3).

Every stop gets a letter (A … Z, AA, AB …). The same stop keeps its letter across versions of a
session, and letters of removed stops are never handed out again, so an old chat message that
mentions [F] still means the same place.
"""

import re
import string

from app.schemas.itinerary import Itinerary, ItineraryDraft

LETTERS = string.ascii_uppercase


def tag_for_index(index: int) -> str:
    """0 → "A", 25 → "Z", 26 → "AA", 27 → "AB" … (spreadsheet-column style)."""
    tag = ""
    number = index + 1
    while number > 0:
        number, remainder = divmod(number - 1, len(LETTERS))
        tag = LETTERS[remainder] + tag
    return tag


def index_for_tag(tag: str) -> int:
    """The inverse of `tag_for_index`: "A" → 0, "AA" → 26."""
    number = 0
    for letter in tag:
        number = number * len(LETTERS) + LETTERS.index(letter) + 1
    return number - 1


def normalize_name(name: str) -> str:
    """Lowercase, no punctuation, single spaces: "  St. Mary's  Café " → "st marys café"."""
    without_punctuation = re.sub(r"[^\w\s]", "", name.lower())
    return " ".join(without_punctuation.split())


def same_place(
    name_a: str, place_id_a: str | None, name_b: str, place_id_b: str | None
) -> bool:
    """Two stops match by `place_id` when both have one, otherwise by normalized name."""
    if place_id_a and place_id_b:
        return place_id_a == place_id_b
    return normalize_name(name_a) == normalize_name(name_b)


def assign_tags(
    draft: ItineraryDraft,
    previous_versions: list[Itinerary],
    place_ids: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map every draft stop `key` to its letter tag.

    `previous_versions` are all earlier itineraries of the session (any order; empty for v1).
    `place_ids` maps a stop key to the place_id of its tool result (step 34); stops without one
    match by name only.
    An earlier version's tag is given to at most one place in this version: two new stops with
    the same name but different place_ids can't both take the letter of an older stop that had
    no place_id.
    """
    place_ids = place_ids or {}
    previous_stops = [
        stop
        for version in sorted(previous_versions, key=lambda itinerary: itinerary.version, reverse=True)
        for stop in version.stops
    ]
    used_indexes = [index_for_tag(stop.tag) for stop in previous_stops]
    next_index = max(used_indexes) + 1 if used_indexes else 0

    stops_by_key = {stop.key: stop for stop in draft.stops}
    tags: dict[str, str] = {}
    tagged_this_version: list[tuple[str, str | None, str]] = []  # (name, place_id, tag)

    for key in _keys_in_walk_order(draft):
        stop = stops_by_key[key]
        place_id = place_ids.get(key)

        tag = next(
            (
                earlier_tag
                for name, earlier_place_id, earlier_tag in tagged_this_version
                if same_place(stop.name, place_id, name, earlier_place_id)
            ),
            None,
        )
        if tag is None:
            # Newest version first, so a stop seen in several versions takes its latest letter.
            # A letter another place already took in this version is skipped.
            used_this_version = {earlier_tag for _, _, earlier_tag in tagged_this_version}
            tag = next(
                (
                    previous.tag
                    for previous in previous_stops
                    if previous.tag not in used_this_version
                    and same_place(stop.name, place_id, previous.name, previous.place_id)
                ),
                None,
            )
        if tag is None:
            tag = tag_for_index(next_index)
            next_index += 1

        tags[key] = tag
        tagged_this_version.append((stop.name, place_id, tag))

    return tags


def _keys_in_walk_order(draft: ItineraryDraft) -> list[str]:
    """Stop keys as first met walking the days in order and items by start_time.

    Stops that no item points to (e.g. lodging only) come after, in draft order.
    """
    ordered: list[str] = []
    for day in sorted(draft.days, key=lambda day: day.day_number):
        for item in sorted(day.items, key=lambda item: item.start_time):
            if item.stop_key and item.stop_key not in ordered:
                ordered.append(item.stop_key)
    for stop in draft.stops:
        if stop.key not in ordered:
            ordered.append(stop.key)
    return ordered
