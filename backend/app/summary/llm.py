"""
Optional LLM polish for spoken alert summaries via OpenRouter.

Constraints:
  - Strict preservation: preserves every number and fact exactly, adds no new facts.
  - Verbatim closing sentence: "Log in to the dashboard for linked accounts."
  - Word count cap: at most 55 words.
  - Fail-safe fallback: on ANY error, missing key, timeout, or validation check failure,
    silently falls back to the deterministic template summary.
  - NEVER logs or displays the API key.
"""

from pathlib import Path
import re
import sys
import time
from typing import Optional, Tuple
import requests

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_BASE_URL,
    LLM_ENABLED,
    LLM_TIMEOUT_SECONDS,
)

REQUIRED_CLOSING = "Log in to the dashboard for linked accounts."
NUMBER_REGEX = re.compile(r"\b\d+(?:\.\d+)?\b")


def _validate_llm_reply(template_text: str, reply_text: str) -> bool:
    """
    Validates LLM reply against strict safety criteria:
      1. Contains exact required closing sentence.
      2. Word count <= 55 words.
      3. Every numeric literal in template text appears in the reply.
    """
    if not reply_text:
        return False

    # 1. Check closing sentence
    if REQUIRED_CLOSING not in reply_text:
        return False

    # 2. Word count <= 55 words
    words = reply_text.strip().split()
    if len(words) > 55:
        return False

    # 3. Check numbers preservation
    template_numbers = set(NUMBER_REGEX.findall(template_text))
    reply_numbers = set(NUMBER_REGEX.findall(reply_text))
    if not template_numbers.issubset(reply_numbers):
        return False

    return True


def polish_summary(template_text: str) -> Tuple[str, str, Optional[float]]:
    """
    Polishes spoken template summary via OpenRouter chat completions.
    Returns: (final_summary_text, summary_source, llm_latency_ms)
      summary_source is either "llm" or "template".
    """
    if not LLM_ENABLED or not OPENROUTER_API_KEY:
        return template_text, "template", None

    system_prompt = (
        "You are an AI assistant for bank financial crime officers. "
        "Rewrite the following spoken AML alert summary for maximum clarity and urgency. "
        "Rules:\n"
        "1. Length: at most 45 words.\n"
        "2. Preserve every number and fact exactly. Do NOT add new facts or change amounts.\n"
        "3. You MUST end the output with this exact closing sentence: "
        f"\"{REQUIRED_CLOSING}\""
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8001",
        "X-Title": "Mule Hunter AML",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": template_text},
        ],
        "temperature": 0.2,
        "max_tokens": 100,
    }

    url = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    t0 = time.perf_counter()

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT_SECONDS)
        dt_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        if resp.status_code == 200:
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            # Clean possible markdown wrapping quotes
            if reply.startswith('"') and reply.endswith('"'):
                reply = reply[1:-1].strip()

            if _validate_llm_reply(template_text, reply):
                return reply, "llm", dt_ms
    except Exception:
        pass

    # Fallback to template
    return template_text, "template", None
