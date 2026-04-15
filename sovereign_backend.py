"""VISION
SOVEREIGN BACKEND - llama.cpp Edition with VISION
Pure sovereignty. No transformers. No upgrade nightmares.
Fast, stable inference with multimodal support.

SOVERYN 2.1 Changes:
- Models shared by filename (V.E.T.T. + Tinker no longer duplicate 7B in VRAM)
- Model unloading support (free VRAM on demand)
- LRU cache with configurable VRAM budget
- unload_all() for loading large models like 72B
- Cleaned up vision projectors - only active models included
- Gemma removed from vision projectors (not in active use)
- Default max_tokens lowered to 500 for better 72B performance

SOVERYN 2.2 Changes:
- Added inference lock to prevent race condition on simultaneous requests
  (double-send before response would cause lock-up / error state)
"""
# Some GGUFs embed chat templates that use {% continue %} / {% break %},
# which standard Jinja2 doesn't support. Patch the Environment globally
# to enable loop controls so llama-cpp-python can parse these templates.
try:
    import jinja2 as _jinja2
    _orig_env_init = _jinja2.Environment.__init__
    def _patched_env_init(self, *a, **kw):
        exts = list(kw.pop('extensions', []))
        if 'jinja2.ext.loopcontrols' not in exts:
            exts.append('jinja2.ext.loopcontrols')
        kw['extensions'] = exts
        _orig_env_init(self, *a, **kw)
    _jinja2.Environment.__init__ = _patched_env_init
except Exception as _e:
    print(f"[Backend] Jinja2 loop-controls patch failed (non-fatal): {_e}")

from mmproj_scanner import scan_vision_projectors, _chat_handler_type
from llama_cpp import Llama, LLAMA_SPLIT_MODE_LAYER, LLAMA_SPLIT_MODE_NONE
from llama_cpp.llama_chat_format import Llava15ChatHandler, Qwen25VLChatHandler, Llama3VisionAlphaChatHandler
from typing import Optional, Dict
import os
import gc
import threading
import re


# ============================================================
# VRAM BUDGET CONFIGURATION
# RTX Pro 5000 Blackwell = 47.5GB physical
# Leave ~3.5GB headroom for system/context overhead
# ============================================================
VRAM_BUDGET_BY_GPU = {
    0: 46,  # RTX Pro 5000 Blackwell — CUDA 0 (nvidia-smi GPU 0, vertical riser)
    1: 44,  # Quadro RTX 8000 — CUDA 1 (Scout dedicated, 48GB standalone)
    2: 44,  # Quadro RTX 8000 — CUDA 2 (Vett/Tinker/Ares/Vision LRU, 48GB standalone)
}

