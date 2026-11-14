"""
Text-to-Speech audio synthesizer for spoken alert summaries.

Uses pyttsx3 with a fresh engine per call protected by a threading lock.
Outputs mono 16-bit PCM WAV to backend/static/audio/{cluster_id}.wav (or -v{n}.wav).
If TTS generation fails or times out, safely falls back to the pre-made sample audio
(red/yellow/green.wav) and flags tts_fallback=True.
"""

from pathlib import Path
import shutil
import sys
import threading
from typing import Tuple
import pyttsx3

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import get_public_base_url

AUDIO_DIR = backend_dir / "static" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

_TTS_LOCK = threading.Lock()


def generate_audio(
    cluster_id: str,
    text: str,
    level: str,
    version: int = 1,
) -> Tuple[Path, str, bool]:
    """
    Synthesizes text into a WAV audio file.
    Returns: (file_path, wav_url, tts_fallback_bool)
    """
    filename = f"{cluster_id}.wav" if version == 1 else f"{cluster_id}-v{version}.wav"
    out_path = AUDIO_DIR / filename
    tts_fallback = False

    acquired = _TTS_LOCK.acquire(timeout=8.0)
    if acquired:
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 165)
            engine.save_to_file(text, str(out_path))
            engine.runAndWait()
            del engine

            # Verify file exists and is non-empty
            if not out_path.exists() or out_path.stat().st_size < 1000:
                tts_fallback = True
        except Exception:
            tts_fallback = True
        finally:
            _TTS_LOCK.release()
    else:
        tts_fallback = True

    # Fallback to pre-made sample audio if TTS generation failed
    if tts_fallback or not out_path.exists() or out_path.stat().st_size < 1000:
        sample_file = AUDIO_DIR / f"{level.lower()}.wav"
        if not sample_file.exists():
            sample_file = AUDIO_DIR / "red.wav"
        if sample_file.exists():
            shutil.copyfile(sample_file, out_path)
        tts_fallback = True

    wav_url = f"{get_public_base_url()}/static/audio/{filename}"
    return out_path, wav_url, tts_fallback
