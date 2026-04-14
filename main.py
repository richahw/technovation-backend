"""
main.py — FastAPI Application Entry Point
------------------------------------------
Run with:
    uvicorn main:app --reload

Cal.com integration has TWO modes:
  TEST MODE:  POST /auth/calcom/test-sync
              Uses CALCOM_API_KEY to pull test coach data into DB right now.

  REAL MODE:  GET /auth/calcom/login  ->  GET /auth/calcom/callback
              Full OAuth for real coaches. Needs CALCOM_CLIENT_ID +
              CALCOM_CLIENT_SECRET. Ready to go — just add the env vars.

NOTE: Uses Cal.com API v2 (v1 was shut down April 8, 2026).
  - Auth: Authorization: Bearer <key> header (not ?apiKey= query param)
  - All responses wrapped in {"status": "success", "data": {...}}
  - Required header on every request: cal-api-version: 2024-08-13
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import os
import httpx

from app.database import engine, get_db, Base
from app import models, schemas

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Scheduling Platform API",
    description="""
    Technovation x Delta Agent-Assisted Scheduling Platform.

    **Cal.com integration — two modes:**
    - **Test mode** → `POST /auth/calcom/test-sync` (uses API key, works now)
    - **Real OAuth** → `GET /auth/calcom/login` (needs Cal.com OAuth app credentials)

    Uses Cal.com API **v2** (v1 shut down April 8, 2026).
    """,
    version="0.4.0",
)

# ── Google OAuth config ───────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
_base_url = (
    os.getenv("GOOGLE_REDIRECT_URI")
    or (f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/auth/google/callback"
        if os.getenv("RENDER_EXTERNAL_HOSTNAME") else None)
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/auth/google/callback"
        if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None)
    or "http://localhost:8000/auth/google/callback"
)
GOOGLE_REDIRECT_URI = _base_url
GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_SCOPES = " ".join([
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
])

# ── Cal.com config ────────────────────────────────────────────────────
CALCOM_API_KEY       = os.getenv("CALCOM_API_KEY")
CALCOM_CLIENT_ID     = os.getenv("CALCOM_CLIENT_ID")
CALCOM_CLIENT_SECRET = os.getenv("CALCOM_CLIENT_SECRET")

# v2 base URL and required version header
CALCOM_BASE_URL      = "https://api.cal.com/v2"
CALCOM_API_VERSION   = "2024-08-13"   # required on every v2 request

# Cal.com OAuth URLs
CALCOM_AUTH_URL  = "https://app.cal.com/oauth/authorize"
CALCOM_TOKEN_URL = "https://app.cal.com/oauth/token"

_calcom_base = (
    os.getenv("CALCOM_REDIRECT_URI")
    or (f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/auth/calcom/callback"
        if os.getenv("RENDER_EXTERNAL_HOSTNAME") else None)
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/auth/calcom/callback"
        if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None)
    or "http://localhost:8000/auth/calcom/callback"
)
CALCOM_REDIRECT_URI = _calcom_base


def calcom_headers(access_token: str = None) -> dict:
    """
    Build the headers required for every Cal.com v2 request.
    - Uses the coach's personal OAuth token if provided (real mode)
    - Falls back to the global API key (test mode)
    """
    token = access_token or CALCOM_API_KEY
    return {
        "Authorization":   f"Bearer {token}",
        "cal-api-version": CALCOM_API_VERSION,
        "Content-Type":    "application/json",
    }


# ══════════════════════════════════════════════════════════════════════
# CAL.COM HELPER FUNCTIONS (all v2)
# ══════════════════════════════════════════════════════════════════════

async def calcom_get_me(access_token: str = None) -> dict:
    """
    GET /v2/me — fetch Cal.com profile.
    Test mode:  uses CALCOM_API_KEY
    Real mode:  uses coach's personal OAuth access_token
    """
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{CALCOM_BASE_URL}/me",
            headers=calcom_headers(access_token)
        )
    r.raise_for_status()
    data = r.json()
    # v2 wraps everything: {"status": "success", "data": {...}}
    return data.get("data", data)


async def calcom_get_event_types(access_token: str = None) -> dict:
    """
    GET /v2/event-types — fetch all event types.
    Returns the raw v2 response so caller can inspect data.eventTypes.
    """
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{CALCOM_BASE_URL}/event-types",
            headers=calcom_headers(access_token)
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


async def calcom_get_slots(
    event_type_id: int,
    start_time: str,
    end_time: str,
    username: Optional[str] = None,
) -> dict:
    """
    GET /v2/slots/available — fetch available slots for an event type.

    v2 uses event_type_id + full ISO 8601 timestamps (not username + date).
    This replaces the old v1 /availability endpoint.

    Args:
        event_type_id: Cal.com event type ID (get from /calcom/event-types)
        start_time:    ISO 8601 e.g. "2026-04-09T00:00:00Z"
        end_time:      ISO 8601 e.g. "2026-04-16T23:59:59Z"
        username:      optional — Cal.com username to filter by

    Returns slots grouped by date:
        {"2026-04-09": [{"time": "2026-04-09T09:00:00Z"}, ...], ...}
    """
    params = {
        "eventTypeId": event_type_id,
        "startTime":   start_time,
        "endTime":     end_time,
    }
    if username:
        params["username"] = username

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{CALCOM_BASE_URL}/slots/available",
            headers=calcom_headers(),
            params=params
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


async def calcom_get_bookings(status_filter: Optional[str] = None) -> dict:
    """
    GET /v2/bookings — fetch all bookings.
    status filter options: accepted, pending, cancelled, rejected
    """
    params = {}
    if status_filter:
        params["status"] = status_filter

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{CALCOM_BASE_URL}/bookings",
            headers=calcom_headers(),
            params=params
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


async def calcom_create_booking(
    event_type_id: int,
    start: str,
    attendee_name: str,
    attendee_email: str,
    timezone: str,
    language: str = "en",
) -> dict:
    """
    POST /v2/bookings — create a real booking on Cal.com.

    v2 changes from v1:
      - `responses` object replaced with `attendee` object
      - `end` time not required (calculated from event type duration)
      - location structure changed

    Args:
        event_type_id:  ID of the Cal.com event type
        start:          ISO 8601 start time e.g. "2026-04-09T10:00:00Z"
        attendee_name:  Participant's full name
        attendee_email: Participant's email
        timezone:       Participant's timezone e.g. "America/Los_Angeles"

    Returns booking with: id, uid, start, end, status, meetingUrl, etc.

    Usage (to replace stub in POST /bookings):
        calcom_booking = await calcom_create_booking(
            event_type_id=coach.calcom_event_types[0]["id"],
            start=booking.start_time.isoformat() + "Z",
            attendee_name=participant.name,
            attendee_email=participant.email,
            timezone=participant.timezone,
        )
        meeting_link = calcom_booking.get("meetingUrl")
        calcom_uid   = calcom_booking.get("uid")
    """
    payload = {
        "eventTypeId": event_type_id,
        "start":       start,
        "attendee": {
            "name":     attendee_name,
            "email":    attendee_email,
            "timeZone": timezone,
            "language": language,
        },
        "metadata": {},
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{CALCOM_BASE_URL}/bookings",
            headers=calcom_headers(),
            json=payload
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


async def calcom_cancel_booking(uid: str, reason: str = "") -> dict:
    """
    POST /v2/bookings/{uid}/cancel — cancel a Cal.com booking.

    v2 change: was DELETE /v1/bookings, now POST /v2/bookings/{uid}/cancel
    Uses booking uid (not id) in the path.
    """
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{CALCOM_BASE_URL}/bookings/{uid}/cancel",
            headers=calcom_headers(),
            json={"cancellationReason": reason}
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


def store_calcom_profile_to_db(coach: models.Coach, profile: dict, event_types_data: dict, db: Session):
    """
    Save Cal.com profile + event types to the Coach DB record.
    Called by both test-sync and real OAuth callback.

    v2 profile fields: username, name, email, timeZone, defaultScheduleId
    v2 event types are in data.eventTypes (list)
    """
    coach.name     = profile.get("username") and profile.get("name", coach.name) or coach.name
    coach.name     = profile.get("name", coach.name)
    coach.email    = profile.get("email", coach.email)
    coach.timezone = profile.get("timeZone", coach.timezone)
    coach.calcom_user_id             = str(profile.get("id", ""))
    coach.calcom_username            = profile.get("username", "")
    coach.calcom_default_schedule_id = str(profile.get("defaultScheduleId", ""))

    # v2 event types live in eventTypes list
    raw = event_types_data.get("eventTypes", [])
    coach.calcom_event_types = [
        {
            "id":          et.get("id"),
            "title":       et.get("title"),
            "length":      et.get("lengthInMinutes"),   # v2 uses lengthInMinutes
            "slug":        et.get("slug"),
            "description": et.get("description"),
        }
        for et in raw
    ]

    db.commit()
    db.refresh(coach)
    return coach


# ══════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "Scheduling Platform API is running", "docs": "/docs"}


# ══════════════════════════════════════════════════════════════════════
# CAL.COM — TEST MODE (API key, works right now)
# ══════════════════════════════════════════════════════════════════════

@app.get("/calcom/test", tags=["Cal.com"])
async def test_calcom_connection():
    """Verify CALCOM_API_KEY works against v2. Start here."""
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set in .env")
    try:
        profile = await calcom_get_me()
        return {"status": "connected", "message": "Cal.com API v2 key is valid!", "profile": profile}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Cal.com error: {e.response.text}")


@app.post("/auth/calcom/test-sync", tags=["Cal.com"])
async def calcom_test_sync(db: Session = Depends(get_db)):
    """
    TEST MODE — pull test coach Cal.com data via API key and store in DB.

    Use this now to verify the full pipeline works end-to-end.
    Real coaches will use GET /auth/calcom/login instead.

    Stores: name, email, timezone, calcom_user_id, calcom_username,
            calcom_default_schedule_id, calcom_event_types (JSON).
    """
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set in .env")
    try:
        profile     = await calcom_get_me()
        event_types = await calcom_get_event_types()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Cal.com error: {e.response.text}")

    email = profile.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Could not get email from Cal.com profile")

    coach = db.query(models.Coach).filter(models.Coach.email == email).first()
    if not coach:
        coach = models.Coach(
            name=profile.get("name", email),
            email=email,
            timezone=profile.get("timeZone", "America/Los_Angeles"),
        )
        db.add(coach)
        db.commit()
        db.refresh(coach)

    coach = store_calcom_profile_to_db(coach, profile, event_types, db)

    return {
        "status":             "success",
        "message":            "Test coach Cal.com data synced to database!",
        "coach_id":           coach.id,
        "name":               coach.name,
        "email":              coach.email,
        "timezone":           coach.timezone,
        "calcom_username":    coach.calcom_username,
        "calcom_user_id":     coach.calcom_user_id,
        "calcom_event_types": coach.calcom_event_types,
        "note":               "Used API key. Real coaches use GET /auth/calcom/login."
    }


@app.get("/calcom/event-types", tags=["Cal.com"])
async def get_calcom_event_types():
    """Fetch all event types from Cal.com account (v2)."""
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        return {"status": "ok", "data": await calcom_get_event_types()}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Cal.com error: {e.response.text}")


@app.get("/calcom/slots", tags=["Cal.com"])
async def get_calcom_slots(
    event_type_id: int,
    start_time: str,
    end_time: str,
    username: Optional[str] = None,
):
    """
    Fetch real available slots for an event type (v2).

    v2 uses event_type_id + full ISO 8601 timestamps.
    (Replaces the old /calcom/availability endpoint which used v1.)

    Example:
        GET /calcom/slots?event_type_id=12345&start_time=2026-04-09T00:00:00Z&end_time=2026-04-16T23:59:59Z

    Get your event_type_id from GET /calcom/event-types first.
    """
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        data = await calcom_get_slots(event_type_id, start_time, end_time, username)
        return {"status": "ok", "slots": data}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Cal.com error: {e.response.text}")


@app.get("/calcom/bookings", tags=["Cal.com"])
async def get_calcom_bookings_endpoint(status: Optional[str] = None):
    """
    Fetch all bookings from Cal.com (v2).
    Status filter options: accepted, pending, cancelled, rejected
    """
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        return {"status": "ok", "bookings": await calcom_get_bookings(status)}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Cal.com error: {e.response.text}")


# ══════════════════════════════════════════════════════════════════════
# CAL.COM — REAL OAUTH MODE (ready when you get credentials)
# ══════════════════════════════════════════════════════════════════════

@app.get("/auth/calcom/login", tags=["Cal.com OAuth"])
def calcom_login():
    """
    REAL MODE — Step 1: Redirect coach to Cal.com consent screen.

    Requires in .env:
        CALCOM_CLIENT_ID=...
        CALCOM_CLIENT_SECRET=...
        CALCOM_REDIRECT_URI=https://your-domain.com/auth/calcom/callback

    To get these: Cal.com dashboard -> Settings -> Developer -> OAuth Apps -> Create.
    Until then, use POST /auth/calcom/test-sync.
    """
    if not CALCOM_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="CALCOM_CLIENT_ID not set. Use POST /auth/calcom/test-sync for now."
        )
    params = {
        "client_id":     CALCOM_CLIENT_ID,
        "redirect_uri":  CALCOM_REDIRECT_URI,
        "response_type": "code",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=f"{CALCOM_AUTH_URL}?{query_string}")


@app.get("/auth/calcom/callback", tags=["Cal.com OAuth"])
async def calcom_oauth_callback(
    code: str = None,
    error: str = None,
    db: Session = Depends(get_db)
):
    """
    REAL MODE — Step 2: Cal.com redirects here after coach approves.

    1. Exchanges code for Cal.com access + refresh tokens
    2. Fetches coach profile + event types from Cal.com (v2)
    3. Creates/updates Coach record in Postgres
    4. Returns needs_preferences=True on first login so agent knows to ask questions
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Cal.com OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code from Cal.com")
    if not CALCOM_CLIENT_ID or not CALCOM_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="CALCOM_CLIENT_ID or CALCOM_CLIENT_SECRET not set.")

    async with httpx.AsyncClient() as client:
        token_response = await client.post(CALCOM_TOKEN_URL, data={
            "code":          code,
            "client_id":     CALCOM_CLIENT_ID,
            "client_secret": CALCOM_CLIENT_SECRET,
            "redirect_uri":  CALCOM_REDIRECT_URI,
            "grant_type":    "authorization_code",
        })
    tokens = token_response.json()
    if "error" in tokens:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {tokens}")

    access_token  = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    token_expiry  = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))

    try:
        profile     = await calcom_get_me(access_token=access_token)
        event_types = await calcom_get_event_types(access_token=access_token)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Cal.com error: {e.response.text}")

    email = profile.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Could not get email from Cal.com profile")

    coach = db.query(models.Coach).filter(models.Coach.email == email).first()
    is_new = coach is None
    if not coach:
        coach = models.Coach(
            name=profile.get("name", email),
            email=email,
            timezone=profile.get("timeZone", "America/Los_Angeles"),
        )
        db.add(coach)
        db.commit()
        db.refresh(coach)

    coach.calcom_access_token  = access_token
    coach.calcom_refresh_token = refresh_token or coach.calcom_refresh_token
    coach.calcom_token_expiry  = token_expiry
    db.commit()

    coach = store_calcom_profile_to_db(coach, profile, event_types, db)

    return {
        "status":             "success",
        "message":            "Coach authenticated via Cal.com!",
        "coach_id":           coach.id,
        "name":               coach.name,
        "email":              coach.email,
        "timezone":           coach.timezone,
        "calcom_username":    coach.calcom_username,
        "calcom_event_types": coach.calcom_event_types,
        "is_new_coach":       is_new,
        "needs_preferences":  not coach.preferences_set,
        "note": "First login — ask preference questions." if not coach.preferences_set else "Returning coach."
    }


