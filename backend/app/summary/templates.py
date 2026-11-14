"""
Deterministic spoken alert templates for Mule Hunter.

Constraints:
  - Spoken-friendly: says "rupees", Indian numbering ("4.2 lakh", "1.3 crore"), no currency symbols.
  - At most 45 words.
  - Must include: level, number of accounts, amount, time span, plain-language typology,
    source/destination when defined, and risk as a percentage.
  - MUST END WITH EXACTLY: "Log in to the dashboard for linked accounts."
"""

from typing import Optional


def format_inr_spoken(amount: float) -> str:
    """Formats amount in Indian spoken representation (crores, lakhs, thousands)."""
    amt = float(amount)
    if amt >= 10_000_000:
        val = amt / 10_000_000
        return f"{val:.1f} crore rupees".replace(".0 crore", " crore")
    elif amt >= 100_000:
        val = amt / 100_000
        return f"{val:.1f} lakh rupees".replace(".0 lakh", " lakh")
    elif amt >= 1_000:
        val = amt / 1_000
        return f"{val:.1f} thousand rupees".replace(".0 thousand", " thousand")
    else:
        return f"{int(amt)} rupees"


def format_timespan_spoken(span_seconds: float) -> str:
    """Formats time span into natural spoken hours or minutes."""
    hrs = span_seconds / 3600.0
    if hrs >= 1.0:
        return f"{hrs:.1f} hours".replace(".0 hours", " hours")
    mins = max(1, int(span_seconds / 60.0))
    return f"{mins} minutes"


def generate_template_summary(
    level: str,
    accounts_count: int,
    total_amount: float,
    span_seconds: float,
    typology: str,
    risk_score: float,
    source: Optional[str] = None,
    destination: Optional[str] = None,
) -> str:
    """
    Generates a spoken summary under 45 words ending with the required call to action.
    """
    amt_str = format_inr_spoken(total_amount)
    span_str = format_timespan_spoken(span_seconds)
    risk_pct = int(round(risk_score * 100))
    level_word = level.capitalize()

    # Plain language typology descriptions & sentences
    if typology == "round_tripping":
        text = (
            f"{level_word} alert. {accounts_count} accounts cycled {amt_str} "
            f"over {span_str} in a round trip loop. Risk is {risk_pct} percent. "
            f"Log in to the dashboard for linked accounts."
        )
    elif typology == "smurfing_fan_out_fan_in":
        src_phrase = f"from {source} " if source else ""
        dst_phrase = f"to {destination} " if destination else ""
        text = (
            f"{level_word} alert. Smurfing detected across {accounts_count} accounts {src_phrase}"
            f"moving {amt_str} {dst_phrase}in {span_str}. Risk is {risk_pct} percent. "
            f"Log in to the dashboard for linked accounts."
        )
    elif typology == "mule_chain":
        text = (
            f"{level_word} alert. A linear mule chain of {accounts_count} accounts forwarded {amt_str} "
            f"over {span_str}. Risk is {risk_pct} percent. "
            f"Log in to the dashboard for linked accounts."
        )
    elif typology == "hybrid":
        text = (
            f"{level_word} alert. Complex hybrid laundering across {accounts_count} accounts "
            f"funneled {amt_str} in {span_str}. Risk is {risk_pct} percent. "
            f"Log in to the dashboard for linked accounts."
        )
    elif typology == "fan_out":
        src_phrase = f"from {source} " if source else ""
        text = (
            f"{level_word} alert. High velocity fan out {src_phrase}to {accounts_count} accounts "
            f"moved {amt_str} in {span_str}. Risk is {risk_pct} percent. "
            f"Log in to the dashboard for linked accounts."
        )
    elif typology == "fan_in":
        dst_phrase = f"into {destination} " if destination else ""
        text = (
            f"{level_word} alert. Rapid fan in from {accounts_count} accounts {dst_phrase}"
            f"gathered {amt_str} in {span_str}. Risk is {risk_pct} percent. "
            f"Log in to the dashboard for linked accounts."
        )
    else:
        text = (
            f"{level_word} alert. Suspicious cluster of {accounts_count} accounts moved {amt_str} "
            f"in {span_str}. Risk is {risk_pct} percent. "
            f"Log in to the dashboard for linked accounts."
        )

    # Word count validation guard
    words = text.split()
    if len(words) > 45:
        # Fallback to ultra-compact form
        text = (
            f"{level_word} alert. {accounts_count} accounts moved {amt_str} "
            f"in {span_str}, matching {typology.replace('_', ' ')}. Risk {risk_pct} percent. "
            f"Log in to the dashboard for linked accounts."
        )

    return text
