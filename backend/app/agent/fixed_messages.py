"""Fixed assistant messages written by code, not the LLM (tone matches prompts/system.md, 04 §4.0)."""

# First message of every new session (POST /api/sessions).
GREETING = (
    "Hi! I'm your trip planner. Where would you like to go, and for how many days? "
    "Short trips of 2–4 days in one or two cities work best.\n\n"
    "Once I know the destination and trip length, click **Generate plan** and I'll draft "
    "an itinerary. You can keep chatting to change it afterwards."
)

# Saved and streamed after each generated itinerary version (POST /api/sessions/{id}/generate).
# Stage 1 doesn't edit plans from chat, so it points back to the button.
PLAN_READY = (
    "Here's a draft itinerary. Tell me what you'd like to change, then click **Regenerate** "
    "to update it."
)
