"""
main.py — FastAPI Application Entry Point

Run locally:
    source .venv/bin/activate
    python -m uvicorn main:app --reload

On Railway: deployed automatically via Procfile.

Agent endpoints:
    POST /agent/chat?session_id=user1&message=hello
    DELETE /agent/sessions/{session_id}
    GET  /agent/sessions/{session_id}/role
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import os
import httpx

from app.database import engine, get_db, Base
from app import models, schemas

# ── Agent import ──────────────────────────────────────────────────────
try:
    from coaching_agent.agent import SessionManager
    agent_manager = SessionManager()
    AGENT_AVAILABLE = True
    print("✅ coaching_agent loaded — /agent/* endpoints enabled.")
except ImportError as e:
    agent_manager = None
    AGENT_AVAILABLE = False
    print(f"⚠️  coaching_agent not installed — /agent/* endpoints disabled. Error: {e}")

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Scheduling Platform API",
    description="""
    Technovation x Delta Agent-Assisted Scheduling Platform.

    **Agent chat:**
    - `POST /agent/chat` — send a message to the scheduling agent
    - `DELETE /agent/sessions/{session_id}` — end a session

    **Cal.com integration:**
    - Test mode: `POST /auth/calcom/test-sync`
    - Real OAuth: `GET /auth/calcom/login`
    """,
    version="0.5.0",
)

# ── CORS — allows frontend to talk to backend ─────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Google OAuth config ───────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

_host = (
    os.getenv("GOOGLE_REDIRECT_URI")
    or (f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/auth/google/callback"
        if os.getenv("RENDER_EXTERNAL_HOSTNAME") else None)
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/auth/google/callback"
        if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None)
    or "http://localhost:8000/auth/google/callback"
)
GOOGLE_REDIRECT_URI = _host
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
CALCOM_BASE_URL      = "https://api.cal.com/v2"
CALCOM_API_VERSION   = "2024-08-13"
CALCOM_AUTH_URL      = "https://app.cal.com/auth/oauth2/authorize"
CALCOM_TOKEN_URL     = "https://app.cal.com/api/auth/oauth/token"

_calcom_redirect = (
    os.getenv("CALCOM_REDIRECT_URI")
    or (f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/auth/calcom/callback"
        if os.getenv("RENDER_EXTERNAL_HOSTNAME") else None)
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/auth/calcom/callback"
        if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None)
    or "http://localhost:8000/auth/calcom/callback"
)
CALCOM_REDIRECT_URI = _calcom_redirect

# Base URL for agent OAuth links
BASE_URL = (
    os.getenv("BASE_URL")
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
        if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None)
    or "http://localhost:8000"
)


def calcom_headers(access_token: str = None) -> dict:
    token = access_token or CALCOM_API_KEY
    return {
        "Authorization":   f"Bearer {token}",
        "cal-api-version": CALCOM_API_VERSION,
        "Content-Type":    "application/json",
    }


# ══════════════════════════════════════════════════════════════════════
# CAL.COM HELPERS
# ══════════════════════════════════════════════════════════════════════

async def calcom_get_me(access_token: str = None) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CALCOM_BASE_URL}/me", headers=calcom_headers(access_token))
    r.raise_for_status()
    return r.json().get("data", r.json())


async def calcom_get_event_types(access_token: str = None) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CALCOM_BASE_URL}/event-types", headers=calcom_headers(access_token))
    r.raise_for_status()
    return r.json().get("data", r.json())


async def calcom_get_slots(event_type_id: int, start_time: str, end_time: str,
                            username: Optional[str] = None) -> dict:
    params = {"eventTypeId": event_type_id, "startTime": start_time, "endTime": end_time}
    if username:
        params["username"] = username
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CALCOM_BASE_URL}/slots/available",
                             headers=calcom_headers(), params=params)
    r.raise_for_status()
    return r.json().get("data", r.json())


async def calcom_get_bookings(status_filter: Optional[str] = None) -> dict:
    params = {}
    if status_filter:
        params["status"] = status_filter
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CALCOM_BASE_URL}/bookings",
                             headers=calcom_headers(), params=params)
    r.raise_for_status()
    return r.json().get("data", r.json())


async def calcom_create_booking(event_type_id: int, start: str, attendee_name: str,
                                 attendee_email: str, timezone: str) -> dict:
    payload = {
        "eventTypeId": event_type_id,
        "start": start,
        "attendee": {"name": attendee_name, "email": attendee_email,
                     "timeZone": timezone, "language": "en"},
        "metadata": {},
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{CALCOM_BASE_URL}/bookings",
                              headers=calcom_headers(), json=payload)
    r.raise_for_status()
    return r.json().get("data", r.json())


def store_calcom_profile_to_db(coach: models.Coach, profile: dict,
                                event_types_data: dict, db: Session):
    coach.name     = profile.get("name", coach.name)
    coach.email    = profile.get("email", coach.email)
    coach.timezone = profile.get("timeZone", coach.timezone)
    coach.calcom_user_id             = str(profile.get("id", ""))
    coach.calcom_username            = profile.get("username", "")
    coach.calcom_default_schedule_id = str(profile.get("defaultScheduleId", ""))
    raw = event_types_data.get("eventTypes", [])
    coach.calcom_event_types = [
        {"id": et.get("id"), "title": et.get("title"),
         "length": et.get("lengthInMinutes"), "slug": et.get("slug")}
        for et in raw
    ]
    db.commit()
    db.refresh(coach)
    return coach


# ══════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
def root():
    return {
        "status":          "ok",
        "message":         "Scheduling Platform API is running",
        "agent_available": AGENT_AVAILABLE,
        "docs":            "/docs",
    }


# ══════════════════════════════════════════════════════════════════════
# AGENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.post("/agent/chat", tags=["Agent"])
def agent_chat(session_id: str, message: str):
    """
    Send a message to the scheduling agent.

    First message → agent asks: coach or participant?
    Coach flow:       Cal.com OAuth → preferences
    Participant flow: Google OAuth → find slots → book → follow-up

    Args:
        session_id: unique ID for this user's conversation (e.g. their email or a UUID)
        message:    the user's message
    """
    if not AGENT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Agent not available. Check that coaching_agent is installed."
        )
    response = agent_manager.respond(session_id, message)
    return {
        "session_id": session_id,
        "response":   response,
        "role":       agent_manager.get_role(session_id),
    }


@app.delete("/agent/sessions/{session_id}", tags=["Agent"])
def delete_session(session_id: str):
    """End a session and clear conversation history."""
    if not AGENT_AVAILABLE:
        raise HTTPException(status_code=503, detail="Agent not available.")
    agent_manager.delete(session_id)
    return {"status": "deleted", "session_id": session_id}


@app.get("/agent/sessions/{session_id}/role", tags=["Agent"])
def get_session_role(session_id: str):
    """Check the detected role (coach/participant) for a session."""
    if not AGENT_AVAILABLE:
        raise HTTPException(status_code=503, detail="Agent not available.")
    return {"session_id": session_id, "role": agent_manager.get_role(session_id)}


# ══════════════════════════════════════════════════════════════════════
# CAL.COM TEST MODE
# ══════════════════════════════════════════════════════════════════════

@app.get("/calcom/test", tags=["Cal.com"])
async def test_calcom_connection():
    """Verify CALCOM_API_KEY works."""
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set in .env")
    try:
        profile = await calcom_get_me()
        return {"status": "connected", "profile": profile}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@app.post("/auth/calcom/test-sync", tags=["Cal.com"])
async def calcom_test_sync(db: Session = Depends(get_db)):
    """Pull test coach Cal.com data via API key and store in DB."""
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set in .env")
    try:
        profile     = await calcom_get_me()
        event_types = await calcom_get_event_types()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

    email = profile.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Could not get email from Cal.com")

    coach = db.query(models.Coach).filter(models.Coach.email == email).first()
    if not coach:
        coach = models.Coach(name=profile.get("name", email), email=email,
                             timezone=profile.get("timeZone", "America/Los_Angeles"))
        db.add(coach); db.commit(); db.refresh(coach)

    coach = store_calcom_profile_to_db(coach, profile, event_types, db)
    return {
        "status":             "success",
        "message":            "Test coach synced!",
        "coach_id":           coach.id,
        "name":               coach.name,
        "calcom_username":    coach.calcom_username,
        "calcom_event_types": coach.calcom_event_types,
    }


@app.get("/calcom/event-types", tags=["Cal.com"])
async def get_calcom_event_types():
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        return {"status": "ok", "data": await calcom_get_event_types()}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@app.get("/calcom/slots", tags=["Cal.com"])
async def get_calcom_slots(event_type_id: int, start_time: str, end_time: str,
                            username: Optional[str] = None):
    """
    Fetch real available slots.
    Example: GET /calcom/slots?event_type_id=12345&start_time=2026-04-21T00:00:00Z&end_time=2026-04-28T23:59:59Z
    """
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        return {"status": "ok", "slots": await calcom_get_slots(event_type_id, start_time, end_time, username)}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@app.get("/calcom/bookings", tags=["Cal.com"])
async def get_calcom_bookings_endpoint(status: Optional[str] = None):
    if not CALCOM_API_KEY:
        raise HTTPException(status_code=500, detail="CALCOM_API_KEY not set.")
    try:
        return {"status": "ok", "bookings": await calcom_get_bookings(status)}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


# ══════════════════════════════════════════════════════════════════════
# CAL.COM REAL OAUTH
# ══════════════════════════════════════════════════════════════════════

@app.get("/auth/calcom/login", tags=["Cal.com OAuth"])
def calcom_login(session_id: Optional[str] = None):
    """
    Redirect coach to Cal.com consent screen.
    Pass session_id so the callback can notify the agent session.

    Example: GET /auth/calcom/login?session_id=user123
    """
    if not CALCOM_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="CALCOM_CLIENT_ID not set. Use POST /auth/calcom/test-sync for now."
        )
    state = session_id or "no-session"
    params = {
        "client_id":     CALCOM_CLIENT_ID,
        "redirect_uri":  CALCOM_REDIRECT_URI,
        "response_type": "code",
        "state":         state,
        # explicitly request needed scopes
        "scope":         "READ_PROFILE READ_EVENT_TYPE READ_BOOKING WRITE_BOOKING READ_AVAILABILITY",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=f"{CALCOM_AUTH_URL}?{query_string}")


@app.get("/auth/calcom/callback", tags=["Cal.com OAuth"])
async def calcom_oauth_callback(code: str = None, state: str = None,
                                 error: str = None, db: Session = Depends(get_db)):
    """Cal.com redirects here after coach approves OAuth."""
    if error:
        raise HTTPException(status_code=400, detail=f"Cal.com OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code from Cal.com")
    if not CALCOM_CLIENT_ID or not CALCOM_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="CALCOM_CLIENT_ID or CALCOM_CLIENT_SECRET not set.")

    async with httpx.AsyncClient() as client:
        tokens = (await client.post(CALCOM_TOKEN_URL, data={
            "code": code, "client_id": CALCOM_CLIENT_ID,
            "client_secret": CALCOM_CLIENT_SECRET,
            "redirect_uri": CALCOM_REDIRECT_URI, "grant_type": "authorization_code",
        })).json()

    if "error" in tokens:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {tokens}")

    access_token  = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    token_expiry  = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))

    try:
        profile     = await calcom_get_me(access_token=access_token)
        event_types = await calcom_get_event_types(access_token=access_token)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

    email = profile.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Could not get email from Cal.com")

    coach = db.query(models.Coach).filter(models.Coach.email == email).first()
    is_new = coach is None
    if not coach:
        coach = models.Coach(name=profile.get("name", email), email=email,
                             timezone=profile.get("timeZone", "America/Los_Angeles"))
        db.add(coach); db.commit(); db.refresh(coach)

    coach.calcom_access_token  = access_token
    coach.calcom_refresh_token = refresh_token or coach.calcom_refresh_token
    coach.calcom_token_expiry  = token_expiry
    db.commit()
    coach = store_calcom_profile_to_db(coach, profile, event_types, db)

    session_id = state if state and state != "no-session" else None
    if session_id and AGENT_AVAILABLE:
        agent_manager.set_calcom_connected(session_id)

    return {
        "status":            "success",
        "message":           "✅ Cal.com connected! You can close this tab and return to the chat.",
        "coach_id":          coach.id,
        "name":              coach.name,
        "calcom_username":   coach.calcom_username,
        "needs_preferences": not coach.preferences_set,
        "session_id":        session_id,
    }


# ══════════════════════════════════════════════════════════════════════
# COACH PREFERENCES
# ══════════════════════════════════════════════════════════════════════

@app.post("/coaches/{coach_id}/preferences", tags=["Coaches"])
def set_coach_preferences(coach_id: int, open_to_rebooking: bool = True,
                           db: Session = Depends(get_db)):
    """Save coach preferences collected after first login."""
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")
    coach.open_to_rebooking = open_to_rebooking
    coach.preferences_set   = True
    db.commit(); db.refresh(coach)
    return {"status": "success", "coach_id": coach.id,
            "open_to_rebooking": coach.open_to_rebooking}


# ══════════════════════════════════════════════════════════════════════
# GOOGLE OAUTH
# ══════════════════════════════════════════════════════════════════════

@app.get("/auth/google/login", tags=["Google OAuth"])
def google_login(user_type: str = "participant", session_id: Optional[str] = None):
    """
    Redirect user to Google consent screen.
    Example: GET /auth/google/login?user_type=participant&session_id=user123
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not set in .env")
    state = f"{user_type}:{session_id or 'no-session'}"
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         GOOGLE_SCOPES,
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         state,
    }
    query_string = "&".join(f"{k}={v.replace(' ', '%20')}" for k, v in params.items())
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{query_string}")


