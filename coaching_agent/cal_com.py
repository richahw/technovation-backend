"""
cal_com.py — Cal.com v2 API wrapper.

All functions return plain dicts. On failure they return {"error": "..."}.
No exceptions are propagated to the caller.
"""

import os
import time
import requests

CAL_API_KEY = os.getenv("CALCOM_API_KEY") or os.getenv("CAL_COM_API_KEY")
BASE_URL = "https://api.cal.com/v2"

# Technovation team id on Cal.com. Discovered via GET /v2/teams.
TECHNOVATION_TEAM_ID = 17818


def _headers(api_version: str = "2024-08-13") -> dict:
    return {
        "Authorization": f"Bearer {CAL_API_KEY}",
        "cal-api-version": api_version,
        "Content-Type": "application/json",
    }


# ── Team event types ─────────────────────────────────────────────────────

# Cache of the full team event-type list. Refreshed lazily.
_team_events_cache: dict = {"fetched_at": 0.0, "events": []}
_TEAM_EVENTS_TTL = 300.0  # seconds


def _fetch_team_events(force: bool = False) -> list[dict]:
    """Return the full list of Technovation team event types (cached for 5 min)."""
    now = time.time()
    if (
        not force
        and _team_events_cache["events"]
        and now - _team_events_cache["fetched_at"] < _TEAM_EVENTS_TTL
    ):
        return _team_events_cache["events"]

    try:
        resp = requests.get(
            f"{BASE_URL}/teams/{TECHNOVATION_TEAM_ID}/event-types",
            headers=_headers("2024-06-14"),
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        events = resp.json().get("data") or []
        _team_events_cache["events"] = events
        _team_events_cache["fetched_at"] = now
        return events
    except requests.RequestException:
        return []


def get_team_event_by_slug(slug: str) -> dict | None:
    """Return the team event-type record for the given slug, or None."""
    for e in _fetch_team_events():
        if e.get("slug") == slug:
            return e
    # One retry in case the cache is stale
    for e in _fetch_team_events(force=True):
        if e.get("slug") == slug:
            return e
    return None


def get_event_hosts(slug: str) -> list[dict]:
    """
    Return the list of registered hosts (coaches) on the team event with this slug.

    Each entry has: userId, name, username, priority, mandatory, avatarUrl.
    """
    event = get_team_event_by_slug(slug)
    if not event:
        return []
    return list(event.get("hosts") or [])


def get_booking_questions(slug: str) -> list[dict]:
    """
    Return the non-hidden booking-field questions for the given event.

    Each entry is a dict with:
        slug, type, label, required, options (for select fields), is_default
    """
    event = get_team_event_by_slug(slug)
    if not event:
        return []
    questions: list[dict] = []
    for field in event.get("bookingFields", []):
        if field.get("hidden"):
            continue
        # Name / email / location / guests are always the standard four.
        questions.append({
            "slug": field.get("slug"),
            "type": field.get("type"),
            "label": field.get("label") or field.get("slug"),
            "required": bool(field.get("required")),
            "options": field.get("options"),
            "is_default": bool(field.get("isDefault")),
        })
    return questions


# ── Slots ────────────────────────────────────────────────────────────────

def fetch_event_slots(event_type_id: int, start_time: str, end_time: str) -> dict:
    """
    Fetch available slots for a specific event type.

    Returns: {"slots": {"2026-04-28": [{"start": "..."}, ...], ...}} or {"error": ...}
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/slots",
            headers=_headers("2024-09-04"),
            params={
                "eventTypeId": event_type_id,
                "start": start_time,
                "end": end_time,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return {"error": f"Cal.com slots API returned {resp.status_code}: {resp.text}"}
        return {"slots": resp.json().get("data", {})}
    except requests.RequestException as exc:
        return {"error": f"Cal.com slots request failed: {exc}"}


# Backwards-compat alias used by older callers.
def fetch_available_slots(event_type_id: int, start_time: str, end_time: str) -> dict:
    return fetch_event_slots(event_type_id, start_time, end_time)


# ── Booking ──────────────────────────────────────────────────────────────

def create_team_booking(
    event_type_id: int,
    start_time: str,
    attendee_name: str,
    attendee_email: str,
    attendee_timezone: str,
    answers: dict | None = None,
    guest_emails: list[str] | None = None,
) -> dict:
    """
    Create a booking on a Technovation team event type.

    Args:
        event_type_id: Cal.com event type id.
        start_time: ISO 8601 UTC timestamp (e.g. "2026-04-28T17:00:00Z").
        attendee_name, attendee_email, attendee_timezone: participant info.
        answers: dict of {bookingField slug: value} for custom questions.
                 Example: {"title": "...", "division": "Junior Division, ages 13-15",
                           "question-1": "...", "ackowledgement": True}
        guest_emails: optional list of additional attendee emails.

    Returns: the booking dict on success, or {"error": "..."} on failure.
    """
    try:
        payload: dict = {
            "eventTypeId": int(event_type_id),
            "start": start_time,
            "attendee": {
                "name": attendee_name,
                "email": attendee_email,
                "timeZone": attendee_timezone,
                "language": "en",
            },
        }
        if guest_emails:
            payload["guests"] = list(guest_emails)
        if answers:
            # Cal.com v2 expects custom field answers under bookingFieldsResponses.
            payload["bookingFieldsResponses"] = answers

        resp = requests.post(
            f"{BASE_URL}/bookings",
            headers=_headers("2024-08-13"),
            json=payload,
            timeout=20,
        )
        if resp.status_code not in (200, 201):
            return {"error": f"Cal.com booking failed ({resp.status_code}): {resp.text}"}
        return resp.json().get("data", {}) or {}
    except requests.RequestException as exc:
        return {"error": f"Cal.com booking request failed: {exc}"}


# Legacy name kept so existing imports don't break.
def create_booking(
    start_time: str,
    event_type_id: int,
    event_type_slug: str,
    username: str,
    attendee_name: str,
    attendee_email: str,
    attendee_timezone: str,
    notes: str = "",
    guest_emails: list[str] | None = None,
) -> dict:
    answers = {"notes": notes} if notes else None
    return create_team_booking(
        event_type_id=event_type_id,
        start_time=start_time,
        attendee_name=attendee_name,
        attendee_email=attendee_email,
        attendee_timezone=attendee_timezone,
        answers=answers,
        guest_emails=guest_emails,
    )
