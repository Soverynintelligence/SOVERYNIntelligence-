"""
core/voice_pipeline.py
Conversational voice pipeline for SOVERYN.

Flow:
  audio bytes → Whisper STT → stream agent tokens → sentence queue → Kokoro TTS → SSE

Key design: TTS starts on the FIRST complete sentence (~55 chars) as tokens arrive.
            Next chunk is pre-generated while the current one plays, eliminating gaps.

Each SSE event:
  {"type": "transcript",  "text": "..."}
  {"type": "agent_text",  "text": "..."}
  {"type": "tts",         "url": "/static/...", "text": "...", "index": 0}
  {"type": "done"}
  {"type": "error",       "text": "..."}
"""

import re
import json
import queue
import threading
import asyncio
from pathlib import Path
from datetime import datetime

BASE_DIR   = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

_SENTENCE_END = re.compile(r'^(.{55,}?[.!?])\s+')
_STOP_SENTINEL = object()


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _clean_for_tts(text: str) -> str:
    """Strip markdown and artifacts that sound bad when spoken."""
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # links → label
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def voice_pipeline(audio_bytes: bytes, agent_name: str, agent_loop,
                   interrupt: threading.Event, conversation_history: list):
    """
    Generator — yields SSE-formatted strings.
    Caller wraps in Flask Response(stream_with_context(...)).

    interrupt: threading.Event — set when user starts speaking again.
    """
    # ── Step 1: STT ──────────────────────────────────────────────────
    try:
        from sovereign_stt import transcribe_bytes
        transcript = transcribe_bytes(audio_bytes)
    except Exception as e:
        yield _sse({"type": "error", "text": f"STT error: {e}"})
        return

    if not transcript or not transcript.strip():
        yield _sse({"type": "error", "text": "Could not transcribe — please speak clearly."})
        return

    yield _sse({"type": "transcript", "text": transcript.strip()})

    if interrupt.is_set():
        return

    # ── Step 2: Stream agent → sentence queue ────────────────────────
    # sentence_q receives either a sentence string or _STOP_SENTINEL
    sentence_q: queue.Queue = queue.Queue()
    full_response_holder = [None]   # [str]
    has_tool_holder       = [False]  # [bool]
    agent_error_holder    = [None]   # [Exception]

    def _run_agent():
        try:
            loop = asyncio.new_event_loop()
            cleaned, has_tool = loop.run_until_complete(
                agent_loop.stream_voice(
                    transcript.strip(),
                    conversation_history=conversation_history[-14:],
                    on_sentence=lambda s: sentence_q.put(s),
                    temperature=1.0,
                    max_tokens=350,
                )
            )
            loop.close()
            full_response_holder[0] = cleaned
            has_tool_holder[0] = has_tool
        except Exception as e:
            agent_error_holder[0] = e
        finally:
            sentence_q.put(_STOP_SENTINEL)

    agent_thread = threading.Thread(target=_run_agent, daemon=True)
    agent_thread.start()

    # ── Step 3: TTS with pre-generation ─────────────────────────────
    # Audio is played client-side via SSE tts events.
    # Pre-generation: generate next chunk while the current one plays in browser.
    # We estimate playback duration from WAV frames/rate to sleep and overlap generation.
    # Pattern: generate[N] → yield SSE[N] → sleep(duration[N]) & generate[N+1] → ...

    import time
    import soundfile as _sf
    from sovereign_tts import speak as tts_speak, detect_emotion, AGENT_SPEED, DEFAULT_SPEED

    chunk_index = 0
    pending_file = None   # (fpath, fname, chunk_text, duration_s)

    def _audio_duration(fpath: str) -> float:
        """Return WAV duration in seconds, default 2.5s on error."""
        try:
            info = _sf.info(fpath)
            return info.frames / info.samplerate
        except Exception:
            return 2.5

    def _generate_chunk(text: str) -> tuple:
        """Generate a TTS file. Returns (fpath, fname, duration) or (None, None, 0)."""
        if not text.strip() or interrupt.is_set():
            return None, None, 0
        clean = _clean_for_tts(text)
        if not clean:
            return None, None, 0
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        fname = f"voice_{agent_name}_{ts}.wav"
        fpath = str(STATIC_DIR / fname)
        try:
            emotion = detect_emotion(clean)
            result = tts_speak(clean, agent=agent_name, output_path=fpath, emotion=emotion)
            if result:
                dur = _audio_duration(fpath)
                return fpath, fname, dur
        except Exception as e:
            print(f"[Voice] TTS error: {e}")
        return None, None, 0

    # Drain the sentence queue, pre-generating and streaming
    done = False

    while not done:
        if interrupt.is_set():
            break

        # Get next sentence from queue (block up to 30s)
        try:
            item = sentence_q.get(timeout=30)
        except queue.Empty:
            break

        if item is _STOP_SENTINEL:
            done = True
            item = None

        if agent_error_holder[0]:
            yield _sse({"type": "error", "text": f"Agent error: {agent_error_holder[0]}"})
            return

        # If we have a pending pre-generated file, emit it then pre-generate the next
        if pending_file:
            fpath, fname, chunk_text, duration = pending_file
            pending_file = None

            # Emit SSE so client starts playing this chunk
            if not interrupt.is_set():
                yield _sse({
                    "type":  "tts",
                    "url":   f"/static/{fname}",
                    "text":  chunk_text,
                    "index": chunk_index,
                })
                chunk_index += 1

            # While client plays current chunk, generate the next one in parallel
            gen_result = [None, None, 0]
            next_thread = None
            if item is not None and not interrupt.is_set():
                def _gen_next(t=item):
                    gen_result[0], gen_result[1], gen_result[2] = _generate_chunk(t)
                next_thread = threading.Thread(target=_gen_next, daemon=True)
                next_thread.start()

            # Sleep for ~audio duration so next emit is timed for seamless playback
            if duration > 0 and not interrupt.is_set():
                deadline = time.time() + duration
                while time.time() < deadline and not interrupt.is_set():
                    time.sleep(0.05)

            if next_thread is not None:
                next_thread.join(timeout=15)
                if gen_result[0]:
                    pending_file = (gen_result[0], gen_result[1], item, gen_result[2])

        elif item is not None:
            # No pending file — generate first chunk synchronously
            fpath, fname, dur = _generate_chunk(item)
            if fpath:
                pending_file = (fpath, fname, item, dur)

    # Emit any final pending chunk
    if pending_file and not interrupt.is_set():
        fpath, fname, chunk_text, _ = pending_file
        yield _sse({
            "type":  "tts",
            "url":   f"/static/{fname}",
            "text":  chunk_text,
            "index": chunk_index,
        })

    # Emit full agent_text after TTS so client can display it
    if full_response_holder[0] and not interrupt.is_set():
        yield _sse({"type": "agent_text", "text": full_response_holder[0].strip()})

    # If tools were called, execute them silently in the background.
    # The spoken response was already delivered — don't re-run inference.
    if has_tool_holder[0] and not interrupt.is_set():
        def _run_tools_silent():
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    agent_loop.process_message(
                        transcript.strip(),
                        conversation_history=conversation_history[-14:],
                        temperature=1.0,
                        max_tokens=200,
                    )
                )
                loop.close()
            except Exception as e:
                print(f"[Voice] Silent tool execution error: {e}")
        threading.Thread(target=_run_tools_silent, daemon=True).start()

    if not interrupt.is_set():
        yield _sse({"type": "done"})
