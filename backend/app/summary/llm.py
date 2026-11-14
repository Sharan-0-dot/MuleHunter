"""
LLM Polish for spoken alert summaries via OpenRouter with visible failure diagnostics.

Constraints & Features:
  - Strict preservation: preserves every important fact (accounts count, amount, risk percentage).
  - Normalised comparison: supports '4.2 lakh', '4.2L', '420000', '25L', '%', spelled-out units.
  - Verbatim closing sentence: "Log in to the dashboard for linked accounts."
  - Word count cap: at most 55 words.
  - Visibility: returns (final_text, summary_source, llm_status, llm_latency_ms).
  - Debug tracking: keeps ring buffer of last 20 attempts for GET /api/debug/llm.
  - NEVER logs, displays, or exposes the API key or raw prompts.
"""

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time
from typing import Dict, List, Optional, Tuple
import requests

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import app.config as cfg

REQUIRED_CLOSING = "Log in to the dashboard for linked accounts."
NUMBER_REGEX = re.compile(r"\b\d+(?:\.\d+)?\b")

# Ring buffer for the last 20 LLM attempts (thread-safe append/pop)
LLM_DEBUG_LOG: deque = deque(maxlen=20)


def get_llm_debug_history() -> List[dict]:
    """Returns copy of the last 20 LLM polish attempts."""
    return list(LLM_DEBUG_LOG)


def _record_debug_attempt(status: str, latency_ms: Optional[float], source: str):
    """Records attempt in debug ring buffer (strictly no keys or prompts)."""
    LLM_DEBUG_LOG.append({
        "time": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "latency_ms": latency_ms,
        "model": cfg.OPENROUTER_MODEL,
        "summary_source": source,
    })


def extract_amounts(text: str) -> List[float]:
    """
    Extracts normalized float amounts from text supporting Indian numbering and standard notation:
    crore/cr, lakh/lac/l, thousand/k, million/m, and raw numbers.
    """
    clean = text.replace(",", "")
    matches = []
    # 1. Crore / cr
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:crores?|cr)\b", clean, re.IGNORECASE):
        matches.append(float(m.group(1)) * 10_000_000.0)
    # 2. Lakh / lac / l
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:lakhs?|lacs?|l)\b", clean, re.IGNORECASE):
        matches.append(float(m.group(1)) * 100_000.0)
    # 3. Thousand / k
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:thousands?|k)\b", clean, re.IGNORECASE):
        matches.append(float(m.group(1)) * 1_000.0)
    # 4. Million / m
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:millions?|m)\b", clean, re.IGNORECASE):
        matches.append(float(m.group(1)) * 1_000_000.0)
    # 5. Raw numbers >= 1000
    for m in re.finditer(r"\b(\d{4,}(?:\.\d+)?)\b", clean):
        matches.append(float(m.group(1)))
    return matches


def _clean_reasoning_and_quotes(text: str) -> str:
    """Strips <think>...</think> reasoning blocks and wrapping quotes."""
    if not text:
        return ""
    # Strip <think>...</think> blocks if present
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip markdown code blocks if wrapped
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]).strip()
    # Strip wrapping quotes
    if cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _validate_llm_reply(
    template_text: str,
    reply_text: str,
    facts: Optional[dict] = None,
) -> Tuple[bool, str]:
    """
    Validates LLM reply against strict safety criteria with normalized fact matching:
      1. Closing sentence present verbatim.
      2. Word count <= 55 words.
      3. Important facts preserved: accounts count, amount, risk percentage.
    Returns: (is_valid, reason)
    """
    if not reply_text or not reply_text.strip():
        return False, "empty_reply"

    # 1. Closing sentence check
    if REQUIRED_CLOSING not in reply_text:
        return False, "missing_closing"

    # 2. Word count check <= 55
    words = reply_text.strip().split()
    if len(words) > 55:
        return False, "word_count"

    # 3. Important facts check
    if facts:
        # 3a. Accounts count
        acc = facts.get("accounts_count")
        if acc is not None:
            acc_pattern = rf"\b{acc}\b"
            if not re.search(acc_pattern, reply_text):
                return False, "missing_accounts"

        # 3b. Risk percent
        risk_pct = facts.get("risk_pct")
        if risk_pct is not None:
            pct_pattern = rf"\b{risk_pct}\s*(?:%|percent)\b|\b{risk_pct}\b"
            if not re.search(pct_pattern, reply_text, re.IGNORECASE):
                return False, "missing_risk"

        # 3c. Amount normalization check
        expected_amount = facts.get("total_amount")
        if expected_amount is not None and expected_amount > 0:
            extracted_amts = extract_amounts(reply_text)
            matched = False
            for amt in extracted_amts:
                # Within 1.5% margin for rounding (e.g. 4.2L vs 420000)
                if abs(amt - expected_amount) / expected_amount <= 0.015:
                    matched = True
                    break
            # Also check if raw expected amount without units appears
            if not matched and str(int(expected_amount)) in reply_text.replace(",", ""):
                matched = True
            if not matched:
                return False, "missing_amount"
    else:
        # Fallback if no facts dict provided: ensure numbers from template appear
        template_numbers = set(NUMBER_REGEX.findall(template_text))
        reply_numbers = set(NUMBER_REGEX.findall(reply_text))
        if not template_numbers.issubset(reply_numbers):
            # Check normalized amounts before failing
            tmpl_amts = extract_amounts(template_text)
            reply_amts = extract_amounts(reply_text)
            if not (tmpl_amts and reply_amts and any(abs(a - b) / max(a, 1.0) <= 0.015 for a in tmpl_amts for b in reply_amts)):
                return False, "missing_numbers"

    return True, "ok"


