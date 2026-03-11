"""
models.py — Database table definitions
---------------------------------------
Each class here becomes a table in Postgres.
SQLAlchemy reads these and creates the actual SQL tables for us.

Tables:
  - Coach        → stores coach profiles + their OAuth tokens
  - Participant  → stores participant profiles + their Google Calendar token
  - Booking      → stores scheduled sessions between a coach and participant
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Coach(Base):
    """
    Represents a coach in the system.
    
    Coaches set their availability directly in Cal.com.
    We store their OAuth tokens here so our agent can:
      - Read their Google Calendar to check conflicts
      - Send emails on their behalf via Gmail
      - Pull their availability from Cal.com
    """
    __tablename__ = "coaches"

    id                   = Column(Integer, primary_key=True, index=True)
    name                 = Column(String(100), nullable=False)
    email                = Column(String(255), unique=True, nullable=False, index=True)
    timezone             = Column(String(50), nullable=False, default="America/Los_Angeles")
    expertise            = Column(String(255))          # e.g. "Python, Machine Learning, Web Dev"
    calcom_user_id       = Column(String(100))          # their Cal.com user ID
    calcom_username      = Column(String(100))          # their Cal.com username (for booking links)

    # OAuth tokens — these let our agent act on the coach's behalf
    # In production you'd encrypt these. For demo purposes, stored as plain text.
    google_access_token  = Column(Text)                 # short-lived token (expires in ~1 hour)
    google_refresh_token = Column(Text)                 # long-lived token (used to get new access tokens)
    google_token_expiry  = Column(DateTime)             # when the access token expires

    is_active            = Column(Boolean, default=True)
    created_at           = Column(DateTime, server_default=func.now())
    updated_at           = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # One coach can have many bookings
    bookings = relationship("Booking", back_populates="coach")

    def __repr__(self):
        return f"<Coach id={self.id} name={self.name} email={self.email}>"


class Participant(Base):
    """
    Represents a participant (typically a student) in the system.
    
    Participants book sessions through the chatbot.
    We store their Google Calendar token so our agent can:
      - Check their calendar for conflicts when suggesting slots
      - Write the confirmed booking to their calendar
    """
    __tablename__ = "participants"

    id                   = Column(Integer, primary_key=True, index=True)
    name                 = Column(String(100), nullable=False)
    email                = Column(String(255), unique=True, nullable=False, index=True)
    timezone             = Column(String(50), default="America/Los_Angeles")

    # Google Calendar OAuth token (read access only for participants)
    google_access_token  = Column(Text)
    google_refresh_token = Column(Text)
    google_token_expiry  = Column(DateTime)

    created_at           = Column(DateTime, server_default=func.now())

    # One participant can have many bookings
    bookings = relationship("Booking", back_populates="participant")

    def __repr__(self):
        return f"<Participant id={self.id} name={self.name}>"


class Booking(Base):
    """
    Represents a scheduled session between a coach and participant.
    
    Created when:
      1. Participant selects a slot in the chatbot
      2. Our agent calls the Cal.com API to create the booking
      3. Cal.com generates a meeting link and confirms the time
      4. We write the event to both Google Calendars
      5. We store the record here for reference + notifications
    """
    __tablename__ = "bookings"

    id                  = Column(Integer, primary_key=True, index=True)

    # Foreign keys linking to coach and participant tables
    coach_id            = Column(Integer, ForeignKey("coaches.id"), nullable=False)
    participant_id      = Column(Integer, ForeignKey("participants.id"), nullable=False)

    # Booking details
    start_time          = Column(DateTime, nullable=False)
    end_time            = Column(DateTime, nullable=False)
    meeting_link        = Column(String(500))           # Zoom/Meet link from Cal.com
    calcom_booking_id   = Column(String(100))           # Cal.com's internal booking ID
    calcom_booking_uid  = Column(String(100))           # Cal.com's UID (used for cancel/reschedule)

    # Status tracking
    status              = Column(String(50), default="confirmed")  # confirmed, cancelled, rescheduled
    notes               = Column(Text)                  # any notes from the participant

    # Calendar event IDs (so we can update/delete them if booking changes)
    coach_gcal_event_id       = Column(String(200))
    participant_gcal_event_id = Column(String(200))

    # Notification tracking
    confirmation_sent   = Column(Boolean, default=False)
    reminder_sent       = Column(Boolean, default=False)

    created_at          = Column(DateTime, server_default=func.now())
    updated_at          = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships — lets us do booking.coach.name, booking.participant.email, etc.
    coach       = relationship("Coach", back_populates="bookings")
    participant = relationship("Participant", back_populates="bookings")

    def __repr__(self):
        return f"<Booking id={self.id} coach_id={self.coach_id} start={self.start_time}>"
