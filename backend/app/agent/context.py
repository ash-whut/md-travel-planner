"""Per-turn system text (architecture §3): the system prompt plus today's date, the profile, the
current plan and, before there is a plan, the forecast for the trip.
"""

from datetime import date
from pathlib import Path

from app.agent.postprocess import CityWeather, short_city_name
from app.schemas.itinerary import DayWeather, Itinerary
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
    profile: TripProfile,
    today: date | None = None,
    plan: Itinerary | None = None,
    weather: list[CityWeather] | None = None,
) -> str:
    """System text for one chat turn. Pass `today` in tests to get a fixed date.

    `plan` is the latest saved itinerary; without one the context says there is no plan yet.
    `weather` is the gathered weather for the trip; when given it is added after the plan.
    """
    today = today or date.today()
    parts = [
        load_prompt("system").strip(),
        "# Context",
        f"Today is {format_date(today)} ({today.isoformat()}).",
        "## Trip profile so far\n" + render_profile(profile),
        compact_itinerary(plan) if plan else "## Current plan\nNo plan yet.",
    ]
    if weather:
        parts.append(render_weather(weather))
    return "\n\n".join(parts)


def render_weather(weather: list[CityWeather]) -> str:
    """The gathered weather per city, one line per day, e.g.
    `- Fri, Mar 5: sunny, high 66°F / low 48°F`. A failed city says so, so the LLM won't guess.
    """
    lines = ["## Weather (from the weather service, Open-Meteo)"]
    for city in weather:
        name = short_city_name(city.name)
        if not city.days:
            lines.append(f"{name}: weather is unavailable right now.")
            continue
        climate = any(day.source == "climate" for day in city.days.values())
        kind = "seasonal average for these dates, no forecast yet" if climate else "forecast"
        lines.append(f"{name} ({kind}):")
        for day, day_weather in sorted(city.days.items()):
            lines.append(f"- {day:%a}, {day:%b} {day.day}: {format_weather(day_weather)}")
    return "\n".join(lines)


def format_weather(weather: DayWeather) -> str:
    return f"{weather.condition}, high {weather.high_f:.0f}°F / low {weather.low_f:.0f}°F"


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


def compact_itinerary(it: Itinerary) -> str:
    """The plan in a compact form for the LLM context: a short header, then one line per day,
    e.g. `Day 1 (Fri Mar 5): 06:00 [A] Home · 09:15 [B] IAH`.

    Tagged items show their stop's tag and name; untagged items (free time) their description.
    The weather, when known, is one `Weather:` line before the day lines, so the day lines keep
    their format.
    """
    stop_names = {stop.tag: stop.name for stop in it.stops}
    lines = [
        f"## Current plan (version {it.version})",
        f"{it.title}: {format_date(it.start_date)} – {format_date(it.end_date)}, "
        f"{it.travelers} traveler(s)",
    ]
    if it.cost_estimate:
        cost = it.cost_estimate
        lines.append(f"Estimated cost per person: ${cost.low:,.0f}–${cost.high:,.0f} (estimate)")
    if it.weather_summary:
        day_weather = [
            f"Day {day.day_number}: {format_weather(day.weather)}"
            for day in it.days
            if day.weather is not None
        ]
        lines.append(f"Weather: {it.weather_summary}. " + " · ".join(day_weather))
    for day in it.days:
        entries = [
            f"{item.start_time} [{item.stop_tag}] {stop_names[item.stop_tag]}"
            if item.stop_tag
            else f"{item.start_time} {item.description}"
            for item in day.items
        ]
        day_label = f"{day.date:%a} {day.date:%b} {day.date.day}"  # "Fri Mar 5"
        lines.append(f"Day {day.day_number} ({day_label}): " + " · ".join(entries))
    if it.assumptions:
        lines.append("Assumptions: " + "; ".join(it.assumptions))
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
