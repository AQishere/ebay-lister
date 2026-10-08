"""Check the LLM provider works by running the real extraction prompt on sample notes.

    python -m scripts.check_llm
    python -m scripts.check_llm "iphone 13 128gb blue unlocked, small scratch on back"
    python -m scripts.check_llm --models     # list Groq models your key can use
"""

import asyncio
import json
import sys
import time

import httpx

from app.cache import Cache
from app.config import get_settings
from app.llm import LLM, LLMError
from app.prompts import extract_messages

SAMPLE = "nike air max 90 white mens size 10, worn twice, comes with original box"


async def list_groq_models() -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {s.groq_api_key}"})
    if resp.status_code != 200:
        print(f"[XX ] {resp.status_code}: {resp.text[:300]}")
        return
    models = sorted(m["id"] for m in resp.json()["data"] if m.get("active", True))
    print("Models available to your key:\n" + "\n".join(f"  {m}" for m in models))


async def main() -> None:
    if sys.argv[1:] == ["--models"]:
        return await list_groq_models()
    s = get_settings()
    notes = sys.argv[1] if len(sys.argv) > 1 else SAMPLE
    model = s.groq_model if s.llm_provider == "groq" else s.ollama_model
    print(f"Provider: {s.llm_provider} | model: {model}\nNotes: {notes}\n")

    llm = LLM(Cache(None), s)
    start = time.perf_counter()
    try:
        result = await llm.chat_json(extract_messages(notes), temperature=0.0)
    except LLMError as e:
        print(f"[XX ] {e}")
        return
    finally:
        await llm.aclose()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n[OK ] {s.llm_provider} answered in {(time.perf_counter() - start) * 1000:.0f} ms")


if __name__ == "__main__":
    asyncio.run(main())
