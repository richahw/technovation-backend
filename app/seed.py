"""
seed.py — Populate the database with sample data
--------------------------------------------------
Run this after starting the server to create sample coaches,
participants, and bookings so you can test all the endpoints.

Usage:
    python app/seed.py
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from app.database import SessionLocal, engine, Base
from app import models

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

db = SessionLocal()

def seed():
    print("🌱 Seeding database...")

    # ── Clear existing data ───────────────────────────────────────────
    db.query(models.Booking).delete()
    db.query(models.Participant).delete()
    db.query(models.Coach).delete()
    db.commit()
    print("   Cleared existing data")

    # ── Create sample coaches ─────────────────────────────────────────
    coaches = [
        models.Coach(
            name="Dr. Sarah Chen",
            email="sarah.chen@technovation.org",
            timezone="America/Los_Angeles",
            expertise="Python, Machine Learning, Data Science",
            calcom_username="sarah-chen",
            calcom_user_id="calcom_001",
            # Simulated OAuth tokens
            google_access_token="simulated_access_token_sarah",
            google_refresh_token="simulated_refresh_token_sarah",
            google_token_expiry=datetime.utcnow() + timedelta(hours=1),
        ),
        models.Coach(
            name="Marcus Johnson",
            email="marcus.j@technovation.org",
            timezone="America/New_York",
            expertise="Web Development, React, Node.js",
            calcom_username="marcus-johnson",
            calcom_user_id="calcom_002",
            google_access_token="simulated_access_token_marcus",
            google_refresh_token="simulated_refresh_token_marcus",
            google_token_expiry=datetime.utcnow() + timedelta(hours=1),
        ),
        models.Coach(
            name="Priya Patel",
            email="priya.p@technovation.org",
            timezone="America/Chicago",
            expertise="Mobile Development, iOS, Swift",
            calcom_username="priya-patel",
            calcom_user_id="calcom_003",
            # This coach hasn't connected Google Calendar yet
            google_access_token=None,
            google_refresh_token=None,
        ),
    ]
    db.add_all(coaches)
    db.commit()
    for c in coaches:
        db.refresh(c)
    print(f"   Created {len(coaches)} coaches")

    # ── Create sample participants ─────────────────────────────────────
    participants = [
        models.Participant(
            name="Anika Giri",
            email="anika.g@student.edu",
            timezone="America/Los_Angeles",
            google_access_token="simulated_access_token_anika",
            google_refresh_token="simulated_refresh_token_anika",
            google_token_expiry=datetime.utcnow() + timedelta(hours=1),
        ),
        models.Participant(
            name="Jordan Lee",
            email="jordan.l@student.edu",
            timezone="America/New_York",
            google_access_token="simulated_access_token_jordan",
            google_refresh_token="simulated_refresh_token_jordan",
            google_token_expiry=datetime.utcnow() + timedelta(hours=1),
        ),
        models.Participant(
            name="Sofia Rodriguez",
            email="sofia.r@student.edu",
            timezone="America/Chicago",
            # This participant hasn't connected Google Calendar yet
            google_access_token=None,
        ),
    ]
    db.add_all(participants)
    db.commit()
    for p in participants:
        db.refresh(p)
    print(f"   Created {len(participants)} participants")

    # ── Create sample bookings ────────────────────────────────────────
    base_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    bookings = [
        models.Booking(
            coach_id=coaches[0].id,
            participant_id=participants[0].id,
            start_time=base_time + timedelta(days=1, hours=10),
            end_time=base_time + timedelta(days=1, hours=11),
            meeting_link="https://meet.google.com/abc-defg-hij",
            calcom_booking_id="calcom_bk_001",
            calcom_booking_uid="uid_001",
            status="confirmed",
            notes="Want to discuss ML project ideas",
            coach_gcal_event_id="gcal_coach_evt_001",
            participant_gcal_event_id="gcal_part_evt_001",
            confirmation_sent=True,
        ),
        models.Booking(
            coach_id=coaches[1].id,
            participant_id=participants[1].id,
            start_time=base_time + timedelta(days=2, hours=14),
            end_time=base_time + timedelta(days=2, hours=15),
            meeting_link="https://meet.google.com/xyz-uvwx-yz",
            calcom_booking_id="calcom_bk_002",
            status="confirmed",
            notes="Portfolio review",
            confirmation_sent=True,
        ),
        models.Booking(
            coach_id=coaches[0].id,
            participant_id=participants[1].id,
            start_time=base_time + timedelta(days=3, hours=9),
            end_time=base_time + timedelta(days=3, hours=10),
            meeting_link=None,
            status="cancelled",
            notes="Had to cancel",
            confirmation_sent=False,
        ),
    ]
    db.add_all(bookings)
    db.commit()
    print(f"   Created {len(bookings)} bookings")

    print("\n✅ Seed complete! Here's what's in your database:")
    print(f"   Coaches:      {db.query(models.Coach).count()}")
    print(f"   Participants: {db.query(models.Participant).count()}")
    print(f"   Bookings:     {db.query(models.Booking).count()}")
    print("\n🚀 Start the server with:  uvicorn app.main:app --reload")
    print("📖 Then visit:             http://localhost:8000/docs")

if __name__ == "__main__":
    seed()
    db.close()
