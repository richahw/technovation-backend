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
              CALCOM_CLIENT_SECRET.

NOTE: Uses Cal.com API v2.
  - Auth: Authorization: Bearer <token>
  - Required header on API requests: cal-api-version: 2024-08-13
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import urlencode
import os
import secrets
import httpx

from app.database import engine, get_db, Base
from app import models, schemas

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Scheduling Platform API",
    description="""
    Technovation x Delta Agent-Assisted Scheduling Platform.

    Cal.com integration:
    - Test mode: POST /auth/calcom/test-sync
    - Real OAuth: GET /auth/calcom/login

    Uses Cal.com API v2.
    """,
    version="0.5.0",
)

# ──────────────────────────────────────────────────────────────────────
# Google OAuth config
# ──────────────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = (
        os.getenv("GOOGLE_REDIRECT_URI")
        or (
            f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/auth/google/callback"
            if os.getenv("RENDER_EXTERNAL_HOSTNAME")
            else None
        )
        or (
            f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/auth/google/callback"
            if os.getenv("RAILWAY_PUBLIC_DOMAIN")
            else None
        )
        or "http://localhost:8000/auth/google/callback"
)
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/gmail.send",
    ]
)

# ──────────────────────────────────────────────────────────────────────
# Cal.com config
# ──────────────────────────────────────────────────────────────────────
CALCOM_API_KEY = os.getenv("CALCOM_API_KEY")
CALCOM_CLIENT_ID = os.getenv("CALCOM_CLIENT_ID")
CALCOM_CLIENT_SECRET = os.getenv("CALCOM_CLIENT_SECRET")

CALCOM_BASE_URL = "https://api.cal.com/v2"
CALCOM_API_VERSION = "2024-08-13"       # for /me, /bookings, /slots
CALCOM_EVENT_TYPES_VERSION = "2024-06-14"  # /event-types requires this specific version

# Correct OAuth endpoints for Cal.com v2
CALCOM_AUTH_URL = "https://app.cal.com/auth/oauth2/authorize"
CALCOM_TOKEN_URL = "https://api.cal.com/v2/auth/oauth2/token"

CALCOM_REDIRECT_URI = (
        os.getenv("CALCOM_REDIRECT_URI")
        or (
            f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/auth/calcom/callback"
            if os.getenv("RENDER_EXTERNAL_HOSTNAME")
            else None
        )
        or (
            f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/auth/calcom/callback"
            if os.getenv("RAILWAY_PUBLIC_DOMAIN")
            else None
        )
        or "http://localhost:8000/auth/calcom/callback"
)

CALCOM_OAUTH_SCOPES = os.getenv(
    "CALCOM_OAUTH_SCOPES",
    "PROFILE_READ EVENT_TYPE_READ BOOKING_READ SCHEDULE_READ",
)


def calcom_headers(access_token: Optional[str] = None) -> dict:
    """
    Build headers for Cal.com v2 API requests.
    - If access_token is provided, use OAuth token
    - Otherwise fall back to CALCOM_API_KEY for test mode
    """
    token = access_token or CALCOM_API_KEY
    if not token:
        raise HTTPException(status_code=500, detail="No Cal.com token available")
    return {
        "Authorization": f"Bearer {token}",
        "cal-api-version": CALCOM_API_VERSION,
        "Content-Type": "application/json",
    }


# ──────────────────────────────────────────────────────────────────────
# Cal.com helper functions
# ──────────────────────────────────────────────────────────────────────
async def calcom_get_me(access_token: Optional[str] = None) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{CALCOM_BASE_URL}/me",
            headers=calcom_headers(access_token),
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


async def calcom_get_event_types(access_token: Optional[str] = None, username: Optional[str] = None) -> list:
    # /event-types requires cal-api-version: 2024-06-14 (different from other endpoints)
    # With API key: pass ?username= to identify whose types to fetch
    # With OAuth token: no username param needed; token provides identity
    params = {}
    if not access_token and username:
        params["username"] = username

    token = access_token or CALCOM_API_KEY
    if not token:
        raise HTTPException(status_code=500, detail="No Cal.com token available")
    headers = {
        "Authorization": f"Bearer {token}",
        "cal-api-version": CALCOM_EVENT_TYPES_VERSION,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{CALCOM_BASE_URL}/event-types",
            headers=headers,
            params=params,
        )
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data", [])
    if isinstance(data, dict):
        # may be wrapped in eventTypeGroups for some account types
        groups = data.get("eventTypeGroups", [])
        if groups:
            return [et for group in groups for et in group.get("eventTypes", [])]
        return data.get("eventTypes", [])
    return data


