"""
schemas.py — Request/Response shapes (Pydantic)
-------------------------------------------------
Pydantic schemas define what data looks like going IN and OUT of our API.

Why do we need this separately from models.py?
  - models.py  = what the DATABASE looks like (tables, columns)
  - schemas.py = what the API sees (requests from clients, responses we send back)

For example, when creating a coach, we don't want the client sending in
an ID (the DB generates that) or raw OAuth tokens (security risk).
Schemas let us be precise about exactly what's allowed in each direction.

Pydantic also validates everything automatically:
  - Wrong type? FastAPI returns a 422 error with a helpful message
  - Missing required field? Same thing
  - No manual validation code needed
"""

from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


# ── OAuth ─────────────────────────────────────────────────────────────

class GoogleOAuthCallback(BaseModel):
    """
    Sent by Google after a user completes the OAuth consent screen.
    Our /auth/google/callback endpoint receives this and saves the tokens to Postgres.
    """
    code: str                    # authorization code from Google (we exchange this for tokens)
    user_type: str               # "coach" or "participant" — so we know which table to update
    user_email: str              # which user this token belongs to


class TokenResponse(BaseModel):
    """Returned after successfully storing tokens."""
    message: str
    user_type: str
    email: str


# ── Coach ─────────────────────────────────────────────────────────────

class CoachCreate(BaseModel):
    """Data required to create a new coach. No ID — Postgres generates that."""
    name: str
    email: str
    timezone: str = "America/Los_Angeles"
    expertise: Optional[str] = None
    calcom_username: Optional[str] = None


class CoachResponse(BaseModel):
    """
    What we send back when returning coach data.
    Notice: NO tokens included — we never expose OAuth tokens in API responses.
    """
    id: int
    name: str
    email: str
    timezone: str
    expertise: Optional[str]
    calcom_username: Optional[str]
    is_active: bool
    created_at: datetime

    # This tells Pydantic to read data from SQLAlchemy model attributes (not just dicts)
    model_config = {"from_attributes": True}


class CoachAvailabilitySlot(BaseModel):
    """A single available time slot for a coach."""
    start: str       # ISO 8601 datetime string e.g. "2025-03-10T10:00:00"
    end: str
    timezone: str


# ── Participant ───────────────────────────────────────────────────────

class ParticipantCreate(BaseModel):
    name: str
    email: str
    timezone: str = "America/Los_Angeles"


class ParticipantResponse(BaseModel):
    id: int
    name: str
    email: str
    timezone: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Booking ───────────────────────────────────────────────────────────

class BookingCreate(BaseModel):
    """
    Sent when a participant confirms a slot in the chatbot.
    Our agent takes this and:
      1. Calls Cal.com to create the booking + get a meeting link
      2. Writes events to both Google Calendars
      3. Saves this record to Postgres
      4. Triggers confirmation emails
    """
    coach_id: int
    participant_id: int
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = None


class BookingResponse(BaseModel):
    id: int
    coach_id: int
    participant_id: int
    start_time: datetime
    end_time: datetime
    meeting_link: Optional[str]
    status: str
    notes: Optional[str]
    confirmation_sent: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── General ───────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """Simple response for operations that just need to confirm success."""
    message: str