# ══════════════════════════════════════════════════════════════════════
# COACH PREFERENCES
# ══════════════════════════════════════════════════════════════════════

@app.post("/coaches/{coach_id}/preferences", tags=["Coaches"])
def set_coach_preferences(
    coach_id: int,
    open_to_rebooking: bool = True,
    db: Session = Depends(get_db)
):
    """
    Save coach preferences after first login.
    The agent asks these because Cal.com doesn't collect them.
    Add more preference fields here as the agent evolves.
    """
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")
    coach.open_to_rebooking = open_to_rebooking
    coach.preferences_set   = True
    db.commit()
    db.refresh(coach)
    return {
        "status":            "success",
        "coach_id":          coach.id,
        "open_to_rebooking": coach.open_to_rebooking,
        "preferences_set":   coach.preferences_set,
    }


# ══════════════════════════════════════════════════════════════════════
# GOOGLE OAUTH (unchanged)
# ══════════════════════════════════════════════════════════════════════

@app.get("/auth/google/login", tags=["Google OAuth"])
def google_login(user_type: str = "participant"):
    """Redirect user to Google consent screen."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not set in .env")
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         GOOGLE_SCOPES,
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         user_type,
    }
    query_string = "&".join(f"{k}={v.replace(' ', '%20')}" for k, v in params.items())
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{query_string}")


@app.get("/auth/google/callback", tags=["Google OAuth"])
async def google_oauth_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    db: Session = Depends(get_db)
):
    """Exchange Google auth code for tokens and save to DB."""
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code from Google")
    user_type = state or "participant"

    async with httpx.AsyncClient() as client:
        tokens = (await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        })).json()

    if "error" in tokens:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {tokens.get('error_description', tokens['error'])}")

    access_token  = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    token_expiry  = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))

    async with httpx.AsyncClient() as client:
        user_info = (await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )).json()

    user_email = user_info.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="Could not get email from Google")

    if user_type == "coach":
        user = db.query(models.Coach).filter(models.Coach.email == user_email).first()
        if not user:
            user = models.Coach(name=user_info.get("name", user_email), email=user_email)
            db.add(user); db.commit(); db.refresh(user)
        user.google_access_token  = access_token
        user.google_refresh_token = refresh_token or user.google_refresh_token
        user.google_token_expiry  = token_expiry
        db.commit()
        return {"message": "Coach Google auth successful", "email": user_email, "coach_id": user.id}

    elif user_type == "participant":
        user = db.query(models.Participant).filter(models.Participant.email == user_email).first()
        if not user:
            user = models.Participant(name=user_info.get("name", user_email), email=user_email)
            db.add(user); db.commit(); db.refresh(user)
        user.google_access_token  = access_token
        user.google_refresh_token = refresh_token or user.google_refresh_token
        user.google_token_expiry  = token_expiry
        db.commit()
        return {"message": "Participant Google auth successful", "email": user_email, "participant_id": user.id}

    else:
        raise HTTPException(status_code=400, detail="state must be 'coach' or 'participant'")


@app.post("/auth/google/callback", response_model=schemas.TokenResponse, tags=["Google OAuth"])
def google_oauth_callback_post(payload: schemas.GoogleOAuthCallback, db: Session = Depends(get_db)):
    """POST version — called by Node OAuth demo server."""
    token_expiry = datetime.utcnow() + timedelta(hours=1)
    if payload.user_type == "coach":
        coach = db.query(models.Coach).filter(models.Coach.email == payload.user_email).first()
        if not coach:
            raise HTTPException(status_code=404, detail=f"No coach with email {payload.user_email}")
        coach.google_access_token  = f"oauth_access_token_for_{payload.user_email}"
        coach.google_refresh_token = f"oauth_refresh_token_for_{payload.user_email}"
        coach.google_token_expiry  = token_expiry
        db.commit()
        return schemas.TokenResponse(message="Google tokens stored for coach", user_type="coach", email=payload.user_email)
    elif payload.user_type == "participant":
        p = db.query(models.Participant).filter(models.Participant.email == payload.user_email).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"No participant with email {payload.user_email}")
        p.google_access_token  = f"oauth_access_token_for_{payload.user_email}"
        p.google_refresh_token = f"oauth_refresh_token_for_{payload.user_email}"
        p.google_token_expiry  = token_expiry
        db.commit()
        return schemas.TokenResponse(message="Google tokens stored for participant", user_type="participant", email=payload.user_email)
    else:
        raise HTTPException(status_code=400, detail="user_type must be 'coach' or 'participant'")


# ══════════════════════════════════════════════════════════════════════
# COACHES (stubs unchanged)
# ══════════════════════════════════════════════════════════════════════

@app.post("/coaches", response_model=schemas.CoachResponse,
          status_code=status.HTTP_201_CREATED, tags=["Coaches"])
def create_coach(coach: schemas.CoachCreate, db: Session = Depends(get_db)):
    if db.query(models.Coach).filter(models.Coach.email == coach.email).first():
        raise HTTPException(status_code=400, detail=f"Coach with email {coach.email} already exists")
    db_coach = models.Coach(**coach.model_dump())
    db.add(db_coach); db.commit(); db.refresh(db_coach)
    return db_coach


@app.get("/coaches", response_model=List[schemas.CoachResponse], tags=["Coaches"])
def list_coaches(db: Session = Depends(get_db)):
    return db.query(models.Coach).filter(models.Coach.is_active == True).all()


@app.get("/coaches/{coach_id}", response_model=schemas.CoachResponse, tags=["Coaches"])
def get_coach(coach_id: int, db: Session = Depends(get_db)):
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")
    return coach


@app.get("/coaches/{coach_id}/availability",
         response_model=List[schemas.CoachAvailabilitySlot], tags=["Coaches"])
def get_coach_availability(coach_id: int, db: Session = Depends(get_db)):
    """
    STUB — returns simulated slots.
    Real data: GET /calcom/slots?event_type_id=<id>&start_time=...&end_time=...
    Get event_type_id from GET /calcom/event-types first.
    """
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")
    if not coach.google_access_token:
        raise HTTPException(status_code=400, detail="Coach has not connected Google Calendar yet.")
    base = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    return [
        schemas.CoachAvailabilitySlot(
            start=(base + timedelta(days=d+1, hours=h)).isoformat(),
            end=(base + timedelta(days=d+1, hours=h+1)).isoformat(),
            timezone=coach.timezone
        )
        for d in range(5) for h in [9, 11, 14, 16]
    ]


# ══════════════════════════════════════════════════════════════════════
# PARTICIPANTS (unchanged)
# ══════════════════════════════════════════════════════════════════════

@app.post("/participants", response_model=schemas.ParticipantResponse,
          status_code=status.HTTP_201_CREATED, tags=["Participants"])
def create_participant(participant: schemas.ParticipantCreate, db: Session = Depends(get_db)):
    if db.query(models.Participant).filter(models.Participant.email == participant.email).first():
        raise HTTPException(status_code=400, detail=f"Participant with email {participant.email} already exists")
    db_p = models.Participant(**participant.model_dump())
    db.add(db_p); db.commit(); db.refresh(db_p)
    return db_p


@app.get("/participants", response_model=List[schemas.ParticipantResponse], tags=["Participants"])
def list_participants(db: Session = Depends(get_db)):
    return db.query(models.Participant).all()


# ══════════════════════════════════════════════════════════════════════
# BOOKINGS (stubs unchanged)
# ══════════════════════════════════════════════════════════════════════

@app.post("/bookings", response_model=schemas.BookingResponse,
          status_code=status.HTTP_201_CREATED, tags=["Bookings"])
def create_booking(booking: schemas.BookingCreate, db: Session = Depends(get_db)):
    """
    STUB — uses simulated meeting link.
    Real version: call calcom_create_booking() with coach's event_type_id.
    v2 booking uses attendee object (not responses) — see calcom_create_booking() above.
    """
    coach = db.query(models.Coach).filter(models.Coach.id == booking.coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {booking.coach_id} not found")
    participant = db.query(models.Participant).filter(
        models.Participant.id == booking.participant_id
    ).first()
    if not participant:
        raise HTTPException(status_code=404, detail=f"Participant {booking.participant_id} not found")
    conflict = db.query(models.Booking).filter(
        models.Booking.coach_id == booking.coach_id,
        models.Booking.status == "confirmed",
        models.Booking.start_time < booking.end_time,
        models.Booking.end_time > booking.start_time
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail=f"Coach already booked {conflict.start_time} to {conflict.end_time}")

    db_booking = models.Booking(
        coach_id=booking.coach_id,
        participant_id=booking.participant_id,
        start_time=booking.start_time,
        end_time=booking.end_time,
        notes=booking.notes,
        meeting_link=f"https://meet.google.com/simulated-{coach.id}-{participant.id}",
        calcom_booking_id=f"calcom_booking_{coach.id}_{participant.id}",
        coach_gcal_event_id=f"gcal_coach_event_{coach.id}",
        participant_gcal_event_id=f"gcal_participant_event_{participant.id}",
        status="confirmed",
        confirmation_sent=False,
    )
    db.add(db_booking); db.commit(); db.refresh(db_booking)
    print(f"[Stub] Would send confirmation to {coach.email} and {participant.email}")
    return db_booking


@app.get("/bookings", response_model=List[schemas.BookingResponse], tags=["Bookings"])
def list_bookings(db: Session = Depends(get_db)):
    return db.query(models.Booking).all()


@app.get("/bookings/{booking_id}", response_model=schemas.BookingResponse, tags=["Bookings"])
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Booking {booking_id} not found")
    return booking


@app.patch("/bookings/{booking_id}/cancel",
           response_model=schemas.BookingResponse, tags=["Bookings"])
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    """
    STUB — updates status in DB only.
    Real version: call calcom_cancel_booking(uid, reason) first, then update DB.
    v2 cancel is POST /v2/bookings/{uid}/cancel (not DELETE).
    """
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Booking {booking_id} not found")
    booking.status = "cancelled"
    db.commit(); db.refresh(booking)
    return booking

