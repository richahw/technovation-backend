# Updated agent: April 23
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
import base64
from email.mime.text import MIMEText
 
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
    allow_origins=["*"],
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
 
BASE_URL = (
    os.getenv("BASE_URL")
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
        if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None)
    or "http://localhost:8000"
)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
 
 
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
                            username: Optional[str] = None, access_token: Optional[str] = None) -> dict:
    params = {"eventTypeId": event_type_id, "startTime": start_time, "endTime": end_time}
    if username:
        params["username"] = username
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CALCOM_BASE_URL}/slots/available",
                             headers=calcom_headers(access_token), params=params)
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
                                 attendee_email: str, timezone: str,
                                 access_token: Optional[str] = None) -> dict:
    payload = {
        "eventTypeId": event_type_id,
        "start": start,
        "attendee": {"name": attendee_name, "email": attendee_email,
                     "timeZone": timezone, "language": "en"},
        "metadata": {},
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{CALCOM_BASE_URL}/bookings",
                              headers=calcom_headers(access_token), json=payload)
    r.raise_for_status()
    return r.json().get("data", r.json())
 
 
async def calcom_cancel_booking(uid: str, reason: str = "",
                                 access_token: Optional[str] = None) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{CALCOM_BASE_URL}/bookings/{uid}/cancel",
            headers=calcom_headers(access_token),
            json={"cancellationReason": reason},
        )
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
# EMAIL HELPER
# ══════════════════════════════════════════════════════════════════════
 
