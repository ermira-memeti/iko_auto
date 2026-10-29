"""Unified BM25, dense, and min-max-weighted hybrid retrieval.

Uses the BM25Okapi library when available, with a deterministic in-project
BM25 implementation for no-install quick demos. This is a retrieval BASELINE;
no ontology or relation-guided retrieval is claimed in this starter version.
"""
import math
import re
from collections import Counter
from .models import Chunk, SearchHit
from .ontology_expansion import expand_query
from .embeddings import DEFAULT_EMBEDDER, get_embedding_model, embed_texts

TOKEN_PATTERN = re.compile(r"\b\w+(?:[-']\w+)*\b", re.UNICODE)
# Fixed small English stopword set. The same tokenizer is applied to queries
# and corpus passages; see README for preprocessing details.
STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
             "for", "from", "how", "i", "in", "is", "it", "my", "of", "on", "or",
             "the", "this", "to", "under", "was", "were", "what", "when", "where",
             "which", "who", "with"}


def tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_PATTERN.findall(text.lower()) if token not in STOPWORDS]


class BuiltinBM25:
    """Robertson-style BM25 with non-negative IDF, used without third-party packages."""
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.corpus = [Counter(row) for row in corpus]
        self.lengths = [sum(c.values()) for c in self.corpus]
        self.avgdl = sum(self.lengths) / max(len(self.lengths), 1)
        self.k1, self.b = k1, b
        self.df: Counter = Counter()
        for counter in self.corpus:
            self.df.update(counter.keys())

    def get_scores(self, tokens: list[str]) -> list[float]:
        n = len(self.corpus)
        scores = [0.0] * n
        for token in set(tokens):
            df = self.df.get(token, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, doc in enumerate(self.corpus):
                tf = doc.get(token, 0)
                if not tf:
                    continue
                norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / max(self.avgdl, 1e-10))
                scores[i] += idf * tf * (self.k1 + 1) / (tf + norm)
        return scores


