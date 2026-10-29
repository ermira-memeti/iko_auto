"""Optional FAISS index for normalized dot-product (cosine) search."""
class FaissIndex:
    def __init__(self, dim: int):
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("Dense retrieval needs requirements-ml.txt (faiss-cpu).") from exc
        self.index = faiss.IndexFlatIP(dim)
        self.ids: list[str] = []

    def add(self, vectors, ids: list[str]) -> None:
        if len(vectors) != len(ids):
            raise ValueError("Vectors and IDs must align")
        if self.index.ntotal != 0:
            raise ValueError("Index already populated")
        self.index.add(vectors.astype("float32"))
        self.ids.extend(ids)

    def search(self, query_vec, k: int = 5) -> list[tuple[str, float]]:
        if self.index.ntotal == 0:
            return []
        scores, idxs = self.index.search(query_vec.astype("float32"), min(k, self.index.ntotal))
        return [(self.ids[int(idx)], float(score)) for idx, score in zip(idxs[0], scores[0]) if idx >= 0]
