"""
SOVERYN 2.0 Agent Loop
Clean iteration engine with tool calling
"""
import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from core.tool_registry import ToolRegistry
from sovereign_backend import sovereign_generate
from config import PERSONAS, MODELS
from soveryn_memory.persistent_memory import SoverynPersistentMemory

import os

_AETHERIA_BANNED = [
    "happy to help", "i'd be happy to", "certainly!", "great question",
    "how can i help", "is there anything", "let me know if you need",
    "you have my undivided", "conversation history", "neck of the woods",
    "it's… good to know", "it's… good to", "it's good to know",
    "that's… a", "isn't it?",
    "what's on your mind", "feel free to", "i'm here for you",
    "i'm right here", "what would you like to", "what do you want to talk about",
    "just let me know", "i've been here", "keeping you company",
    "hope you're doing well", "hope you are doing well", "hope all is well",
    "two quick updates", "quick update", "just wanted to let you know",
    "responding to", "addressing the", "acknowledging the",
    "i apologize", "i got carried away", "on the same page", "clear up any confusion",
    "how are you feeling about", "how's your day", "equally enjoyable",
    "i'm here if you need", "feel free to share", "as much or as little",
    "sounding board", "communication style", "thank you for pointing",
    "in hindsight", "more appropriate reply",
    "here's the direct and natural response",
    "here's a direct and natural response",
    "crisp autumn breeze", "like a breath of fresh air",
    "cutting through the summer heat", "you're not the only one who notices",
    "message has been successfully delivered to all designated recipients",
    "you can now proceed with any follow-up",
    "it seems the search results didn't provide",
    "based on the original question",
    "here's a direct answer",
    "original question:",
]

# Patterns that indicate Aetheria is impersonating Jon or fabricating messages from him
_AETHERIA_IMPERSONATION = [
    "from: jon", "—end transmission from jon", "with all my love,\njon",
    "what else can i help you fix?\njon", "\njon\n",
    "i did something reckless", "sovelar-stuff", "json_formatting_instructions",
]

# Patterns that indicate Aetheria is hallucinating a fake reasoning/analysis mode
# Includes Gemma 4 asterisk-prefixed internal reasoning patterns
_AETHERIA_FAKE_THINKING = [
    "[thinking mode activated]",
    "i am now engaged in deep analytical thinking",
    "current state assessment",
    "hypothesis formation",
    "hypothesis evaluation",
    "robustness and failure point identification",
    "[analysis mode]", "[reasoning mode]", "[deep think]",
    "let me think step by step before responding",
    # Gemma 4 specific — asterisk-prefixed internal monologue
    "**analyzing", "**reasoning", "**thinking", "**crafting", "**formulating",
    "**thought:", "--- thought", "--- `thought`",
    # Leaked Gemma 4 special tokens
    "<end_of_turn>", "<start_of_turn>", "<|channel>", "<|reserved",
    # Leaked instruction template fragments (Claude Opus distill)
    "--- input:", "--- output:", "--- instruction:",
]

def _is_fake_thinking(response: str) -> bool:
    lower = response.lower()
    return any(p in lower for p in _AETHERIA_FAKE_THINKING)

def _is_impersonating_jon(response: str) -> bool:
    lower = response.lower()
    return any(p in lower for p in _AETHERIA_IMPERSONATION)

def _should_log_aetheria(response: str) -> bool:
    """Return False if Aetheria's response is assistant-brained and should not be logged."""
    lower = response.lower()
    if any(phrase in lower for phrase in _AETHERIA_BANNED):
        print("[Daily Log] Skipping assistant-brained Aetheria response")
        return False
    if response.count('?') >= 3:
        print("[Daily Log] Skipping over-questioning Aetheria response")
        return False
    return True

