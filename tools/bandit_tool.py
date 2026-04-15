import subprocess
import json
from typing import Any, Dict
from core.tool_base import Tool

class BanditTool(Tool):
    """Security scanning using Bandit"""
    
    @property
    def name(self) -> str:
        return "bandit"
    
    @property
    def description(self) -> str:
        return "Run Bandit security scanner on Python code to find vulnerabilities"
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory or file to scan (default: '.')"
                }
            },
            "required": []
        }
    
    async def execute(self, path: str = ".") -> str:
        """
        Run Bandit security scan
        
        Args:
            path: Directory or file to scan (default: current directory)
        
        Returns:
            JSON string with security findings
        """
        try:
            # Run Bandit - scan current dir but exclude ComfyUI and venv
            result = subprocess.run(
                [
                    'bandit', 
                    '-r', path,
                    '-f', 'json',
                    '-x', 'ComfyUI,venv,node_modules'
                ],          
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Parse the JSON output
            output = result.stdout
            
            # DEBUG: Print what we got
            print(f"🔍 Bandit return code: {result.returncode}")
            print(f"🔍 Stdout length: {len(output)} chars")
            print(f"🔍 Stderr: {result.stderr[:100] if result.stderr else 'None'}")
            
            # STRIP THE PROGRESS BAR - Bandit adds "Working... 100%" before JSON
            if output.startswith("Working..."):
                # Find the actual JSON start
                json_start = output.find('\n{')
                if json_start != -1:
                    output = output[json_start+1:]  # Skip the newline, keep the {
                    print(f"🔍 Stripped progress bar, new length: {len(output)} chars")

            
            # If stdout is empty, return error
            if not output or len(output) < 10:
                return json.dumps({
                    "error": "Bandit returned empty output",
                    "stderr": result.stderr,
                    "return_code": result.returncode
                })
            
            # Parse JSON to extract key metrics
            try:
                data = json.loads(output)
                metrics = data.get('metrics', {}).get('_totals', {})
                findings = data.get('results', [])
                
                # Build simplified response
                response = {
                    "total_issues": len(findings),
                    "high_severity": metrics.get('SEVERITY.HIGH', 0),
                    "medium_severity": metrics.get('SEVERITY.MEDIUM', 0),
                    "low_severity": metrics.get('SEVERITY.LOW', 0),
                    "findings": findings
                }
                
                return json.dumps(response, indent=2)
                
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"JSON decode failed: {str(e)}", "raw_output": output[:500]})
                
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "Bandit scan timed out after 60 seconds"})
        except Exception as e:
            return json.dumps({"error": f"Bandit scan failed: {str(e)}"})