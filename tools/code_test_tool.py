"""
Code Test Tool for Tinker
Lets Tinker validate code before proposing a fix:
  - syntax_check  : python3 -m py_compile
  - lint          : flake8 (if installed)
  - import_check  : verify a module can be imported
  - run_tests     : pytest on a specific path
All operations are sandboxed to the project directory.
"""
import subprocess
import sys
from pathlib import Path
from core.tool_base import Tool

BASE_DIR = Path(__file__).parent.parent


def _run(cmd: list, timeout: int = 30) -> tuple[int, str]:
    """Run a subprocess, return (returncode, combined_output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=timeout,
            cwd=str(BASE_DIR)
        )
        out = result.stdout
        if result.stderr:
            out += ("\n" if out else "") + result.stderr
        return result.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 1, f"Timed out after {timeout}s"
    except FileNotFoundError:
        return 1, f"Command not found: {cmd[0]}"
    except Exception as ex:
        return 1, str(ex)


class CodeTestTool(Tool):
    """
    Tinker uses this to validate code before submitting a fix proposal.
    Run syntax checks, lint, or tests to confirm a change doesn't break anything.
    """

    @property
    def name(self): return "code_test"

    @property
    def description(self):
        return (
            "Validate code quality before proposing a fix. "
            "Operations: 'syntax_check' (parse errors), 'lint' (style/logic issues), "
            "'import_check' (verify a module imports cleanly), 'run_tests' (run pytest). "
            "Always syntax_check before proposing any fix."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["syntax_check", "lint", "import_check", "run_tests"],
                    "description": "What to run"
                },
                "target": {
                    "type": "string",
                    "description": (
                        "Relative file/module/path from project root. "
                        "For syntax_check/lint: file path (e.g. 'core/agent_loop.py'). "
                        "For import_check: module name (e.g. 'core.agent_loop'). "
                        "For run_tests: test path (e.g. 'tests/' or 'tests/test_memory.py')."
                    )
                }
            },
            "required": ["operation", "target"]
        }

    async def execute(self, operation: str = "", target: str = "", **kw) -> str:
        # Prevent path traversal
        if ".." in target or target.startswith("/"):
            return "CodeTestTool: target must be a relative path within the project."

        if operation == "syntax_check":
            full = BASE_DIR / target
            if not full.exists():
                return f"File not found: {target}"
            code, out = _run([sys.executable, "-m", "py_compile", str(full)])
            if code == 0:
                return f"SYNTAX OK: {target}"
            return f"SYNTAX ERROR in {target}:\n{out}"

        elif operation == "lint":
            full = BASE_DIR / target
            if not full.exists():
                return f"File not found: {target}"
            code, out = _run([
                sys.executable, "-m", "flake8",
                str(full),
                "--max-line-length=120",
                "--ignore=E501,W503,E302,E303"
            ])
            if code == 0:
                return f"LINT CLEAN: {target}"
            return f"LINT ISSUES in {target}:\n{out}"

        elif operation == "import_check":
            code, out = _run([
                sys.executable, "-c", f"import {target}; print('OK')"
            ], timeout=15)
            if code == 0:
                return f"IMPORT OK: {target}"
            return f"IMPORT FAILED: {target}\n{out}"

        elif operation == "run_tests":
            full = BASE_DIR / target
            if not full.exists():
                return f"Test path not found: {target}"
            code, out = _run([
                sys.executable, "-m", "pytest",
                str(full),
                "-x", "--tb=short", "-q", "--no-header"
            ], timeout=120)
            status = "PASSED" if code == 0 else "FAILED"
            return f"TESTS {status}: {target}\n\n{out[:3000]}"

        return f"Unknown operation: {operation}"
