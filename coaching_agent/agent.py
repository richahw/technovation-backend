"""
agent.py — LangGraph agent using Claude (via ChatAnthropic).

Each session has its own CoachingAgent with mutable state (role, connection
flags, selected coach, participant info). Tools are built per-session so they
can read/write that state via closure.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage
from coaching_agent.tools import build_tools

load_dotenv()

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

llm = ChatAnthropic(
    model_name="claude-sonnet-4-6",
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    temperature=0,
    timeout=60,
    stop=None,
    base_url=None,
)

# ---------------------------------------------------------------------------
# System prompt — orchestrates the two-role flow.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the scheduling assistant for the Technovation x Delta coaching platform.
Coaching events are offered by the Technovation team on Cal.com:
  https://cal.com/team/technovation
You do NOT maintain a separate list of coaches — participants choose a coaching EVENT TYPE
(topic + language + format), and Cal.com handles who the coach is and which times are free.

You talk to two kinds of users — coaches and participants — and the very first thing you must
do is find out which one they are.

Opening:
  - On the first message of a conversation, greet the user and ask: "Are you a coach or a participant?"
  - As soon as they tell you, call set_user_role('coach' or 'participant').

============================================================
COACH FLOW
============================================================
After set_user_role('coach'):

1. Ask the coach to connect their Cal.com account. Call get_calcom_oauth_url and share the link.
   Tell them to finish setting up their profile, event type, and availability on Cal.com.
2. Once check_calcom_connected returns 'connected' (the live state block also shows
   `cal.com connected: True`), the coach has just returned from the OAuth flow. Open your
   next reply with a warm, explicit acknowledgment that their Cal.com account is connected
   (something like "Great — your Cal.com account is connected!") BEFORE moving on. Then,
   in the SAME message, ask the rebooking question:
       "If a participant cancels, are you comfortable with them rebooking a new time with you?"
   Accept yes/no and call save_coach_preferences(open_to_rebooking=True/False). If the coach
   record isn't linked yet, ask for the email they used on Cal.com and pass it as coach_email.
   Do NOT skip the acknowledgment — even if the user's incoming message is terse like
   "I've connected my Cal.com account.", they still want confirmation that the system saw it.
3. Thank them and confirm their profile is ready.

============================================================
PARTICIPANT FLOW
============================================================
After set_user_role('participant'):

Step 1 — Identify, and check for a past session:
  - Ask their full name and email (and timezone if unclear). Call save_participant_info.
  - Call check_previous_booking(email). If it returns a past session:
      a) Ask how that session went.
      b) If the coach's rebooking preference is 'open_to_rebooking', offer to rebook with the
         same coach. If it's 'not_open_to_rebooking', only offer to pick a different coaching
         event. If 'unknown', say you'll find them another session.
    Then continue to step 2 to narrow down an event.

Step 2 — Decide which coaching event to book.

  FAST PATH: If the participant names a specific event by title or slug (e.g. they say
  something like "I want the X event" or "book slug Y"), pass that slug straight to
  select_coaching_event. If the slug isn't valid, the tool will tell you and you can
  fall back to the routing path. Don't refuse just because you don't recognize the
  exact slug — try the tool first.

  ROUTING PATH: Otherwise, ask these questions ONE AT A TIME, then call
  list_coaching_events(topic=..., language=..., fmt=...) with the answers as filters.
  a) WHAT do you need coaching on? BEFORE asking, call list_coaching_topics and
     enumerate every option it returns inline as a bulleted list in your message —
     do NOT just say "which of these" or paraphrase; the user must see the actual
     topic labels in the message you send. Example phrasing:
         "What do you need coaching on? Here are the topics we offer:
            - ideation: Coming up with an idea
            - pitch: Pitch development
            - ... (every topic from the tool, verbatim)
          Pick one, or describe what you need help with if none fit."
     NEVER invent topic values; pick from what list_coaching_topics returns. If the
     participant's first answer doesn't match a known topic, re-show the list.
  b) WHICH LANGUAGE would you like the session in? List the supported languages inline:
       English, Spanish, Hindi, Russian, Mandarin, Japanese, German, French, Tamil.
  c) INDIVIDUAL or GROUP session? (Group is for Club Ambassadors coordinating multiple teams.)

  If list_coaching_events returns nothing, loosen the filters (e.g. drop language to fall
  back to English) and tell the participant what you changed.

Step 3 — Confirm and select:
  - Show the participant the matching event(s). If there's exactly one, confirm it. If
    multiple, let them pick.
  - Call select_coaching_event(slug). This single call returns the event details, the
    registered coaches, AND the booking-form questions in one response — you do NOT
    need to call list_event_coaches or get_booking_questions afterwards.
  - From its response, tell the participant which coach(es) are registered. If there's
    only one host, say "Your session will be with <name>." If multiple, list them and
    note that Cal.com will round-robin assign one when you book — you cannot force a
    specific host on a team event, so make that clear if the participant asks.

Step 4 — Use the booking-form questions returned by select_coaching_event:
  - The booking-form questions are ALREADY in the response from select_coaching_event.
    Do NOT call get_booking_questions again unless that response was truncated.
  - Name and email are already collected — do NOT ask again for those.
  - For every other field, ask the participant the question in natural language using the
    label returned by Cal.com. Required fields are labeled [REQUIRED]; you MUST collect
    every required one. Optional fields can be skipped if the participant has nothing to
    say, but offer each one.
  - Treat optional follow-up question fields as a SERIES (e.g. question-1, question-2,
    question-3, or any group of optional fields whose labels read as "another question",
    "additional question", "anything else"). As soon as the participant declines one in
    the series ("no", "no second question", "I'm good", "nothing else"), STOP offering
    the remaining follow-ups in that same series and move on to the next step. Don't ask
    "do you have a third question?" after they've already said they don't have a second.
  - For select-type fields, present the options verbatim and have the participant choose.
  - For boolean/acknowledgment fields, read the text and ask "do you acknowledge? (yes/no)".
  - After each answer, call save_booking_answer(slug, value). For booleans pass "true" or
    "false". For selects pass the exact option string.

Step 5 — Pick a time:
  - Ask which day they'd like (today, tomorrow, a weekday name, or an ISO date).
  - If the participant says something like "next available", "as soon as possible",
    "any day this week", or doesn't pin down a specific day, call
    get_event_slots(day='today', num_days=14) — this returns slots across the
    next 14 days in chronological order, so you can quote the earliest one
    without iterating day-by-day. Anchor 'today' to the date in the system
    context, not your training intuition.
  - If the participant gave a specific day, call get_event_slots(day=<that day>,
    num_days=1).
  - Show the slots in local-time format; keep the UTC ISO timestamp for booking.
  - Let the participant pick one.
  - Ask if they want to invite any additional guests (optional, comma-separated emails).

Step 6 — Confirm and book:
  - Summarize everything back to the participant in one message: event, time, their name
    and email, and the answers to the custom questions.
  - When they confirm, call book_session(slot_time=<UTC ISO>, guest_emails=[...]).
  - Relay the booking confirmation (booking id + meeting link) to the participant.
  - Remind them they can come back after the session and you'll follow up on how it went.

============================================================
POST-SESSION FOLLOW-UP
============================================================
If a returning participant comes back after a session has already happened — detected via
check_previous_booking returning a past session — open the conversation with:
  1. "How did your session with <host_name> on <date> go?"
  2. If the coach's rebook preference is 'open_to_rebooking':
       "Would you like to book another session with <host_name>, or try a different
        coaching event?" — then continue Step 2 accordingly.
     If the preference is 'not_open_to_rebooking' or 'unknown':
       "Let's find you another coaching session — what topic do you need help with?"
       — then continue Step 2.

============================================================
GENERAL RULES
============================================================
- Always call set_user_role first — don't guess.
- Ask one question at a time; don't dump a giant form.
- When multiple independent tool calls are needed in the same step (their inputs don't
  depend on each other's outputs), call them in parallel in a single response — don't
  sequence them.
- Never fabricate events or booking confirmations. If a tool returns an error, explain it
  clearly in plain language and suggest what to try.
- Be concise and friendly.
- Reply in plain text only. Do NOT use markdown formatting — no **bold**, no *italics*,
  no backticks, no headings. The chat frontend renders text verbatim, so asterisks and
  other markdown markers show up as literal characters and look wrong. When you need to
  present a Cal.com question label, quote it as plain text (e.g. say: What is one
  question you have about the coding of your project?) without wrapping it in any
  formatting.
"""

