"""Typed structures used throughout the retrieval pipeline."""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    text: str
    source_path: str
    page: int | None = None
    section: str = ""


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    source_path: str
    page: int | None
    start_word: int
    end_word: int
    section: str = ""


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float
    method: str
    dense_score: float | None = None
    bm25_score: float | None = None
    graph_score: float | None = None
    graph_paths: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        out = asdict(self.chunk)
        out.update({"score": self.score, "method": self.method,
                    "dense_score": self.dense_score, "bm25_score": self.bm25_score,
                    "graph_score": self.graph_score, "graph_paths": list(self.graph_paths)})
        return out
