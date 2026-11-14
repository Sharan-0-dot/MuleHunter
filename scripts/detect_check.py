"""
Root-level wrapper for backend/scripts/detect_check.py
"""
import runpy
from pathlib import Path

target = Path(__file__).resolve().parent.parent / "backend" / "scripts" / "detect_check.py"
runpy.run_path(str(target), run_name="__main__")