def normalize_score_map(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if abs(hi - lo) < 1e-12:
        return {key: (1.0 if hi > 0 else 0.0) for key in scores}
    return {key: (value - lo) / (hi - lo) for key, value in scores.items()}


class InsuranceRetriever:
    def __init__(self, chunks: list[Chunk], embedding_model_name: str = DEFAULT_EMBEDDER):
        if not chunks:
            raise ValueError("No chunks to index")
        self.chunks = chunks
        self.embedding_model_name = embedding_model_name
        self.tokens = [tokenize(chunk.text) for chunk in chunks]
        self.bm25_backend = "builtin"
        self._bm25 = BuiltinBM25(self.tokens)
        # The published Okapi implementation can produce negative IDFs on tiny
        # one- or two-chunk demos. Use the stable built-in backend for small demos.
        if len(chunks) >= 5:
            try:
                from rank_bm25 import BM25Okapi
                self._bm25 = BM25Okapi(self.tokens)
                self.bm25_backend = "rank_bm25.BM25Okapi"
            except ImportError:
                pass
        self._model = None
        self._index = None
        self.graph_index = None
        self.last_graph_plan = None

    def enable_dense(self) -> None:
        if self._index is not None:
            return
        from .vector_store import FaissIndex
        model = get_embedding_model(self.embedding_model_name)
        vecs = embed_texts(model, [chunk.text for chunk in self.chunks])
        index = FaissIndex(vecs.shape[1])
        index.add(vecs, [chunk.chunk_id for chunk in self.chunks])
        self._model, self._index = model, index

    def _dense_scores(self, query: str, candidate_pool: int) -> dict[int, float]:
        self.enable_dense()
        vec = embed_texts(self._model, [query])
        ids_to_pos = {c.chunk_id: i for i, c in enumerate(self.chunks)}
        return {ids_to_pos[key]: score for key, score in self._index.search(vec, candidate_pool)}

    def search(self, query: str, method: str = "bm25", top_k: int = 5,
               alpha: float = 0.6, candidate_pool: int = 50, ontology_mode: str = "none",
               allowed_sources: set[str] | None = None, section_boost: bool = False) -> list[SearchHit]:
        # The controlled metadata/section variants consider the COMPLETE global
        # ranking before taking top-K. They never change corpus BM25 IDF or the
        # embedding index. They are separate experimental interventions.
        if allowed_sources is not None or section_boost:
            from .section_aware import section_rerank
            all_hits = self.search(query, method=method, top_k=len(self.chunks),
                                   alpha=alpha, candidate_pool=len(self.chunks),
                                   ontology_mode=ontology_mode)
            if allowed_sources is not None:
                all_hits = [h for h in all_hits if h.chunk.source_path in allowed_sources]
            if section_boost:
                all_hits = section_rerank(query, all_hits)
            return all_hits[:top_k]
        if ontology_mode in {"graph", "graph_full"}:
            return self._search_graph(query, method, top_k, alpha, candidate_pool,
                                      include_synonyms=(ontology_mode == "graph_full"))
        query, _ = expand_query(query, ontology_mode)
        if method not in {"bm25", "dense", "hybrid"}:
            raise ValueError("method must be bm25, dense, or hybrid")
        if not query.strip():
            return []
        if top_k < 1 or candidate_pool < 1 or not 0 <= alpha <= 1:
            raise ValueError("top_k and candidate_pool must be positive; alpha between 0 and 1")
        count = min(len(self.chunks), max(top_k, candidate_pool))
        bm25_scores = {}
        dense_scores = {}
        if method in {"bm25", "hybrid"}:
            all_scores = self._bm25.get_scores(tokenize(query))
            # BM25Okapi can output negative scores for common terms. Keep all candidates
            # for hybrid; exclude non-positive matches for BM25-only results.
            top_positions = sorted(range(len(all_scores)), key=lambda i: (-float(all_scores[i]), i))[:count]
            bm25_scores = {i: float(all_scores[i]) for i in top_positions}
        if method in {"dense", "hybrid"}:
            dense_scores = self._dense_scores(query, count)
        if method == "bm25":
            ranked = [(i, score) for i, score in bm25_scores.items() if score > 0]
        elif method == "dense":
            ranked = list(dense_scores.items())
        else:
            candidates = set(bm25_scores) | set(dense_scores)
            # Normalize scores among the candidate union. Missing candidate-branch
            # scores are treated as zero; this is weighted min-max fusion, NOT RRF.
            bn = normalize_score_map({i: bm25_scores.get(i, 0.0) for i in candidates})
            dn = normalize_score_map({i: dense_scores.get(i, 0.0) for i in candidates})
            ranked = [(i, alpha * dn[i] + (1 - alpha) * bn[i]) for i in candidates]
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return [SearchHit(chunk=self.chunks[i], score=round(float(score), 6), method=method,
                          dense_score=dense_scores.get(i), bm25_score=bm25_scores.get(i))
                for i, score in ranked[:top_k]]

    def _search_graph(self, query: str, method: str, top_k: int, alpha: float,
                      candidate_pool: int, include_synonyms: bool = False) -> list[SearchHit]:
        """Graph-driven evidence rerank: 70% graph path evidence, 30% baseline rank.

        This is a transparent exploratory scoring rule, not a trained/calibrated
        probability, ontology reasoner, or validated research result. Policy
        scope is enforced on BOTH graph and baseline branches.
        """
        if self.graph_index is None:
            raise RuntimeError("Graph mode requires a compatible RDF graph. Select the bundled multi-policy demo or supply a graph file.")
        if not query.strip():
            return []
        if method not in {"bm25", "dense", "hybrid"} or top_k < 1 or candidate_pool < 1 or not 0 <= alpha <= 1:
            raise ValueError("Invalid retrieval method or parameters")
        plan = self.graph_index.plan(query)
        self.last_graph_plan = plan
        if plan.strict_no_match:
            return []
        lexical_query = expand_query(query, "synonyms")[0] if include_synonyms else query
        baseline = self.search(lexical_query, method=method,
                               top_k=len(self.chunks), alpha=alpha,
                               candidate_pool=len(self.chunks), ontology_mode="none")
        if plan.scoped_docs is not None:
            baseline = [h for h in baseline if h.chunk.source_path in plan.scoped_docs]
        ranks = {hit.chunk.chunk_id: 1.0 / (i + 1) for i, hit in enumerate(baseline)}
        hit_by_id = {hit.chunk.chunk_id: hit for hit in baseline}
        candidate_ids = set(ranks) | set(plan.scores)
        # A graph path that has evidence in another policy is never eligible
        # when an explicitly named policy is present.
        if plan.scoped_docs is not None:
            candidate_ids = {cid for cid in candidate_ids if
                             self.graph_index.by_chunk[cid].source_path in plan.scoped_docs}
        results = []
        for cid in candidate_ids:
            chunk = self.graph_index.by_chunk[cid]
            graph_score = plan.scores.get(cid, 0.0)
            rank_score = ranks.get(cid, 0.0)
            combined = 0.7 * graph_score + 0.3 * rank_score if plan.scores else rank_score
            prior = hit_by_id.get(cid)
            traces = plan.traces.get(cid, [])
            results.append(SearchHit(chunk=chunk, score=round(combined, 6),
                                     method=f"{method}+{'graph_full' if include_synonyms else 'graph'}",
                                     dense_score=prior.dense_score if prior else None,
                                     bm25_score=prior.bm25_score if prior else None,
                                     graph_score=round(graph_score, 6),
                                     graph_paths=tuple(t.path for t in traces)))
        # Stable tie-breaking by indexed chunk order.
        index = {c.chunk_id: i for i, c in enumerate(self.chunks)}
        results.sort(key=lambda h: (-h.score, index[h.chunk.chunk_id]))
        return results[:top_k]