@app.get("/auth/google/callback", tags=["Google OAuth"])
async def google_oauth_callback(code: str = None, state: str = None,
                                 error: str = None, db: Session = Depends(get_db)):
    """Exchange Google auth code for tokens and save to DB."""
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code from Google")

    parts      = (state or "participant:no-session").split(":", 1)
    user_type  = parts[0] if parts else "participant"
    session_id = parts[1] if len(parts) > 1 and parts[1] != "no-session" else None

    async with httpx.AsyncClient() as client:
        tokens = (await client.post(GOOGLE_TOKEN_URL, data={
            "code": code, "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
        })).json()

    if "error" in tokens:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {tokens.get('error_description', tokens['error'])}")

    access_token  = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    token_expiry  = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))

    async with httpx.AsyncClient() as client:
        user_info = (await client.get(GOOGLE_USERINFO_URL,
                                      headers={"Authorization": f"Bearer {access_token}"})).json()

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
        if session_id and AGENT_AVAILABLE:
            agent_manager.set_google_connected(session_id)
        return {"message": "✅ Google connected! Close this tab and return to the chat.",
                "email": user_email, "coach_id": user.id}

    else:  # participant
        user = db.query(models.Participant).filter(models.Participant.email == user_email).first()
        if not user:
            user = models.Participant(name=user_info.get("name", user_email), email=user_email)
            db.add(user); db.commit(); db.refresh(user)
        user.google_access_token  = access_token
        user.google_refresh_token = refresh_token or user.google_refresh_token
        user.google_token_expiry  = token_expiry
        db.commit()
        if session_id and AGENT_AVAILABLE:
            agent_manager.set_google_connected(session_id)
        return {"message": "✅ Google connected! Close this tab and return to the chat.",
                "email": user_email, "participant_id": user.id}


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
        return schemas.TokenResponse(message="Tokens stored", user_type="coach", email=payload.user_email)
    elif payload.user_type == "participant":
        p = db.query(models.Participant).filter(models.Participant.email == payload.user_email).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"No participant with email {payload.user_email}")
        p.google_access_token  = f"oauth_access_token_for_{payload.user_email}"
        p.google_refresh_token = f"oauth_refresh_token_for_{payload.user_email}"
        p.google_token_expiry  = token_expiry
        db.commit()
        return schemas.TokenResponse(message="Tokens stored", user_type="participant", email=payload.user_email)
    else:
        raise HTTPException(status_code=400, detail="user_type must be coach or participant")


