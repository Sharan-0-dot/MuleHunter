import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import app.config as cfg

def main():
    print("=== CONFIG REPORT ===")
    print(f".env loaded path      : {cfg.env_path} (exists: {cfg.env_path.exists()})")
    is_set = "yes" if bool(cfg.OPENROUTER_API_KEY) else "no"
    key_len = len(cfg.OPENROUTER_API_KEY)
    print(f"OPENROUTER_API_KEY set: {is_set} (length: {key_len})")
    print(f"OPENROUTER_MODEL      : {cfg.OPENROUTER_MODEL}")
    print(f"OPENROUTER_BASE_URL   : {cfg.OPENROUTER_BASE_URL}")
    print(f"LLM_ENABLED           : {cfg.LLM_ENABLED}")
    print(f"LLM_TIMEOUT_SECONDS   : {cfg.LLM_TIMEOUT_SECONDS}")
    print("Import-time behaviour : Values are evaluated once at module import time.")
    print("Stale values in server: If backend/.env changes while uvicorn is running, the running server uses stale values unless reloaded.")

if __name__ == "__main__":
    main()
