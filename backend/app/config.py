import os
from pathlib import Path
import socket
from dotenv import load_dotenv

# Path to backend/.env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

SHARED_SECRET: str = os.getenv("SHARED_SECRET", "mulehunter-demo-secret")
LISTEN_SECONDS: int = int(os.getenv("LISTEN_SECONDS", "25"))
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-jwt-secret")
PORT: int = int(os.getenv("PORT", "8000"))
REAL_PORT: int = int(os.getenv("REAL_PORT", "8000"))
SIM_NAIVE_THRESHOLD: float = float(os.getenv("SIM_NAIVE_THRESHOLD", "50000"))
WINDOW_HOURS: float = float(os.getenv("WINDOW_HOURS", "48"))

# Risk bands
ALERT_MIN: float = float(os.getenv("ALERT_MIN", "0.40"))
GREEN_MAX: float = float(os.getenv("GREEN_MAX", "0.65"))
YELLOW_MAX: float = float(os.getenv("YELLOW_MAX", "0.85"))

# Real backend public URL & LLM configuration
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").strip()
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
LLM_ENABLED: bool = os.getenv("LLM_ENABLED", "true").lower() in ("true", "1", "yes")
LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "8.0"))

# Simulator & Engine timing
SIM_SPEED: float = float(os.getenv("SIM_SPEED", "15.0"))
DETECT_TICK_SIM_MINUTES: float = float(os.getenv("DETECT_TICK_SIM_MINUTES", "5.0"))
DETECT_TICK_WALL_SECONDS: float = float(os.getenv("DETECT_TICK_WALL_SECONDS", "3.0"))
WARMUP_SIM_HOURS: float = float(os.getenv("WARMUP_SIM_HOURS", "24.0"))
OFFICER_DELAY_SIM_MINUTES: float = float(os.getenv("OFFICER_DELAY_SIM_MINUTES", "10.0"))


def get_lan_ip() -> str:
    """Auto-detect laptop LAN IP via UDP socket trick."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_public_base_url() -> str:
    """Returns PUBLIC_BASE_URL if configured, otherwise http://<LAN_IP>:<REAL_PORT>."""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return f"http://{get_lan_ip()}:{REAL_PORT}"
