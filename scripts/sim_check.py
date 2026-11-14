"""
Root-level wrapper for backend/scripts/sim_check.py
"""
import runpy
from pathlib import Path

target = Path(__file__).resolve().parent.parent / "backend" / "scripts" / "sim_check.py"
runpy.run_path(str(target), run_name="__main__")
