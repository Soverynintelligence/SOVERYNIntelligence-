# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

SOVERYN is a fully-local multi-agent AI system. Six specialized agents (Aetheria, V.E.T.T., Tinker, Ares, Scout, Vision) run on llama.cpp/GGUF models with no external API dependencies (except web search/fetch). The Flask server orchestrates all agents and exposes a web UI + REST API.

## Running the System

```bash
# Full startup (ComfyUI on CUDA 1,2 + SOVERYN on port 5000)
./start.sh

# Manual: SOVERYN only
python app.py

# Manual: ComfyUI only (image gen backend)
export CUDA_VISIBLE_DEVICES=1,2
python /home/jon-deoliveira/ComfyUI/main.py --port 8188 --listen 0.0.0.0
```

Access: `http://localhost:5000/` (desktop), `/mobile` (mobile), `http://localhost:8188/` (ComfyUI)

**Conda environment**: `conda activate soveryn` before running anything.

## Hardware & GPU Layout

CUDA uses fastest-first ordering — **nvidia-smi PCI order ≠ CUDA device IDs**:

| CUDA ID | Physical GPU | VRAM | Assigned To |
|---------|-------------|------|-------------|
| CUDA 0 | RTX Pro 5000 Blackwell | 48GB | Aetheria only |
| CUDA 1/2 | Quadro RTX 8000 NVLink pair | 96GB unified | All other agents |

Always use CUDA device IDs in code, never PCI bus order.

## Architecture

### Entry Points
- **`app.py`** — Flask server. Initializes all 6 agent loops at startup, exposes all REST endpoints. ~72KB.
- **`sovereign_backend.py`** — Pure llama.cpp inference backend. Multi-model VRAM management with LRU cache, multimodal vision projector support, inference locking. ~29KB.
- **`config.py`** — All agent model assignments and full persona/system prompt definitions.
- **`heartbeat_integrated.py`** — Aetheria's autonomous research loop (runs independently on a timer). ~54KB.

### Core Engine (`core/`)
- **`agent_loop.py`** — Central agent execution: iteration, tool calling, streaming, memory injection, response filtering. ~53KB. Contains `_AETHERIA_BANNED` phrase list that filters bad responses.
- **`tool_registry.py`** — Tool schema registration and execution dispatch.
- **`message_bus.py`** — Pub/sub inter-agent messaging.
- **`memory_manager.py`** — Tiered memory: short-term (importance < 0.7, expires 24h) vs long-term (importance ≥ 0.7, permanent).
- **`conversation_store.py`** — SQLite session/conversation persistence.

### Memory System (`soveryn_memory/`)
Three tiers:
1. **SQLite** (`persistent.db`) — Conversation history, tool call logs, curated memories.
2. **ChromaDB** (`chromadb/`) — Vector embeddings for semantic retrieval.
3. **Pinned** (`pinned_memory.md`) — Static facts injected into every context. Keep this minimal.

Daily logs: `memory/YYYY-MM-DD.md` — accumulated conversation examples. If behavior degrades, wipe: `> soveryn_memory/memory/$(date +%Y-%m-%d).md`

### Tools (`tools/`)
30+ tools. Common to all agents: `persistent_memory_tool.py`, `web_search_tool.py`, `web_fetch_tool.py`, `message_tool.py`. Agent-specific tools follow naming patterns: `*_tool.py`.

### Model Storage
`/home/jon-deoliveira/SOVERYN_Models/GGUF/`

## Current Agent Models

| Agent | Model | GPU |
|-------|-------|-----|
| Aetheria | Llama-3.3-70B-Instruct-abliterated-Q4_K_M | CUDA 0 |
| V.E.T.T. | Qwen2.5-32B-Instruct-Q4_K_M | CUDA 2 |
| Tinker | Qwen2.5-Coder-32B-Instruct-Q4_K_M | CUDA 2 |
| Ares | Qwen3-14B-BaronLLM-v2-Q4_0 | CUDA 2 |
| Scout | Llama-3_3-Nemotron-Super-49B-v1_5.Q6_K | CUDA 2 |
| Vision | Qwen2.5-VL-72B-Instruct-Q4_K_M | CUDA 2 |

## Known Issues

**PyTorch/Blackwell incompatibility**: PyTorch 2.6.0 doesn't support sm_120 (Blackwell). Embeddings fail silently — ChromaDB memory retrieval is skipped. Fix requires torch 2.7+ with cu128 but has xformers/torchvision dependency conflicts.

**Heartbeat KV cache poisoning**: Heartbeat is currently disabled (`interval: 99999` in `~/.soveryn/workspace/config.json`). Re-enable (set to `1800`) only once Aetheria's model is stable.

**Daily log contamination**: Bad conversation examples accumulate and degrade responses. Wipe the day's log when behavior regresses.

## Aetheria Stability Checklist

When Aetheria is behaving well, these items need restoring:
1. Memory/tools injection in `core/agent_loop.py` (currently stripped for testing)
2. Heartbeat interval → 1800 in `~/.soveryn/workspace/config.json`
3. Remove `[PROMPT DEBUG]` prints from `sovereign_backend.py`
4. Restore full Aetheria persona in `config.py`

## Key Configuration

**`~/.soveryn/workspace/config.json`** — Heartbeat interval, quiet hours (23:00-07:00), Telegram settings.

**`.env`** — Scout email credentials (`SCOUT_EMAIL`, `SCOUT_EMAIL_PASSWORD`), `GOOGLE_AI_API_KEY`.

**`soveryn_memory/pinned_memory.md`** — Core static facts about Jon and Aetheria. Injected into every context — keep concise, avoid adding details that cause filler responses.