async def send_confirmation_email(
    access_token: str,
    to_email: str,
    to_name: str,
    other_name: str,
    start_time: str,
    meeting_link: str,
    is_coach: bool = False,
):
    """Send a booking confirmation email via Gmail API using stored OAuth token."""
    other_role = "participant" if is_coach else "coach"
 
    body = f"""
Hi {to_name},
 
Your coaching session has been confirmed!
 
Details:
- Date/Time: {start_time}
- {other_role.capitalize()}: {other_name}
- Meeting Link: {meeting_link}
 
See you then!
 
Best,
Technovation Scheduling Platform
"""
 
    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = f"Coaching Session Confirmed - {start_time}"
 
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
 
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
    return r.status_code
 
 
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
async def agent_chat(session_id: str, message: str):
    if not AGENT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Agent not available. Check that coaching_agent is installed."
        )
    import asyncio
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None, lambda: agent_manager.respond(session_id, message)
    )

    try:
        role = agent_manager.get_role(session_id)
    except AttributeError:
        role = "unknown"

    return {
        "session_id": session_id,
        "response":   response,
        "role":       role,
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
    Fetch real available slots from Cal.com.
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
    Example: GET /auth/calcom/login?session_id=user123
    """
    if not CALCOM_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="CALCOM_CLIENT_ID not set. Use POST /auth/calcom/test-sync for now."
        )
    from urllib.parse import urlencode
    state = session_id or "no-session"
    params = {
        "client_id":     CALCOM_CLIENT_ID,
        "redirect_uri":  CALCOM_REDIRECT_URI,
        "response_type": "code",
        "state":         state,
        "scope":         "READ_PROFILE READ_EVENT_TYPE READ_AVAILABILITY",
    }
    return RedirectResponse(url=f"{CALCOM_AUTH_URL}?{urlencode(params)}")
 
 
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

    return RedirectResponse(url="https://cal.com")
 
 
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
    from urllib.parse import urlencode
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
 
 
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
         tags=["Coaches"])
async def get_coach_availability(
    coach_id: int,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Returns real available slots from Cal.com for this coach.
    Falls back to simulated slots if Cal.com data is unavailable.
    """
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")
 
    # Try to get real Cal.com slots if coach has event types set up
    if coach.calcom_event_types and len(coach.calcom_event_types) > 0:
        event_type_id = coach.calcom_event_types[0].get("id")
        start = start_time or datetime.utcnow().isoformat() + "Z"
        end = end_time or (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
        try:
            slots = await calcom_get_slots(
                event_type_id=event_type_id,
                start_time=start,
                end_time=end,
                username=coach.calcom_username,
                access_token=coach.calcom_access_token,
            )
            return {"status": "ok", "source": "calcom", "slots": slots}
        except Exception as e:
            print(f"[Cal.com] Failed to get real slots, falling back to simulated: {e}")
 
    # Fallback to simulated slots
    base = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    simulated = [
        {
            "start": (base + timedelta(days=d+1, hours=h)).isoformat(),
            "end": (base + timedelta(days=d+1, hours=h+1)).isoformat(),
            "timezone": coach.timezone,
        }
        for d in range(5) for h in [9, 11, 14, 16]
    ]
    return {"status": "ok", "source": "simulated", "slots": simulated}
 
 
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
async def create_booking(booking: schemas.BookingCreate, db: Session = Depends(get_db)):
    """Creates a real booking via Cal.com API and sends confirmation emails."""
    coach = db.query(models.Coach).filter(models.Coach.id == booking.coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {booking.coach_id} not found")
 
    participant = db.query(models.Participant).filter(
        models.Participant.id == booking.participant_id).first()
    if not participant:
        raise HTTPException(status_code=404, detail=f"Participant {booking.participant_id} not found")
 
    # Check for conflicts in our database
    conflict = db.query(models.Booking).filter(
        models.Booking.coach_id == booking.coach_id,
        models.Booking.status == "confirmed",
        models.Booking.start_time < booking.end_time,
        models.Booking.end_time > booking.start_time
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Coach already has a booking at that time")
 
    # Try to create a real Cal.com booking
    real_meeting_link = f"https://meet.google.com/simulated-{coach.id}-{participant.id}"
    real_booking_uid = f"calcom_booking_{coach.id}_{participant.id}"
 
    if coach.calcom_event_types and len(coach.calcom_event_types) > 0:
        event_type_id = coach.calcom_event_types[0].get("id")
        try:
            calcom_booking = await calcom_create_booking(
                event_type_id=event_type_id,
                start=booking.start_time.isoformat(),
                attendee_name=participant.name,
                attendee_email=participant.email,
                timezone=getattr(participant, "timezone", None) or "America/Los_Angeles",
                access_token=coach.calcom_access_token,
            )
            real_meeting_link = (
                calcom_booking.get("meetingUrl")
                or calcom_booking.get("videoCallUrl")
                or real_meeting_link
            )
            real_booking_uid = calcom_booking.get("uid", real_booking_uid)
            print(f"[Cal.com] Real booking created: {real_booking_uid}")
        except Exception as e:
            print(f"[Cal.com] Failed to create real booking, saving to DB only: {e}")
 
    # Save booking to database
    db_booking = models.Booking(
        coach_id=booking.coach_id,
        participant_id=booking.participant_id,
        start_time=booking.start_time,
        end_time=booking.end_time,
        notes=booking.notes,
        meeting_link=real_meeting_link,
        calcom_booking_id=real_booking_uid,
        status="confirmed",
        confirmation_sent=False,
    )
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)
 
    # Send confirmation emails
    try:
        if participant.google_access_token:
            await send_confirmation_email(
                access_token=participant.google_access_token,
                to_email=participant.email,
                to_name=participant.name,
                other_name=coach.name,
                start_time=str(booking.start_time),
                meeting_link=real_meeting_link,
                is_coach=False,
            )
            print(f"[Email] Confirmation sent to participant {participant.email}")
        else:
            print(f"[Email] No Google token for participant {participant.email} — skipping email")
 
        if coach.google_access_token:
            await send_confirmation_email(
                access_token=coach.google_access_token,
                to_email=coach.email,
                to_name=coach.name,
                other_name=participant.name,
                start_time=str(booking.start_time),
                meeting_link=real_meeting_link,
                is_coach=True,
            )
            print(f"[Email] Confirmation sent to coach {coach.email}")
        else:
            print(f"[Email] No Google token for coach {coach.email} — skipping email")
 
        # Mark confirmation as sent if at least one email went out
        if participant.google_access_token or coach.google_access_token:
            db_booking.confirmation_sent = True
            db.commit()
 
    except Exception as e:
        print(f"[Email] Failed to send confirmation emails: {e}")
 
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
async def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    """Cancels booking in Cal.com first, then updates database."""
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Booking {booking_id} not found")
 
    # Cancel in Cal.com first if we have the booking UID
    if booking.calcom_booking_id and not booking.calcom_booking_id.startswith("calcom_booking_"):
        try:
            coach = db.query(models.Coach).filter(models.Coach.id == booking.coach_id).first()
            await calcom_cancel_booking(
                uid=booking.calcom_booking_id,
                reason="Cancelled by user",
                access_token=coach.calcom_access_token if coach else None,
            )
            print(f"[Cal.com] Booking {booking.calcom_booking_id} cancelled in Cal.com")
        except Exception as e:
            print(f"[Cal.com] Failed to cancel in Cal.com: {e}")
 
    # Update database status
    booking.status = "cancelled"
    db.commit()
    db.refresh(booking)
    return booking
