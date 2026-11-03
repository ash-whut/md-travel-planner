"""ItineraryDraft → Itinerary (04-backend-design §5.0, Stage 1 postprocess v0).

Code adds everything the LLM must not invent: letter tags, item and checklist IDs, the
version, Google Maps search links and the booking checklist. Values that later stages look
up (coordinates, place ids, ratings, prices, weather, transit) stay null.
"""

import datetime as dt
import uuid
from urllib.parse import quote

from app.agent.tags import assign_place_tags, lodging_tag, normalize_name
from app.schemas import (
    ChecklistItem,
    City,
    Day,
    DraftItem,
    DraftLodging,
    DraftPlace,
    Item,
    Itinerary,
    ItineraryDraft,
    Lodging,
    Place,
)


def maps_search_url(name: str, city: str) -> str:
    """Google Maps search link (03 §5, without `query_place_id` until places are looked up)."""
    return "https://www.google.com/maps/search/?api=1&query=" + quote(f"{name} {city}", safe="")


def draft_to_itinerary(
    draft: ItineraryDraft,
    *,
    version: int = 1,
    itinerary_id: str | None = None,
    created_at: dt.datetime | None = None,
) -> Itinerary:
    """Build a validated Itinerary from a draft; raises pydantic `ValidationError` if it can't.

    Steps (04 §5.0): sort items by start time, tag hotels H1/H2 by check-in and places A, B, …
    by first appearance, assign IDs `d{day}-i{n}`, add a checklist item per hotel
    (`chk-lodging-H1`) and per other booking-required item (`chk-booking-d2-i7`), validate.
    """
    hotels = sorted(draft.lodging, key=lambda h: h.check_in)
    hotel_tags = {normalize_name(h.name): lodging_tag(i) for i, h in enumerate(hotels)}

    def hotel_tag_of(item: DraftItem) -> str | None:
        """H1/H2 if the item is about a hotel: via `lodging_ref`, or a place named like the hotel."""
        if item.lodging_ref is not None:
            return hotel_tags[normalize_name(item.lodging_ref)]  # the draft checked it resolves
        if item.place is not None:
            return hotel_tags.get(normalize_name(item.place.name))
        return None

    # Days in order, items by start time (stable, so equal times keep the LLM's order).
    days = [(day, sorted(day.items, key=lambda item: item.start_time)) for day in draft.days]

    # Places in first-appearance order; the day's city goes into the maps link.
    occurrences: list[tuple[DraftPlace, str]] = [
        (item.place, day.city)
        for day, items in days
        for item in items
        if item.place is not None and hotel_tag_of(item) is None
    ]
    place_tags = assign_place_tags([place.name for place, _ in occurrences])
    places: dict[str, Place] = {}
    for place, city in occurrences:
        tag = place_tags[normalize_name(place.name)]
        if tag not in places:
            places[tag] = Place(
                tag=tag,
                name=place.name,
                address=place.address,
                category=place.category,
                maps_url=maps_search_url(place.name, city),
            )
        elif places[tag].address is None:
            places[tag].address = place.address  # a later mention may carry the address

    lodging = [_lodging(hotel, lodging_tag(i)) for i, hotel in enumerate(hotels)]
    checklist = [_lodging_checklist_item(hotel) for hotel in lodging]

    out_days: list[Day] = []
    for day, items in days:
        out_items: list[Item] = []
        for n, item in enumerate(items, start=1):
            item_id = f"d{day.day_number}-i{n}"
            hotel_tag = hotel_tag_of(item)
            if hotel_tag is not None:
                tag = hotel_tag
            elif item.place is not None:
                tag = place_tags[normalize_name(item.place.name)]
            else:
                tag = None

            checklist_item_id = None
            if item.booking_required and hotel_tag is not None:
                checklist_item_id = f"chk-lodging-{hotel_tag}"  # booking a hotel = its lodging item
            elif item.booking_required:
                checklist_item_id = f"chk-booking-{item_id}"
                checklist.append(
                    ChecklistItem(
                        id=checklist_item_id, category="activities", title=f"Book {item.title}", date=day.date
                    )
                )

            out_items.append(
                Item(
                    id=item_id,
                    kind=item.kind,
                    title=item.title,
                    description=item.description,
                    start_time=item.start_time,
                    end_time=item.end_time,
                    place_tag=tag,
                    est_cost=item.est_cost,
                    booking_required=item.booking_required,
                    checklist_item_id=checklist_item_id,
                    tips=item.tips,
                )
            )
        out_days.append(
            Day(
                day_number=day.day_number,
                date=day.date,
                title=day.title,
                city=day.city,
                lodging_tag=_hotel_for_night(lodging, day.date),
                items=out_items,
            )
        )

    return Itinerary(
        id=itinerary_id or str(uuid.uuid4()),
        version=version,
        title=draft.title,
        summary=draft.summary,
        start_date=draft.start_date,
        end_date=draft.end_date,
        travelers=draft.travelers,
        cities=[City(name=c.name, region=c.region, country=c.country) for c in draft.cities],
        cost_estimate=draft.cost_estimate,
        assumptions=draft.assumptions,
        places=list(places.values()),
        lodging=lodging,
        days=out_days,
        checklist=checklist,
        created_at=created_at or dt.datetime.now(dt.UTC),
    )


def _lodging(hotel: DraftLodging, tag: str) -> Lodging:
    """No pricing source in Stage 1, so prices stay null with `price_source: "none"`."""
    return Lodging(
        tag=tag,
        name=hotel.name,
        city=hotel.city,
        check_in=hotel.check_in,
        check_out=hotel.check_out,
        nights=(hotel.check_out - hotel.check_in).days,
        price_source="none",
    )


def _lodging_checklist_item(hotel: Lodging) -> ChecklistItem:
    nights = f"{hotel.nights} night" + ("" if hotel.nights == 1 else "s")
    return ChecklistItem(
        id=f"chk-lodging-{hotel.tag}",
        category="lodging",
        title=f"Book {hotel.name} ({hotel.tag})",
        details=f"{nights}, {_date_range(hotel.check_in, hotel.check_out)}.",
        date=hotel.check_in,
    )


def _date_range(start: dt.date, end: dt.date) -> str:
    """Format as "Mar 6–8", or "Mar 30–Apr 1" across months."""
    same_month = (start.year, start.month) == (end.year, end.month)
    return f"{start:%b} {start.day}–" + (f"{end.day}" if same_month else f"{end:%b} {end.day}")


def _hotel_for_night(lodging: list[Lodging], date: dt.date) -> str | None:
    """The hotel you sleep in that night; null on the departure day."""
    return next((h.tag for h in lodging if h.check_in <= date < h.check_out), None)
