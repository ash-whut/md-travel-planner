"""Per-turn system text (architecture §3): the system prompt plus today's date, the profile and
the current plan. A later step adds the forecast here.
"""

from datetime import date
from pathlib import Path

from app.schemas.itinerary import Itinerary
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


def build_system(
    profile: TripProfile, today: date | None = None, plan: Itinerary | None = None
) -> str:
    """System text for one chat turn. Pass `today` in tests to get a fixed date.

    `plan` is the latest saved itinerary; without one the context says there is no plan yet.
    """
    today = today or date.today()
    return "\n\n".join(
        [
            load_prompt("system").strip(),
            "# Context",
            f"Today is {format_date(today)} ({today.isoformat()}).",
            "## Trip profile so far\n" + render_profile(profile),
            render_plan(plan),
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


def render_plan(plan: Itinerary | None) -> str:
    """The plan in a compact form: one line per day and per item, with the stop tags."""
    if plan is None:
        return "## Current plan\nNo plan yet."
    stop_names = {stop.tag: stop.name for stop in plan.stops}
    lines = [
        f"## Current plan (version {plan.version})",
        f"{plan.title}: {format_date(plan.start_date)} – {format_date(plan.end_date)}, "
        f"{plan.travelers} traveler(s)",
    ]
    if plan.cost_estimate:
        cost = plan.cost_estimate
        lines.append(f"Estimated cost per person: ${cost.low:,.0f}–${cost.high:,.0f} (estimate)")
    for day in plan.days:
        lines.append(f"Day {day.day_number} · {format_date(day.date)} · {day.city}: {day.title}")
        for item in day.items:
            stop = f"[{item.stop_tag}] {stop_names[item.stop_tag]}: " if item.stop_tag else ""
            lines.append(f"  - {format_time(item.start_time)} {stop}{item.description}")
    if plan.assumptions:
        lines.append("Assumptions: " + "; ".join(plan.assumptions))
    return "\n".join(lines)


def format_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, date):
        return f"{format_date(value)} ({value.isoformat()})"
    return str(value)


def format_time(hhmm: str) -> str:
    """A 24-hour "HH:MM" as 12-hour time, e.g. "14:30" → "2:30 PM" (the prompt asks for 12h)."""
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return f"{(hours - 1) % 12 + 1}:{minutes:02d} {'AM' if hours < 12 else 'PM'}"


def format_date(day: date) -> str:
    """US style with the year, e.g. "Fri, Mar 5, 2027" (no %-d: it doesn't work on Windows)."""
    return f"{day:%a}, {day:%b} {day.day}, {day.year}"
