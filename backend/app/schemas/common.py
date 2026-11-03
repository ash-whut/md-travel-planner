"""Small types shared by the schemas (03-contracts conventions)."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, PlainSerializer, StringConstraints


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything we store is UTC, so treat naive as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# Timestamp that serializes to JSON as ISO-8601 UTC, e.g. "2026-11-01T18:04:05Z".
UtcDatetime = Annotated[
    datetime,
    AfterValidator(_as_utc),
    PlainSerializer(lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ"), return_type=str, when_used="json"),
]

# Local time of day, "HH:MM" 24h (the UI formats it as 12h).
TimeHHMM = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class Money(BaseModel):
    amount: float
    currency: Literal["USD"] = "USD"


class Link(BaseModel):
    label: str
    url: str