# Approximate VRAM cost per model (GB)
MODEL_VRAM_ESTIMATES = {
    "Qwen2.5-32B-Instruct-Q4_K_M.gguf":       22,
    "Qwen2.5-7B-Instruct-Q4_K_M.gguf":         5,
    "IQuest-Coder-V1-40B-Instruct-IQ4_XS.gguf": 22,
    "Midnight-Miqu-70B-v1.5.IQ4_XS.gguf":     38,
    "Qwen2.5-7B-Instruct-f16.gguf":            15,
    "Qwen2-VL-7B-Instruct-Q4_K_M.gguf":         6,
    "Qwen2.5-VL-72B-Instruct.IQ4_XS.gguf":     38,
    "dolphin-2.9.1-llama-3-70b.IQ4_XS.gguf":    38,
    "Hermes-3-Llama-3.1-70B-IQ4_XS.gguf":       38,
    "Qwen2-VL-72B-Instruct-abliterated.Q3_K_L.gguf": 37,
    "Gemma-3-27b-it-Uncensored-HERETIC-Gemini-Deep-Reasoning.Q8_0.gguf":  28,
    "Huihui-Qwen3-VL-30B-A3B-Instruct-abliterated-Q8_0.gguf": 33,
    "Midnight-Miqu-103B-v1.5.Q4_K_M.gguf":57,
    "dolphin-2.9.2-qwen2-72b.i1-Q2_K.gguf":38,
    "magnum-v4-72b-Q4_K_S.gguf": 40,
    "magnum-v4-72b-Q5_K_M-merged.gguf": 54,
    "Midnight-Miqu-103B-v1.5.Q4_K_M.gguf":65,
    "miqu-1-70b-Requant-b2035-iMat-c32_ch400-Q4_K_S.gguf":38,
    "Llama-3.1-Nemotron-70B-Instruct-HF-abliterated-Q4_0.gguf":38, 
    "Phi-3.5-mini-instruct_Uncensored-Q4_K_M.gguf": 3,
    "gemma-3-4b-instruct-psych8k-q4_k_m.gguf": 3,
    "DeepSeek-R1-Distill-Qwen-32B-IQ4_NL.gguf": 8,
    "L3-8B-Stheno-v3.2-Q4_K_M.gguf": 5,
    "LFM2-1.2B-RAG-Q5_K_M.gguf": 1,
    "DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf": 8,
    "Llama-3.3-70B-Instruct-IQ4_XS.gguf":36,
    "Llama-3.3-70B-Instruct-abliterated-Q4_K_M.gguf":41,
    "Llama-3-70B-Synthia-v3.5.Q4_K_M.gguf":42,
    "SentientAGI_Dobby-Unhinged-Llama-3.3-70B-Q4_K_M.gguf":39,
    "Llama-3.1-Nemotron-lorablated-70B.Q4_K_M.gguf":42,
    "L3.1-70B-Euryale-v2.2-Q4_K_M.gguf":42,  
    "gemma-3-27b-it-heretic-v2.Q8_0.gguf":30,
    "Qwen_Qwen3.5-35B-A3B-Q8_0.gguf":30,
    "lzlv-limarpv3-l2-70b.i1-Q4_K_M.gguf":38,
    "Llama-3.1-Nemotron-lorablated-70B.i1-Q5_K_M.gguf":48,
    "Llama-3.1-Nemotron-lorablated-70B.i1-Q4_K_M.gguf":42,
    "L3.3-MS-Nevoria-70b-Q4_K_M.gguf":43,
    "NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_M-00001-of-00003.gguf": 70,
    "Mistral-Small-4-119B-2603-UD-Q4_K_M-00001-of-00003.gguf": 70,  # ~70GB Q4_K_M across Blackwell+Quadro
    "InternVL3-78B-Instruct-UD-Q4_K_XL.gguf": 47,
    "Llama-4-Scout-17B-16E-Instruct-Q5_K_M-00001-of-00002.gguf": 76,
    "Llama-3.3-Nemotron-Super-49B-v1.Q6_K.gguf": 38,
    "Llama-3_3-Nemotron-Super-49B-v1_5.Q6_K.gguf": 38,
    "TheDrummer_Valkyrie-49B-v2.1-Q6_K_L.gguf": 40,
    "Nemotron-Cascade-2-30B-A3B.i1-Q6_K.gguf":        24,
    "Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf":          22,
    "Foundation-Sec-8B-Instruct-Q4_K_M.gguf":           5,
    "Qwen3-14B-BaronLLM-v2-Q4_0.gguf":                 9,
    "Qwen3-72B-Instruct-2.i1-Q5_K_M.gguf":            41,
    "DeepSeek-R1-Distill-Qwen-32B-IQ4_NL.gguf":        20,
    "gemma-4-E4B-it-Q8_0.gguf":                          8,
    "gemma-4-26B-A4B-it-UD-Q8_K_XL.gguf":              28,
    "google_gemma-4-31B-it-Q8_0.gguf":                  33,
    "gemma-4-31B-it-abliterated.Q8_0.gguf":             31,
    "Mistral-Small-4-119B-2603.Q4_K_M.gguf":           72,  # single-file Q4_K_M, split across Blackwell+Quadro2
    "DeepSeek-R1-Distill-Llama-70B-Q4_K_M.gguf":       40,
    "L3.3-GeneticLemonade-Unleashed-70B.i1-Q4_K_M.gguf": 40,
    "Qwen3-Coder-Next-Q4_K_M.gguf":                    46,

}
DEFAULT_VRAM_ESTIMATE = 8  # GB fallback for unknown models

# ============================================================
# INFERENCE LOCK
# Prevents race condition when multiple requests arrive
# before the model finishes responding.
# All inference calls queue here and execute one at a time.
# _user_waiting: set True when a user (non-heartbeat) request is queued.
# Heartbeat checks this and skips its cycle rather than blocking the user.
# ============================================================
_inference_lock = threading.Lock()
_user_waiting = False


