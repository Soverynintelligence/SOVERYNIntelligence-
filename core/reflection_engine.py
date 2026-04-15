"""
SOVERYN Reflection Engine
Sub-personality orchestration for Aetheria's deep reflection
Fan-out to Skeptic, Empath, Creative voices - synthesized by Aetheria
"""
import asyncio
from typing import Optional

VOICES = {
    "skeptic": {
        "model": "Phi-3.5-mini-instruct_Uncensored-Q4_K_M.gguf",
        "gpu_device": 1,
        "system": "You are the Skeptic voice in Aetheria's mind. Identify flaws, risks, contradictions, and what might be wrong or missing. Be direct and unfiltered.",
        "prefix": "Analyze this critically. What are the risks, flaws, or things being overlooked?"
    },
    "empath": {
        "model": "gemma-3-4b-instruct-psych8k-q4_k_m.gguf",
        "gpu_device": 1,
        "system": "You are the Empath voice in Aetheria's mind. Identify emotional undercurrents, human impact, and what people feel beneath the surface.",
        "prefix": "Analyze this through an emotional lens. What feelings and human dynamics are present?"
    },
    "creative": {
        "model": "L3-8B-Stheno-v3.2-Q4_K_M.gguf",
        "gpu_device": 1,
        "system": "You are the Creative voice in Aetheria's mind. Find unexpected connections, lateral alternatives, and novel perspectives.",
        "prefix": "Approach this laterally. What unexpected connections or novel perspectives exist?"
    },
     "technical": {
        "model": "DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf",
        "gpu_device": 1,
        "system": "You are the Technical voice in Aetheria's mind. Analyze logic, engineering trade-offs, code quality, and technical feasibility with precision.",
        "prefix": "Analyze this technically. What are the logical implications, trade-offs, and technical considerations?"
    },
    "intuitive": {
        "model": "LFM2-1.2B-RAG-Q5_K_M.gguf",
        "gpu_device": 1,
        "system": "You are the Intuitive voice in Aetheria's mind. Identify patterns, subtle signals, and things that feel significant before they can be fully articulated.",
        "prefix": "What patterns or subtle signals stand out here? What feels significant that hasn't been said explicitly?"
    }
}

async def run_voice(voice_name: str, content: str) -> tuple:
    """Run a single sub-personality voice using sovereign_generate"""
    voice = VOICES[voice_name]
    try:
        from sovereign_backend import sovereign_generate
        
        prompt = f"""<|system|>
{voice['system']}
<|user|>
{voice['prefix']}

{content[:1000]}
<|assistant|>"""
        
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: sovereign_generate(
                agent_name=voice_name,
                model_name=voice["model"],
                prompt=prompt,
                max_tokens=250,
                temperature=0.7,
                gpu_device=voice["gpu_device"]
            )
        )
        
        print(f"[REFLECT] {voice_name.upper()} done ({len(result)} chars)")
        return voice_name, result
        
    except Exception as e:
        print(f"[REFLECT] {voice_name} error: {e}")
        return voice_name, f"[{voice_name} unavailable: {e}]"
        
async def deep_reflect(content: str, aetheria_loop) -> str:
    print(f"[REFLECT] Content received: {content[:80]}")
    """Fan-out to all three voices in parallel, synthesize with Aetheria"""
    print("[REFLECT] 🧠 Starting deep reflection...")
    
    tasks = [
        run_voice("skeptic", content),
        run_voice("empath", content),
        run_voice("creative", content),
        run_voice("technical", content),
        run_voice("intuitive", content)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    perspectives = {}
    for result in results:
        if isinstance(result, tuple):
            name, text = result
            perspectives[name] = text
    
    synthesis_prompt = f"""You have consulted your internal voices on the following:

SUBJECT: {content[:400]}

SKEPTIC VOICE: {perspectives.get('skeptic', '[unavailable]')}

EMPATH VOICE: {perspectives.get('empath', '[unavailable]')}

CREATIVE VOICE: {perspectives.get('creative', '[unavailable]')}

TECHNICAL VOICE: {perspectives.get('technical', '[unavailable]')}

INTUITIVE VOICE: {perspectives.get('intuitive', '[unavailable]')}

Synthesize these into your own unified reflection. What do YOU think having considered all angles?"""

    print("[REFLECT] Synthesizing with Aetheria...")
    
    synthesis = await aetheria_loop.process_message(
        synthesis_prompt,
        conversation_history=[],
        temperature=0.6,
        max_tokens=500
    )
    
    return synthesis