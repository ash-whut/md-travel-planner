"""Per-turn system text (architecture §3): the system prompt plus today's date and the profile.

Later steps add the compact itinerary and the forecast here.
"""

from datetime import date
from pathlib import Path

from app.schemas.profile import TripProfile

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Profile fields in the order they are shown, with their labels.
# `missing_required` is not listed here; it is rendered as its own line.
PROFILE_LABELS: dict[str, str] = {
    "cities": "Cities",
    "vibe": "Vibe",
    "start_date": "Start date",
    "end_date": "End date",
    "duration_days": "Length (days)",
    "rough_timing": "Rough timing",
    "origin": "Traveling from",
    "travelers": "Travelers",
    "budget_level": "Budget",
    "interests": "Interests",
    "dietary": "Dietary needs",
    "pace": "Pace",
    "transport": "Transport",
    "notes": "Notes",
}


def load_prompt(name: str) -> str:
    """The text of `agent/prompts/<name>.md`."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def build_system(profile: TripProfile, today: date | None = None) -> str:
    """System text for one chat turn. Pass `today` in tests to get a fixed date."""
    today = today or date.today()
    return "\n\n".join(
        [
            load_prompt("system").strip(),
            "# Context",
            f"Today is {format_date(today)} ({today.isoformat()}).",
            "## Trip profile so far\n" + render_profile(profile),
        ]
    )


def render_profile(profile: TripProfile) -> str:
    """One `- Label: value` line per known field; unknown (empty) fields are left out."""
    lines: list[str] = []
    for field, label in PROFILE_LABELS.items():
        value = getattr(profile, field)
        if value is None or value == []:
            continue
        lines.append(f"- {label}: {format_value(value)}")
    if not lines:
        lines.append("- Nothing known yet.")
    if profile.missing_required:
        lines.append(f"- Still needed: {', '.join(profile.missing_required)}")
    return "\n".join(lines)


def format_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, date):
        return f"{format_date(value)} ({value.isoformat()})"
    return str(value)


def format_date(day: date) -> str:
    """US style with the year, e.g. "Fri, Mar 5, 2027" (no %-d: it doesn't work on Windows)."""
    return f"{day:%a}, {day:%b} {day.day}, {day.year}"
