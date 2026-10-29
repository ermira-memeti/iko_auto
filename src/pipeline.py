"""Build indexes and run retrieval from a document folder."""
from pathlib import Path
from .chunking import chunk_documents
from .data_ingest import load_documents
from .retrieval import InsuranceRetriever
from .embeddings import DEFAULT_EMBEDDER


def build_pipeline(folder: str | Path, chunk_words: int = 170, overlap_words: int = 45,
                   embedding_model_name: str = DEFAULT_EMBEDDER,
                   graph_file: str | Path | None = None) -> InsuranceRetriever:
    docs = load_documents(folder)
    chunks = chunk_documents(docs, chunk_words, overlap_words)
    retriever = InsuranceRetriever(chunks, embedding_model_name=embedding_model_name)
    if graph_file is not None:
        from .graph_retrieval import GraphIndex
        retriever.graph_index = GraphIndex(graph_file, chunks)
    return retriever