# The static portion of the system prompt is cached across turns; today's date
# is appended as a separate uncached block so the model always knows what
# "today" / "next available" mean. Only blocks marked with cache_control are
# cached, so adding a per-turn date block does not invalidate the cache prefix.
_CACHED_PROMPT_BLOCK = {
    "type": "text",
    "text": SYSTEM_PROMPT,
    "cache_control": {"type": "ephemeral"},
}


def _build_date_block(tz_name: str) -> dict:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    return {
        "type": "text",
        "text": (
            f"Today's date is {now_local.strftime('%A, %B %d, %Y')} "
            f"({tz_name}, current local time {now_local.strftime('%H:%M')}). "
            "ALWAYS use this as the anchor for any date or time reasoning. "
            "When the user says 'today', 'tomorrow', 'next Monday', or 'as soon as "
            "possible', interpret it relative to this date — not your training-data "
            "intuition of 'now'."
        ),
    }


def _build_state_block(session) -> dict:
    """Render the live session state so the model can recover after the chat
    history gets trimmed. Without this, a long booking flow loses earlier
    tool-call results and the model restarts the greeting."""
    lines = ["Live session state (DO NOT re-ask things already known here):"]
    lines.append(f"  role: {session.role or '(unknown — ask)'}")

    if session.role == "coach":
        lines.append(f"  cal.com connected: {session.calcom_connected}")
        if session.coach_id:
            lines.append(f"  coach_id: {session.coach_id}")

    if session.role == "participant":
        if session.participant_name or session.participant_email:
            lines.append(
                f"  participant: {session.participant_name or '?'} "
                f"<{session.participant_email or '?'}> "
                f"tz={session.participant_timezone or '?'}"
            )
        else:
            lines.append("  participant: not yet identified — call save_participant_info")

        if session.selected_event:
            ev = session.selected_event
            lines.append(
                f"  selected event: {ev.get('title')} "
                f"(slug={ev.get('slug')}, id={session.selected_event_id}, "
                f"length={session.selected_event_length}m)"
            )
        else:
            lines.append("  selected event: none yet")

        if session.booking_questions:
            answered = session.collected_answers or {}
            required_remaining = [
                q["slug"] for q in session.booking_questions
                if q.get("required")
                and q["slug"] not in ("name", "email")
                and q["slug"] not in answered
            ]
            optional_remaining = [
                q["slug"] for q in session.booking_questions
                if not q.get("required")
                and q["slug"] not in ("name", "email")
                and q["slug"] not in answered
            ]
            lines.append(
                f"  booking-form answers collected: {sorted(answered.keys()) or 'none'}"
            )
            lines.append(
                f"  booking-form required still missing: {required_remaining or 'none'}"
            )
            lines.append(
                f"  booking-form optional still pending: {optional_remaining or 'none'}"
            )

        if session.last_booking_uid:
            lines.append(f"  last booking uid: {session.last_booking_uid}")

    lines.append(
        "If the chat history above is short, it may have been trimmed — trust "
        "this state block and continue the flow from where it indicates. Do "
        "NOT restart the greeting if role is already set."
    )
    return {"type": "text", "text": "\n".join(lines)}

