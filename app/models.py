"""
models.py — Database table definitions
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Coach(Base):
    __tablename__ = "coaches"

    id                   = Column(Integer, primary_key=True, index=True)
    name                 = Column(String(100), nullable=False)
    email                = Column(String(255), unique=True, nullable=False, index=True)
    timezone             = Column(String(50), nullable=False, default="America/Los_Angeles")
    expertise            = Column(String(255))

    # Cal.com profile fields
    calcom_user_id              = Column(String(100))
    calcom_username             = Column(String(100))
    calcom_default_schedule_id  = Column(String(100))
    calcom_event_types          = Column(JSON)

    # Cal.com OAuth tokens
    calcom_access_token  = Column(Text)
    calcom_refresh_token = Column(Text)
    calcom_token_expiry  = Column(DateTime)

    # Google OAuth tokens
    google_access_token  = Column(Text)
    google_refresh_token = Column(Text)
    google_token_expiry  = Column(DateTime)

    # Coach preferences
    open_to_rebooking    = Column(Boolean, default=True)
    preferences_set      = Column(Boolean, default=False)

    is_active            = Column(Boolean, default=True)
    created_at           = Column(DateTime, server_default=func.now())
    updated_at           = Column(DateTime, server_default=func.now(), onupdate=func.now())

    bookings = relationship("Booking", back_populates="coach")

    def __repr__(self):
        return f"<Coach id={self.id} name={self.name} email={self.email}>"


class Participant(Base):
    __tablename__ = "participants"

    id                   = Column(Integer, primary_key=True, index=True)
    name                 = Column(String(100), nullable=False)
    email                = Column(String(255), unique=True, nullable=False, index=True)
    timezone             = Column(String(50), default="America/Los_Angeles")

    google_access_token  = Column(Text)
    google_refresh_token = Column(Text)
    google_token_expiry  = Column(DateTime)

    created_at           = Column(DateTime, server_default=func.now())

    bookings = relationship("Booking", back_populates="participant")

    def __repr__(self):
        return f"<Participant id={self.id} name={self.name}>"


class Booking(Base):
    __tablename__ = "bookings"

    id                  = Column(Integer, primary_key=True, index=True)
    coach_id            = Column(Integer, ForeignKey("coaches.id"), nullable=False)
    participant_id      = Column(Integer, ForeignKey("participants.id"), nullable=False)

    start_time          = Column(DateTime, nullable=False)
    end_time            = Column(DateTime, nullable=False)
    meeting_link        = Column(String(500))
    calcom_booking_id   = Column(String(100))
    calcom_booking_uid  = Column(String(100))

    status              = Column(String(50), default="confirmed")
    notes               = Column(Text)

    coach_gcal_event_id       = Column(String(200))
    participant_gcal_event_id = Column(String(200))

    confirmation_sent   = Column(Boolean, default=False)
    reminder_sent       = Column(Boolean, default=False)

    created_at          = Column(DateTime, server_default=func.now())
    updated_at          = Column(DateTime, server_default=func.now(), onupdate=func.now())

    coach       = relationship("Coach", back_populates="bookings")
    participant = relationship("Participant", back_populates="bookings")

    def __repr__(self):
        return f"<Booking id={self.id} coach_id={self.coach_id} start={self.start_time}>"