async def calcom_get_slots(
        event_type_id: int,
        start_time: str,
        end_time: str,
        username: Optional[str] = None,
        access_token: Optional[str] = None,
) -> dict:
    params = {
        "eventTypeId": event_type_id,
        "startTime": start_time,
        "endTime": end_time,
    }
    if username:
        params["username"] = username

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{CALCOM_BASE_URL}/slots/available",
            headers=calcom_headers(access_token),
            params=params,
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


async def calcom_get_bookings(
        status_filter: Optional[str] = None,
        access_token: Optional[str] = None,
) -> dict:
    params = {}
    if status_filter:
        params["status"] = status_filter

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{CALCOM_BASE_URL}/bookings",
            headers=calcom_headers(access_token),
            params=params,
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
        access_token: Optional[str] = None,
) -> dict:
    payload = {
        "eventTypeId": event_type_id,
        "start": start,
        "attendee": {
            "name": attendee_name,
            "email": attendee_email,
            "timeZone": timezone,
            "language": language,
        },
        "metadata": {},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{CALCOM_BASE_URL}/bookings",
            headers=calcom_headers(access_token),
            json=payload,
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


async def calcom_cancel_booking(
        uid: str,
        reason: str = "",
        access_token: Optional[str] = None,
) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{CALCOM_BASE_URL}/bookings/{uid}/cancel",
            headers=calcom_headers(access_token),
            json={"cancellationReason": reason},
        )
    r.raise_for_status()
    data = r.json()
    return data.get("data", data)


def store_calcom_profile_to_db(
        coach: models.Coach,
        profile: dict,
        event_types_data,
        db: Session,
):
    coach.name = profile.get("name", coach.name)
    coach.email = profile.get("email", coach.email)
    coach.timezone = profile.get("timeZone", coach.timezone)
    coach.calcom_user_id = str(profile.get("id", "")) if profile.get("id") is not None else coach.calcom_user_id
    coach.calcom_username = profile.get("username", coach.calcom_username or "")
    coach.calcom_default_schedule_id = (
        str(profile.get("defaultScheduleId", ""))
        if profile.get("defaultScheduleId") is not None
        else coach.calcom_default_schedule_id
    )

    raw_event_types = event_types_data if isinstance(event_types_data, list) else []

    coach.calcom_event_types = [
        {
            "id": et.get("id"),
            "title": et.get("title"),
            "length": et.get("lengthInMinutes"),
            "slug": et.get("slug"),
            "description": et.get("description"),
        }
        for et in raw_event_types
    ]

    db.commit()
    db.refresh(coach)
    return coach


# ──────────────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {
        "status": "ok",
        "message": "Scheduling Platform API is running",
        "docs": "/docs",
    }


# ──────────────────────────────────────────────────────────────────────
# Cal.com test mode
# ──────────────────────────────────────────────────────────────────────
@app.get("/calcom/test", tags=["Cal.com"])
async def test_calcom_connection():
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set in .env")
    try:
        profile = await calcom_get_me()
        return {
            "status": "connected",
            "message": "Cal.com API v2 key is valid!",
            "profile": profile,
        }
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Cal.com error: {e.response.text}",
        )


@app.post("/auth/calcom/test-sync", tags=["Cal.com"])
async def calcom_test_sync(db: Session = Depends(get_db)):
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set in .env")

    try:
        profile = await calcom_get_me()
        username = profile.get("username")
        event_types = await calcom_get_event_types(username=username)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Cal.com error: {e.response.text}",
        )

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
        "status": "success",
        "message": "Test coach Cal.com data synced to database!",
        "coach_id": coach.id,
        "name": coach.name,
        "email": coach.email,
        "timezone": coach.timezone,
        "calcom_username": coach.calcom_username,
        "calcom_user_id": coach.calcom_user_id,
        "calcom_event_types": coach.calcom_event_types,
        "note": "Used API key. Real coaches use GET /auth/calcom/login.",
    }