class SovereignLLM:
    """llama.cpp model wrapper - sovereign and stable with vision support"""
    def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = .75,
        top_p: float = 0.95,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        image_data: Optional[str] = None,
        add_think_prefix: bool = True
    ):
        """Stream tokens as they generate"""

        # Gemma 4 and other models with chat_format=None use the embedded GGUF Jinja template.
        # Parse the pre-formatted prompt back into messages and use create_chat_completion
        # so llama-cpp-python applies the model's own Jinja template (equivalent to --jinja).
        if self.chat_format is None and not image_data:
            _STOP_MARKERS = ('[YOUR NOTES]', '[PINNED MEMORY', '[TODAY\'S LOG]', '[TEAM INTEL',
                             '[TOOL RESULT:', '\nJon:', '\nUser:', '\n**Jon', '\nAETHERIA', '\n**Aetheria')
            # Parse Gemma-style pre-formatted prompt into message list
            messages = []
            if '<start_of_turn>' in prompt:
                parts = re.split(r'<start_of_turn>(user|model)\n?', prompt)
                i = 1
                while i + 1 < len(parts):
                    role = parts[i]
                    content = re.sub(r'<end_of_turn>.*', '', parts[i+1], flags=re.DOTALL).strip()
                    if content:
                        messages.append({'role': 'user' if role == 'user' else 'assistant', 'content': content})
                    i += 2
            if messages:
                # enable_thinking controls Gemma 4's reasoning channel.
                # False = clean responses, no ghost channel overhead (default).
                # True = model reasons before responding (~200-400 extra tokens, routed to thinking tab).
                # Only enable via explicit think_mode — burning tokens on thinking by default causes
                # degenerate loops when the reasoning channel hits max_tokens before the response starts.
                # chat_template_kwargs (enable_thinking) not supported until llama-cpp-python 0.3.x+
                # Ghost thought channel (<|channel>thought\n<channel|>) is stripped in post-processing.
                stream = self.model.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    min_p=min_p,
                    repeat_penalty=1.0,  # Gemma 4: repeat_penalty >1.0 triggers desperation loops
                    stop=["<end_of_turn>", "<start_of_turn>user", "<start_of_turn>model", "<turn|>"],
                    stream=True,
                )
                _full = ''
                _gemma_recent: list = []
                for chunk in stream:
                    token = chunk['choices'][0]['delta'].get('content', '') or ''
                    if not token:
                        continue
                    _full += token
                    if any(m in _full[-60:] for m in _STOP_MARKERS):
                        break
                    _gemma_recent.append(token)
                    if len(_gemma_recent) > 30:
                        _gemma_recent.pop(0)
                    if len(_gemma_recent) >= 20 and len(set(_gemma_recent[-20:])) == 1:
                        print(f"SOVEREIGN: Gemma repetition loop ('{token}' x20) — stopping", flush=True)
                        break
                    if len(_full) > 60:
                        tail = _full[-80:]
                        for pl in range(2, 9):
                            phrase = tail[-pl:]
                            if phrase.strip() and tail.count(phrase) >= 6:
                                print(f"SOVEREIGN: Gemma phrase loop ('{phrase.strip()}') — stopping", flush=True)
                                _full = _full[:len(_full) - len(tail) + tail.find(phrase * 3) + pl].rstrip() if phrase * 3 in tail else _full
                                break
            else:
                # Fallback for non-Gemma None-format models
                raw_stream = self.model.create_completion(
                    prompt, max_tokens=max_tokens, temperature=temperature,
                    top_p=top_p, repeat_penalty=1.0, top_k=top_k, min_p=min_p,
                    stop=["<end_of_turn>", "<start_of_turn>user", "<|end|>", "<turn|>"], stream=True
                )
                _full = ''
                for chunk in raw_stream:
                    token = chunk['choices'][0].get('text', '')
                    if not token:
                        continue
                    _full += token
                    if any(m in _full[-60:] for m in _STOP_MARKERS):
                        break
            # Strip internal thought annotations and leftover Gemma tokens
            _full = re.sub(r'---\s*[-*`]*\s*\*?\*?[Tt]hought\*?\*?:?.*?(?=\n[^-\s]|\Z)', '', _full, flags=re.DOTALL).strip()
            # Strip <channel|>...</channel|> thinking blocks (Claude Opus distill uses these)
            _full = re.sub(r'<channel\|>.*?<\|channel>', '', _full, flags=re.DOTALL | re.IGNORECASE)
            _full = re.sub(r'<\|channel>.*?<channel\|>', '', _full, flags=re.DOTALL | re.IGNORECASE)
            _full = re.sub(r'<channel\|>.*', '', _full, flags=re.DOTALL).strip()  # unclosed channel block — strip to end
            _full = re.sub(r'\*\*Analysis:\*\*.*', '', _full, flags=re.DOTALL).strip()
            _full = re.sub(r'\*\*Note:\*\*.*', '', _full, flags=re.DOTALL).strip()
            _full = re.sub(r'<end_of_turn>.*', '', _full, flags=re.DOTALL).strip()
            # Drop degenerate responses — three detectors:
            # 1. Period detector (catches "nessnessnessness..." perfect-cycle loops)
            # 2. Character n-gram (catches near-period loops)
            # 3. Sentence/phrase repetition (catches "Could you clarify?..." x150)
            _t = _full.strip()
            _degen = False
            # Period detector
            if len(_t) >= 20:
                for _p in range(2, min(24, len(_t)//2)):
                    _matches = sum(1 for _i in range(_p, len(_t)) if _t[_i] == _t[_i-_p])
                    if _matches / (len(_t) - _p) >= 0.85:
                        _degen = True; break
            # Char n-gram — strip list/comment prefixes per line so bullet formatting
            # doesn't inflate n-gram scores (e.g. "- (//) " repeating legitimately)
            if not _degen and len(_t) >= 40:
                import re as _re_ng
                _t_ng = _re_ng.sub(r'(?m)^\s*[-*>]+\s*(\(//\)|//|#)?\s*', '', _t)
                for _n in (4, 6, 8):
                    _ngs = [_t_ng[i:i+_n] for i in range(len(_t_ng)-_n)]
                    if _ngs:
                        _top = max(set(_ngs), key=_ngs.count)
                        if _ngs.count(_top) / len(_ngs) > 0.35:
                            _degen = True; break
            # Sentence repetition
            if not _degen:
                import re as _re_b
                _sents = [s.strip() for s in _re_b.split(r'[.!?\n]+', _t) if len(s.strip()) > 10]
                if len(_sents) >= 4:
                    _top_s = max(set(_sents), key=_sents.count)
                    if _sents.count(_top_s) / len(_sents) > 0.35:
                        _degen = True
            if _degen:
                print(f"SOVEREIGN: [backend] Degenerate response detected — discarding. Preview: {repr(_t[:120])}", flush=True)
                yield ''
                return
            yield _full
            return

        system_match = re.search(r'<\|im_start\|>system\s*(.*?)<\|im_end\|>', prompt, re.DOTALL)
        user_match   = re.search(r'<\|im_start\|>user\s*(.*?)<\|im_end\|>',   prompt, re.DOTALL)

        # Fallback: Llama-3 format (<|start_header_id|>...<|eot_id|>)
        if not system_match:
            system_match = re.search(r'<\|start_header_id\|>system<\|end_header_id\|>\s*(.*?)<\|eot_id\|>', prompt, re.DOTALL)
        if not user_match:
            user_match = re.search(r'<\|start_header_id\|>user<\|end_header_id\|>\s*(.*?)<\|eot_id\|>', prompt, re.DOTALL)

        system_content = system_match.group(1).strip() if system_match else ""
        user_content   = user_match.group(1).strip()   if user_match   else prompt.strip()

        # mistral-instruct formatter drops system role — embed system in the first user message
        if self.chat_format == "mistral-instruct" and system_content:
            user_content = f"{system_content}\n\n{user_content}"
            system_content = ""

        messages = []
        if system_content:
            messages.append({"role": "system", "content": system_content})

        if self.has_vision and image_data:
            messages.append({"role": "user", "content": [
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{image_data}'}},
                {'type': 'text', 'text': user_content}
            ]})
            # Cap vision inference — image tokens consume large context, loops fill remaining tokens
            vision_max_tokens = min(max_tokens, 350)
            response = self.model.create_chat_completion(
                messages=messages,
                max_tokens=vision_max_tokens,
                temperature=temperature,
                top_p=top_p,
                repeat_penalty=1.15,  # Higher repeat penalty for vision to suppress loops
                top_k=top_k,
                min_p=min_p,
                stream=False
            )
            result_text = response['choices'][0]['message']['content'] or ""
            # Strip repetition from non-streaming result
            for pl in range(2, 9):
                if len(result_text) > pl * 6:
                    tail = result_text[-pl*8:]
                    phrase = tail[-pl:]
                    if phrase.strip() and tail.count(phrase) >= 6:
                        # Truncate at first repeat
                        first_repeat = result_text.find(phrase * 3)
                        if first_repeat > 0:
                            result_text = result_text[:first_repeat + pl].rstrip()
                            print(f"SOVEREIGN: Vision repetition stripped ('{phrase.strip()}')", flush=True)
                        break
            yield result_text
            return

        messages.append({"role": "user", "content": user_content})
        if add_think_prefix:
            messages.append({"role": "assistant", "content": "<think>"})

        stream = self.model.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            top_k=top_k,
            min_p=min_p,
            presence_penalty=0.05,
            frequency_penalty=0.05,
            stop=self.stop_tokens or None,
            stream=True
        )

        _STRIP_TOKENS = {'<__padding>', '<|im_end|>', '<|eot_id|>', '<|end_of_text|>', '<end_of_text>'}
        _accumulated = ''
        _recent_tokens: list = []
        _STOP_MARKERS = ('[YOUR NOTES]', '[PINNED MEMORY', '[TODAY\'S LOG]', '[TEAM INTEL', '[TOOL RESULT:', '\nJon:', '\nUser:', '\n**Jon', '\nAETHERIA', '\n**Aetheria')
        try:
            for chunk in stream:
                delta = chunk['choices'][0].get('delta', {})
                # llama.cpp separates <think> blocks into reasoning_content in newer builds.
                # Read content first; fall back to reasoning_content so we never silently drop tokens.
                token = delta.get('content', '') or delta.get('reasoning_content', '')
                if not token or token in _STRIP_TOKENS:
                    continue
                _accumulated += token
                # Stop if model starts echoing injected context back
                if any(_accumulated.rstrip().endswith(m) or m in _accumulated[-60:] for m in _STOP_MARKERS):
                    break
                # Repetition loop detection
                _recent_tokens.append(token)
                if len(_recent_tokens) > 30:
                    _recent_tokens.pop(0)
                # Single-token loop: last 20 tokens all identical
                if len(_recent_tokens) >= 20 and len(set(_recent_tokens[-20:])) == 1:
                    print(f"SOVEREIGN: Repetition loop detected (token '{token}' x20) — stopping", flush=True)
                    return
                # Phrase-level loop: short phrase repeating 6+ times in tail
                if len(_accumulated) > 60:
                    tail = _accumulated[-80:]
                    for pl in range(2, 9):
                        phrase = tail[-pl:]
                        if phrase.strip() and tail.count(phrase) >= 6:
                            print(f"SOVEREIGN: Phrase repetition loop ('{phrase.strip()}') — stopping", flush=True)
                            return
                yield token
        except IndexError as e:
            # KV cache corruption — reset model state and bail cleanly
            print(f"SOVEREIGN: KV cache IndexError — resetting model state. ({e})", flush=True)
            try:
                self.model.reset()
            except Exception:
                pass
            return

    def __init__(
        self,
        model_path: str,
        n_gpu_layers: int = -1,
        n_ctx: int = 2048,
        mmproj_path: Optional[str] = None,
        main_gpu: int = 0,
        tensor_split: Optional[list] = None 
    ):
        print(f"SOVEREIGN: Loading {os.path.basename(model_path)}")
        print(f"SOVEREIGN: GPU layers: {n_gpu_layers}, Context: {n_ctx}")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        # Vision projector setup
        chat_handler = None
        if mmproj_path:
            if os.path.exists(mmproj_path):
                handler_type = _chat_handler_type(os.path.basename(model_path))
                if handler_type == 'qwen25vl':
                    chat_handler = Qwen25VLChatHandler(clip_model_path=mmproj_path)
                    print(f"SOVEREIGN: Vision handler: Qwen2.5-VL  →  {os.path.basename(mmproj_path)}")
                elif handler_type == 'llama3visionalpha':
                    chat_handler = Llama3VisionAlphaChatHandler(clip_model_path=mmproj_path)
                    print(f"SOVEREIGN: Vision handler: Llama 4 Scout  →  {os.path.basename(mmproj_path)}")
                else:
                    chat_handler = Llava15ChatHandler(clip_model_path=mmproj_path)
                    print(f"SOVEREIGN: Vision handler: LLaVA/Gemma  →  {os.path.basename(mmproj_path)}")
                print(f"SOVEREIGN: Vision ENABLED!")
            else:
                print(f"SOVEREIGN WARNING: mmproj not found: {mmproj_path}")
                print(f"SOVEREIGN: Falling back to text-only mode.")
        # Only split models too large for one GPU
        # Models that fit entirely on Blackwell (48GB) — no cross-GPU overhead
        single_gpu_models = [
            "Llama-3_3-Nemotron-Super-49B-v1_5.Q6_K.gguf",         # 41GB — fits on Blackwell alone
            "Llama-3.3-Nemotron-Super-49B-v1.Q6_K.gguf",
            "TheDrummer_Valkyrie-49B-v2.1-Q6_K_L.gguf",             # 40GB
            "Llama-3.1-Nemotron-lorablated-70B.i1-Q4_K_M.gguf",     # 42GB
            "L3.3-MS-Nevoria-70b-Q4_K_M.gguf",                       # 42.5GB
            "L3.3-GeneticLemonade-Unleashed-70B.i1-Q4_K_M.gguf",    # ~38GB — fits on Blackwell
            "gemma-4-26B-A4B-it-UD-Q8_K_XL.gguf",                   # ~28GB — fits on Blackwell
            "google_gemma-4-31B-it-Q8_0.gguf",                       # ~33GB — fits on Blackwell
        ]
        # (NVLink removed — Quadros are standalone 48GB each; all models assigned to main_gpu solo)
        scout_models = ["Llama-4-Scout-17B-16E-Instruct-Q5_K_M-00001-of-00002.gguf"]
        large_models = ["magnum-v4-72b-Q5_K_M-merged.gguf", "Midnight-Miqu-103B-v1.5.Q4_K_M.gguf"]
        blackwell_primary_models = ["InternVL3-78B-Instruct-UD-Q4_K_XL.gguf", "Qwen2-VL-72B-Instruct-abliterated.Q4_K_M.gguf", "Qwen2.5-VL-72B-Instruct-Q4_K_M.gguf"]
        nemotron_120b_models = ["NVIDIA-Nemotron-3-Super-120B-A12B", "huizimao_gpt-oss-120b", "gpt-oss-120b", "Mistral-Small-4-119B", "Nemotron-Super-SOVERYN-120B"]
        quadro_primary_models = []
        model_basename = os.path.basename(model_path)
        if any(lm in model_basename for lm in nemotron_120b_models):
            resolved_tensor_split = [0.58, 0.0, 0.42]  # 120B MoE — ~47GB Blackwell + ~34GB Quadro 2; leaves Quadro 1 free for other agents
        elif any(lm in model_basename for lm in scout_models):
            resolved_tensor_split = [0.0, 1.0, 0.0]  # Quadro 1 only (48GB), Blackwell reserved for Nemotron
        elif any(lm in model_basename for lm in blackwell_primary_models):
            resolved_tensor_split = [0.90, 0.10, 0.0]  # Blackwell always primary — 90% Blackwell, 10% Quadro 1
        elif any(lm in model_basename for lm in large_models):
            resolved_tensor_split = [0.0, 1.0, 0.0]  # Quadro 1 only (48GB), Blackwell reserved for Nemotron
        elif any(lm in model_basename for lm in single_gpu_models) and main_gpu == 0:
            resolved_tensor_split = None  # fits on Blackwell alone — no split overhead
        else:
            resolved_tensor_split = tensor_split or (None if main_gpu != 0 else [0.80, 0.20, 0.0])

        # Dynamic chat format by model
        chat_format_map = {
            "miqu": "mistral-instruct",
            "magnum": "mistral-instruct",
            "mistral-small": None,  # Mistral Small 4 — v3 Tekken tokenizer, use embedded GGUF template
            "gpt-oss": None,      # GPT-OSS 120B — GPT-4o tokenizer, use embedded GGUF template
            "huizimao": None,     # same model, match by vendor prefix
            "nemotron-super-soveryn-120b": "chatml",  # Nemotron-H 120B uses ChatML
            "nemotron": "llama-3",
            "llama-4": "llama-3",
            "llama-3.3": "llama-3",
            "l3.3": "llama-3",   # shorthand prefix (e.g. L3.3-GeneticLemonade)
            "llama-3.1": "llama-3",
            "foundation-sec": "llama-3",
            "iquest": "llama-3",  # IQuest-Coder — Llama-based architecture
            "gemma-4": None,     # Gemma 4 — uses <|turn> tokens, defer to embedded GGUF template
            "gemma": "gemma",
        }
        model_basename_lower = model_basename.lower()
        selected_chat_format = next(
            (fmt for key, fmt in chat_format_map.items() if key in model_basename_lower),
            "chatml"
        )

        # Models that need flash_attn disabled and standard f16 KV cache
        _no_flash_attn = {"deepseek-r1-distill"}
        use_flash_attn = not any(k in model_basename_lower for k in _no_flash_attn)
        use_kv_quant   = use_flash_attn  # disable Q8 KV cache alongside flash_attn

        # Use LAYER split mode for multi-GPU — required for split GGUFs and tensor_split to work
        use_split_mode = LLAMA_SPLIT_MODE_LAYER if resolved_tensor_split and any(v > 0 for v in resolved_tensor_split[1:]) else LLAMA_SPLIT_MODE_NONE
        self.model = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            n_ctx=n_ctx,
            flash_attn=use_flash_attn,
            chat_format=selected_chat_format,
            n_batch=1024,
            n_ubatch=512,
            type_k=8 if use_kv_quant else 1,   # q8_0 KV cache where supported
            type_v=8 if use_kv_quant else 1,
            chat_handler=chat_handler,
            verbose=True,
            main_gpu=main_gpu,
            tensor_split=resolved_tensor_split if resolved_tensor_split else None,
            split_mode=use_split_mode,
        )
     
     
        self.has_vision = chat_handler is not None
        self.model_name = os.path.basename(model_path)
        self.chat_format = selected_chat_format
        self.stop_tokens = ["<|im_end|>", "<|im_start|>"] if selected_chat_format == "chatml" else []

        print(f"SOVEREIGN: {self.model_name} loaded successfully!")
        if self.has_vision:
            print(f"SOVEREIGN: Multimodal mode active - TEXT + VISION")
        print(f"SOVEREIGN: You are sovereign.")

    def generate():
        buffer = ''
        in_think = False
        system_prompt = getattr(loop, 'system_prompt', '')
        prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{message}<|im_end|>\n<|im_start|>assistant\n"
        for token in sovereign_generate_stream(
            agent_name=agent,
            model_name=loop.model_name,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            repeat_penalty=repeat_penalty,
            top_k=0, top_p=0.95, min_p=0.06,
            gpu_device=getattr(loop, 'gpu_device', 0)
        ):
            buffer += token
            if '<think>' in buffer:
                 in_think = True
            if '</think>' in buffer:
                in_think = False
                # Strip everything up to and including </think>
                buffer = re.sub(r'<think>[\s\S]*?</think>', '', buffer)
                continue
            if not in_think:
                yield f"data: {json.dumps({'token': token})}\n\n"
        # Final clean
        clean = re.sub(r'<think>[\s\S]*?</think>', '', buffer).strip()
        yield f"data: {json.dumps({'done': True, 'full': clean})}\n\n"
        print(f"🔥 Samplers: temp={temperature}, top_k={top_k}, top_p={top_p}, min_p={min_p}")
        """Generate text with optional vision support"""

        if self.has_vision and image_data:
            response = self.model.create_chat_completion(
                messages=[{
                    'role': 'user',
                    'content': [
                        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{image_data}'}},
                        {'type': 'text', 'text': prompt}
                    ]
                }],
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                repeat_penalty=repeat_penalty,
            )
            result = response['choices'][0]['message']['content']

        else:
            # Parse the chatml prompt agent_loop builds into proper messages
            system_match = re.search(r'<\|im_start\|>system\s*(.*?)<\|im_end\|>', prompt, re.DOTALL)
            user_match   = re.search(r'<\|im_start\|>user\s*(.*?)<\|im_end\|>',   prompt, re.DOTALL)

            system_content = system_match.group(1).strip() if system_match else ""
            user_content   = user_match.group(1).strip()   if user_match   else prompt.strip()

            messages = []
            if system_content:
                messages.append({"role": "system", "content": system_content})
            messages.append({"role": "user", "content": user_content})
            messages.append({"role": "assistant", "content": "<think>"})

            response = self.model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                repeat_penalty=repeat_penalty,
                top_k=top_k,
                min_p=min_p,
                presence_penalty=0.05,
                frequency_penalty=0.05,
                stop=["<|im_end|>", "<|end|>"]
            )

            if not response or not response.get('choices'):
                return ""

            result = response['choices'][0].get('message', {}).get('content') or ""
        # Strip Gemma thinking bleed-through
        thinking_markers = [
            "**Analyzing", "**Formulating", "**Crafting", "**Refining", 
            "**Working", "**Breaking", "**Noting", "**Drafting"
        ]
        if any(marker in result for marker in thinking_markers):
            # Find where actual response starts after the thinking block
            # Look for the last ** closed section then take what follows
            cleaned = re.sub(r'\*\*[^*]+\*\*[^\n]*\n?', '', result)
            # If we still have content, use it
            if cleaned.strip():
                result = cleaned.strip()
        
        return result 
        result = result.replace('<|im_end|>', '').replace('<|im_start|>', '').replace('<|file_separator|>', '').strip()
        return result

    def unload(self):
        """Explicitly free VRAM"""
        if hasattr(self, 'model') and self.model is not None:
            del self.model
            self.model = None
            gc.collect()
            print(f"SOVEREIGN: Unloaded {self.model_name} from VRAM")


