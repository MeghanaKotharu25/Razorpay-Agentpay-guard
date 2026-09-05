"""
Standalone diagnostic: isolates exactly why the live semantic-guard LLM call
is failing, without any of the gateway's exception-truncation in the way.

Run from backend/ with your venv active:
    PYTHONPATH=. python diagnose_openrouter.py
"""
import asyncio
import time
from openai import AsyncOpenAI
from app.config import settings


async def main():
    key = settings.OPENROUTER_API_KEY.strip()
    print(f"Base URL: {settings.OPENROUTER_BASE_URL}")
    print(f"Model:    {settings.GUARD_MODEL}")
    print(f"Key (masked): {key[:12]}...{key[-4:] if len(key) > 16 else ''}")
    print(f"Key looks live: {bool(key and not key.startswith('mock') and 'placeholder' not in key)}")
    print("-" * 60)

    client = AsyncOpenAI(base_url=settings.OPENROUTER_BASE_URL, api_key=key)

    start = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=settings.GUARD_MODEL,
            messages=[
                {"role": "system", "content": "You are a test. Reply with only the word OK."},
                {"role": "user", "content": "ping"}
            ],
            temperature=0.0,
        )
        elapsed = (time.perf_counter() - start) * 1000
        print(f"SUCCESS in {elapsed:.0f}ms")
        print(f"Response: {response.choices[0].message.content}")
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        print(f"FAILED after {elapsed:.0f}ms")
        print(f"Exception type: {type(e).__name__}")
        print(f"Full message: {e}")


if __name__ == "__main__":
    asyncio.run(main())