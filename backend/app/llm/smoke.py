"""Manual live check of the configured LLM provider (04-backend-design §3.0). Not run by pytest.

Run from `backend/` with the venv active:

    python -m app.llm.smoke

It uses `LLM_*` settings from `backend/.env` (environment variables override them), streams one
short reply, then asks for one small JSON object. It never prints the API key.
"""

import asyncio
import sys

from pydantic import BaseModel

from app.core.config import get_settings
from app.llm import LLMError, get_provider


class Place(BaseModel):
    city: str
    state: str


async def main() -> int:
    settings = get_settings()
    try:
        provider = get_provider(settings)
    except LLMError as err:
        print(f"Config error: {err}", file=sys.stderr)
        return 1
    print(f"Provider: {provider.name}   Model: {getattr(provider, 'model', '(none)')}")

    try:
        print("stream_text: ", end="", flush=True)
        async for text in provider.stream_text(
            system="You are a friendly travel planner. Answer in one short sentence.",
            messages=[{"role": "user", "content": "Say hi and name one fun thing to do in Austin, TX."}],
        ):
            print(text, end="", flush=True)
        print()

        place = await provider.generate_json(
            system="You are a travel planner.",
            messages=[{"role": "user", "content": "Name one city in Texas that is good for a weekend trip."}],
            schema=Place,
        )
        print(f"generate_json: {place!r}")
    except LLMError as err:
        print(f"\nLLM error (retryable={err.retryable}): {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")  # don't crash on characters the console can't show
    sys.exit(asyncio.run(main()))
