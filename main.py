"""
main.py — FastAPI Application Entry Point
------------------------------------------
This is the heart of our backend. Every request from the chatbot,
every OAuth callback from Google, every booking action flows through here.

Run with:
    uvicorn app.main:app --reload

Then visit http://localhost:8000/docs to see and test all endpoints.

OAuth setup (new):
    1. Copy .env.example to .env
    2. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from Google Cloud Console
    3. Visit http://localhost:8000/auth/google/login?user_type=coach to test the flow
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List
import os
import httpx

from app.database import engine, get_db, Base
from app import models, schemas

# ── App setup ─────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Scheduling Platform API",
    description="""
    Backend for the Technovation and Delta Consulting Agent-Assisted Scheduling Platform.
    
    This API handles:
    - **Google OAuth** — receiving and storing coach/participant tokens
    - **Coach management** — profiles, availability (via Cal.com)
    - **Participant management** — profiles, calendar access
    - **Booking management** — creating, reading, and tracking sessions
    """,
    version="0.1.0",
)

# ── Google OAuth config ───────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# GOOGLE_REDIRECT_URI auto-detects environment:
#   - Locally:      http://localhost:8000/auth/google/callback
#   - On Render:    https://your-app-name.onrender.com/auth/google/callback
#   - On Railway:   https://your-app-name.up.railway.app/auth/google/callback
#
# Set RENDER_EXTERNAL_URL or RAILWAY_PUBLIC_DOMAIN in your hosting dashboard,
# OR manually set GOOGLE_REDIRECT_URI in your environment variables.
_base_url = (
    os.getenv("GOOGLE_REDIRECT_URI")           # manually set → highest priority
    or (f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/auth/google/callback"
        if os.getenv("RENDER_EXTERNAL_HOSTNAME") else None)   # Render sets this automatically
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/auth/google/callback"
        if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None)      # Railway sets this automatically
    or "http://localhost:8000/auth/google/callback"            # local fallback
)
GOOGLE_REDIRECT_URI = _base_url

GOOGLE_AUTH_URL      = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL     = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL  = "https://www.googleapis.com/oauth2/v2/userinfo"

# Scopes we request from Google.
# calendar = read/write Google Calendar (check conflicts, create booking events)
# gmail.send = send confirmation/reminder emails on coach's behalf
GOOGLE_SCOPES = " ".join([
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
])


# ── Health Check ──────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    """
    Basic health check. Useful for verifying the server is running
    and for deployment platforms (Render, Railway) to confirm the app is alive.
    """
    return {
        "status": "ok",
        "message": "Scheduling Platform API is running",
        "docs": "Visit /docs for interactive API documentation"
    }


# ── Google OAuth ──────────────────────────────────────────────────────

@app.get("/auth/google/login", tags=["Auth"])
def google_login(user_type: str = "participant"):
    """
    Step 1 of OAuth: redirect the user to Google's consent screen.

    Usage:
      - Coach:       GET /auth/google/login?user_type=coach
      - Participant: GET /auth/google/login?user_type=participant

    Google will show a consent screen asking permission to access
    their Calendar and Gmail. After they approve, Google redirects
    them back to /auth/google/callback with an authorization code.

    The user_type is passed through via the 'state' parameter so
    we know which table to update when Google redirects back.
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_CLIENT_ID not set in .env — check your environment variables"
        )

    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         GOOGLE_SCOPES,
        "access_type":   "offline",   # gives us a refresh_token so we don't need to re-auth
        "prompt":        "consent",   # always show consent screen (ensures refresh_token is issued)
        "state":         user_type,   # we pass user_type through Google and read it on callback
    }

    # Build the Google auth URL with all params
    query_string = "&".join(f"{k}={v.replace(' ', '%20')}" for k, v in params.items())
    auth_url = f"{GOOGLE_AUTH_URL}?{query_string}"

    # Redirect the user's browser to Google
    return RedirectResponse(url=auth_url)