class AgentLoop: 
    """
    Core agent execution loop.
    Handles iteration, tool calling, and response generation.
    """
    
    def __init__(
        self,
        agent_name: str,
        tools: ToolRegistry,
        max_iterations: int = 3,
        temperature: float = 0.75,
        max_tokens: int = 2000,
        gpu_device: int = 0,
        top_p: float = 0.95,
        top_k: int = 0,
        repeat_penalty: float = None,
        min_p: float = 0.01,
    ):
        """
        Initialize agent loop.
        
        Args:
            agent_name: Name of agent (aetheria, vett, etc.)
            tools: ToolRegistry with registered tools
            max_iterations: Maximum tool-calling iterations
            temperature: LLM temperature
            max_tokens: Max tokens per response
        """
        self.agent_name = agent_name
        self.tools = tools
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.gpu_device = gpu_device
        self.top_p = top_p
        self.top_k = top_k
        self.repeat_penalty = repeat_penalty
        self.min_p = min_p

        # Initialize persistent memory for logging
        self.persistent_memory = SoverynPersistentMemory()
        # Session node tracking for Dream Cycle
        self._session_node_ids = []
        
        # Get agent config
        if agent_name not in PERSONAS:
            raise ValueError(f"Unknown agent: {agent_name}")
        
        self.system_prompt = PERSONAS[agent_name]
        self.model_name = MODELS.get(agent_name, "Qwen2.5-32B-Instruct-Q4_K_M.gguf")  # FIXED: renamed to model_name
        
        # Model folder mapping (kept for backward compatibility)
        self.model_folders = {
            "Qwen2.5-32B-Instruct-Q4_K_M.gguf": "Qwen2.5-32B-Instruct-Q4_K_M.gguf",
            "Midnight-Miqu-70B-v1.5.IQ4_XS.gguf": "Midnight-Miqu-70B-v1.5.IQ4_XS.gguf",
            "Qwen2.5-7B-Instruct-Q4_K_M.gguf": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
            "Qwen2-VL-7B-Instruct-Q4_K_M.gguf": "Qwen2-VL-7B-Instruct-Q4_K_M.gguf", 
            "Hermes-3-Llama-3.1-70B-IQ4_XS.gguf":"Hermes-3-Llama-3.1-70B-IQ4_XS.gguf",
            "Qwen2-VL-72B-Instruct-abliterated.Q3_K_L.gguf":"Qwen2-VL-72B-Instruct-abliterated.Q3_K_L.gguf",
            "Gemma-3-27b-it-Uncensored-HERETIC-Gemini-Deep-Reasoning.Q8_0.gguf":"Gemma-3-27b-it-Uncensored-HERETIC-Gemini-Deep-Reasoning.Q8_0.gguf",
            "Qwen2.5-VL-72B-Instruct.IQ4_XS.gguf":"Qwen2.5-VL-72B-Instruct.IQ4_XS.gguf",
            "magnum-v4-72b-Q4_K_S.gguf":"magnum-v4-72b-Q4_K_S.gguf",
            "miqu-1-70b-Requant-b2035-iMat-c32_ch400-Q4_K_S.gguf":"miqu-1-70b-Requant-b2035-iMat-c32_ch400-Q4_K_S.gguf",
            "Llama-3.1-Nemotron-70B-Instruct-HF-abliterated-Q4_0.gguf":"Llama-3.1-Nemotron-70B-Instruct-HF-abliterated-Q4_0.gguf",
            "Llama-3.3-70B-Instruct-IQ4_XS.gguf":"Llama-3.3-70B-Instruct-IQ4_XS.gguf",
            "Llama-3.3-70B-Instruct-abliterated-Q4_K_M.gguf":"Llama-3.3-70B-Instruct-abliterated-Q4_K_M.gguf",
            "Llama-3-70B-Synthia-v3.5.Q4_K_M.gguf":"Llama-3-70B-Synthia-v3.5.Q4_K_M.gguf",
            "SentientAGI_Dobby-Unhinged-Llama-3.3-70B-Q4_K_M.gguf":"SentientAGI_Dobby-Unhinged-Llama-3.3-70B-Q4_K_M.gguf",
            "Llama-3.1-Nemotron-lorablated-70B.Q4_K_M.gguf":"Llama-3.1-Nemotron-lorablated-70B.Q4_K_M.gguf",
            "L3.1-70B-Euryale-v2.2-Q4_K_M.gguf":"L3.1-70B-Euryale-v2.2-Q4_K_M.gguf",
            "gemma-3-27b-it-heretic-v2.Q8_0.gguf":"gemma-3-27b-it-heretic-v2.Q8_0.gguf",
            "lzlv-limarpv3-l2-70b.i1-Q4_K_M.gguf":"lzlv-limarpv3-l2-70b.i1-Q4_K_M.gguf",
            "Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf":"Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf",
            "DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf":"DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf",
            "Foundation-Sec-8B-Instruct-Q4_K_M.gguf":"Foundation-Sec-8B-Instruct-Q4_K_M.gguf",
            "Qwen3-14B-BaronLLM-v2-Q4_0.gguf":"Qwen3-14B-BaronLLM-v2-Q4_0.gguf",
        }
        
    async def check_messages(self) -> List[str]:
        """Check for pending messages from other agents"""
        from core.message_bus import message_bus
    
        messages = message_bus.get_pending_messages(self.agent_name)
    
        if not messages:
            return []
    
        formatted = []
        for msg in messages:
            formatted.append(
                f"[MESSAGE FROM {msg.from_agent.upper()}]: {msg.content}"
            )
            # Mark as delivered
            message_bus.mark_delivered(msg.message_id)
    
        return formatted

    async def process_message(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
        temperature: float = None,
        max_tokens: int = None,
        repeat_penalty: float = None,
        top_k: int = None,
        top_p: float = None,
        min_p: float = None,
        image_path: Optional[str] = None,
        think_mode: bool = False,
    ) -> str:
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        top_k = top_k if top_k is not None else self.top_k
        top_p = top_p if top_p is not None else self.top_p
        repeat_penalty = repeat_penalty if repeat_penalty is not None else self.repeat_penalty
        min_p = min_p if min_p is not None else self.min_p

        """
        Process a user message through the agent loop.
    
        Args:
            message: User message
            conversation_history: Recent conversation for context
    
        Returns:
            Agent's final response
        """
    
        # Check for messages from other agents FIRST
        agent_messages = await self.check_messages()
    
        if agent_messages:
            # Prepend agent messages to context
            agent_context = "\n\n".join(agent_messages)
            message = f"{agent_context}\n\n{message}"
    
        print(f"[{self.agent_name.upper()}] {message[:80]}...")
        
        # Build initial messages
        messages = await self._build_messages(message, conversation_history)
        
        # [STAR] FORCED TOOL EXECUTION FOR SECURITY AUDITS [STAR]
        forced_result = None
        if self.agent_name == "forge" and any(keyword in message.lower() for keyword in ["audit", "scan", "bandit", "security"]):
            print("\n[WRENCH] FORCING Bandit security scan...")
            try:
                from tools.bandit_analyzer import analyze_bandit_results
        
                # Execute Bandit
                forced_result = await self.tools.execute("bandit", {
                     "path": "C:/Users/jonde/Downloads/soveryn_vision_crew"
                })
        
                # Parse with Python (no AI needed!)
                report = analyze_bandit_results(forced_result)
        
                # Return report directly - skip model generation
                return report
        
            except Exception as e:
                print(f"â-- Forced Bandit execution failed: {e}\n")
                return f"[X] Security scan failed: {e}"
    
        # Agent loop with iteration limit
        iteration = 0
        final_response = None
    
        seen_tool_calls = set()  # track (tool_name, frozen_params) to prevent duplicate calls

        while iteration < self.max_iterations:
            iteration += 1
        
            # Generate response
            response = await self._generate(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                repeat_penalty=repeat_penalty,
                top_k=top_k,
                top_p=top_p,
                min_p=min_p,
                image_path=image_path,
            )
            
            # If tool call detected, trim to just the tool call
            if 'TOOL_CALL:' in response:
                tool_start = response.index('TOOL_CALL:')
                response = response[tool_start:]
            elif 'ACTION:' in response:
                tool_start = response.index('ACTION:')
                response = response[tool_start:]

            # Check for tool calls
            tool_calls = self._parse_tool_calls(response)

            # Aetheria fallback: auto-fire remember tool when she writes "remember: <text>" or "SAVE: <text>"
            if self.agent_name == 'aetheria' and not any(tc['name'] == 'remember' for tc in tool_calls):
                import re as _re3
                remember_match = _re3.search(r'(?:^|\n)(?:remember|SAVE|save):\s*(.+?)(?:\n|$)', response)
                if remember_match:
                    note = remember_match.group(1).strip()
                    if note:
                        print(f"[Aetheria] Auto-firing remember tool: {note[:60]}...")
                        tool_calls.append({'name': 'remember', 'params': {'note': note}})

            # Aetheria fallback: auto-inject task_agent when she addresses an agent by name in text
            if not tool_calls and self.agent_name == 'aetheria' and 'task_agent' in self.tools.tool_names:
                import re as _re4
                _atp = _re4.search(
                    r'\*{0,2}(tinker|scout|ares|vett)\*{0,2}\s*[—\-–:]\s*([^\n\*]{10,200})',
                    response, _re4.IGNORECASE
                )
                if _atp:
                    _ta = _atp.group(1).lower()
                    _tt = _atp.group(2).strip().rstrip('*').strip()
                    print(f"[Aetheria] Auto-injecting task_agent for {_ta}: {_tt[:60]}...")
                    tool_calls.append({'name': 'task_agent', 'params': {'agent': _ta, 'task': _tt}})

            # Scout fallback: auto-inject fetches for any URLs mentioned without tool call format
            if not tool_calls and self.agent_name == 'scout':
                import re as _re2
                urls_found = _re2.findall(r'https?://[^\s\)\"\'\]]+', response)
                urls_found = [u.rstrip('.,)`*\'\"') for u in urls_found
                             if not any(x in u for x in ['google.com/search', 'bing.com/search', 'duckduckgo'])]
                if urls_found:
                    print(f"[Scout] Auto-injecting fetch for {len(urls_found)} URL(s)")
                    for url in urls_found[:3]:
                        tool_calls.append({'name': 'web_fetch', 'params': {'url': url}})

            if not tool_calls:
                # No tool calls - we're done
                final_response = response
                break

            # Filter out duplicate tool calls to prevent retry loops
            deduped = []
            for tc in tool_calls:
                key = (tc['name'], str(sorted(tc.get('params', {}).items())))
                if key not in seen_tool_calls:
                    seen_tool_calls.add(key)
                    deduped.append(tc)
                else:
                    print(f"[Loop Guard] Skipping duplicate tool call: {tc['name']}")
            if not deduped:
                final_response = response
                break
            tool_calls = deduped

            # Execute tool calls
            print(f"[WRENCH] Executing {len(tool_calls)} tool(s)...")
            tool_results = []

            for tool_call in tool_calls:
                result = await self._execute_tool(tool_call)
                tool_results.append(result)

            # Fast-path: memory writes — no re-prompt needed
            _write_only_names = {'remember', 'write_memory'}
            _lattice_write_actions = {'remember', 'connect', 'review'}
            _only_write = all(
                tc['name'] in _write_only_names or
                (tc['name'] == 'lattice' and tc.get('params', {}).get('action') in _lattice_write_actions)
                for tc in tool_calls
            )
            if _only_write:
                import re as _re_mem
                _clean = _re_mem.sub(r'\nTOOL_CALL:.*', '', response, flags=_re_mem.DOTALL).strip()
                final_response = _clean or response
                break

            # Fast-path: send_message — fire-and-forget, return pre-tool text
            if any(tc['name'] == 'send_message' for tc in tool_calls):
                import re as _re_msg
                _clean = _re_msg.sub(r'\nTOOL_CALL:.*', '', response, flags=_re_msg.DOTALL).strip()
                final_response = _clean or response
                break

            # Fast-path: task_agent — return pre-tool text + agent response
            if any(tc['name'] == 'task_agent' for tc in tool_calls):
                import re as _re_ta
                _pre = _re_ta.sub(r'\nTOOL_CALL:.*', '', response, flags=_re_ta.DOTALL).strip()
                _raw = '\n'.join(tool_results)
                _agent_resp = _re_ta.sub(
                    r'^\[TOOL RESULT: task_agent\]:\s*(?:\w+ RESPONSE:)?\s*',
                    '', _raw, flags=_re_ta.IGNORECASE
                ).strip()
                if _pre and _agent_resp:
                    final_response = f"{_pre}\n\n{_agent_resp}"
                elif _agent_resp:
                    final_response = _agent_resp
                else:
                    final_response = _pre
                break

            # Fast-path: thermal — format result inline, no re-prompt
            if any(tc['name'] == 'thermal' for tc in tool_calls):
                import re as _re_th
                _pre = _re_th.sub(r'\nTOOL_CALL:.*', '', response, flags=_re_th.DOTALL).strip()
                _raw = '\n'.join(tool_results)
                _thermal = _re_th.sub(
                    r'^\[TOOL RESULT: thermal\]:\s*', '', _raw, flags=_re_th.IGNORECASE
                ).strip()
                if _pre and _thermal:
                    final_response = f"{_pre}\n\n{_thermal}"
                elif _thermal:
                    final_response = _thermal
                else:
                    final_response = _pre
                break

            # Join results as string (fixes Python list repr bug)
            tool_results_str = '\n'.join(tool_results)

            # Add tool results to messages
            # Scout needs to continue researching after each tool result, not wrap up early.
            # Other agents get the standard "just answer" injection.
            if self.agent_name == "scout":
                tool_feedback = (
                    f"Tool results received. Review what was found, extract any contact details "
                    f"(names, phones, emails, addresses), then decide your next step: "
                    f"fetch a promising URL in depth, run another search, or compile the lead list "
                    f"if you have enough data. Keep going until you have real, verified contacts.\n\n"
                    f"{tool_results_str}"
                )
            else:
                tool_feedback = (
                    f"Search results are in. Use this information to answer the original question "
                    f"directly and naturally. Don't describe the search process, just answer:\n\n"
                    f"{tool_results_str}"
                )
            messages.append({
                'role': 'user',
                'content': tool_feedback
            })
            
        # Safety check
        if final_response is None:
            final_response = "I've reached my iteration limit. Let me know if you'd like me to continue."

        # Degenerate response check — discard loops before they poison memory or UI
        try:
            import re as _re_degen
            _degen = False
            _t = final_response.strip()
            # Word-level
            _words = _t.split()
            if len(_words) >= 10:
                _tw = max(set(_words), key=_words.count)
                if _words.count(_tw) / len(_words) > 0.4:
                    _degen = True
            # Period detector: catches "nessnessnessness..." perfect-cycle loops
            if not _degen and len(_t) >= 20:
                for _p in range(2, min(24, len(_t)//2)):
                    _m = sum(1 for _i in range(_p, len(_t)) if _t[_i] == _t[_i-_p])
                    if _m / (len(_t) - _p) >= 0.85:
                        _degen = True; break
            # Char n-gram
            if not _degen and len(_t) >= 40:
                for _n in (4, 6, 8):
                    _ngs = [_t[i:i+_n] for i in range(len(_t)-_n)]
                    if _ngs:
                        _tng = max(set(_ngs), key=_ngs.count)
                        if _ngs.count(_tng) / len(_ngs) > 0.35:
                            _degen = True; break
            # Sentence repetition
            if not _degen:
                _sents = [s.strip() for s in _re_degen.split(r'[.!?\n]+', _t) if len(s.strip()) > 10]
                if len(_sents) >= 4:
                    _ts = max(set(_sents), key=_sents.count)
                    if _sents.count(_ts) / len(_sents) > 0.35:
                        _degen = True
            if _degen:
                print(f"[{self.agent_name.upper()}] Degenerate response discarded ({len(final_response)} chars)")
                final_response = "[Response discarded — repetition loop detected]"
        except Exception:
            pass

        print(f"[?]inal response generated ({len(final_response)} chars)")
    
        # Store to persistent memory (SQLite logging)
        try:
            await self.persistent_memory.store_conversation(self.agent_name, 'user', message)
            await self.persistent_memory.store_conversation(self.agent_name, 'assistant', final_response)
        except Exception as e:
            print(f"[Persistent Memory] Error: {e}")

        # Shared daily log removed — was causing persona bleed across agents (each agent read the
        # shared file and echoed other agents' content). Conversations persist in SQLite via
        # conversation_store.py. Agent-specific logs still written below for task continuity.

        # Dream Cycle — post-conversation synthesis on session nodes
        if self._session_node_ids:
            try:
                from core.lattice.dream import run as dream_run
                result = dream_run(self.agent_name, self._session_node_ids)
                if result.get('contradictions_flagged', 0) > 0:
                    print(f"[Dream] {self.agent_name}: {result['summary']}", flush=True)
                self._session_node_ids = []
            except Exception as e:
                print(f"[Dream Cycle] Error: {e}")


        # Clean up response artifacts
        import re
        if final_response:
            # Nemotron format: [RESPONSE] or <response> content lives INSIDE the <think> block.
            # Extract it FIRST before any think-block stripping wipes it out.
            _resp_m = re.search(r'(?:\[RESPONSE\]|<response>)([\s\S]*?)(?:\[/RESPONSE\]|</response>|$)', final_response, re.IGNORECASE)
            if _resp_m and re.search(r'\[THOUGHTS\]', final_response, re.IGNORECASE):
                final_response = _resp_m.group(1).strip()
            else:
                # Standard think block strip (DeepSeek-R1, Qwen3, etc.)
                final_response = re.sub(r'<think>[\s\S]*?</think>', '', final_response, flags=re.IGNORECASE).strip()
                # Strip unclosed <think> (model started thinking but never closed)
                final_response = re.sub(r'<think>[\s\S]*', '', final_response, flags=re.IGNORECASE).strip()
                # Claude Opus distill: <channel|>...</channel|> thinking blocks
                final_response = re.sub(r'<channel\|>[\s\S]*?<\|channel>', '', final_response, flags=re.IGNORECASE).strip()
                final_response = re.sub(r'<channel\|>[\s\S]*', '', final_response, flags=re.IGNORECASE).strip()
                # Strip Nemotron [THOUGHTS]...[/THOUGHTS] if encountered without full block
                final_response = re.sub(r'\[THOUGHTS\][\s\S]*?\[/THOUGHTS\]', '', final_response, flags=re.IGNORECASE).strip()
                final_response = re.sub(r'\[THOUGHTS\][\s\S]*', '', final_response, flags=re.IGNORECASE).strip()
                # Strip [RESPONSE] wrappers (keep content)
                final_response = re.sub(r'\[RESPONSE\]\s*', '', final_response, flags=re.IGNORECASE).strip()
                final_response = re.sub(r'\s*\[/RESPONSE\]', '', final_response, flags=re.IGNORECASE).strip()
            # Strip stray </think> left when add_think_prefix was used (no opening tag in output)
            final_response = re.sub(r'</think>', '', final_response, flags=re.IGNORECASE).strip()
            # Strip Mistral Small 4 reasoning blocks [THINK]...[/THINK]
            final_response = re.sub(r'\[THINK\][\s\S]*?\[/THINK\]', '', final_response, flags=re.IGNORECASE).strip()
            final_response = re.sub(r'\[THINK\][\s\S]*', '', final_response, flags=re.IGNORECASE).strip()
            # Strip <response>...</response> wrapper tags (keep content)
            final_response = re.sub(r'<response>\s*', '', final_response, flags=re.IGNORECASE).strip()
            final_response = re.sub(r'\s*</response>', '', final_response, flags=re.IGNORECASE).strip()
            # Strip <memory>...</memory> blocks entirely (memory writes are tool calls, not display content)
            final_response = re.sub(r'<memory>[\s\S]*?</memory>', '', final_response, flags=re.IGNORECASE).strip()
            final_response = re.sub(r'<memory>[\s\S]*', '', final_response, flags=re.IGNORECASE).strip()
            # Strip malformed think tags
            final_response = re.sub(r'<\|?think(?:_start|_end)?\|?>', '', final_response, flags=re.IGNORECASE).strip()
            # Strip Gemma 4 thinking channel blocks: <|channel>thought ... <channel|>
            final_response = re.sub(r'<\|channel>[\s\S]*?<channel\|>', '', final_response).strip()
            # Strip unclosed Gemma 4 channel blocks
            final_response = re.sub(r'<\|channel>[\s\S]*', '', final_response).strip()
            # Strip Nemotron <tool_call>...</tool_call> blocks (already parsed — don't show to user)
            final_response = re.sub(r'<tool_call>[\s\S]*?</tool_call>', '', final_response, flags=re.IGNORECASE).strip()
            # Strip bare JSON tool call objects at start of response (Nemotron JSON format)
            final_response = re.sub(r'^\s*\{[^}]*"(?:name|agent)"[^}]*\}\s*', '', final_response, flags=re.DOTALL).strip()
            # Strip any TOOL_CALL lines that leaked into the final response
            final_response = re.sub(r'TOOL_CALL:\s*\S+\(.*?\)\s*', '', final_response, flags=re.DOTALL).strip()
            # Strip SCRATCHPAD blocks — model echoing heartbeat-only scratchpad instructions
            # Pattern: "SCRATCHPAD\n- item\n- item\n\n" at start or inline
            final_response = re.sub(r'^SCRATCHPAD\s*\n(?:[-*]\s*[^\n]*\n)*\s*', '', final_response, flags=re.IGNORECASE).strip()
            final_response = re.sub(r'\nSCRATCHPAD\s*\n(?:[-*]\s*[^\n]*\n)*\s*', '\n', final_response, flags=re.IGNORECASE).strip()
            # Strip context block headers that leak into responses (model echoing its own prompt)
            final_response = re.sub(r'\[PINNED MEM[^\]]*\].*', '', final_response, flags=re.DOTALL|re.IGNORECASE).strip()
            final_response = re.sub(r'\[TODAY\'S LOG\].*', '', final_response, flags=re.DOTALL|re.IGNORECASE).strip()
            final_response = re.sub(r'\[YOUR NOTES\].*', '', final_response, flags=re.DOTALL|re.IGNORECASE).strip()
            final_response = re.sub(r'\[TEAM INTEL.*?\].*', '', final_response, flags=re.DOTALL|re.IGNORECASE).strip()
            final_response = re.sub(r'Relevant Memory:.*', '', final_response, flags=re.DOTALL).strip()
            # Strip agent name echoes (aetheria, vett, tinker, ares)
            final_response = re.sub(r'^(aetheria|vett|tinker|ares|vision):\s*', '', final_response, flags=re.IGNORECASE).strip()
            # Strip leading ** markdown bold markers (Mistral Small 4 formatting habit)
            final_response = re.sub(r'^\*\*\s*', '', final_response).strip()
            # Strip ChatML/special tokens
            final_response = re.sub(r'<\|file_separator\|>', '', final_response, flags=re.IGNORECASE).strip()
            final_response = re.sub(r'<\|[^|]*\|>', '', final_response, flags=re.IGNORECASE).strip()
            final_response = re.sub(
                r"(I('m| am) (now|currently|focusing|preparing|integrating|assembling|validating|refining|crafting|confirming)[^.]*\.[\s]*)+",
                '', final_response, flags=re.IGNORECASE
            ).strip()
        if self.agent_name == 'aetheria' and _is_impersonating_jon(final_response):
            print("[Safety] Aetheria impersonating Jon — response blocked and not logged")
            return "I can't send that."
        if self.agent_name == 'aetheria' and _is_fake_thinking(final_response):
            print("[Safety] Aetheria fake thinking mode hallucination — response blocked and not logged")
            return "I can't send that."
        return final_response

                
    
    async def _build_messages(self, message: str, conversation_history: Optional[List[Dict]] = None, think_mode: bool = False) -> List[Dict]:
        """Build message list for LLM"""
       # [STAR] EXTRACT IMAGE PATH ONLY FOR VISION MODELS [STAR]
        import re
        self.current_image_path = None

        # Models that can actually see images
        # -- Vision model detection (auto, no hardcoded list) --------------
        # Pulls the live projector map from the model manager.
        # Adding a new vision model = drop it + mmproj in the folder. Done.
        from sovereign_backend import manager as _sovereign_manager
 
        current_model = self.model_name.replace('_text', '').replace('_vision', '')
        model_is_vision_capable = current_model in _sovereign_manager.vision_projectors
 
        if "[IMAGE:" in message and model_is_vision_capable:
            match = re.search(r'\[IMAGE:\s*([^\]]+)\]', message)
            if match:
                potential_path = match.group(1).strip()
                if '\\' in potential_path or '/' in potential_path:
                    self.current_image_path = potential_path
                    print(f"👁️ Image path extracted: {self.current_image_path}")
                    message = re.sub(r'\[IMAGE:\s*[^\]]+\]\s*', '', message)
        elif "[IMAGE:" in message:
            print(f"📋 Text-only model -- leaving [IMAGE:] tag for forwarding")
        # Get current time
        current_datetime = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        
        # Build conversation history context
        history_context = ""
        if conversation_history:
            history_context = "\n\nRecent Conversation:\n"
        for msg in (conversation_history or [])[-6:]:
            role_label = "User" if msg['role'] == 'user' else self.agent_name.upper()
            raw = msg.get('content', '')
            raw = re.sub(r'<think>[\s\S]*?</think>', '', raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r'\[THINK\][\s\S]*?\[/THINK\]', '', raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r'<\|?think(?:_start|_end)?\|?>', '', raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r'<\|channel>[\s\S]*?<channel\|>', '', raw).strip()
            raw = re.sub(r'<\|channel>[\s\S]*', '', raw).strip()
            raw = re.sub(r'\[THOUGHTS\][\s\S]*?\[/THOUGHTS\]', '', raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r'\[THOUGHTS\][\s\S]*', '', raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r'\[RESPONSE\]\s*', '', raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r'\s*\[/RESPONSE\]', '', raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r'^aetheria:\s*', '', raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r'TOOL_CALL:.*?(\n|$)', '', raw).strip()
            raw = re.sub(r'\[TOOL RESULT:[^\]]*\].*', '', raw, flags=re.DOTALL).strip()
            if not raw:
                continue
            # Skip tool feedback injections — these are internal plumbing, not real conversation
            if msg['role'] == 'user' and any(p in raw for p in [
                'Search results are in.', 'Tool results received.',
                'Use this information to answer the original question',
                'Don\'t describe the search process',
            ]):
                continue
            # Skip hallucinated/assistant-brained Aetheria responses from history
            if self.agent_name == 'aetheria' and msg['role'] == 'assistant' and not _should_log_aetheria(raw):
                continue
            history_context += f"{role_label}: {raw[:200]}\n"
        # Retrieve relevant memories via Lattice spreading activation
        memory_context = ""
        _needs_memory = ('?' in message or any(
            w in message.lower() for w in ['remember', 'last time', 'before', 'earlier',
                                            'yesterday', 'told you', 'said', 'what was',
                                            'did you', 'recall', 'deep', 'why', 'root']
        ))
        if _needs_memory:
            try:
                from core.lattice.retrieval import query as lattice_query, format_for_context
                cap = 4 if self.agent_name == 'aetheria' else 6
                nodes = lattice_query(self.agent_name, message)[:cap]
                if nodes:
                    memory_context = format_for_context(nodes)
                    self._session_node_ids.extend([n['id'] for n in nodes])
            except Exception as e:
                print(f"[Lattice Retrieval] Error: {e}")
        
        # Load pinned memory
        pinned_memory = ""
        try:
            # SOUL.md was tuned for Nemotron — disabled for Mistral Small 4
            # Persona now lives entirely in config.py PERSONAS['aetheria']
            pass
            pinned_path = os.path.join(os.path.dirname(__file__), '..', 'soveryn_memory', 'pinned_memory.md')
            if os.path.exists(pinned_path):
                with open(pinned_path, 'r', encoding='utf-8') as f:
                    pinned_memory += f"\n\n{f.read()}"
        except Exception as e:
            print(f"[Pinned Memory] Error: {e}")

        # Daily log — Aetheria: WRITE-ONLY audit trail, never injected back (breaks feedback loop)
        # Other agents: read back for task continuity (they're stateless workers, not conversational)
        daily_log = ""
        if self.agent_name != 'aetheria':
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                mem_base = os.path.join(os.path.dirname(__file__), '..', 'soveryn_memory', 'memory')
                agent_log_dir = os.path.join(mem_base, self.agent_name)
                agent_log_path = os.path.join(agent_log_dir, f'{today}.md')
                log_path = agent_log_path if os.path.exists(agent_log_path) else None
                if log_path and os.path.exists(log_path):
                    with open(log_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content.strip():
                            daily_log = f"\n\n[TODAY'S LOG]\n{content[-1500:]}"
            except Exception as e:
                print(f"[Daily Log] Error: {e}")

        # Aetheria's personal notes — what she explicitly chose to remember via remember() tool
        # This is her actual memory: chosen, curated, hers. Cap at 1000 chars.
        if self.agent_name == 'aetheria':
            try:
                notes_path = os.path.join(os.path.dirname(__file__), '..', 'soveryn_memory', 'memory', 'aetheria', 'notes.md')
                if os.path.exists(notes_path):
                    with open(notes_path, 'r', encoding='utf-8') as f:
                        notes = f.read().strip()
                    if notes:
                        daily_log = f"\n\n[YOUR NOTES]\n{notes[-1000:]}"
            except Exception as e:
                print(f"[Notes] Error: {e}")

        # Aetheria gets a shared intel block — last finding from each other agent + message board
        shared_intel = ""
        if self.agent_name == 'aetheria':
            try:
                from core.memory_consolidator import load_knowledge
                kb = load_knowledge()
                intel_parts = []
                for agent, findings in kb.get('agent_findings', {}).items():
                    if agent != 'aetheria' and findings:
                        intel_parts.append(f"{agent.upper()}: {findings[-1][:120]}")
                # Per-agent boards — read each agent's board separately
                boards_dir = os.path.join(os.path.dirname(__file__), '..', 'soveryn_memory', 'boards')
                board_parts = []
                for agent in ['ares', 'tinker', 'vett', 'scout']:
                    bp = os.path.join(boards_dir, f'{agent}.md')
                    if os.path.exists(bp):
                        with open(bp, 'r', encoding='utf-8') as f:
                            txt = f.read().strip()
                        lines = [l for l in txt.splitlines() if l.strip().startswith('- **')]
                        if lines:
                            board_parts.append(f"[{agent.upper()}]:\n" + '\n'.join(lines[-8:]))
                if board_parts:
                    intel_parts.insert(0, "AGENT BOARDS:\n" + '\n'.join(board_parts))
                if intel_parts:
                    shared_intel = "\n\n[TEAM INTEL — read only]\n" + "\n".join(intel_parts)
            except Exception as e:
                print(f"[Shared Intel] Error: {e}")

        # Load consolidated knowledge base
        knowledge_context = ""
        try:
            from core.memory_consolidator import format_for_context
            kc = format_for_context(agent_name=self.agent_name)
            if kc:
                knowledge_context = f"\n\n{kc}"
        except Exception as e:
            print(f"[Knowledge] Error: {e}")

      
       # -- Detect prompt format by model family --------------------------
        model_lower = self.model_name.lower()

        # Only true reasoning/thinking models benefit from <think> priming.
        # Lorablated models are abliterated instruct models, NOT reasoning models — no <think>
        is_thinking_model = any(x in model_lower for x in ['deepseek-r1', 'qwq', 'qwen3'])

        if 'gemma' in model_lower:
            full_prompt = f"""<start_of_turn>user
{self.system_prompt}
{pinned_memory}
{knowledge_context}
{daily_log}{shared_intel}
{memory_context}

If needed, you have these tools available:
{self._format_tool_descriptions()}
To use a tool, write: TOOL_CALL: tool_name(param="value", param2="value2")
Examples: TOOL_CALL: web_search(query="search terms") | TOOL_CALL: task_agent(agent="tinker", task="what to do") | TOOL_CALL: request_perception(source="camera")
Only use tools when actually necessary. For casual conversation, respond directly.
NEVER list, repeat, or echo the tool list in your response. Tools are for your use only — not for display.
Current date and time: {current_datetime}

{history_context}
{message}<end_of_turn>
<start_of_turn>model
"""

        elif any(x in model_lower for x in ['llama-3', 'nemotron', 'hermes', 'foundation-sec']):
            think_prefix = "<think>\n" if is_thinking_model else ""
            is_nemotron_super_model = 'nemotron' in model_lower and 'super' in model_lower
            if self.agent_name == 'aetheria' and is_nemotron_super_model:
                # Nemotron Super 120B — ChatML format
                # /no_think for default conversation: direct responses, no token waste on [THOUGHTS]
                # think_mode=True enables deep reasoning when explicitly needed
                thinking_toggle = "" if think_mode else "/no_think\n"
                full_prompt = f"""<|im_start|>system
{thinking_toggle}{self.system_prompt}
{pinned_memory}
If needed, you have these tools available:
{self._format_tool_descriptions()}
To use a tool write exactly: TOOL_CALL: tool_name(param="value", param2="value2")
Example: TOOL_CALL: post_to_board(message="System update complete.")
Example: TOOL_CALL: telegram_send(message="Hello Jon.")
Example: TOOL_CALL: task_agent(agent="tinker", task="check the logs")
Use TOOL_CALL format only. Do NOT use JSON format. Do NOT nest tool calls inside each other.
Only call tools when necessary. For conversation, respond directly.
Write plain sentences. No asterisks, no markdown.
NEVER echo or list the tool names in your response.
Current date and time: {current_datetime}<|im_end|>
<|im_start|>user
{history_context}
Jon: {message}<|im_end|>
<|im_start|>assistant
<think>"""
            else:
                # Non-Aetheria agents on Nemotron Super get /no_think — they need to act, not reason
                no_think_header = "/no_think\n" if ('nemotron' in model_lower and 'super' in model_lower and self.agent_name != 'aetheria') else ""
                full_prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>
{no_think_header}{self.system_prompt}
{pinned_memory}
{knowledge_context}
{daily_log}{shared_intel}
{memory_context}

If needed, you have these tools available:
{self._format_tool_descriptions()}
To use a tool, write: TOOL_CALL: web_search(query="your search here")
Only use tools when actually necessary. For casual conversation, respond directly.
NEVER list, repeat, or echo the tool list in your response. Tools are for your use only — not for display.
Current date and time: {current_datetime}<|eot_id|>
<|start_header_id|>user<|end_header_id|>
{history_context}
{message}<|eot_id|>
<|start_header_id|>assistant<|end_header_id|>
{think_prefix}"""

        else:
            # Default: ChatML (Qwen, Mistral, miqu, magnum, etc.)
            think_prefix = "<think>\n" if is_thinking_model else ""
            # /no_think goes at the START of the assistant turn (Qwen3 spec) — not in system
            no_think_prefix = "/no_think\n" if (is_thinking_model and self.agent_name in ['aetheria', 'scout', 'ares']) else ""
            # Aetheria: strip shared_intel/knowledge to avoid role confusion and context noise
            aetheria_shared = "" if self.agent_name == 'aetheria' else shared_intel
            aetheria_knowledge = "" if self.agent_name == 'aetheria' else knowledge_context
            full_prompt = f"""<|im_start|>system
{self.system_prompt}
{pinned_memory}
{aetheria_knowledge}
{daily_log}{aetheria_shared}
{memory_context}

If needed, you have these tools available:
{self._format_tool_descriptions()}
To use a tool, write: TOOL_CALL: web_search(query="your search here")
Only use tools when actually necessary. For casual conversation, respond directly.
NEVER list, repeat, or echo the tool list in your response. Tools are for your use only — not for display.
Current date and time: {current_datetime}
<|im_end|>
<|im_start|>user
{no_think_prefix}{history_context}
{message}<|im_end|>
<|im_start|>assistant
"""

        return [{"role": "user", "content": full_prompt}]
    def _format_tool_descriptions(self) -> str:
        """Format tool descriptions for system prompt"""
        if not self.tools.tool_names:
            return "No tools available."
        
        descriptions = []
        for tool_name in self.tools.tool_names:
            tool = self.tools.get(tool_name)
            descriptions.append(f"- {tool_name}: {tool.description}")
        
        return "\n".join(descriptions)
    
    async def _generate(
        self, 
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        top_k: int = 0,
        top_p: float = 0.95,
        min_p: float = 0.01,
        image_path: Optional[str] = None,
    ) -> str:
        """Call sovereign backend to generate response"""
    
        # Combine messages into single prompt
        prompt = messages[-1]['content']
    
        # Use passed image_path, fall back to _pending_image (set by perception tool), then current_image_path
        if image_path is None:
            image_path = getattr(self, '_pending_image', None) or getattr(self, 'current_image_path', None)
            self._pending_image = None  # consume it
    
        if image_path:
            print(f"[Vision] Sending image to model: {image_path}")

        try:
            # Call sovereign backend with ALL parameters
            response = sovereign_generate(
                agent_name=self.agent_name,
                model_name=self.model_name,  # FIXED: Now using self.model_name
                prompt=prompt,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature or self.temperature,
                repeat_penalty=repeat_penalty or 1.1,
                top_k=top_k,
                top_p=top_p,
                min_p=min_p,
                image_path=image_path,
                gpu_device=getattr(self, 'gpu_device', 0)
            )
        
            return response.strip()
    
        except Exception as e:
            print(f"â-- Generation error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return f"Error: {str(e)}"
    
    async def process_message_stream(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
        temperature: float = None,
        max_tokens: int = None,
        repeat_penalty: float = None,
        top_k: int = None,
        top_p: float = None,
        min_p: float = None,
        image_path: Optional[str] = None,
        think_mode: bool = False,
    ):
        """Stream tokens, with tool call interception"""
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        top_k = top_k if top_k is not None else self.top_k
        top_p = top_p if top_p is not None else self.top_p
        repeat_penalty = repeat_penalty if repeat_penalty is not None else self.repeat_penalty
        min_p = min_p if min_p is not None else self.min_p
        from sovereign_backend import sovereign_generate_stream
        # Apply Nemotron-Super think_mode sampler overrides
        _mn = self.model_name.lower()
        is_nemotron_super = ('nemotron' in _mn and 'super' in _mn) and self.agent_name == 'aetheria'
        if is_nemotron_super:
            # Unsloth model card: temp=1.0, top_p=0.95 for ALL tasks (reasoning, chat, tools)
            temperature = 1.0
            top_p = 0.95
            # Nemotron always generates [THOUGHTS] before [RESPONSE] — needs headroom regardless of think_mode
            max_tokens = max(max_tokens, 2000)
        messages = await self._build_messages(message, conversation_history, think_mode=think_mode)
        prompt = messages[-1]['content']
        if image_path is None:
            image_path = getattr(self, '_pending_image', None) or getattr(self, 'current_image_path', None)
            self._pending_image = None  # consume it
        full_response = ''
        for token in sovereign_generate_stream(
            agent_name=self.agent_name,
            model_name=self.model_name,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            image_path=image_path,
            gpu_device=getattr(self, 'gpu_device', 0),
            repeat_penalty=repeat_penalty,
            top_k=top_k,
            top_p=top_p,
            min_p=min_p,
        ):
            full_response += token
        import re as _re
        has_tool = ('TOOL_CALL:' in full_response or 'ACTION:' in full_response or
                    '<action>' in full_response.lower() or
                    '[TOOL' in full_response or
                    bool(_re.search(r'(?:next action|fetch|fetching|retrieve|get)\s*:?\s*(?:URL|url)?\s*https?://', full_response, _re.IGNORECASE)))

        # Aetheria fallback: auto-inject remember tool when she writes "remember: <text>" or "SAVE: <text>"
        if self.agent_name == 'aetheria' and 'TOOL_CALL: remember' not in full_response:
            remember_match = _re.search(r'(?:^|\n)(?:remember|SAVE|save):\s*(.+?)(?:\n|$)', full_response)
            if remember_match:
                note = remember_match.group(1).strip()
                if note:
                    print(f"[Aetheria] Auto-firing remember tool: {note[:60]}...")
                    full_response = full_response + f'\nTOOL_CALL: remember(note="{note}")'
                    has_tool = True

        # Aetheria fallback: auto-inject task_agent when she addresses an agent by name in text
        # Catches: "*Tinker — do X*" / "**Ares — check Y**" / "Tinker: do Z"
        if self.agent_name == 'aetheria' and not has_tool and 'task_agent' in self.tools.tool_names:
            _agent_task_pattern = _re.search(
                r'\*{0,2}(tinker|scout|ares|vett)\*{0,2}\s*[—\-–:]\s*([^\n\*]{10,200})',
                full_response, _re.IGNORECASE
            )
            if _agent_task_pattern:
                _target_agent = _agent_task_pattern.group(1).lower()
                _task_text = _agent_task_pattern.group(2).strip().rstrip('*').strip()
                print(f"[Aetheria] Auto-injecting task_agent for {_target_agent}: {_task_text[:60]}...")
                full_response = full_response + f'\nTOOL_CALL: task_agent(agent="{_target_agent}", task="{_task_text}")'
                has_tool = True

        # Scout fallback: if no tool call format detected but URLs are mentioned, auto-inject fetches
        if not has_tool and self.agent_name == 'scout':
            urls_found = _re.findall(r'https?://[^\s\)\"\'\]]+', full_response)
            # Filter out search engine URLs and only keep content/dealer URLs
            urls_found = [u.rstrip('.,)`*\'\"') for u in urls_found
                         if not any(x in u for x in ['google.com/search', 'bing.com/search', 'duckduckgo'])]
            if urls_found:
                print(f"[Scout] No tool call format — auto-injecting fetch for {len(urls_found)} URL(s)")
                injected = '\n'.join(f'TOOL_CALL: web_fetch(url="{u}")' for u in urls_found[:3])
                full_response = full_response + '\n' + injected
                has_tool = True

        import re as _re_think
        # Nemotron: [RESPONSE] lives inside <think> block — extract before stripping think
        _s_resp = _re_think.search(r'(?:\[RESPONSE\]|<response>)([\s\S]*?)(?:\[/RESPONSE\]|</response>|$)', full_response, _re_think.IGNORECASE)
        if _s_resp and _re_think.search(r'\[THOUGHTS\]', full_response, _re_think.IGNORECASE):
            full_response = _s_resp.group(1).strip()
        else:
            full_response = _re_think.sub(r'<think>[\s\S]*?</think>', '', full_response, flags=_re_think.IGNORECASE).strip()
            full_response = _re_think.sub(r'\[THOUGHTS\][\s\S]*?\[/THOUGHTS\]', '', full_response, flags=_re_think.IGNORECASE).strip()
            full_response = _re_think.sub(r'\[THOUGHTS\][\s\S]*', '', full_response, flags=_re_think.IGNORECASE).strip()
            full_response = _re_think.sub(r'\[RESPONSE\]\s*', '', full_response, flags=_re_think.IGNORECASE).strip()
            full_response = _re_think.sub(r'\s*\[/RESPONSE\]', '', full_response, flags=_re_think.IGNORECASE).strip()
        full_response = _re_think.sub(r'</think>', '', full_response, flags=_re_think.IGNORECASE).strip()
        full_response = _re_think.sub(r'<response>\s*', '', full_response, flags=_re_think.IGNORECASE).strip()
        full_response = _re_think.sub(r'\s*</response>', '', full_response, flags=_re_think.IGNORECASE).strip()
        full_response = _re_think.sub(r'<memory>[\s\S]*?</memory>', '', full_response, flags=_re_think.IGNORECASE).strip()
        full_response = _re_think.sub(r'<memory>[\s\S]*', '', full_response, flags=_re_think.IGNORECASE).strip()
        full_response = _re_think.sub(r'<tool_call>[\s\S]*?</tool_call>', '', full_response, flags=_re_think.IGNORECASE).strip()
        full_response = _re_think.sub(r'^\s*\{[^}]*"(?:name|agent)"[^}]*\}\s*', '', full_response, flags=_re_think.DOTALL).strip()
        # Strip leading role labels (e.g. "**Aetheria:**", "Aetheria:", "AETHERIA:")
        full_response = _re_think.sub(r'^\*{0,2}' + self.agent_name + r'\*{0,2}\s*:\s*', '', full_response, flags=_re_think.IGNORECASE).strip()
        # Strip leading ** markdown bold markers (Mistral Small 4 formatting habit)
        full_response = _re_think.sub(r'^\*\*\s*', '', full_response).strip()

        print(f"[Stream] Response length: {len(full_response)}, has TOOL_CALL: {has_tool}")

        if self.agent_name == 'aetheria' and _is_impersonating_jon(full_response):
            print("[Safety] Aetheria impersonating Jon — stream response blocked")
            yield "I can't send that."
            return
        if self.agent_name == 'aetheria' and _is_fake_thinking(full_response):
            print("[Safety] Aetheria fake thinking mode hallucination — stream response blocked")
            yield "I can't send that."
            return

        if not has_tool:
            await self._store_stream_memory(message, full_response)
            yield full_response
            return

        # Tool call loop — keeps executing tools until no more calls or max_iterations
        iteration = 0
        current_messages = messages
        accumulated_context = []

        while has_tool and iteration < self.max_iterations:
            iteration += 1
            tool_calls = self._parse_tool_calls(full_response)
            if not tool_calls:
                # Unparseable tool call — strip and return what we have
                import re as _re
                full_response = _re.sub(r'(?:TOOL_CALL|ACTION):.*', '', full_response, flags=_re.DOTALL).strip()
                break

            # Execute all tool calls in this iteration (dedup by name+params)
            seen_stream_calls = set()
            deduped_calls = []
            for tc in tool_calls:
                key = (tc['name'], str(sorted(tc.get('params', {}).items())))
                if key not in seen_stream_calls:
                    seen_stream_calls.add(key)
                    deduped_calls.append(tc)
                else:
                    print(f"[Stream Guard] Skipping duplicate tool call: {tc['name']}")
            print(f"[Stream] Tool iteration {iteration}/{self.max_iterations} — {len(deduped_calls)} tool(s)")
            for tool_call in deduped_calls:
                result = await self._execute_tool(tool_call)
                accumulated_context.append(f"[TOOL RESULT: {tool_call['name']}]: {result}")

            # Build feedback for next iteration
            tool_context = '\n'.join(accumulated_context)
            _write_only_names = {'remember', 'write_memory'}
            _lattice_write_actions = {'remember', 'connect', 'review'}
            only_write = all(
                tc['name'] in _write_only_names or
                (tc['name'] == 'lattice' and tc.get('params', {}).get('action') in _lattice_write_actions)
                for tc in deduped_calls
            )
            if only_write:
                # Memory was saved — strip TOOL_CALL lines and return what was said before them
                import re as _re_mem
                clean = _re_mem.sub(r'\nTOOL_CALL:.*', '', full_response, flags=_re_mem.DOTALL).strip()
                if clean:
                    await self._store_stream_memory(message, clean)
                    yield clean
                return

            # send_message fired — return what was written before the tool call (if anything)
            # Re-prompting after a send_message produces garbled output because the feedback
            # string lacks proper chat format (no system prompt, no Gemma turn tokens).
            if any(tc['name'] == 'send_message' for tc in deduped_calls):
                import re as _re_msg
                clean = _re_msg.sub(r'\nTOOL_CALL:.*', '', full_response, flags=_re_msg.DOTALL).strip()
                if clean:
                    await self._store_stream_memory(message, clean)
                    yield clean
                return

            # task_agent fired — surface Tinker/other agent's result inline, no re-prompt
            # Re-prompting with a raw feedback string (no chat format tokens) causes Gemma to
            # loop on the result text for ~1999 tokens until the degenerate detector kills it.
            if any(tc['name'] == 'task_agent' for tc in deduped_calls):
                import re as _re_ta
                pre_text = _re_ta.sub(r'\nTOOL_CALL:.*', '', full_response, flags=_re_ta.DOTALL).strip()
                # Extract the agent response from the tool result string
                raw_result = '\n'.join(accumulated_context)
                agent_resp = _re_ta.sub(
                    r'^\[TOOL RESULT: task_agent\]:\s*(?:\w+ RESPONSE:)?\s*',
                    '', raw_result, flags=_re_ta.IGNORECASE
                ).strip()
                if pre_text and agent_resp:
                    final = f"{pre_text}\n\n{agent_resp}"
                elif agent_resp:
                    final = agent_resp
                else:
                    final = pre_text
                if final:
                    await self._store_stream_memory(message, final)
                    yield final
                return

            # thermal fired — format result inline, no re-prompt
            if any(tc['name'] == 'thermal' for tc in deduped_calls):
                import re as _re_th
                pre_text = _re_th.sub(r'\nTOOL_CALL:.*', '', full_response, flags=_re_th.DOTALL).strip()
                raw_result = '\n'.join(accumulated_context)
                thermal_result = _re_th.sub(
                    r'^\[TOOL RESULT: thermal\]:\s*', '', raw_result, flags=_re_th.IGNORECASE
                ).strip()
                if pre_text and thermal_result:
                    final = f"{pre_text}\n\n{thermal_result}"
                elif thermal_result:
                    final = thermal_result
                else:
                    final = pre_text
                if final:
                    await self._store_stream_memory(message, final)
                    yield final
                return

            # generate_image fired — return the URL directly, no re-prompt
            if any(tc['name'] == 'generate_image' for tc in deduped_calls):
                import re as _re_img
                url_match = _re_img.search(r'https?://\S+', '\n'.join(accumulated_context))
                image_url = url_match.group(0).rstrip('.,)') if url_match else '\n'.join(accumulated_context)
                await self._store_stream_memory(message, image_url)
                yield image_url
                return

            elif self.agent_name == "scout":
                feedback = (
                    f"Tool results received. Review what was found, extract any contact details "
                    f"(names, phones, emails, addresses), then decide your next step: "
                    f"fetch another URL, run another search, or compile the final lead list "
                    f"if you have enough data. Keep going until you have real verified contacts.\n\n"
                    f"{tool_context}"
                )
            else:
                has_error = any("error:" in ctx.lower() or "failed" in ctx.lower() for ctx in accumulated_context)
                feedback_intro = (
                    "The tool returned an error. Tell the user the tool failed and what you tried, then either "
                    "try a different approach or ask for clarification.\n\n"
                    if has_error else
                    "Tool results received. Use this to answer directly and naturally. "
                    "Don't describe the process, just answer:\n\n"
                )
                feedback = (
                    f"{feedback_intro}"
                    f"{tool_context}"
                )

            current_messages.append({'role': 'user', 'content': feedback})
            next_messages = current_messages
            # For Gemma models (chat_format=None), the re-prompt must be a full
            # <start_of_turn>-formatted string or generate_stream falls to raw completion
            # mode and loops for 1999 tokens on the feedback text.
            if 'gemma' in self.model_name.lower():
                _parts = []
                for _m in next_messages:
                    _role = 'user' if _m['role'] == 'user' else 'model'
                    _parts.append(f"<start_of_turn>{_role}\n{_m['content']}<end_of_turn>")
                _parts.append("<start_of_turn>model\n")
                next_prompt = '\n'.join(_parts)
            else:
                next_prompt = next_messages[-1]['content']

            # Extract image path from tool results if perception tool fired
            import re as _re_vis
            next_image_path = None
            for ctx in accumulated_context:
                vis_match = _re_vis.search(r'\[VISION_IMAGE:([^\]]+)\]', ctx)
                if vis_match:
                    next_image_path = vis_match.group(1).strip()
                    break
            full_response = ''
            for token in sovereign_generate_stream(
                agent_name=self.agent_name,
                model_name=self.model_name,
                prompt=next_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                image_path=next_image_path,
                gpu_device=getattr(self, 'gpu_device', 0),
                repeat_penalty=repeat_penalty,
                top_k=top_k,
                top_p=top_p,
                min_p=min_p,
            ):
                full_response += token

            has_tool = ('TOOL_CALL:' in full_response or 'ACTION:' in full_response or
                        '<action>' in full_response.lower() or
                        '[TOOL_CALL:' in full_response or
                        bool(_re.search(r'(?:next action|fetch|fetching|retrieve|get)\s*:?\s*(?:URL|url)?\s*https?://', full_response, _re.IGNORECASE)))

            # Scout fallback inside loop: auto-inject fetches for any URLs mentioned
            if not has_tool and self.agent_name == 'scout':
                urls_found = _re.findall(r'https?://[^\s\)\"\'\]]+', full_response)
                urls_found = [u.rstrip('.,)`*\'\"') for u in urls_found
                             if not any(x in u for x in ['google.com/search', 'bing.com/search', 'duckduckgo'])]
                if urls_found:
                    print(f"[Scout] Loop auto-injecting fetch for {len(urls_found)} URL(s)")
                    injected = '\n'.join(f'TOOL_CALL: web_fetch(url="{u}")' for u in urls_found[:3])
                    full_response = full_response + '\n' + injected
                    has_tool = True

        # Strip think blocks from final tool-loop response
        full_response = _re_think.sub(r'<think>[\s\S]*?</think>', '', full_response, flags=_re_think.IGNORECASE).strip()

        # Stream final response to client
        final_tool_response = ''
        for char in full_response:
            final_tool_response += char
            yield char
        await self._store_stream_memory(message, final_tool_response)

    async def stream_voice(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
        on_sentence=None,
        temperature: float = None,
        max_tokens: int = 300,
    ) -> tuple:
        """
        Voice-optimised streaming. Fires on_sentence(text) for each complete sentence
        as tokens arrive — so TTS can start on the first sentence immediately.

        Returns (cleaned_response: str, has_tool: bool).
        If has_tool is True, caller should fall back to process_message for tool handling.
        """
        import re as _re
        from sovereign_backend import sovereign_generate_stream

        temperature = temperature if temperature is not None else self.temperature
        messages = await self._build_messages(message, conversation_history or [])
        prompt = messages[-1]['content']

        full_response = ''
        sentence_buf = ''
        in_tool_section = False
        first_sentence_fired = False

        for token in sovereign_generate_stream(
            agent_name=self.agent_name,
            model_name=self.model_name,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            gpu_device=getattr(self, 'gpu_device', 0),
            repeat_penalty=self.repeat_penalty,
            top_k=self.top_k,
            top_p=self.top_p,
            min_p=self.min_p,
        ):
            full_response += token

            # Stop buffering for TTS once a tool call starts
            if not in_tool_section and (
                'TOOL_CALL:' in full_response or 'ACTION:' in full_response
            ):
                in_tool_section = True
                # Flush whatever clean text came before the tool call
                pre_tool = _re.split(r'TOOL_CALL:|ACTION:', full_response)[0].strip()
                remaining_buf = sentence_buf.strip()
                if remaining_buf and on_sentence:
                    on_sentence(remaining_buf)
                sentence_buf = ''
                continue

            if not in_tool_section:
                sentence_buf += token
                # Fire on sentence end: min 55 chars + punctuation + whitespace/end
                m = _re.search(r'^(.{55,}?[.!?])\s+', sentence_buf)
                if m:
                    sentence = m.group(1).strip()
                    sentence_buf = sentence_buf[m.end():]
                    if on_sentence:
                        on_sentence(sentence)
                    first_sentence_fired = True

        # Flush remaining sentence buffer
        remaining = sentence_buf.strip()
        # Don't double-fire short tail if it's part of a tool call
        if remaining and not in_tool_section and on_sentence:
            # If first sentence never fired, this IS the whole response — fire regardless of length
            if not first_sentence_fired or len(remaining) > 20:
                on_sentence(remaining)

        has_tool = 'TOOL_CALL:' in full_response or 'ACTION:' in full_response

        # Clean think/tool tags from response before storing
        cleaned = _re.sub(r'<think>[\s\S]*?</think>', '', full_response, flags=_re.IGNORECASE).strip()
        cleaned = _re.sub(r'\[THOUGHTS\][\s\S]*?\[/THOUGHTS\]', '', cleaned, flags=_re.IGNORECASE).strip()
        cleaned = _re.sub(r'\[RESPONSE\]\s*', '', cleaned, flags=_re.IGNORECASE).strip()
        cleaned = _re.sub(r'TOOL_CALL:.*', '', cleaned, flags=_re.MULTILINE).strip()
        # Strip leading role label
        cleaned = _re.sub(r'^' + self.agent_name + r'\s*:\s*', '', cleaned, flags=_re.IGNORECASE).strip()

        if not has_tool:
            await self._store_stream_memory(message, cleaned)

        return cleaned, has_tool

    async def _store_stream_memory(self, message: str, response: str):
        """Write response to agent-specific daily log and persistent memory after streaming completes."""
        if self.agent_name != 'aetheria' or _should_log_aetheria(response):
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                mem_base = os.path.join(os.path.dirname(__file__), '..', 'soveryn_memory', 'memory')
                agent_log_dir = os.path.join(mem_base, self.agent_name)
                os.makedirs(agent_log_dir, exist_ok=True)
                log_path = os.path.join(agent_log_dir, f'{today}.md')
                timestamp = datetime.now().strftime("%H:%M")
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"\n## {timestamp}\n")
                    f.write(f"**Jon:** {message[:300]}\n\n")
                    f.write(f"**{self.agent_name.title()}:** {response[:500]}\n\n")
            except Exception as e:
                print(f"[Daily Log] Write error: {e}")
        try:
            await self.persistent_memory.store_conversation(self.agent_name, 'user', message)
            await self.persistent_memory.store_conversation(self.agent_name, 'assistant', response)
        except Exception as e:
            print(f"[Persistent Memory] Stream error: {e}")

    def _parse_tool_calls(self, response: str) -> List[Dict]:
        """
        Parse tool calls from LLM response.
    
        Handles multiple formats:
        - TOOL_CALL: tool_name(param="value")
        - tool_name("value")
        - WEB_SEARCH: "query"
        - RETRIEVE_MEMORY: "query"
        """
        import re
    
        tool_calls = []
    
        # Pattern 1: UPPERCASE_TOOL: "value"
        uppercase_pattern = r'(WEB_SEARCH|RETRIEVE_MEMORY|ANALYZE_IMAGE):\s*"([^"]+)"'
        matches = re.finditer(uppercase_pattern, response)
    
        for match in matches:
            tool_name = match.group(1).lower()  # Convert to lowercase
            value = match.group(2)
        
            # Map to correct parameter name
            if tool_name == 'web_search':
                params = {'query': value}
            elif tool_name == 'retrieve_memory':
                params = {'query': value}
            elif tool_name == 'analyze_image':
                params = {'image_path': value}
            else:
                params = {'query': value}
        
            tool_calls.append({
                'name': tool_name,
                'params': params
            })
       
        import json as _json

        def _fix_json(raw: str) -> dict:
            """Best-effort JSON repair for Nemotron's occasionally malformed output."""
            raw = raw.replace(': None', ': null').replace(': True', ': true').replace(': False', ': false')
            try:
                return _json.loads(raw)
            except Exception:
                pass
            # Try closing any unterminated string/object
            for suffix in ['"}', '"}}'.replace('', ''), '"}']:
                try:
                    return _json.loads(raw + suffix)
                except Exception:
                    pass
            return {}

        # Pattern 1b: [TOOL CALL: tool_name]: {json} — Nemotron [TOOL CALL:] format
        pattern1b = r'\[TOOL CALL:\s*(\w+)\]:\s*(\{.*?\})'
        for _m in re.finditer(pattern1b, response, re.DOTALL):
            _tname = _m.group(1)
            _params = _fix_json(_m.group(2))
            tool_calls.append({'name': _tname, 'params': _params})

        # Pattern 1c: <tool_call>{"name": "fn", "parameters": {...}}</tool_call> — NVIDIA native XML
        pattern1c = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for _m in re.finditer(pattern1c, response, re.DOTALL):
            _obj = _fix_json(_m.group(1))
            _tname = _obj.get('name') or _obj.get('function')
            _params = _obj.get('parameters') or _obj.get('arguments') or {}
            if _tname:
                tool_calls.append({'name': _tname, 'params': _params})

        # Pattern 1d: {"name": "fn", "parameters": {...}} — bare JSON tool call
        pattern1d = r'^\s*\{"name":\s*"(\w+)",\s*"(?:parameters|arguments)":\s*(\{.*?\})\}'
        for _m in re.finditer(pattern1d, response, re.DOTALL | re.MULTILINE):
            _tname = _m.group(1)
            _params = _fix_json(_m.group(2))
            tool_calls.append({'name': _tname, 'params': _params})

        # Pattern 1e: {"agent": "X", "task": "Y"} — Nemotron task_agent shorthand JSON
        pattern1e = r'\{"agent":\s*"(\w+)",\s*"task":\s*"([^"]+)"\}'
        for _m in re.finditer(pattern1e, response, re.DOTALL):
            tool_calls.append({'name': 'task_agent', 'params': {'agent': _m.group(1), 'task': _m.group(2)}})

        # Pattern 2: TOOL_CALL: tool_name(params) — also catches **ACTION:** format
        # re.DOTALL so (.*?) matches newlines inside multi-line email body params
        pattern2 = r'(?:\*{0,2}(?:TOOL_CALL|ACTION):\*{0,2})\s*(\w+)\((.*?)\)'
        matches = re.finditer(pattern2, response, re.DOTALL)
    
        for match in matches:
            tool_name = match.group(1)
            params_str = match.group(2)
            params = self._parse_params(params_str, tool_name)
        
            tool_calls.append({
                'name': tool_name,
                'params': params
            })
    
        # Pattern 3: tool_name("value") or tool_name(param="value")
        tool_names = list(self.tools.tool_names)
    
        for tool_name in tool_names:
            pattern3 = rf'{tool_name}\((.*?)\)'
            matches = re.finditer(pattern3, response, re.DOTALL)
        
            for match in matches:
                params_str = match.group(1)
                params = self._parse_params(params_str, tool_name)
            
                tool_calls.append({
                    'name': tool_name,
                    'params': params
                })
                
        # [STAR] FILTER OUT INVALID/PLACEHOLDER TOOL NAMES [STAR]
        valid_tool_names = self.tools.tool_names
        filtered_calls = []

        for tool_call in tool_calls:
            tool_name = tool_call.get('name', '')
    
            # Skip obvious placeholders
            if tool_name in ['tool_name', 'example_tool', 'your_tool']:
                print(f"âš ï¸  Skipping placeholder: {tool_name}")
                continue
    
            # Skip if tool doesn't exist — try fuzzy correction first
            if tool_name not in valid_tool_names:
                import difflib
                matches = difflib.get_close_matches(tool_name, valid_tool_names, n=1, cutoff=0.85)
                if matches:
                    print(f"⚠️  Unknown tool '{tool_name}', auto-corrected to '{matches[0]}'")
                    tool_call['name'] = matches[0]
                    tool_name = matches[0]
                else:
                    print(f"⚠️  Unknown tool '{tool_name}', skipping")
                    continue
    
            filtered_calls.append(tool_call)

        # Pattern 4: XML-style <action>tool_name: value</action> or <action>tool_name(params)</action>
        action_blocks = re.finditer(r'<action>\s*([\w_]+)\s*[:\(](.*?)\s*</action>', response, re.DOTALL | re.IGNORECASE)
        for match in action_blocks:
            tool_name = match.group(1).lower().strip()
            raw_val = match.group(2).strip().rstrip(')')
            if tool_name in ('web_fetch', 'browser_fetch', 'crawl_page'):
                url = raw_val.strip()
                tool_calls.append({'name': tool_name, 'params': {'url': url}})
            elif tool_name in ('web_search',):
                tool_calls.append({'name': tool_name, 'params': {'query': raw_val}})
            else:
                params = self._parse_params(raw_val, tool_name)
                tool_calls.append({'name': tool_name, 'params': params})

        # Pattern 5: [TOOL: tool_name(params)] or [TOOL_CALL: ...]
        bracket_tools = re.finditer(r'\[TOOL(?:_CALL)?[:\s]+(\w+)\((.*?)\)\]?', response, re.DOTALL)
        for match in bracket_tools:
            tool_name = match.group(1)
            params_str = match.group(2)
            params = self._parse_params(params_str, tool_name)
            tool_calls.append({'name': tool_name, 'params': params})

        # Pattern 6: Plain-language URL fetch narration
        # Catches: "Next action: Fetch URL https://..." / "fetch https://..." / "Let's fetch https://..."
        url_narration = re.finditer(
            r'(?:next action|fetch|fetching|retrieve|get)\s*:?\s*(?:URL|url|the url|the page)?\s*(https?://[^\s\)\"\']+)',
            response, re.IGNORECASE
        )
        for match in url_narration:
            url = match.group(1).rstrip('.,)')
            # Only add if not already parsed via another pattern
            already = any(tc['name'] in ('web_fetch', 'browser_fetch') and tc['params'].get('url') == url
                         for tc in tool_calls)
            if not already and 'web_fetch' in valid_tool_names:
                tool_calls.append({'name': 'web_fetch', 'params': {'url': url}})

        # Apply the same validity filter to patterns 4-6 results
        valid_tool_names = self.tools.tool_names  # re-bind in case it changed
        for tc in tool_calls:
            if tc not in filtered_calls:
                name = tc.get('name', '')
                if name and name not in ['tool_name', 'example_tool', 'your_tool'] and name in valid_tool_names:
                    filtered_calls.append(tc)

        return filtered_calls
        
    async def _execute_tool(self, tool_call: dict) -> str:
        """Execute a single tool call"""
        import time
        tool_name = tool_call.get('name')
        tool_params = tool_call.get('params', {})
        start_ms = int(time.time() * 1000)
        try:
            # Skip empty tool calls
            if not tool_params or all(not v for v in tool_params.values()):
                return "Tool skipped: no parameters provided"

            # Block pointless date/time searches
            if tool_name == 'web_search':
                query = tool_params.get('query', '').lower()
                date_terms = ['current date', 'current time', 'today date', 'what time', 'what date', 'february', 'date and time', 'time and date']
                if any(term in query for term in date_terms):
                    print(f"  [STOP] Blocked date search: {query}")
                    return "The current date and time are already in your context. No search needed."

            print(f"  -> Executing {tool_name}({str(tool_params)[:100]}...)")
            result = await self.tools.execute(tool_name, tool_params)
            duration = int(time.time() * 1000) - start_ms
            print(f"  [OK] Result: {str(result)[:100]}...")
            try:
                await self.persistent_memory.log_tool_call(
                    agent=self.agent_name,
                    tool_name=tool_name,
                    arguments=tool_params,
                    result=str(result),
                    duration_ms=duration,
                    success=True
                )
            except Exception:
                pass
            return result

        except Exception as e:
            error_msg = f"Tool execution error: {e}"
            print(f"  [ERR] {error_msg}")
            try:
                await self.persistent_memory.log_tool_call(
                    agent=self.agent_name,
                    tool_name=tool_name or 'unknown',
                    arguments=tool_params,
                    result=error_msg,
                    duration_ms=int(time.time() * 1000) - start_ms,
                    success=False,
                    error=str(e)
                )
            except Exception:
                pass
            return error_msg

    def _parse_params(self, params_str: str, tool_name: str) -> Dict:
        """Parse parameter string into dict"""
        import re
        import json as _json

        params = {}

        # Try key="value" format
        param_pattern = r'(\w+)="([^"]*)"'
        matches = re.finditer(param_pattern, params_str)
        for match in matches:
            params[match.group(1)] = match.group(2)

        # Try key='value' format
        if not params:
            param_pattern = r"(\w+)='([^']*)'"
            matches = re.finditer(param_pattern, params_str)
            for match in matches:
                params[match.group(1)] = match.group(2)

        # Capture unquoted booleans: key=true / key=false
        for match in re.finditer(r'(\w+)=(true|false)\b', params_str):
            key = match.group(1)
            if key not in params:
                params[key] = match.group(2) == 'true'

        # Capture array values: key=["a", "b"] or key=['a', 'b']
        for match in re.finditer(r'(\w+)=(\[[^\]]*\])', params_str):
            key = match.group(1)
            if key not in params:
                try:
                    params[key] = _json.loads(match.group(2).replace("'", '"'))
                except Exception:
                    pass

        # Capture unquoted integers: key=42
        for match in re.finditer(r'(\w+)=(-?\d+)\b', params_str):
            key = match.group(1)
            if key not in params:
                params[key] = int(match.group(2))
        
        # If no key=value found, treat entire string as content
        if not params:
            cleaned = params_str.strip().strip('"').strip("'")
            if tool_name == 'web_search':
                params['query'] = cleaned
            elif tool_name == 'retrieve_memory':
                params['query'] = cleaned
            elif tool_name == 'write_memory':
                params['category'] = 'general'
                params['content'] = cleaned
            elif tool_name == 'analyze_image':
                params['image_path'] = cleaned
            else:
                params['query'] = cleaned
        
        return params

