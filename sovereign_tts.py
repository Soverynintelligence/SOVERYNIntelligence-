"""
sovereign_tts.py
SOVERYN Voice Output - Kokoro TTS
Fast, low-latency TTS on cuda:1 (Quadro RTX 8000).

Usage:
    from sovereign_tts import speak, speak_async, preload, is_ready
"""

import re
import threading
import queue
import soundfile as sf
from datetime import datetime
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

# Kokoro voice per agent
# Available voices: af_bella, af_heart, af_nicole, af_sky, af_sarah,
#                   am_adam, am_michael, bf_alice, bf_emma, bm_george
AGENT_VOICES = {
    "aetheria": "bf_alice:6+af_heart:4",
    "vett":     "am_michael",
    "tinker":   "bm_george",
    "ares":     "am_adam",
    "scout":    "am_michael",
}
DEFAULT_VOICE = "af_bella"

AGENT_SPEED = {
    "aetheria": 1.2,
    "vett":     1.0,
    "tinker":   1.05,
    "ares":     0.95,
    "scout":    1.0,
}
DEFAULT_SPEED = 1.0

# ============================================================
# EMOTION DETECTION
# Reads text cues and returns a speed modifier for natural prosody.
# Keeps Kokoro feeling conversational rather than flat.
# ============================================================

_EXCITED    = re.compile(r'[!]{1,}|(?:^|\s)(yes|exactly|absolutely|incredible|love|amazing|perfect|let\'s go|got it)(?:\s|$|[!,.])', re.I)
_QUESTION   = re.compile(r'\?')
_REFLECTIVE = re.compile(r'(?:^|\s)(hmm|i see|interesting|curious|wonder|think|feel|sense|perhaps|maybe|actually)(?:\s|$|[,.])', re.I)
_DIRECT     = re.compile(r'^[^,]{0,60}[.!]$')  # short punchy sentence


def detect_emotion(text: str) -> str:
    """
    Returns an emotion tag: 'excited', 'question', 'reflective', 'direct', or 'neutral'.
    Used to modulate TTS speed for more natural delivery.
    """
    t = text.strip()
    if _EXCITED.search(t):
        return 'excited'
    if _QUESTION.search(t):
        return 'question'
    if _REFLECTIVE.search(t):
        return 'reflective'
    if _DIRECT.match(t):
        return 'direct'
    return 'neutral'


# Speed delta per emotion (added to base agent speed)
_EMOTION_SPEED_DELTA = {
    'excited':    +0.12,
    'question':   -0.06,
    'reflective': -0.10,
    'direct':     +0.05,
    'neutral':     0.0,
}

# ============================================================
# ENGINE — LOADED ONCE
# ============================================================

_pipeline = None
_engine_lock = threading.Lock()
_engine_ready = False


def _load_engine():
    global _pipeline, _engine_ready
    with _engine_lock:
        if _engine_ready:
            return _pipeline
        try:
            print("SOVEREIGN TTS: Loading Kokoro on cuda:1...")
            from kokoro import KPipeline
            _pipeline = KPipeline(lang_code='a', device='cuda:1')
            _engine_ready = True
            print("SOVEREIGN TTS: Kokoro ready on cuda:1")
        except Exception as e:
            print(f"SOVEREIGN TTS: Failed to load engine: {e}")
            _pipeline = None
            _engine_ready = False
    return _pipeline


def get_engine():
    if not _engine_ready:
        return _load_engine()
    return _pipeline


# ============================================================
# ASYNC SPEECH QUEUE
# ============================================================

_speech_queue = queue.Queue()
_speech_thread = None


def _speech_worker():
    while True:
        try:
            item = _speech_queue.get(timeout=1)
            if item is None:
                break
            text, agent, output_path = item
            _generate_speech(text, agent, output_path)
            _speech_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"SOVEREIGN TTS: Worker error: {e}")


def _start_speech_worker():
    global _speech_thread
    if _speech_thread is None or not _speech_thread.is_alive():
        _speech_thread = threading.Thread(target=_speech_worker, daemon=True)
        _speech_thread.start()