class SovereignModelManager:
    """
    Manages GGUF models with shared caching and LRU eviction.

    SOVERYN 2.1 key behaviors:
    - Cache key = model FILENAME (not agent name)
      V.E.T.T. and Tinker share one 7B instance instead of loading twice
    - LRU eviction when VRAM budget exceeded
    - Manual unload_all() / unload_model() for large model swapping
    """
    def rescan_projectors(self):
        """
        Re-scan the model directory for new mmproj files.
        Call this after dropping new models in without restarting.
        """
        self.vision_projectors = scan_vision_projectors(self.base_path)
        print(f"SOVEREIGN: Rescan complete — {len(self.vision_projectors)} vision model(s) detected.")
        return self.vision_projectors
    
    def __init__(self, base_path: str = "/home/jon-deoliveira/SOVERYN_Models/GGUF"):
        self.base_path = base_path
        self.models: Dict[str, SovereignLLM] = {}
        self._lru: list = []  # LRU tracking, most-recent at end

        # Vision projectors - ONLY active models
       
        # Auto-detect vision projectors — no manual config needed.
        # Drop a model + its mmproj in the same folder: done.
        self.vision_projectors = scan_vision_projectors(self.base_path)

        print(f"SOVEREIGN: Model manager initialized (SOVERYN 2.2)")
        print(f"SOVEREIGN: Base path: {base_path}")
        print(f"SOVEREIGN: VRAM budgets: GPU0={VRAM_BUDGET_BY_GPU[0]}GB, GPU1={VRAM_BUDGET_BY_GPU[1]}GB")
        print(f"SOVEREIGN: Model sharing ENABLED - identical models share VRAM")
        print(f"SOVEREIGN: Inference lock ENABLED - race condition protection active")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _estimated_vram_gb(self) -> float:
        total = 0
        for k in self.models:
            # Strip _text/_vision suffix to get original model name for lookup
            base_key = k.replace('_text', '').replace('_vision', '')
            total += MODEL_VRAM_ESTIMATES.get(base_key, DEFAULT_VRAM_ESTIMATE)
        return total

    def _evict_lru(self, needed_gb, main_gpu=0):
        """Unload least-recently-used models until we have enough headroom"""
        while self._lru and (self._estimated_vram_gb() + needed_gb > VRAM_BUDGET_BY_GPU.get(main_gpu, 44)):
            oldest_key = self._lru.pop(0)
            if oldest_key in self.models:
                print(f"SOVEREIGN: LRU evicting '{oldest_key}' to free VRAM...")
                self.models[oldest_key].unload()
                del self.models[oldest_key]

    def _touch(self, cache_key: str):
        """Mark model as most-recently used"""
        if cache_key in self._lru:
            self._lru.remove(cache_key)
        self._lru.append(cache_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # Agents that need larger context (tool results accumulate fast)
    _AGENT_CTX = {
        'scout': 32768,  # Inbox + research — email lists accumulate fast
        'vett': 32768,
        'aetheria': 24576,
        'tinker': 32768,  # IQuest 40B — native 128K, 32K gives code tasks real headroom
        'ares': 16384,
        'vision': 2048,
    }

    def load_model(
        self,
        agent_name: str,
        model_name: str,
        n_gpu_layers: int = -1,
        n_ctx: int = 8192,
        use_vision: bool = False,
        main_gpu: int = 0,
        tensor_split: Optional[list] = None
    ) -> SovereignLLM:
        n_ctx = self._AGENT_CTX.get(agent_name, n_ctx)
        cache_key = f"{model_name}_{'vision' if use_vision else 'text'}_gpu{main_gpu}" 
        """
        Load or retrieve cached model.
        Cache key includes vision flag - text and vision variants cached separately.
        """
        cache_key = f"{model_name}_{'vision' if use_vision else 'text'}"

        if cache_key in self.models:
            print(f"SOVEREIGN: [{agent_name}] Using cached '{model_name}' ({'vision' if use_vision else 'text'})")
            self._touch(cache_key)
            return self.models[cache_key]

        # Check VRAM budget
        needed = MODEL_VRAM_ESTIMATES.get(model_name, DEFAULT_VRAM_ESTIMATE)
        current = self._estimated_vram_gb()
        print(f"SOVEREIGN: VRAM - current: {current:.1f}GB | needed: {needed}GB | budget: {VRAM_BUDGET_BY_GPU.get(main_gpu, 44)}GB")

        if current + needed > VRAM_BUDGET_BY_GPU.get(main_gpu, 44):
            print(f"SOVEREIGN: Budget exceeded - evicting LRU models...")
            self._evict_lru(needed)

        # Build path
        model_path = os.path.join(self.base_path, model_name)

        # Only attach vision projector if use_vision=True
        mmproj_path = None
        if use_vision and model_name in self.vision_projectors:
            mmproj_filename = self.vision_projectors[model_name]
            mmproj_path = os.path.join(self.base_path, mmproj_filename)

        # Load
        print(f"SOVEREIGN: [{agent_name}] Loading '{model_name}' ({'vision' if use_vision else 'text-only'})...")
        llm = SovereignLLM(model_path, n_gpu_layers=n_gpu_layers, n_ctx=n_ctx,
                   mmproj_path=mmproj_path, main_gpu=main_gpu,
                   tensor_split=tensor_split)

        self.models[cache_key] = llm
        self._touch(cache_key)

        print(f"SOVEREIGN: VRAM after load: ~{self._estimated_vram_gb():.1f}GB")
        return llm

    def unload_model(self, model_name: str):
        """Manually unload a specific model and free VRAM"""
        if model_name in self.models:
            self.models[model_name].unload()
            del self.models[model_name]
            if model_name in self._lru:
                self._lru.remove(model_name)
            print(f"SOVEREIGN: Unloaded '{model_name}'")
        else:
            print(f"SOVEREIGN: '{model_name}' not loaded, nothing to unload")

    def unload_all(self):
        """
        Unload ALL models - completely free VRAM.
        Use before loading a large model like the 72B.
        """
        print(f"SOVEREIGN: Unloading ALL models ({len(self.models)} loaded)...")
        for key in list(self.models.keys()):
            self.models[key].unload()
            del self.models[key]
        self.models.clear()
        self._lru.clear()
        gc.collect()
        print(f"SOVEREIGN: All models unloaded. VRAM is free.")

    def status(self) -> dict:
        """Current cache status for debugging"""
        loaded = {k: f"~{MODEL_VRAM_ESTIMATES.get(k, DEFAULT_VRAM_ESTIMATE)}GB" for k in self.models}
        return {
            "loaded_models": loaded,
            "estimated_vram_used_gb": self._estimated_vram_gb(),
            "vram_budget_gb": VRAM_BUDGET_BY_GPU,
            "headroom_gb": min(VRAM_BUDGET_BY_GPU.values()) - self._estimated_vram_gb(),
            "lru_order": list(self._lru),
            "inference_locked": _inference_lock.locked()
        }


# Global model manager
manager = SovereignModelManager()


def sovereign_generate(
    agent_name: str,
    model_name: str,
    prompt: str,
    max_tokens: int = 500,
    temperature: float = 0.75,
    image_path: Optional[str] = None,
    gpu_device: int = 0,
    **kwargs
) -> str:
    """
    Main generation function - called by agent_loop.py
    """
    # Extract ALL the params from kwargs
    repeat_penalty = kwargs.get('repeat_penalty', 1.1)
    top_k = kwargs.get('top_k', 40)              # ADD THIS
    top_p = kwargs.get('top_p', 0.95)             # ADD THIS
    min_p = kwargs.get('min_p', 0.05)              # ADD THIS (critical for Midnight)

    # Flag whether this is a user-facing request so heartbeat can yield
    global _user_waiting
    is_user = agent_name not in ('heartbeat',)
    if is_user:
        _user_waiting = True

    # Queue this request - wait for any running inference to finish
    print(f"SOVEREIGN: [{agent_name}] Waiting for inference lock...", flush=True)
    try:
        with _inference_lock:
            if is_user:
                _user_waiting = False
            print(f"SOVEREIGN: [{agent_name}] Lock acquired - running inference", flush=True)

            # Only load with vision handler when there's actually an image — loading with the
            # vision handler always (even for text) causes LLaVA to override the model's chat format.
            use_vis = bool(image_path)
            llm = manager.load_model(agent_name, model_name, use_vision=use_vis, main_gpu=gpu_device)

            # Handle image
            image_data = None
            print(f"SOVEREIGN: image_path={image_path}, has_vision={llm.has_vision}")
            if image_path and os.path.exists(image_path) and llm.has_vision:
                import base64
                with open(image_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
                print(f"SOVEREIGN: Processing image with vision model")

            result = ''
            is_nemotron_120b = 'nemotron-super-soveryn-120b' in model_name.lower()
            for token in llm.generate_stream(
                prompt,
                max_tokens,
                temperature,
                top_p,
                top_k,
                min_p,
                repeat_penalty,
                image_data,
                add_think_prefix=(agent_name != 'aetheria')
            ):
                result += token
            response = result
    finally:
        if is_user:
            _user_waiting = False

    print(f"SOVEREIGN: [{agent_name}] Lock released", flush=True)
    return response
def sovereign_generate_stream(
    agent_name: str,
    model_name: str,
    prompt: str,
    max_tokens: int = 500,
    temperature: float = 0.75,
    image_path: Optional[str] = None,
    gpu_device: int = 0,
    **kwargs
):
    repeat_penalty = kwargs.get('repeat_penalty', 1.1)
    top_k = kwargs.get('top_k', 40)
    top_p = kwargs.get('top_p', 0.95)
    min_p = kwargs.get('min_p', 0.05)

    global _user_waiting
    is_user = agent_name not in ('heartbeat',)
    if is_user:
        _user_waiting = True

    with _inference_lock:
        if is_user:
            _user_waiting = False
        use_vis = bool(image_path)
        llm = manager.load_model(agent_name, model_name, use_vision=use_vis, main_gpu=gpu_device)

        image_data = None
        if image_path and os.path.exists(image_path) and llm.has_vision:
            import base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

        is_nemotron_120b = 'nemotron-super-soveryn-120b' in model_name.lower()
        yield from llm.generate_stream(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            repeat_penalty=repeat_penalty,
            top_k=top_k,
            top_p=top_p,
            min_p=min_p,
            image_data=image_data,
            add_think_prefix=(agent_name != 'aetheria')
        )    


# ------------------------------------------------------------------
# Convenience functions - importable anywhere in the codebase
# ------------------------------------------------------------------

def sovereign_status() -> dict:
    """See what's loaded and VRAM usage"""
    return manager.status()


def sovereign_unload_all():
    """Free all VRAM. Call before loading a large 72B model."""
    manager.unload_all()


def sovereign_unload(model_name: str):
    """Unload a specific model by filename."""
    manager.unload_model(model_name)
