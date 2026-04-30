"""
events_catalog.py — Curated list of Technovation team coaching event types.

Source: https://cal.com/team/technovation (fetched 2026-04-23).

Each entry is:
    slug     — URL slug after /team/technovation/
    title    — human-facing event title
    topic    — ideation | pitch | entrepreneurship | ai |
               python | thunkable | app-inventor | scratch |
               group | other
    language — en | es | hi | ru | zh | ja | de | fr | ta
    format   — individual | group | other
    description — one-line hint for the agent
"""

TEAM_SLUG = "technovation"
BASE_URL = f"https://cal.com/team/{TEAM_SLUG}"


EVENTS: list[dict] = [
    # ── Test ─────────────────────────────────────────────────────────────
    {"slug": "test-coaching", "title": "TEST Coaching", "topic": "other",
     "language": "en", "format": "individual",
     "description": "Test event to verify workflow."},

    # ── Ideation ─────────────────────────────────────────────────────────
    {"slug": "technovation-ideation-coaching", "title": "Technovation Ideation Coaching",
     "topic": "ideation", "language": "en", "format": "individual",
     "description": "Ideation coaching for English-speaking teams."},
    {"slug": "technovation-ideation-coaching-russian", "title": "Technovation Ideation Coaching (Russian)",
     "topic": "ideation", "language": "ru", "format": "individual",
     "description": "Ideation coaching for Russian-speaking teams."},
    {"slug": "technovation-ideation-coaching-hindi", "title": "Technovation Ideation Coaching (Hindi)",
     "topic": "ideation", "language": "hi", "format": "individual",
     "description": "Ideation coaching for Hindi-speaking teams."},
    {"slug": "technovation-ideation-coaching-mandarin", "title": "Technovation Ideation Coaching (Mandarin)",
     "topic": "ideation", "language": "zh", "format": "individual",
     "description": "Ideation coaching for Mandarin-speaking teams."},
    {"slug": "technovation-ideation-coaching-tamil", "title": "Technovation Ideation Coaching (Tamil)",
     "topic": "ideation", "language": "ta", "format": "individual",
     "description": "Ideation coaching for Tamil-speaking teams."},
    {"slug": "technovation-ideation-coaching-japanese", "title": "Technovation Ideation Coaching (Japanese)",
     "topic": "ideation", "language": "ja", "format": "individual",
     "description": "Ideation coaching for Japanese-speaking teams."},
    {"slug": "technovation-ideation-coaching-german", "title": "Technovation Ideation Coaching (German)",
     "topic": "ideation", "language": "de", "format": "individual",
     "description": "Ideation coaching for German-speaking teams."},
    {"slug": "technovation-ideation-coaching-french", "title": "Technovation Ideation Coaching (French)",
     "topic": "ideation", "language": "fr", "format": "individual",
     "description": "Ideation coaching for French-speaking teams."},
    {"slug": "technovation-ideation-coaching-spanish", "title": "Technovation Ideation Coaching (Spanish)",
     "topic": "ideation", "language": "es", "format": "individual",
     "description": "Ideation coaching for Spanish-speaking teams."},

    # ── Pitch ────────────────────────────────────────────────────────────
    {"slug": "technovation-pitch-coaching", "title": "Technovation Pitch Coaching",
     "topic": "pitch", "language": "en", "format": "individual",
     "description": "Pitch development coaching for English-speaking teams."},
    {"slug": "technovation-pitch-coaching-hindi", "title": "Technovation Pitch Coaching (Hindi)",
     "topic": "pitch", "language": "hi", "format": "individual",
     "description": "Pitch coaching for Hindi-speaking teams."},
    {"slug": "technovation-pitch-coaching-mandarin", "title": "Technovation Pitch Coaching (Mandarin)",
     "topic": "pitch", "language": "zh", "format": "individual",
     "description": "Pitch coaching for Mandarin-speaking teams."},
    {"slug": "technovation-pitch-coaching-japanese", "title": "Technovation Pitch Coaching (Japanese)",
     "topic": "pitch", "language": "ja", "format": "individual",
     "description": "Pitch coaching for Japanese-speaking teams."},
    {"slug": "technovation-pitch-coaching-spanish", "title": "Technovation Pitch Coaching (Spanish)",
     "topic": "pitch", "language": "es", "format": "individual",
     "description": "Pitch coaching for Spanish-speaking teams."},

    # ── Entrepreneurship ─────────────────────────────────────────────────
    {"slug": "technovation-entrepreneurship-coaching", "title": "Technovation Entrepreneurship Coaching",
     "topic": "entrepreneurship", "language": "en", "format": "individual",
     "description": "Entrepreneurship guidance for English-speaking teams."},
    {"slug": "technovation-entrepreneurship-coaching-hindi", "title": "Technovation Entrepreneurship Coaching (Hindi)",
     "topic": "entrepreneurship", "language": "hi", "format": "individual",
     "description": "Entrepreneurship guidance for Hindi-speaking teams."},
    {"slug": "technovation-entrepreneurship-coaching-spanish", "title": "Technovation Entrepreneurship Coaching (Spanish)",
     "topic": "entrepreneurship", "language": "es", "format": "individual",
     "description": "Entrepreneurship guidance for Spanish-speaking teams."},
    {"slug": "technovation-entrepreneurship-coaching-mandarin", "title": "Technovation Entrepreneurship Coaching (Mandarin)",
     "topic": "entrepreneurship", "language": "zh", "format": "individual",
     "description": "Entrepreneurship guidance for Mandarin-speaking teams."},

    # ── AI ───────────────────────────────────────────────────────────────
    {"slug": "technovation-ai-coaching", "title": "Technovation AI Coaching",
     "topic": "ai", "language": "en", "format": "individual",
     "description": "AI coaching for English-speaking teams."},
    {"slug": "technovation-ai-coaching-russian", "title": "Technovation AI Coaching (Russian)",
     "topic": "ai", "language": "ru", "format": "individual",
     "description": "AI coaching for Russian-speaking teams."},
    {"slug": "technovation-ai-coaching-german", "title": "Technovation AI Coaching (German)",
     "topic": "ai", "language": "de", "format": "individual",
     "description": "AI coaching for German-speaking teams."},
    {"slug": "technovation-ai-coaching-tamil", "title": "Technovation AI Coaching (Tamil)",
     "topic": "ai", "language": "ta", "format": "individual",
     "description": "AI coaching for Tamil-speaking teams."},
    {"slug": "technovation-ai-coaching-hindi", "title": "Technovation AI Coaching (Hindi)",
     "topic": "ai", "language": "hi", "format": "individual",
     "description": "AI coaching for Hindi-speaking teams."},
    {"slug": "technovation-ai-coaching-spanish", "title": "Technovation AI Coaching (Spanish)",
     "topic": "ai", "language": "es", "format": "individual",
     "description": "AI coaching for Spanish-speaking teams."},

    # ── Python ───────────────────────────────────────────────────────────
    {"slug": "technovation-python-coaching", "title": "Technovation Python Coding Coaching",
     "topic": "python", "language": "en", "format": "individual",
     "description": "Python coding for English-speaking teams."},
    {"slug": "technovation-python-coding-coaching-hindi", "title": "Technovation Python Coding Coaching (Hindi)",
     "topic": "python", "language": "hi", "format": "individual",
     "description": "Python coding for Hindi-speaking teams."},
    {"slug": "technovation-python-coding-coaching-spanish", "title": "Technovation Python Coding Coaching (Spanish)",
     "topic": "python", "language": "es", "format": "individual",
     "description": "Python coding for Spanish-speaking teams."},
    {"slug": "technovation-python-coding-coaching-russian", "title": "Technovation Python Coding Coaching (Russian)",
     "topic": "python", "language": "ru", "format": "individual",
     "description": "Python coding for Russian-speaking teams."},
    {"slug": "technovation-python-coding-coaching-tamil", "title": "Technovation Python Coding Coaching (Tamil)",
     "topic": "python", "language": "ta", "format": "individual",
     "description": "Python coding for Tamil-speaking teams."},
    {"slug": "technovation-python-coding-coaching-german", "title": "Technovation Python Coding Coaching (German)",
     "topic": "python", "language": "de", "format": "individual",
     "description": "Python coding for German-speaking teams."},
    {"slug": "technovation-python-coding-coaching-mandarin", "title": "Technovation Python Coding Coaching (Mandarin)",
     "topic": "python", "language": "zh", "format": "individual",
     "description": "Python coding for Mandarin-speaking teams."},

    # ── Thunkable ────────────────────────────────────────────────────────
    {"slug": "technovation-thunkable-coaching", "title": "Technovation Thunkable Coding Coaching",
     "topic": "thunkable", "language": "en", "format": "individual",
     "description": "Thunkable coding for English-speaking teams."},
    {"slug": "technovation-thunkable-coding-coaching-mandarin", "title": "Technovation Thunkable Coding Coaching (Mandarin)",
     "topic": "thunkable", "language": "zh", "format": "individual",
     "description": "Thunkable coding for Mandarin-speaking teams."},
    {"slug": "technovation-thunkable-coding-coaching-german", "title": "Technovation Thunkable Coding Coaching (German)",
     "topic": "thunkable", "language": "de", "format": "individual",
     "description": "Thunkable coding for German-speaking teams."},
    {"slug": "technovation-thunkable-coding-coaching-spanish", "title": "Technovation Thunkable Coding Coaching (Spanish)",
     "topic": "thunkable", "language": "es", "format": "individual",
     "description": "Thunkable coding for Spanish-speaking teams."},
    {"slug": "technovation-thunkable-coding-coaching-french", "title": "Technovation Thunkable Coding Coaching (French)",
     "topic": "thunkable", "language": "fr", "format": "individual",
     "description": "Thunkable coding for French-speaking teams."},

    # ── App Inventor ─────────────────────────────────────────────────────
    {"slug": "technovation-app-inventor-coaching", "title": "Technovation App Inventor Coding Coaching",
     "topic": "app-inventor", "language": "en", "format": "individual",
     "description": "App Inventor coding for English-speaking teams."},
    {"slug": "technovation-app-inventor-coding-coaching-german", "title": "Technovation App Inventor Coding Coaching (German)",
     "topic": "app-inventor", "language": "de", "format": "individual",
     "description": "App Inventor coding for German-speaking teams."},
    {"slug": "technovation-app-inventor-coding-coaching-mandarin", "title": "Technovation App Inventor Coding Coaching (Mandarin)",
     "topic": "app-inventor", "language": "zh", "format": "individual",
     "description": "App Inventor coding for Mandarin-speaking teams."},
    {"slug": "technovation-app-inventor-coding-coaching-spanish", "title": "Technovation App Inventor Coding Coaching (Spanish)",
     "topic": "app-inventor", "language": "es", "format": "individual",
     "description": "App Inventor coding for Spanish-speaking teams."},

    # ── Scratch ──────────────────────────────────────────────────────────
    {"slug": "technovation-scratch-coding-coaching", "title": "Technovation Scratch Coding Coaching",
     "topic": "scratch", "language": "en", "format": "individual",
     "description": "Scratch coding for English-speaking teams."},
    {"slug": "technovation-scratch-coding-coaching-german", "title": "Technovation Scratch Coding Coaching (German)",
     "topic": "scratch", "language": "de", "format": "individual",
     "description": "Scratch coding for German-speaking teams."},
    {"slug": "technovation-scratch-coding-coaching-hindi", "title": "Technovation Scratch Coding Coaching (Hindi)",
     "topic": "scratch", "language": "hi", "format": "individual",
     "description": "Scratch coding for Hindi-speaking teams."},
    {"slug": "technovation-scratch-coding-coaching-mandarin", "title": "Technovation Scratch Coding Coaching (Mandarin)",
     "topic": "scratch", "language": "zh", "format": "individual",
     "description": "Scratch coding for Mandarin-speaking teams."},

    # ── Group ────────────────────────────────────────────────────────────
    {"slug": "group-coaching-ideation", "title": "Group Coaching - Ideation",
     "topic": "ideation", "language": "en", "format": "group",
     "description": "Multi-team ideation coaching session for Club Ambassadors."},
    {"slug": "group-coaching-pitch", "title": "Group Coaching - Pitch",
     "topic": "pitch", "language": "en", "format": "group",
     "description": "Multi-team pitch coaching session for Club Ambassadors."},
    {"slug": "group-coaching-business", "title": "Group Coaching - Business",
     "topic": "entrepreneurship", "language": "en", "format": "group",
     "description": "Multi-team business coaching session for Club Ambassadors."},
    {"slug": "group-coaching-thunkable", "title": "Group Coaching - Thunkable",
     "topic": "thunkable", "language": "en", "format": "group",
     "description": "Multi-team Thunkable coaching session for Club Ambassadors."},
    {"slug": "group-coaching-app-inventor", "title": "Group Coaching - App Inventor",
     "topic": "app-inventor", "language": "en", "format": "group",
     "description": "Multi-team App Inventor coaching session for Club Ambassadors."},
    {"slug": "group-coaching-python", "title": "Group Coaching - Python",
     "topic": "python", "language": "en", "format": "group",
     "description": "Multi-team Python coaching session for Club Ambassadors."},
    {"slug": "group-coaching-artificial-intelligence", "title": "Group Coaching - Artificial Intelligence",
     "topic": "ai", "language": "en", "format": "group",
     "description": "Multi-team AI coaching session for Club Ambassadors."},
]


LANGUAGE_LABELS = {
    "en": "English", "es": "Spanish", "hi": "Hindi", "ru": "Russian",
    "zh": "Mandarin", "ja": "Japanese", "de": "German", "fr": "French",
    "ta": "Tamil",
}

TOPIC_LABELS = {
    "ideation": "Ideation",
    "pitch": "Pitch development",
    "entrepreneurship": "Entrepreneurship / business",
    "ai": "AI",
    "python": "Python coding",
    "thunkable": "Thunkable coding",
    "app-inventor": "App Inventor coding",
    "scratch": "Scratch coding",
    "other": "Other",
}


def filter_events(
    topic: str | None = None,
    language: str | None = None,
    fmt: str | None = None,
) -> list[dict]:
    """Return events matching the non-None filters."""
    results = []
    for e in EVENTS:
        if topic and e["topic"] != topic:
            continue
        if language and e["language"] != language:
            continue
        if fmt and e["format"] != fmt:
            continue
        results.append(e)
    return results


def find_by_slug(slug: str) -> dict | None:
    for e in EVENTS:
        if e["slug"] == slug:
            return e
    return None


def booking_url(slug: str) -> str:
    return f"{BASE_URL}/{slug}"
