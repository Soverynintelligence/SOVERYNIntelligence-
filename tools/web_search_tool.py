"""
Web Search Tool - Wraps your existing Brave API search
"""
from core.tool_base import Tool
from typing import Any, Dict

class WebSearchTool(Tool):
    """Search the web using Brave API"""
    
    @property
    def name(self) -> str:
        return "web_search"
    
    @property
    def description(self) -> str:
        return "Search the web for current information. Use for recent events, current facts, or technical documentation."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results (default 3)",
                    "default": 3
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, query: str, num_results: int = 3, **kwargs) -> str:
        """Execute web search using your existing function"""
        try:
            from web_search import search_web
            
            results = search_web(query, num_results)
            
            if not results:
                return f"No search results found for: {query}"
            
            # Format results
            formatted = f"Web search results for '{query}':\n\n"
            for i, r in enumerate(results, 1):
                formatted += f"{i}. {r['title']}\n"
                formatted += f"   {r['description'][:200]}\n"
                formatted += f"   URL: {r['url']}\n\n"
            
            return formatted
        except Exception as e:
            return f"Web search error: {e}"