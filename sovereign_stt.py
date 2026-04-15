"""
sovereign_stt.py
SOVERYN Voice Input - Faster Whisper STT
Loads Whisper once at startup, keeps it hot.

Usage:
    from sovereign_stt import transcribe_audio_file, transcribe_bytes
    
    text = transcribe_audio_file("recording.wav")
    text = transcribe_bytes(audio_bytes)
"""

import io
import os
import threading
import tempfile
from pathlib import Path

# ============================================================
# ENGINE - LOADED ONCE
# ============================================================

_model = None
_model_lock = threading.Lock()
_model_ready = False

MODEL_SIZE = "large-v3"
DEVICE = "cuda"
DEVICE_INDEX = 1  # Use GPU 1 - GPU 0 is reserved for Magnum
COMPUTE_TYPE = "float16"


def _load_model():
    global _model, _model_ready
    with _model_lock:
        if _model_ready:
            return _model
        try:
            print(f"SOVEREIGN STT: Loading Whisper {MODEL_SIZE}...")
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_SIZE, device=DEVICE, device_index=DEVICE_INDEX, compute_type=COMPUTE_TYPE)
            _model_ready = True
            print("SOVEREIGN STT: Whisper ready")
        except Exception as e:
            print(f"SOVEREIGN STT: Failed to load Whisper: {e}")
            _model = None
            _model_ready = False
    return _model


def get_model():
    global _model_ready
    if not _model_ready:
        return _load_model()
    return _model


def preload():
    """Preload Whisper at startup. Call from app.py."""
    return _load_model()


def is_ready() -> bool:
    return _model_ready


# ============================================================
# TRANSCRIPTION
# ============================================================

def transcribe_audio_file(filepath: str, language: str = "en") -> str:
    """
    Transcribe audio from a file path.
    Returns transcribed text string.
    """
    model = get_model()
    if model is None:
        return ""

    try:
        segments, info = model.transcribe(
            filepath,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        text = " ".join(seg.text.strip() for seg in segments)
        print(f"SOVEREIGN STT: Transcribed: '{text}'")
        return text.strip()
    except Exception as e:
        print(f"SOVEREIGN STT: Transcription error: {e}")
        return ""


def transcribe_bytes(audio_bytes: bytes, language: str = "en") -> str:
    """
    Transcribe audio from raw bytes (WAV/WebM/etc).
    Saves to temp file then transcribes.
    Returns transcribed text string.
    """
    if not audio_bytes:
        return ""

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        text = transcribe_audio_file(tmp_path, language=language)
        os.unlink(tmp_path)
        return text
    except Exception as e:
        print(f"SOVEREIGN STT: Bytes transcription error: {e}")
        return ""


if __name__ == "__main__":
    print("SOVEREIGN STT - Test Mode")
    model = preload()
    if model:
        print("Whisper loaded successfully")
    else:
        print("Failed to load Whisper")
