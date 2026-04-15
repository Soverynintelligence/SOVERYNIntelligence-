"""
View Tool - Read files and directories
"""
from core.tool_base import Tool
from typing import Any, Dict
import os
from pathlib import Path

class ViewTool(Tool):
    """View files and directories for security audit"""
    
    @property
    def name(self) -> str:
        return "view"
    
    @property
    def description(self) -> str:
        return """View file contents or list directory contents. Use for security audits and code review. Provide absolute or relative path."""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to file or directory to view"
                }
            },
            "required": ["path"]
        }
    
    async def execute(self, path: str = "", **kwargs) -> str:
        """View file or directory"""
        try:
            if not path:
                return "Error: Must provide path"
            
            p = Path(path)
            
            # Security: Only allow access to project directory
            project_root = Path.cwd()
            try:
                resolved = p.resolve()
                resolved.relative_to(project_root)
            except:
                return f"Error: Access denied - path outside project directory"
            
            if not p.exists():
                return f"Error: Path does not exist: {path}"
            
            # Directory listing
            if p.is_dir():
                items = []
                for item in sorted(p.iterdir()):
                    item_type = "DIR" if item.is_dir() else "FILE"
                    items.append(f"{item_type}: {item.name}")
                return f"Directory: {path}\n" + "\n".join(items[:100])  # Limit to 100 items
            
            # File reading
            if p.is_file():
                # Only read text files
                if p.suffix in ['.py', '.txt', '.md', '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini', '.conf']:
                    with open(p, 'r', encoding='utf-8') as f:
                        content = f.read(10000)  # Limit to 10KB
                        return f"File: {path}\n\n{content}"
                else:
                    return f"File: {path}\nBinary file - cannot display"
            
            return f"Error: Unknown path type: {path}"
            
        except Exception as e:
            return f"Error viewing {path}: {e}"