# ══════════════════════════════════════════════════════════════════════
# COACHES
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
    """STUB — real data at GET /calcom/slots"""
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")
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
# PARTICIPANTS
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
# BOOKINGS
# ══════════════════════════════════════════════════════════════════════

@app.post("/bookings", response_model=schemas.BookingResponse,
          status_code=status.HTTP_201_CREATED, tags=["Bookings"])
def create_booking(booking: schemas.BookingCreate, db: Session = Depends(get_db)):
    """STUB — agent books directly via Cal.com API"""
    coach = db.query(models.Coach).filter(models.Coach.id == booking.coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {booking.coach_id} not found")
    participant = db.query(models.Participant).filter(
        models.Participant.id == booking.participant_id).first()
    if not participant:
        raise HTTPException(status_code=404, detail=f"Participant {booking.participant_id} not found")
    conflict = db.query(models.Booking).filter(
        models.Booking.coach_id == booking.coach_id, models.Booking.status == "confirmed",
        models.Booking.start_time < booking.end_time, models.Booking.end_time > booking.start_time
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Coach already has a booking at that time")

    db_booking = models.Booking(
        coach_id=booking.coach_id, participant_id=booking.participant_id,
        start_time=booking.start_time, end_time=booking.end_time, notes=booking.notes,
        meeting_link=f"https://meet.google.com/simulated-{coach.id}-{participant.id}",
        calcom_booking_id=f"calcom_booking_{coach.id}_{participant.id}",
        status="confirmed", confirmation_sent=False,
    )
    db.add(db_booking); db.commit(); db.refresh(db_booking)
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
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Booking {booking_id} not found")
    booking.status = "cancelled"
    db.commit(); db.refresh(booking)
    return booking