@app.get("/calcom/event-types", tags=["Cal.com"])
async def get_calcom_event_types():
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        return {"status": "ok", "data": await calcom_get_event_types()}
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Cal.com error: {e.response.text}",
        )


@app.get("/calcom/slots", tags=["Cal.com"])
async def get_calcom_slots(
        event_type_id: int,
        start_time: str,
        end_time: str,
        username: Optional[str] = None,
):
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        data = await calcom_get_slots(
            event_type_id=event_type_id,
            start_time=start_time,
            end_time=end_time,
            username=username,
        )
        return {"status": "ok", "slots": data}
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Cal.com error: {e.response.text}",
        )


@app.get("/calcom/bookings", tags=["Cal.com"])
async def get_calcom_bookings_endpoint(status: Optional[str] = None):
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        return {"status": "ok", "bookings": await calcom_get_bookings(status)}
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Cal.com error: {e.response.text}",
        )


# ──────────────────────────────────────────────────────────────────────
# Cal.com real OAuth mode
# ──────────────────────────────────────────────────────────────────────
@app.get("/auth/calcom/login", tags=["Cal.com OAuth"])
def calcom_login():
    """
    Redirect coach to Cal.com OAuth consent page.
    """
    if not CALCOM_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="CALCOM_CLIENT_ID not set. Use POST /auth/calcom/test-sync for now.",
        )

    state = secrets.token_urlsafe(32)

    params = {
        "client_id": CALCOM_CLIENT_ID,
        "redirect_uri": CALCOM_REDIRECT_URI,
        "response_type": "code",
        "scope": CALCOM_OAUTH_SCOPES,
        "state": state,
    }

    return RedirectResponse(url=f"{CALCOM_AUTH_URL}?{urlencode(params)}")


@app.get("/auth/calcom/callback", tags=["Cal.com OAuth"])
async def calcom_oauth_callback(
        code: Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
        db: Session = Depends(get_db),
):
    """
    Exchange authorization code for tokens, fetch coach profile, and store in DB.
    """
    if error:
        message = error_description or error
        raise HTTPException(status_code=400, detail=f"Cal.com OAuth error: {message}")

    if not code:
        raise HTTPException(status_code=400, detail="No authorization code from Cal.com")

    if not CALCOM_CLIENT_ID or not CALCOM_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="CALCOM_CLIENT_ID or CALCOM_CLIENT_SECRET not set.",
        )

    token_payload = {
        "client_id": CALCOM_CLIENT_ID,
        "client_secret": CALCOM_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": CALCOM_REDIRECT_URI,
    }

    # FIX 2: send as form-encoded (data=), not JSON (json=)
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_response = await client.post(
            CALCOM_TOKEN_URL,
            data=token_payload,
        )

    if token_response.status_code >= 400:
        raise HTTPException(
            status_code=token_response.status_code,
            detail=f"Token exchange failed: {token_response.text}",
        )

    tokens = token_response.json()

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 1800)

    if not access_token:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {tokens}")

    token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

    try:
        profile = await calcom_get_me(access_token=access_token)
        username = profile.get("username")
        event_types = await calcom_get_event_types(access_token=access_token, username=username)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Cal.com API error after OAuth: {e.response.text}",
        )

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

    coach.calcom_access_token = access_token
    coach.calcom_refresh_token = refresh_token or coach.calcom_refresh_token
    coach.calcom_token_expiry = token_expiry
    db.commit()
    db.refresh(coach)

    coach = store_calcom_profile_to_db(coach, profile, event_types, db)

    return {
        "status": "success",
        "message": "Coach authenticated via Cal.com!",
        "coach_id": coach.id,
        "name": coach.name,
        "email": coach.email,
        "timezone": coach.timezone,
        "calcom_username": coach.calcom_username,
        "calcom_event_types": coach.calcom_event_types,
        "is_new_coach": is_new,
        "needs_preferences": not getattr(coach, "preferences_set", False),
        "granted_scope": tokens.get("scope"),
        "note": "First login — ask preference questions."
        if not getattr(coach, "preferences_set", False)
        else "Returning coach.",
    }


