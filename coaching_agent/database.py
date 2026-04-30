"""
database.py — PostgreSQL access for coach/participant/booking info.

Reads and writes using short-lived connections.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")


def _connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_coach(coach_name: str | None = None) -> dict | None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if coach_name:
                cur.execute(
                    "SELECT * FROM coaches WHERE LOWER(name) = LOWER(%s) AND is_active = true LIMIT 1",
                    (coach_name,),
                )
            else:
                cur.execute("SELECT * FROM coaches WHERE is_active = true LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_coach_by_id(coach_id: int) -> dict | None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM coaches WHERE id = %s AND is_active = true LIMIT 1",
                (coach_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_coach_by_email(email: str) -> dict | None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM coaches WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                (email,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def list_coaches() -> list[dict]:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, email, timezone, expertise, calcom_username
                FROM coaches
                WHERE is_active = true
                ORDER BY name
                """
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def update_coach_preferences(coach_id: int, open_to_rebooking: bool) -> bool:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE coaches
                SET open_to_rebooking = %s,
                    preferences_set = true,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (open_to_rebooking, coach_id),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_participant_by_email(email: str) -> dict | None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM participants WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                (email,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def upsert_participant(name: str, email: str, timezone: str = "America/Los_Angeles") -> dict:
    """Create the participant if new, otherwise update the name/timezone."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO participants (name, email, timezone)
                VALUES (%s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                   SET name = EXCLUDED.name,
                       timezone = EXCLUDED.timezone
                RETURNING *
                """,
                (name, email, timezone),
            )
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else {"name": name, "email": email, "timezone": timezone}
    finally:
        conn.close()


def get_latest_past_booking_for_participant(participant_id: int) -> dict | None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT b.*, c.name AS coach_name
                FROM bookings b
                JOIN coaches c ON c.id = b.coach_id
                WHERE b.participant_id = %s
                  AND b.start_time < NOW()
                  AND b.status = 'confirmed'
                ORDER BY b.start_time DESC
                LIMIT 1
                """,
                (participant_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
