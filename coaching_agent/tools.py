"""
tools.py — LangChain tools for the coaching scheduling agent.

Tools are built per-session by `build_tools(session)` so each tool has access
to that session's mutable state (role, selected event, connection flags, etc.).

The participant flow is event-catalog-driven: coaches aren't picked individually;
the participant picks a coaching event type (from the Technovation team on Cal.com)
by topic + language + format. Booking happens on Cal.com's team page via a
pre-filled deep link.
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests
from langchain.tools import tool

from coaching_agent.database import (
    get_coach_by_email,
    update_coach_preferences,
    upsert_participant,
)
from coaching_agent.events_catalog import (
    EVENTS,
    LANGUAGE_LABELS,
    TOPIC_LABELS,
    filter_events,
    find_by_slug,
)
from coaching_agent.cal_com import (
    get_team_event_by_slug,
    get_event_hosts as calcom_event_hosts,
    get_booking_questions as calcom_booking_questions,
    fetch_event_slots,
    create_team_booking,
)

CAL_API_KEY = os.getenv("CALCOM_API_KEY") or os.getenv("CAL_COM_API_KEY")
CAL_BASE = "https://api.cal.com/v2"


def _cal_headers(api_version: str = "2024-08-13") -> dict:
    return {
        "Authorization": f"Bearer {CAL_API_KEY}",
        "cal-api-version": api_version,
        "Content-Type": "application/json",
    }


def build_tools(session):
    """Return a list of tools bound to this session's state."""

    # ── role + OAuth ─────────────────────────────────────────────────────

    @tool
    def set_user_role(role: str) -> str:
        """
        Record whether the current user is a 'coach' or 'participant'.
        Call this as soon as the user tells you which they are.
        """
        r = role.strip().lower()
        if r not in ("coach", "participant"):
            return "Error: role must be 'coach' or 'participant'."
        session.role = r
        return f"Role set to {r}."

    @tool
    def get_calcom_oauth_url() -> str:
        """Return the URL the coach should open to connect their Cal.com account."""
        if not session.base_url:
            return "Error: BASE_URL is not configured on the server."
        if not os.getenv("CALCOM_CLIENT_ID"):
            return (
                "Cal.com OAuth isn't configured (CALCOM_CLIENT_ID unset). Ask the "
                "admin to set CALCOM_CLIENT_ID / CALCOM_CLIENT_SECRET, or use "
                "POST /auth/calcom/test-sync to seed a test coach record."
            )
        return f"{session.base_url}/auth/calcom/login?session_id={session.session_id}"

    @tool
    def get_google_oauth_url() -> str:
        """Return the URL for the user (coach or participant) to connect their Google account."""
        if not session.base_url:
            return "Error: BASE_URL is not configured on the server."
        role = session.role or "participant"
        return (
            f"{session.base_url}/auth/google/login"
            f"?user_type={role}&session_id={session.session_id}"
        )

    @tool
    def check_calcom_connected() -> str:
        """Whether the coach has finished Cal.com OAuth in this session."""
        return "connected" if session.calcom_connected else "not_connected"

    @tool
    def save_coach_preferences(open_to_rebooking: bool, coach_email: str = "") -> str:
        """
        Save the coach's rebooking-comfort preference.

        Args:
            open_to_rebooking: True if the coach is comfortable with participants
                rebooking after a cancellation.
            coach_email: The coach's email on Cal.com. Required if the coach record
                hasn't been linked to this session yet.
        """
        coach_id = session.coach_id
        if not coach_id and coach_email:
            coach = get_coach_by_email(coach_email)
            if coach:
                coach_id = coach["id"]
                session.coach_id = coach_id
        if not coach_id:
            return (
                "Error: no coach identified yet. Ask the coach for the email they use "
                "on Cal.com and pass it as coach_email."
            )
        ok = update_coach_preferences(coach_id, bool(open_to_rebooking))
        if not ok:
            return f"Error: couldn't find coach id {coach_id} to save preferences."
        return f"Saved: coach id={coach_id} open_to_rebooking={bool(open_to_rebooking)}."

    # ── participant identity ─────────────────────────────────────────────

    @tool
    def save_participant_info(
        name: str,
        email: str,
        timezone: str = "America/Los_Angeles",
    ) -> str:
        """
        Save the participant's name, email, and timezone so the booking can be
        made in their name and so we can look up past sessions for follow-up.
        """
        p = upsert_participant(name=name, email=email, timezone=timezone)
        session.participant_id = p.get("id")
        session.participant_name = p.get("name", name)
        session.participant_email = p.get("email", email)
        session.participant_timezone = p.get("timezone", timezone)
        return f"Saved participant: {session.participant_name} <{session.participant_email}>."

    # ── event catalog ────────────────────────────────────────────────────

    @tool
    def list_coaching_topics() -> str:
        """
        List the coaching topics the Technovation team offers.
        Use this when deciding with the participant what kind of coaching they need.
        """
        return "Available topics:\n" + "\n".join(
            f"- {key}: {label}" for key, label in TOPIC_LABELS.items()
        )

    @tool
    def list_coaching_events(
        topic: str = "",
        language: str = "",
        fmt: str = "",
    ) -> str:
        """
        List coaching events from the Technovation Cal.com team, optionally
        filtered by topic, language, and format. Leave any filter empty to
        ignore it.

        Args:
            topic: one of ideation, pitch, entrepreneurship, ai, python,
                   thunkable, app-inventor, scratch, other.
            language: two-letter code — en, es, hi, ru, zh, ja, de, fr, ta.
            fmt: 'individual' or 'group'.
        """
        t = topic.strip().lower() or None
        l = language.strip().lower() or None
        f = fmt.strip().lower() or None
        matches = filter_events(topic=t, language=l, fmt=f)
        if not matches:
            return (
                f"No events matched (topic={topic!r}, language={language!r}, "
                f"format={fmt!r}). Try broader filters."
            )
        lines = []
        for e in matches:
            lang = LANGUAGE_LABELS.get(e["language"], e["language"])
            lines.append(
                f"- slug={e['slug']} | {e['title']} "
                f"[{TOPIC_LABELS.get(e['topic'], e['topic'])}, {lang}, {e['format']}]"
            )
        return f"Matching coaching events ({len(matches)}):\n" + "\n".join(lines)

    @tool
    def select_coaching_event(slug: str) -> str:
        """
        Record which coaching event the participant picked and load its real
        Cal.com event id + booking-form questions. Pass the slug from
        list_coaching_events (e.g. 'technovation-ideation-coaching').
        """
        event = find_by_slug(slug.strip())
        if not event:
            return f"Error: no event with slug {slug!r}. Call list_coaching_events to see options."

        cal_event = get_team_event_by_slug(slug.strip())
        if not cal_event:
            return (
                f"Error: couldn't find event {slug!r} on Cal.com (team "
                "Technovation). The slug may have changed or the team API key "
                "may have lost access."
            )

        session.selected_event = event
        session.selected_event_id = int(cal_event.get("id") or 0)
        session.selected_event_length = int(cal_event.get("lengthInMinutes") or 60)
        session.booking_questions = calcom_booking_questions(slug.strip())
        session.collected_answers = {}
        return (
            f"Selected event: {event['title']} (slug={event['slug']}, "
            f"id={session.selected_event_id}, length={session.selected_event_length}m). "
            "Next: call get_booking_questions to see the form fields this event requires."
        )

    @tool
    def list_event_coaches() -> str:
        """
        Return the list of coaches (hosts) registered on Cal.com for the
        currently selected event type. Use this right after select_coaching_event
        to show the participant who could run their session.
        """
        if not session.selected_event:
            return "Error: no event selected. Call select_coaching_event first."
        hosts = calcom_event_hosts(session.selected_event["slug"])
        if not hosts:
            return f"No coaches are currently registered on {session.selected_event['title']}."
        lines = []
        for h in hosts:
            mandatory = " (mandatory)" if h.get("mandatory") else ""
            lines.append(
                f"- userId={h.get('userId')} | {h.get('name')} (@{h.get('username')})"
                f"{mandatory} priority={h.get('priority', 'medium')}"
            )
        return (
            f"Coaches registered on {session.selected_event['title']} "
            f"({len(hosts)} total):\n" + "\n".join(lines)
        )

    # ── dynamic booking questions ────────────────────────────────────────

    @tool
    def get_booking_questions() -> str:
        """
        Return the list of booking-form questions the selected event requires,
        pulled directly from Cal.com. Call this after select_coaching_event,
        then ask the participant each question one-by-one.
        """
        if not session.booking_questions:
            return "Error: no event selected. Call select_coaching_event first."

        lines = []
        for q in session.booking_questions:
            marker = "[REQUIRED]" if q["required"] else "[optional]"
            line = f"- {marker} slug={q['slug']} type={q['type']} — {q['label']}"
            if q.get("options"):
                line += f"  options={q['options']}"
            lines.append(line)
        return "Booking-form questions:\n" + "\n".join(lines)

    @tool
    def save_booking_answer(slug: str, value: str) -> str:
        """
        Save the participant's answer to one booking-form question.

        Args:
            slug: the field slug from get_booking_questions
                (e.g. 'title', 'solution', 'division', 'question-1', 'ackowledgement').
            value: the participant's answer. For boolean fields pass 'true'/'false'.
                For select fields pass the exact option string.
        """
        if not session.booking_questions:
            return "Error: no event selected. Call select_coaching_event first."
        known_slugs = {q["slug"] for q in session.booking_questions}
        if slug not in known_slugs:
            return (
                f"Error: {slug!r} is not a field on this event. "
                f"Known slugs: {sorted(known_slugs)}."
            )
        # Coerce booleans
        field = next(q for q in session.booking_questions if q["slug"] == slug)
        v: object = value
        if field["type"] == "boolean":
            v = str(value).strip().lower() in ("true", "yes", "y", "1", "agree", "ok")
        session.collected_answers[slug] = v
        return f"Saved answer for {slug}."

    # ── availability + booking ───────────────────────────────────────────

    @tool
    def get_event_slots(day: str) -> str:
        """
        Fetch available time slots for the selected coaching event on a given day.

        Args:
            day: 'today', 'tomorrow', a weekday name, or an ISO date like '2026-04-28'.
        """
        if not session.selected_event_id:
            return "Error: no event selected. Call select_coaching_event first."

        tz_name = session.participant_timezone or "America/Los_Angeles"
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        day_clean = day.strip().lower()

        if day_clean == "today":
            target = now
        elif day_clean == "tomorrow":
            target = now + timedelta(days=1)
        else:
            try:
                target = datetime.fromisoformat(day_clean)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=tz)
            except ValueError:
                weekdays = {
                    "monday": 0, "tuesday": 1, "wednesday": 2,
                    "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
                    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
                }
                wd = weekdays.get(day_clean) or weekdays.get(day_clean[:3])
                if wd is None:
                    return f"Error: couldn't understand day {day!r}."
                target = now + timedelta(days=(wd - now.weekday()) % 7)

        local_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        if local_start.tzinfo is None:
            local_start = local_start.replace(tzinfo=tz)
        local_end = local_start + timedelta(days=1) - timedelta(seconds=1)
        utc_start = local_start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        utc_end = local_end.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

        result = fetch_event_slots(session.selected_event_id, utc_start, utc_end)
        if "error" in result:
            return f"Error fetching slots: {result['error']}"

        tz_abbrev = datetime.now(tz).strftime("%Z")
        lines = []
        for _date_key, times in result.get("slots", {}).items():
            if not isinstance(times, list):
                continue
            for slot in times:
                utc_str = slot.get("start", "") if isinstance(slot, dict) else slot
                if not utc_str:
                    continue
                utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                local_dt = utc_dt.astimezone(tz)
                local_label = local_dt.strftime("%a %b %d, %I:%M %p").replace(" 0", " ")
                lines.append(f"{local_label} {tz_abbrev} (UTC: {utc_str})")

        if not lines:
            return f"No available slots found for {day}."
        return (
            f"Available slots for {day} ({session.selected_event['title']}):\n"
            + "\n".join(lines)
        )

    @tool
    def book_session(slot_time: str, guest_emails: Optional[List[str]] = None) -> str:
        """
        Book the selected coaching event at the given slot using the answers
        already collected via save_booking_answer. This calls Cal.com directly
        and actually creates the booking.

        Args:
            slot_time: exact UTC ISO timestamp from get_event_slots (e.g.
                '2026-04-28T17:00:00Z').
            guest_emails: optional list of extra attendee emails to invite.
        """
        if not session.selected_event_id:
            return "Error: no event selected."
        if not session.participant_name or not session.participant_email:
            return "Error: participant info missing. Call save_participant_info first."

        # Check that every required booking-form question has been answered.
        missing = [
            q["slug"] for q in session.booking_questions
            if q["required"]
            and q["slug"] not in ("name", "email")  # those come from save_participant_info
            and q["slug"] not in (session.collected_answers or {})
        ]
        if missing:
            return (
                f"Error: missing required answers for: {missing}. "
                "Call save_booking_answer for each before booking."
            )

        result = create_team_booking(
            event_type_id=session.selected_event_id,
            start_time=slot_time,
            attendee_name=session.participant_name,
            attendee_email=session.participant_email,
            attendee_timezone=session.participant_timezone or "America/Los_Angeles",
            answers=session.collected_answers,
            guest_emails=guest_emails or [],
        )
        if "error" in result:
            return f"Booking failed: {result['error']}"

        booking_uid = result.get("uid") or result.get("id") or "unknown"
        meeting_url = result.get("meetingUrl") or result.get("location") or ""
        session.last_booking_uid = str(booking_uid)
        msg = (
            f"Booked! {session.selected_event['title']} at {slot_time} "
            f"for {session.participant_name} <{session.participant_email}>. "
            f"Booking ID: {booking_uid}."
        )
        if meeting_url:
            msg += f" Meeting link: {meeting_url}."
        if guest_emails:
            msg += f" Guests invited: {', '.join(guest_emails)}."
        return msg

    # ── follow-up ────────────────────────────────────────────────────────

    @tool
    def check_previous_booking(email: str) -> str:
        """
        Look up a returning participant's most recent past Cal.com session by email,
        so you can ask how it went and offer a rebook.

        Returns a short description of the past session (host name, event title,
        when it happened, and whether the host has opted-in to rebooking), or 'none'.
        """
        if not CAL_API_KEY:
            return "Error: CALCOM_API_KEY is not set; can't query bookings."
        try:
            r = requests.get(
                f"{CAL_BASE}/bookings",
                headers=_cal_headers(),
                params={"attendeeEmail": email, "status": "past", "take": 5},
                timeout=15,
            )
        except requests.RequestException as exc:
            return f"Error fetching bookings: {exc}"

        if r.status_code != 200:
            return f"Error fetching bookings ({r.status_code}): {r.text}"

        bookings = r.json().get("data", [])
        if not bookings:
            return "none"

        # Bookings are ordered newest first in Cal.com's response; take the first.
        latest = bookings[0]
        hosts = latest.get("hosts") or []
        host = hosts[0] if hosts else {}
        host_name = host.get("name", "your coach")
        host_email = host.get("email", "")
        start = latest.get("start", "")
        event = latest.get("eventType", {}) or {}
        event_title = event.get("slug", latest.get("title", "coaching session"))

        rebook_hint = "unknown"
        if host_email:
            coach_record = get_coach_by_email(host_email)
            if coach_record and coach_record.get("preferences_set"):
                rebook_hint = (
                    "open_to_rebooking"
                    if coach_record.get("open_to_rebooking")
                    else "not_open_to_rebooking"
                )

        session.last_host_email = host_email
        session.last_host_name = host_name
        session.last_event_slug = event.get("slug", "")
        session.last_booking_start = start
        session.last_rebook_hint = rebook_hint

        return (
            f"Most recent past session: {event_title} with {host_name} on {start}. "
            f"Coach rebooking preference: {rebook_hint}."
        )

    return [
        set_user_role,
        get_calcom_oauth_url,
        get_google_oauth_url,
        check_calcom_connected,
        save_coach_preferences,
        save_participant_info,
        list_coaching_topics,
        list_coaching_events,
        select_coaching_event,
        list_event_coaches,
        get_booking_questions,
        save_booking_answer,
        get_event_slots,
        book_session,
        check_previous_booking,
    ]
