"""
Library Search Tool — Aetheria searches her document library.
Returns the most relevant passages from ingested papers and documents.
"""
from pathlib import Path
from typing import Any, Dict
from core.tool_base import Tool

import chromadb
from chromadb.config import Settings
from sovereign_embeddings import sovereign_embed

CHROMA_PATH = Path(__file__).parent.parent / "soveryn_memory" / "chromadb"
COLLECTION_NAME = "soveryn_library"


def _get_collection():
    client = chromadb.PersistentClient(
        path=str(CHROMA_PATH),
        settings=Settings(anonymized_telemetry=False)
    )
    return client.get_or_create_collection(COLLECTION_NAME)


class LibrarySearchTool(Tool):
    """Search Aetheria's document library for relevant passages."""

    @property
    def name(self) -> str:
        return "search_library"

    @property
    def description(self) -> str:
        return (
            "Search the document library for relevant information. "
            "Use when you want to find what a paper says, look up a specific concept, "
            "or check what's been written about a topic. Returns the most relevant passages."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What you're looking for"
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of passages to return (default 4)",
                    "default": 4
                }
            },
            "required": ["query"]
        }

    async def execute(self, query: str = "", n_results: int = 4, **kw) -> str:
        if not query.strip():
            return "No query provided."
        try:
            collection = _get_collection()
            count = collection.count()
            if count == 0:
                return "Library is empty — no documents have been ingested yet."

            emb = sovereign_embed(query)
            if not emb:
                return "Could not generate query embedding."

            results = collection.query(
                query_embeddings=[emb],
                n_results=min(n_results, count),
                include=["documents", "metadatas", "distances"]
            )

            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            if not docs:
                return "No relevant passages found."

            lines = []
            for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances)):
                source = meta.get("source", "unknown")
                relevance = round((1 - dist) * 100, 1)
                lines.append(f"[{i+1}] Source: {source} (relevance: {relevance}%)\n{doc.strip()}")

            return "\n\n---\n\n".join(lines)

        except Exception as e:
            return f"Library search error: {e}"
