import json
import re
import sys
import time
from pathlib import Path
import requests

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import app.config as cfg
from app.summary.templates import generate_template_summary

REQUIRED_CLOSING = "Log in to the dashboard for linked accounts."
NUMBER_REGEX = re.compile(r"\b\d+(?:\.\d+)?\b")


def redact_key(text: str) -> str:
    if not text:
        return text
    if cfg.OPENROUTER_API_KEY:
        text = text.replace(cfg.OPENROUTER_API_KEY, "[REDACTED_API_KEY]")
    # Also catch any generic sk-or-v1 pattern
    text = re.sub(r"sk-or-v1-[a-f0-9]{32,}", "[REDACTED_API_KEY]", text)
    return text


def test_call(timeout_seconds: float):
    print("=" * 70)
    print(f"CALLING OPENROUTER DIRECTLY (TIMEOUT = {timeout_seconds}s)")
    print("=" * 70)

    template_text = generate_template_summary(
        level="red",
        accounts_count=6,
        total_amount=2500000.0,
        span_seconds=3600.0,
        typology="round_tripping",
        risk_score=0.95,
        source="ACC-0142",
        destination="ACC-0142",
    )
    print(f"Template summary text:\n  '{template_text}'\n")

    system_prompt = (
        "You are an AI assistant for bank financial crime officers. "
        "Rewrite the following spoken AML alert summary for maximum clarity and urgency. "
        "Rules:\n"
        "1. Length: at most 45 words.\n"
        "2. Preserve every number and fact exactly. Do NOT add new facts or change amounts.\n"
        "3. You MUST end the output with this exact closing sentence: "
        f'"{REQUIRED_CLOSING}"'
    )

    headers = {
        "Authorization": f"Bearer {cfg.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "Mule Hunter AML",
    }

    payload = {
        "model": cfg.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": template_text},
        ],
        "temperature": 0.2,
        "max_tokens": 150,
    }

    url = f"{cfg.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    t0 = time.perf_counter()

    status_code = None
    error_body = None
    raw_reply = None
    is_content_empty_or_null = True
    reasoning_content = None

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
        latency = round(time.perf_counter() - t0, 3)
        status_code = resp.status_code

        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices and "message" in choices[0]:
                msg = choices[0]["message"]
                raw_reply = msg.get("content")
                reasoning_content = msg.get("reasoning") or msg.get("reasoning_content")
                is_content_empty_or_null = raw_reply is None or raw_reply.strip() == ""
        else:
            error_body = redact_key(resp.text)
    except requests.exceptions.Timeout:
        latency = round(time.perf_counter() - t0, 3)
        error_body = f"Request timed out after {timeout_seconds}s"
    except Exception as e:
        latency = round(time.perf_counter() - t0, 3)
        error_body = redact_key(str(e))

    print(f"HTTP Status               : {status_code}")
    print(f"Wall Latency              : {latency} s")
    print(f"Content Empty or Null     : {is_content_empty_or_null}")
    if reasoning_content:
        print(f"Reasoning Content Present : True (length: {len(reasoning_content)})")
    if error_body:
        print(f"Error Body                :\n{error_body}")
    print(f"Raw Reply                 :\n{raw_reply}")

    # Validation breakdown
    print("\n--- Validation Breakdown ---")
    if raw_reply:
        # Check 1: Closing sentence
        closing_ok = REQUIRED_CLOSING in raw_reply
        print(f"  Check 1 (closing sentence present): {closing_ok}")
        if not closing_ok:
            print(f"    Expected: '{REQUIRED_CLOSING}'")

        # Check 2: Word count
        words = raw_reply.strip().split()
        word_count = len(words)
        word_count_ok = word_count <= 55
        print(f"  Check 2 (word count <= 55): {word_count_ok} (count = {word_count})")

        # Check 3: Number preservation
        template_numbers = set(NUMBER_REGEX.findall(template_text))
        reply_numbers = set(NUMBER_REGEX.findall(raw_reply))
        missing_numbers = template_numbers - reply_numbers
        numbers_ok = len(missing_numbers) == 0
        print(f"  Check 3 (all template numbers found): {numbers_ok}")
        print(f"    Template numbers: {sorted(template_numbers)}")
        print(f"    Reply numbers   : {sorted(reply_numbers)}")
        if missing_numbers:
            print(f"    Missing numbers : {sorted(missing_numbers)}")
    else:
        print("  Skipped: No valid text reply to validate.")
    print()


def main():
    test_call(4.0)
    test_call(15.0)


if __name__ == "__main__":
    main()
