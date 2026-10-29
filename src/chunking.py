"""Deterministic word-based chunking. Overlap is in WORDS (not characters)."""
from .models import SourceDocument, Chunk


def chunk_document(document: SourceDocument, chunk_words: int = 170, overlap_words: int = 45) -> list[Chunk]:
    if chunk_words < 1 or not (0 <= overlap_words < chunk_words):
        raise ValueError("chunk_words must be positive; overlap_words must be between 0 and chunk_words - 1")
    words = document.text.split()
    if not words:
        return []
    chunks = []
    step = chunk_words - overlap_words
    for start in range(0, len(words), step):
        end = min(start + chunk_words, len(words))
        chunks.append(Chunk(
            chunk_id=f"{document.doc_id}::c{len(chunks)+1:04d}",
            doc_id=document.doc_id,
            text=" ".join(words[start:end]),
            source_path=document.source_path,
            page=document.page,
            start_word=start,
            end_word=end,
            section=document.section,
        ))
        if end == len(words):
            break
    return chunks


def chunk_documents(documents: list[SourceDocument], chunk_words: int = 170,
                    overlap_words: int = 45) -> list[Chunk]:
    return [chunk for doc in documents for chunk in chunk_document(doc, chunk_words, overlap_words)]


def simple_chunk(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """Backward-compatible character chunker with ACTUAL overlap.

    Unlike the research chunker above, sizes here are characters.
    """
    if chunk_size < 1 or not 0 <= overlap < chunk_size:
        raise ValueError("Invalid chunk size/overlap")
    import re
    text = re.sub(r"\s+", " ", text).strip()
    chunks = []
    step = chunk_size - overlap
    for start in range(0, len(text), step):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
    return chunks


def chunk_corpus(corpus: dict[str, str], chunk_size: int = 500, overlap: int = 100) -> dict[str, list[str]]:
    return {doc_id: simple_chunk(text, chunk_size, overlap) for doc_id, text in corpus.items()}
