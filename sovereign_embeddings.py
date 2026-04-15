"""
SOVEREIGN EMBEDDINGS — llama.cpp backend
Uses nomic-embed-text-v1.5 GGUF for local embeddings.
No PyTorch required — works on Blackwell and all hardware.
"""

from pathlib import Path
from typing import List, Optional

MODEL_PATH = Path.home() / "SOVERYN_Models" / "GGUF" / "nomic-embed-text-v1.5.Q8_0.gguf"

_model = None


def _get_model():
    global _model
    if _model is None:
        from llama_cpp import Llama
        print(f"[Embeddings] Loading nomic-embed-text from {MODEL_PATH}...")
        _model = Llama(
            model_path=str(MODEL_PATH),
            embedding=True,
            n_ctx=2048,
            n_gpu_layers=-1,
            main_gpu=1,        # Quadro — leave Blackwell for Aetheria
            verbose=False,
        )
        print("[Embeddings] nomic-embed-text loaded.")
    return _model


def sovereign_embed(text: str) -> Optional[List[float]]:
    """Generate embedding for text. Returns list of floats or None on failure."""
    if not text or not text.strip():
        return None
    try:
        model = _get_model()
        result = model.embed(text.strip()[:2000])
        if isinstance(result, list) and len(result) > 0:
            if isinstance(result[0], list):
                return result[0]
            return result
        return None
    except Exception as e:
        print(f"[Embeddings] Error: {e}", flush=True)
        return None


class SovereignEmbedder:
    """Compatibility wrapper — used by legacy code."""

    def embed(self, text: str) -> list:
        return sovereign_embed(text) or []

    def embed_batch(self, texts: list) -> list:
        return [sovereign_embed(t) or [] for t in texts]


# Legacy compatibility
def get_embedder() -> SovereignEmbedder:
    return SovereignEmbedder()


if __name__ == "__main__":
    print("=" * 60)
    print("SOVEREIGN EMBEDDINGS TEST")
    print("=" * 60)
    test_text = "This is a test of sovereign embeddings."
    print(f"\nEmbedding: '{test_text}'")
    embedding = sovereign_embed(test_text)
    if embedding:
        print(f"Dimensions: {len(embedding)}")
        print(f"First 10 values: {embedding[:10]}")
        print("\nSOVEREIGN EMBEDDINGS WORKING!")
    else:
        print("FAILED — check model path and llama_cpp install")
    print("=" * 60)