# ──────────────────────────────────────────────────────────────────────
# Coach preferences
# ──────────────────────────────────────────────────────────────────────
@app.post("/coaches/{coach_id}/preferences", tags=["Coaches"])
def set_coach_preferences(
        coach_id: int,
        open_to_rebooking: bool = True,
        db: Session = Depends(get_db),
):
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")

    coach.open_to_rebooking = open_to_rebooking
    coach.preferences_set = True
    db.commit()
    db.refresh(coach)

    return {
        "status": "success",
        "coach_id": coach.id,
        "open_to_rebooking": coach.open_to_rebooking,
        "preferences_set": coach.preferences_set,
    }


# ──────────────────────────────────────────────────────────────────────
# Google OAuth
# ──────────────────────────────────────────────────────────────────────
@app.get("/auth/google/login", tags=["Google OAuth"])
def google_login(user_type: str = "participant"):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not set in .env")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": user_type,
    }
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@app.get("/auth/google/callback", tags=["Google OAuth"])
async def google_oauth_callback(
        code: Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        db: Session = Depends(get_db),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code from Google")

    user_type = state or "participant"

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

    tokens = token_resp.json()
    if "error" in tokens:
        raise HTTPException(
            status_code=400,
            detail=f"Token exchange failed: {tokens.get('error_description', tokens['error'])}",
        )

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    token_expiry = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))

    async with httpx.AsyncClient(timeout=30.0) as client:
        user_info_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    user_info = user_info_resp.json()

    user_email = user_info.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="Could not get email from Google")

    if user_type == "coach":
        user = db.query(models.Coach).filter(models.Coach.email == user_email).first()
        if not user:
            user = models.Coach(name=user_info.get("name", user_email), email=user_email)
            db.add(user)
            db.commit()
            db.refresh(user)

        user.google_access_token = access_token
        user.google_refresh_token = refresh_token or user.google_refresh_token
        user.google_token_expiry = token_expiry
        db.commit()

        return {
            "message": "Coach Google auth successful",
            "email": user_email,
            "coach_id": user.id,
        }

    if user_type == "participant":
        user = db.query(models.Participant).filter(models.Participant.email == user_email).first()
        if not user:
            user = models.Participant(name=user_info.get("name", user_email), email=user_email)
            db.add(user)
            db.commit()
            db.refresh(user)

        user.google_access_token = access_token
        user.google_refresh_token = refresh_token or user.google_refresh_token
        user.google_token_expiry = token_expiry
        db.commit()

        return {
            "message": "Participant Google auth successful",
            "email": user_email,
            "participant_id": user.id,
        }

    raise HTTPException(status_code=400, detail="state must be 'coach' or 'participant'")


@app.post("/auth/google/callback", response_model=schemas.TokenResponse, tags=["Google OAuth"])
def google_oauth_callback_post(
        payload: schemas.GoogleOAuthCallback,
        db: Session = Depends(get_db),
):
    token_expiry = datetime.utcnow() + timedelta(hours=1)

    if payload.user_type == "coach":
        coach = db.query(models.Coach).filter(models.Coach.email == payload.user_email).first()
        if not coach:
            raise HTTPException(status_code=404, detail=f"No coach with email {payload.user_email}")

        coach.google_access_token = f"oauth_access_token_for_{payload.user_email}"
        coach.google_refresh_token = f"oauth_refresh_token_for_{payload.user_email}"
        coach.google_token_expiry = token_expiry
        db.commit()

        return schemas.TokenResponse(
            message="Google tokens stored for coach",
            user_type="coach",
            email=payload.user_email,
        )

    if payload.user_type == "participant":
        participant = db.query(models.Participant).filter(
            models.Participant.email == payload.user_email
        ).first()
        if not participant:
            raise HTTPException(
                status_code=404,
                detail=f"No participant with email {payload.user_email}",
            )

        participant.google_access_token = f"oauth_access_token_for_{payload.user_email}"
        participant.google_refresh_token = f"oauth_refresh_token_for_{payload.user_email}"
        participant.google_token_expiry = token_expiry
        db.commit()

        return schemas.TokenResponse(
            message="Google tokens stored for participant",
            user_type="participant",
            email=payload.user_email,
        )

    raise HTTPException(status_code=400, detail="user_type must be 'coach' or 'participant'")


