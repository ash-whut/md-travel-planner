"""Booking route: PATCH /api/sessions/{id}/bookings/{booking_id} (contracts §4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import repo
from app.db.engine import get_db
from app.schemas.dto import UpdateBookingBody
from app.schemas.itinerary import Booking

router = APIRouter()

Db = Annotated[Session, Depends(get_db)]


@router.patch("/sessions/{session_id}/bookings/{booking_id}")
def update_booking(
    session_id: str, booking_id: str, body: UpdateBookingBody, db: Db
) -> Booking:
    """Mark a booking booked (or back to todo) in the latest plan; no new version is saved."""
    if repo.get_session(db, session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    booking = repo.update_booking_status(db, session_id, booking_id, body.status)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking
