import sys
import time
from pathlib import Path
import requests

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import app.config as cfg
from app.summary.templates import generate_template_summary

template = generate_template_summary("red", 6, 2500000.0, 3600.0, "round_tripping", 0.95)
prompt = (
    "You are an AI assistant for bank financial crime officers. "
    "Rewrite the following spoken AML alert summary for maximum clarity and urgency. "
    "Rules:\n"
    "1. Length: at most 45 words.\n"
    "2. Preserve every number and fact exactly. Do NOT add new facts or change amounts.\n"
    '3. You MUST end the output with this exact closing sentence: "Log in to the dashboard for linked accounts."'
)

for m in ["openai/gpt-4o-mini", "meta-llama/llama-3.1-8b-instruct", "deepseek/deepseek-chat"]:
    t0 = time.perf_counter()
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {cfg.OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": m, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": template}], "max_tokens": 100},
        timeout=10.0,
    )
    dt = round(time.perf_counter() - t0, 2)
    print(f"=== {m} ({r.status_code} in {dt}s) ===")
    if r.status_code == 200:
        c = r.json()["choices"][0]["message"]["content"].strip()
        print(c)
    else:
        print(r.text[:120])
    print()