def polish_summary(
    template_text: str,
    facts: Optional[dict] = None,
) -> Tuple[str, str, str, Optional[float]]:
    """
    Polishes spoken template summary via OpenRouter chat completions.

    Args:
        template_text: Base deterministic template string.
        facts: Optional dict with important facts:
               {"accounts_count": int, "total_amount": float, "risk_pct": int}

    Returns:
        (final_summary_text, summary_source, llm_status, llm_latency_ms)
        summary_source: "llm" or "template"
        llm_status: "ok", "disabled", "no_key", "timeout", "http_429", "http_401",
                    "http_<code>", "empty_reply", "validation_failed:<check>"
    """
    if not cfg.LLM_ENABLED:
        _record_debug_attempt("disabled", None, "template")
        return template_text, "template", "disabled", None

    if not cfg.OPENROUTER_API_KEY:
        _record_debug_attempt("no_key", None, "template")
        return template_text, "template", "no_key", None

    system_prompt = (
        "You are an AI assistant for bank financial crime compliance officers. "
        "Rewrite the following spoken AML alert summary for maximum clarity and urgency. "
        "Rules:\n"
        "1. Length: at most 45 words.\n"
        "2. Preserve every number and fact exactly (accounts count, amount, time, risk). Do NOT add new facts.\n"
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
        "max_tokens": 120,
    }

    url = f"{cfg.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    t0 = time.perf_counter()

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=cfg.LLM_TIMEOUT_SECONDS,
        )
        dt_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            reply = ""
            if choices and "message" in choices[0]:
                msg = choices[0]["message"]
                raw_content = msg.get("content") or ""
                # Also check reasoning fallback if content was placed in text
                if not raw_content and msg.get("text"):
                    raw_content = msg.get("text")
                reply = _clean_reasoning_and_quotes(raw_content)

            if not reply:
                status = "empty_reply"
                _record_debug_attempt(status, dt_ms, "template")
                return template_text, "template", status, dt_ms

            is_valid, reason = _validate_llm_reply(template_text, reply, facts=facts)
            if is_valid:
                status = "ok"
                _record_debug_attempt(status, dt_ms, "llm")
                return reply, "llm", status, dt_ms
            else:
                status = f"validation_failed:{reason}"
                _record_debug_attempt(status, dt_ms, "template")
                return template_text, "template", status, dt_ms
        elif resp.status_code == 429:
            status = "http_429"
        elif resp.status_code == 401:
            status = "http_401"
        else:
            status = f"http_{resp.status_code}"

        _record_debug_attempt(status, dt_ms, "template")
        return template_text, "template", status, dt_ms

    except requests.exceptions.Timeout:
        dt_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        status = "timeout"
        _record_debug_attempt(status, dt_ms, "template")
        return template_text, "template", status, dt_ms
    except Exception as e:
        dt_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        status = f"exception:{type(e).__name__}"
        _record_debug_attempt(status, dt_ms, "template")
        return template_text, "template", status, dt_ms
