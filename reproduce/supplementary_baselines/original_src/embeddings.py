"""Optional semantic embeddings; model is downloaded on first use if uncached."""
DEFAULT_EMBEDDER = "sentence-transformers/all-MiniLM-L6-v2"


def get_embedding_model(model_name: str = DEFAULT_EMBEDDER):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Dense retrieval needs requirements-ml.txt (sentence-transformers).") from exc
    return SentenceTransformer(model_name)


def embed_texts(model, texts: list[str]):
    return model.encode(texts, convert_to_numpy=True, normalize_embeddings=True,
                        show_progress_bar=False)