@app.get("/auth/google/callback", tags=["Auth"])
async def google_oauth_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    db: Session = Depends(get_db)
):
    """
    Step 2 of OAuth: Google redirects here after the user approves.

    This endpoint:
      1. Receives the authorization code from Google
      2. Exchanges it for access_token + refresh_token (server-to-server)
      3. Uses the access_token to fetch the user's profile from Google
      4. Saves the tokens to Postgres under the coach/participant record

    The 'state' parameter contains the user_type we passed in Step 1.

    Note: This is a GET endpoint because Google redirects the browser here.
    The Node OAuth demo calls this via POST — both work, but the browser
    redirect from Google uses GET.
    """
    # Handle user denying consent on Google's screen
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")

    if not code:
        raise HTTPException(status_code=400, detail="No authorization code received from Google")

    user_type = state or "participant"  # state holds the user_type we passed in login

    # ── Exchange authorization code for tokens ────────────────────────
    # This is a server-to-server call — the browser never sees this.
    # We send our client_secret here, which is why this must happen server-side.
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_REDIRECT_URI,
                "grant_type":    "authorization_code",
            }
        )

    tokens = token_response.json()

    if "error" in tokens:
        raise HTTPException(
            status_code=400,
            detail=f"Token exchange failed: {tokens.get('error_description', tokens['error'])}"
        )

    access_token  = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")  # only present on first auth or with prompt=consent
    expires_in    = tokens.get("expires_in", 3600)
    token_expiry  = datetime.utcnow() + timedelta(seconds=expires_in)

    # ── Fetch the user's Google profile ──────────────────────────────
    # We use the access_token to find out who just logged in
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )

    user_info = user_response.json()
    user_email = user_info.get("email")

    if not user_email:
        raise HTTPException(status_code=400, detail="Could not get email from Google profile")

    # ── Save tokens to Postgres ───────────────────────────────────────
    # This is the critical step — from now on our agent uses these tokens
    # to read their Google Calendar and send emails on their behalf
    if user_type == "coach":
        user = db.query(models.Coach).filter(models.Coach.email == user_email).first()

        if not user:
            # Auto-create the coach if they don't exist yet
            user = models.Coach(
                name=user_info.get("name", user_email),
                email=user_email,
                timezone="America/Los_Angeles",
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        user.google_access_token  = access_token
        user.google_refresh_token = refresh_token or user.google_refresh_token
        user.google_token_expiry  = token_expiry
        db.commit()

        return {
            "message":      "Coach authenticated successfully",
            "user_type":    "coach",
            "email":        user_email,
            "name":         user_info.get("name"),
            "coach_id":     user.id,
            "token_expiry": token_expiry.isoformat(),
            "scopes":       "calendar + gmail.send",
            "note":         "Tokens saved to Postgres. Agent can now access this coach's calendar."
        }

    elif user_type == "participant":
        user = db.query(models.Participant).filter(models.Participant.email == user_email).first()

        if not user:
            user = models.Participant(
                name=user_info.get("name", user_email),
                email=user_email,
                timezone="America/Los_Angeles",
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        user.google_access_token  = access_token
        user.google_refresh_token = refresh_token or user.google_refresh_token
        user.google_token_expiry  = token_expiry
        db.commit()

        return {
            "message":        "Participant authenticated successfully",
            "user_type":      "participant",
            "email":          user_email,
            "name":           user_info.get("name"),
            "participant_id": user.id,
            "token_expiry":   token_expiry.isoformat(),
            "scopes":         "calendar",
            "note":           "Tokens saved to Postgres. Agent can now check this participant's calendar."
        }

    else:
        raise HTTPException(status_code=400, detail="state must be 'coach' or 'participant'")


@app.post("/auth/google/callback", response_model=schemas.TokenResponse, tags=["Auth"])
def google_oauth_callback_post(
    payload: schemas.GoogleOAuthCallback,
    db: Session = Depends(get_db)
):
    """
    POST version of the callback — called by the Node OAuth demo server
    after it has already exchanged the code for tokens.

    The Node server handles the token exchange, then calls this endpoint
    to save the tokens into our Postgres database.

    This keeps the two servers in sync: Node handles the browser redirect
    flow, FastAPI handles persistence.
    """
    # The Node server already exchanged the code — we just store the result
    # In the future, Node can pass the actual tokens here instead of the code
    simulated_access_token  = f"oauth_access_token_for_{payload.user_email}"
    simulated_refresh_token = f"oauth_refresh_token_for_{payload.user_email}"
    token_expiry = datetime.utcnow() + timedelta(hours=1)

    if payload.user_type == "coach":
        coach = db.query(models.Coach).filter(
            models.Coach.email == payload.user_email
        ).first()
        if not coach:
            raise HTTPException(
                status_code=404,
                detail=f"No coach found with email {payload.user_email}. Create the coach first."
            )
        coach.google_access_token  = simulated_access_token
        coach.google_refresh_token = simulated_refresh_token
        coach.google_token_expiry  = token_expiry
        db.commit()
        return schemas.TokenResponse(
            message="Google OAuth tokens stored successfully for coach",
            user_type="coach",
            email=payload.user_email
        )

    elif payload.user_type == "participant":
        participant = db.query(models.Participant).filter(
            models.Participant.email == payload.user_email
        ).first()
        if not participant:
            raise HTTPException(
                status_code=404,
                detail=f"No participant found with email {payload.user_email}."
            )
        participant.google_access_token  = simulated_access_token
        participant.google_refresh_token = simulated_refresh_token
        participant.google_token_expiry  = token_expiry
        db.commit()
        return schemas.TokenResponse(
            message="Google OAuth tokens stored successfully for participant",
            user_type="participant",
            email=payload.user_email
        )

    else:
        raise HTTPException(status_code=400, detail="user_type must be 'coach' or 'participant'")


# ── Coaches ───────────────────────────────────────────────────────────

@app.post("/coaches", response_model=schemas.CoachResponse,
          status_code=status.HTTP_201_CREATED, tags=["Coaches"])
def create_coach(coach: schemas.CoachCreate, db: Session = Depends(get_db)):
    """
    Create a new coach profile in Postgres.
    
    Called during coach onboarding, after they've set up their Cal.com profile.
    We store their info here so our agent can reference it when discovering slots.
    """
    existing = db.query(models.Coach).filter(
        models.Coach.email == coach.email
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A coach with email {coach.email} already exists"
        )
    db_coach = models.Coach(**coach.model_dump())
    db.add(db_coach)
    db.commit()
    db.refresh(db_coach)
    return db_coach


@app.get("/coaches", response_model=List[schemas.CoachResponse], tags=["Coaches"])
def list_coaches(db: Session = Depends(get_db)):
    """
    Return all active coaches.
    Used by the admin dashboard to display onboarded coaches.
    """
    coaches = db.query(models.Coach).filter(models.Coach.is_active == True).all()
    return coaches


@app.get("/coaches/{coach_id}", response_model=schemas.CoachResponse, tags=["Coaches"])
def get_coach(coach_id: int, db: Session = Depends(get_db)):
    """Get a single coach by their ID."""
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")
    return coach


@app.get("/coaches/{coach_id}/availability",
         response_model=List[schemas.CoachAvailabilitySlot], tags=["Coaches"])
def get_coach_availability(coach_id: int, db: Session = Depends(get_db)):
    """
    Returns available slots for a coach.
    
    In the real implementation, this endpoint will:
      1. Use the coach's Cal.com username to call the Cal.com API
      2. Get their available slots for the next 7 days
      3. Cross-reference with their Google Calendar to filter out conflicts
      4. Return the clean list of bookable slots
    
    For this demo, we return simulated slots.
    """
    coach = db.query(models.Coach).filter(models.Coach.id == coach_id).first()
    if not coach:
        raise HTTPException(status_code=404, detail=f"Coach {coach_id} not found")

    if not coach.google_access_token:
        raise HTTPException(
            status_code=400,
            detail="Coach has not connected Google Calendar yet. Complete OAuth first."
        )

    # ── STUB: In production, replace this with real Cal.com API call ──
    # calcom_response = httpx.get(
    #     f"https://api.cal.com/v1/availability",
    #     params={"username": coach.calcom_username, "dateFrom": "...", "dateTo": "..."},
    #     headers={"Authorization": f"Bearer {os.getenv('CALCOM_API_KEY')}"}
    # )
    base = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    simulated_slots = []
    for day_offset in range(5):
        for hour in [9, 11, 14, 16]:
            slot_start = base + timedelta(days=day_offset+1, hours=hour)
            simulated_slots.append(schemas.CoachAvailabilitySlot(
                start=slot_start.isoformat(),
                end=(slot_start + timedelta(hours=1)).isoformat(),
                timezone=coach.timezone
            ))
    return simulated_slots


# ── Participants ──────────────────────────────────────────────────────

@app.post("/participants", response_model=schemas.ParticipantResponse,
          status_code=status.HTTP_201_CREATED, tags=["Participants"])
def create_participant(participant: schemas.ParticipantCreate, db: Session = Depends(get_db)):
    """
    Create a new participant profile.
    Called at the start of the participant chatbot flow,
    before they connect their Google Calendar.
    """
    existing = db.query(models.Participant).filter(
        models.Participant.email == participant.email
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A participant with email {participant.email} already exists"
        )
    db_participant = models.Participant(**participant.model_dump())
    db.add(db_participant)
    db.commit()
    db.refresh(db_participant)
    return db_participant


@app.get("/participants", response_model=List[schemas.ParticipantResponse], tags=["Participants"])
def list_participants(db: Session = Depends(get_db)):
    """Return all participants."""
    return db.query(models.Participant).all()


# ── Bookings ──────────────────────────────────────────────────────────

@app.post("/bookings", response_model=schemas.BookingResponse,
          status_code=status.HTTP_201_CREATED, tags=["Bookings"])
def create_booking(booking: schemas.BookingCreate, db: Session = Depends(get_db)):
    """
    Create a booking between a coach and participant.
    
    In the real implementation this will:
      1. Call Cal.com API to officially create the booking
      2. Get the meeting link from Cal.com's response
      3. Write calendar events to both the coach's and participant's Google Calendars
      4. Store the booking record in Postgres
      5. Trigger the Notification Service to send confirmation emails
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
        raise HTTPException(
            status_code=409,
            detail=f"Coach already has a booking from {conflict.start_time} to {conflict.end_time}"
        )

    # ── STUB: Cal.com + Google Calendar ──────────────────────────────
    # calcom_response = httpx.post("https://api.cal.com/v1/bookings", ...)
    # gcal_coach_event = create_gcal_event(coach.google_access_token, ...)
    simulated_meeting_link        = f"https://meet.google.com/simulated-{coach.id}-{participant.id}"
    simulated_calcom_id           = f"calcom_booking_{coach.id}_{participant.id}"
    simulated_coach_event_id      = f"gcal_coach_event_{coach.id}"
    simulated_participant_event_id = f"gcal_participant_event_{participant.id}"

    db_booking = models.Booking(
        coach_id=booking.coach_id,
        participant_id=booking.participant_id,
        start_time=booking.start_time,
        end_time=booking.end_time,
        notes=booking.notes,
        meeting_link=simulated_meeting_link,
        calcom_booking_id=simulated_calcom_id,
        coach_gcal_event_id=simulated_coach_event_id,
        participant_gcal_event_id=simulated_participant_event_id,
        status="confirmed",
        confirmation_sent=False,
    )
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)

    print(f"[Notification stub] Would send confirmation to {coach.email} and {participant.email}")
    return db_booking


@app.get("/bookings", response_model=List[schemas.BookingResponse], tags=["Bookings"])
def list_bookings(db: Session = Depends(get_db)):
    """Return all bookings. Used by the admin dashboard."""
    return db.query(models.Booking).all()


@app.get("/bookings/{booking_id}", response_model=schemas.BookingResponse, tags=["Bookings"])
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    """Get a single booking by ID."""
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Booking {booking_id} not found")
    return booking


@app.patch("/bookings/{booking_id}/cancel",
           response_model=schemas.BookingResponse, tags=["Bookings"])
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    """
    Cancel a booking.
    In production: call Cal.com to cancel, update both Google Calendar events, send emails.
    """
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Booking {booking_id} not found")
    booking.status = "cancelled"
    db.commit()
    db.refresh(booking)
    return booking