# ============================================================
# CORE GENERATION
# ============================================================

def _resolve_voice(voice_spec: str):
    """
    Resolve a voice spec to a tensor.
    Supports blends like 'af_bella:7+bf_emma:3' or plain 'af_bella'.
    Returns a torch tensor or the plain string (fallback to Kokoro default loading).
    """
    if '+' not in voice_spec and ':' not in voice_spec:
        return voice_spec  # plain voice name — let Kokoro handle it

    import torch
    import re as _re
    from pathlib import Path

    # Find the Kokoro voices directory
    cache_base = Path.home() / '.cache' / 'huggingface' / 'hub'
    snap_dirs = list((cache_base / 'models--hexgrad--Kokoro-82M' / 'snapshots').iterdir())
    if not snap_dirs:
        return voice_spec.split(':')[0]  # fallback to first voice name
    voices_dir = snap_dirs[0] / 'voices'

    parts = voice_spec.split('+')
    mixed = None
    total_weight = 0.0
    for part in parts:
        if ':' in part:
            name, weight = part.rsplit(':', 1)
            weight = float(weight)
        else:
            name, weight = part, 1.0
        vpath = voices_dir / f'{name.strip()}.pt'
        if not vpath.exists():
            print(f"SOVEREIGN TTS: Voice '{name}' not found at {vpath}, skipping")
            continue
        vtensor = torch.load(vpath, weights_only=True)
        mixed = vtensor * weight if mixed is None else mixed + vtensor * weight
        total_weight += weight

    if mixed is None:
        return voice_spec.split(':')[0]
    return mixed / total_weight  # normalize


def _generate_speech(text: str, agent: str = "aetheria", output_path: str = None,
                     emotion: str = 'neutral') -> str:
    import numpy as np

    pipe = get_engine()
    if pipe is None:
        print("SOVEREIGN TTS: Engine not available")
        return None

    voice_spec = AGENT_VOICES.get(agent.lower(), DEFAULT_VOICE)
    voice = _resolve_voice(voice_spec)
    base_speed = AGENT_SPEED.get(agent.lower(), DEFAULT_SPEED)
    delta = _EMOTION_SPEED_DELTA.get(emotion, 0.0)
    speed = round(max(0.7, min(1.6, base_speed + delta)), 3)

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(STATIC_DIR / f"speech_{agent}_{ts}.wav")

    try:
        parts = []
        for gs, ps, audio in pipe(text, voice=voice, speed=speed):
            parts.append(audio)

        if parts:
            combined = np.concatenate(parts)
            sf.write(output_path, combined, 24000)
            print(f"SOVEREIGN TTS: [{agent}] saved to {output_path}")
            return output_path
        return None

    except Exception as e:
        print(f"SOVEREIGN TTS: Generation error: {e}")
        return None


# ============================================================
# PUBLIC API
# ============================================================

def speak(text: str, agent: str = "aetheria", output_path: str = None,
          emotion: str = 'neutral') -> str:
    """Generate speech synchronously. Returns path to WAV file."""
    if not text or not text.strip():
        return None
    return _generate_speech(text, agent, output_path, emotion=emotion)


def speak_async(text: str, agent: str = "aetheria", output_path: str = None):
    """Queue speech generation. Returns immediately."""
    if not text or not text.strip():
        return
    _start_speech_worker()
    _speech_queue.put((text, agent, output_path))


def speak_response(text: str, agent: str = "aetheria"):
    """Speak an agent response asynchronously."""
    speak_async(text, agent)


def preload():
    """Preload TTS engine at startup."""
    _start_speech_worker()
    return _load_engine()


def is_ready() -> bool:
    return _engine_ready


if __name__ == "__main__":
    print("SOVEREIGN TTS - Kokoro Startup Test")
    engine = preload()
    if engine:
        path = speak("Sovereign voice synthesis is online.", agent="aetheria")
        print(f"Output: {path}")
    else:
        print("Engine failed to load")