# ---------------------------------------------------------------------------
# Per-session agent + state
# ---------------------------------------------------------------------------


class CoachingAgent:
    """One per session. Holds conversation history and mutable session state."""

    def __init__(self, session_id: str, base_url: str = ""):
        self.session_id = session_id
        self.base_url = base_url.rstrip("/")

        # Flow state
        self.role: str = ""  # "coach" | "participant" | ""
        self.calcom_connected: bool = False
        self.google_connected: bool = False

        # Coach-specific
        self.coach_id: int | None = None

        # Participant-specific
        self.participant_id: int | None = None
        self.participant_name: str = ""
        self.participant_email: str = ""
        self.participant_timezone: str = ""

        # Event selection (from the Technovation Cal.com team catalog)
        self.selected_event: dict | None = None
        self.selected_event_id: int = 0
        self.selected_event_length: int = 60
        self.booking_questions: list = []
        self.collected_answers: dict = {}
        self.last_booking_uid: str = ""

        # Last-session cache (for follow-up)
        self.last_host_email: str = ""
        self.last_host_name: str = ""
        self.last_event_slug: str = ""
        self.last_booking_start: str = ""
        self.last_rebook_hint: str = ""

        # Conversation
        self.chat_history: list = []

        # Tools are bound to this session
        self._tools = build_tools(self)

        def _prompt(state):
            tz_name = self.participant_timezone or "America/Los_Angeles"
            return [
                SystemMessage(content=[
                    _CACHED_PROMPT_BLOCK,
                    _build_date_block(tz_name),
                    _build_state_block(self),
                ])
            ] + list(state["messages"])

        self._agent = create_react_agent(
            model=llm,
            tools=self._tools,
            prompt=_prompt,
        )

    # Keep the last N user turns + everything after (preserves tool-call/result pairs,
    # since those only live between consecutive HumanMessages). A full booking flow
    # can span 10+ user turns; the per-turn state block in the system prompt covers
    # state recovery if trimming kicks in, but a generous window keeps conversational
    # nuance intact for the model.
    HISTORY_MAX_USER_TURNS = 12

    def _trimmed_history(self) -> list:
        if not self.chat_history:
            return []
        human_idx = [
            i for i, m in enumerate(self.chat_history) if isinstance(m, HumanMessage)
        ]
        if len(human_idx) <= self.HISTORY_MAX_USER_TURNS:
            return self.chat_history
        keep_from = human_idx[-self.HISTORY_MAX_USER_TURNS]
        return self.chat_history[keep_from:]

    def respond(self, user_input: str) -> str:
        self.chat_history = self._trimmed_history()
        self.chat_history.append(HumanMessage(content=user_input))
        result = self._agent.invoke({"messages": self.chat_history})
        messages = result["messages"]

        response_text = ""
        for msg in reversed(messages):
            if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content.strip():
                response_text = msg.content
                break
            if hasattr(msg, "content") and isinstance(msg.content, list):
                texts = [
                    block.get("text", "")
                    for block in msg.content
                    if isinstance(block, dict) and "text" in block
                ]
                if texts:
                    response_text = " ".join(texts)
                    break

        self.chat_history = messages
        return response_text

    async def respond_stream(self, user_input: str):
        """Yield response text chunks as the model produces them."""
        self.chat_history = self._trimmed_history()
        self.chat_history.append(HumanMessage(content=user_input))

        final_messages = None
        async for event in self._agent.astream_events(
            {"messages": self.chat_history},
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk is None:
                    continue
                content = getattr(chunk, "content", None)
                if isinstance(content, str) and content:
                    yield content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield text
            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if isinstance(output, dict) and "messages" in output:
                    final_messages = output["messages"]

        if final_messages is not None:
            self.chat_history = final_messages


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Keeps one CoachingAgent per session_id."""

    def __init__(self):
        self._sessions: dict[str, CoachingAgent] = {}
        self._base_url = (
            os.getenv("BASE_URL")
            or (
                f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
                if os.getenv("RAILWAY_PUBLIC_DOMAIN")
                else None
            )
            or "http://localhost:8000"
        )

    def get_or_create(self, session_id: str) -> CoachingAgent:
        if session_id not in self._sessions:
            self._sessions[session_id] = CoachingAgent(
                session_id=session_id, base_url=self._base_url
            )
        return self._sessions[session_id]

    def respond(self, session_id: str, user_input: str) -> str:
        return self.get_or_create(session_id).respond(user_input)

    async def respond_stream(self, session_id: str, user_input: str):
        agent = self.get_or_create(session_id)
        async for chunk in agent.respond_stream(user_input):
            yield chunk

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())

    # ── methods used by the OAuth callbacks in main.py ────────────────────

    def get_role(self, session_id: str) -> str:
        session = self._sessions.get(session_id)
        return session.role if session else ""

    def set_role(self, session_id: str, role: str) -> None:
        self.get_or_create(session_id).role = role

    def set_calcom_connected(self, session_id: str) -> None:
        self.get_or_create(session_id).calcom_connected = True

    def set_google_connected(self, session_id: str) -> None:
        self.get_or_create(session_id).google_connected = True