# ──────────────────────────────────────────────────────────────────────
# Coaches
# ──────────────────────────────────────────────────────────────────────
@app.post(
    "/coaches",
    response_model=schemas.CoachResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Coaches"],
)
def create_coach(coach: schemas.CoachCreate, db: Session = Depends(get_db)):
    if db.query(models.Coach).filter(models.Coach.email == coach.email).first():
        raise HTTPException(status_code=400, detail=f"Coach with email {coach.email} already exists")

    db_coach = models.Coach(**coach.model_dump())
    db.add(db_coach)
    db.commit()
    db.refresh(db_coach)
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


@app.get(
    "/coaches/{coach_id}/availability",
    response_model=List[schemas.CoachAvailabilitySlot],
    tags=["Coaches"],
)
def get_coach_availability(coach_id: int, db: Session = Depends(get_db)):
    """
    STUB — returns simulated slots.
    Real data: GET /calcom/slots?event_type_id=<id>&start_time=...&end_time=...
    """
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")
    if not coach.google_access_token:
        raise HTTPException(status_code=400, detail="Coach has not connected Google Calendar yet.")

    base = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    return [
        schemas.CoachAvailabilitySlot(
            start=(base + timedelta(days=d + 1, hours=h)).isoformat(),
            end=(base + timedelta(days=d + 1, hours=h + 1)).isoformat(),
            timezone=coach.timezone,
        )
        for d in range(5)
        for h in [9, 11, 14, 16]
    ]


# ──────────────────────────────────────────────────────────────────────
# Participants
# ──────────────────────────────────────────────────────────────────────
@app.post(
    "/participants",
    response_model=schemas.ParticipantResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Participants"],
)
def create_participant(participant: schemas.ParticipantCreate, db: Session = Depends(get_db)):
    if db.query(models.Participant).filter(models.Participant.email == participant.email).first():
        raise HTTPException(
            status_code=400,
            detail=f"Participant with email {participant.email} already exists",
        )

    db_participant = models.Participant(**participant.model_dump())
    db.add(db_participant)
    db.commit()
    db.refresh(db_participant)
    return db_participant


@app.get("/participants", response_model=List[schemas.ParticipantResponse], tags=["Participants"])
def list_participants(db: Session = Depends(get_db)):
    return db.query(models.Participant).all()


# ──────────────────────────────────────────────────────────────────────
# Bookings
# ──────────────────────────────────────────────────────────────────────
@app.post(
    "/bookings",
    response_model=schemas.BookingResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Bookings"],
)
def create_booking(booking: schemas.BookingCreate, db: Session = Depends(get_db)):
    """
    STUB — uses simulated meeting link.
    Real version: call calcom_create_booking() with coach's event_type_id.
    """
    coach = db.query(models.Coach).filter(models.Coach.id == booking.coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {booking.coach_id} not found")

    participant = db.query(models.Participant).filter(
        models.Participant.id == booking.participant_id
    ).first()
    if not participant:
        raise HTTPException(
            status_code=404,
            detail=f"Participant {booking.participant_id} not found",
        )

    conflict = (
        db.query(models.Booking)
        .filter(
            models.Booking.coach_id == booking.coach_id,
            models.Booking.status == "confirmed",
            models.Booking.start_time < booking.end_time,
            models.Booking.end_time > booking.start_time,
            )
        .first()
    )
    if conflict:
        raise HTTPException(
            status_code=409,
            detail=f"Coach already booked {conflict.start_time} to {conflict.end_time}",
        )

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
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)

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


@app.patch(
    "/bookings/{booking_id}/cancel",
    response_model=schemas.BookingResponse,
    tags=["Bookings"],
)
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    """
    STUB — updates status in DB only.
    Real version: call calcom_cancel_booking(uid, reason) first, then update DB.
    """
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Booking {booking_id} not found")

    booking.status = "cancelled"
    db.commit()
    db.refresh(booking)
    return booking


