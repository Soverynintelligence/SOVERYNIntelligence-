"""
Bash Tool - SECURED with Human-in-the-Loop
"""
from core.tool_base import Tool
from typing import Any, Dict
import subprocess
import os
import re

class BashTool(Tool):
    """Execute bash commands with human approval for dangerous operations"""

    def __init__(self, agent_name: str = 'ares'):
        self._agent_name = agent_name

    # WHITELIST of safe read-only/coding commands
    SAFE_COMMANDS = [
        # System info
        'ls', 'dir', 'pwd', 'whoami', 'hostname',
        'ps', 'tasklist', 'netstat', 'ipconfig', 'ifconfig',
        'echo', 'cat', 'type', 'head', 'tail',
        'wc', 'find', 'where', 'which',
        'nvidia-smi', 'nvcc',
        # Coding / dev
        'python', 'python3', 'pytest', 'pip', 'pip3',
        'git', 'grep', 'diff', 'tree', 'env',
        'conda', 'node', 'npm',
    ]
    
    # Patterns that ALWAYS require approval
    DANGEROUS_PATTERNS = [
        r'rm\s', r'del\s', r'format', r'mkfs',
        r'dd\s', r'wget', r'curl', r'powershell',
        r'chmod\s+[0-7]{3}', r'chown', r'sudo',
        r'kill\s', r'taskkill', r'shutdown', r'reboot',
        r'>\s*/', r'>\s*~', r'>\s*\$',  # File overwrites
        r'\|', r'&&', r';',  # Command chaining
        r'`', r'\$\(', r'\$\{',  # Command substitution
        r'base64', r'xxd', r'hexdump'  # Encoding (bypass attempts)
    ]
    
    @property
    def name(self) -> str:
        return "bash"
    
    @property
    def description(self) -> str:
        return """Execute bash/shell commands for security audits. 
        
SAFE COMMANDS (auto-execute): ls, dir, ps, netstat, etc.
DANGEROUS COMMANDS (require approval): Anything that modifies system, chains commands, or uses encoding.

When requesting approval, explain WHY you need this command."""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this command is needed (required for dangerous commands)"
                }
            },
            "required": ["command"]
        }
    
    def _is_safe_command(self, command: str) -> bool:
        """Check if command is whitelisted as safe"""
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False
        
        base_cmd = cmd_parts[0].lower()
        return base_cmd in self.SAFE_COMMANDS
    
    def _is_dangerous(self, command: str) -> bool:
        """Check if command matches dangerous patterns"""
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False
    
    async def execute(self, command: str = "", reason: str = "", **kwargs) -> str:
        """Execute shell command with approval for dangerous ops"""
        try:
            if not command:
                return "Error: Must provide command"
            
            # Check if safe command
            if self._is_safe_command(command):
                return await self._execute_command(command)
            
            # Check if dangerous
            if self._is_dangerous(command):
                return self._request_approval(command, reason)
            
            # Default: Require approval for unknown commands
            return self._request_approval(command, reason or "Unknown command type")
            
        except Exception as e:
            return f"Error: {e}"
    
    def _request_approval(self, command: str, reason: str) -> str:
        """Request human approval for dangerous command"""
        from tools.approval_queue import approval_queue
        
        request_id = approval_queue.add_request(
            agent=self._agent_name,
            tool="bash",
            command=command,
            reason=reason
        )
        
        return f"""⚠️ APPROVAL REQUIRED

Command: {command}
Reason: {reason}
Request ID: {request_id}

This command requires human approval. To approve:
1. Review the command and reason carefully
2. Use the approval interface to approve/reject
3. Re-run your query after approval

SECURITY: This command was blocked because it could modify your system or chain multiple operations."""
    
    async def _execute_command(self, command: str) -> str:
        """Actually execute the command"""
        try:
            result = subprocess.run(
                command,
                shell=True,  # nosec - This tool is intentionally designed to execute shell commands
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getcwd()
            )
            
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            
            if len(output) > 5000:
                output = output[:5000] + "\n... (output truncated)"
            
            return output or "Command executed successfully (no output)"
            
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error executing command: {e}"