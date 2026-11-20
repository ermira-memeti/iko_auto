"""Conservative structural PDF section hints and explicit heading reranking.

The section boost is a separate retrieval configuration, never blended into
BM25 baseline results without an experiment label.
"""
from __future__ import annotations
import re
from .models import SearchHit

SECTION_RE = re.compile(r'^\s*(Section\s+(?:[A-L]|\d+)(?:\s*[-–:]\s*[^\n]{3,90})?)\s*$', re.I)


def page_section(text: str) -> str:
    # Only identify isolated printed headings (not contents entries), scanning
    # the leading portion of each extracted page.
    if re.search(r"(?im)^\s*contents(?: page)?\s*$", "\n".join(text.splitlines()[:8])):
        return ''
    for line in text.splitlines()[:18]:
        s = line.strip()
        if SECTION_RE.fullmatch(s):
            return s
    return ''


def section_signal(query: str, hit: SearchHit) -> float:
    """0–1 query-to-PDF-section match, based only on visible page headings.

    Generic "excluded" passages in unrelated sections do NOT receive a full
    boost for damage questions. This avoids promoting an unrelated breakdown
    appendix over the requested coverage section.
    """
    q = query.casefold()
    section = hit.chunk.section.casefold()
    if not section:
        return 0.0
    requested = re.search(r'\bsection\s+([a-l]|\d+)\b', q)
    if requested:
        return float(bool(re.search(r'\bsection\s+' + re.escape(requested.group(1)) + r'\b', section)))
    topics = ((('accidental damage', 'vehicle damage', 'damage to your car', 'collision'), 'damage'),
              (('fire', 'theft'), 'fire'),
              (('windscreen', 'glass'), 'windscreen'),
              (('third party', 'liability'), 'liability'))
    heading = re.sub(r'^section\s+(?:[a-l]|\d+)\s*[-–:]\s*', '', section).strip()
    for words, section_word in topics:
        if any(w in q for w in words):
            if section_word == 'damage' and heading in {'damage', 'damage to your vehicle'}:
                return 1.0
            if section_word != 'damage' and section_word in heading:
                return 1.0
    # A generic "exclusions" question without a section cannot reliably
    # identify the intended policy section, so no structural rerank.
    return 0.0


def section_rerank(query: str, hits: list[SearchHit], strength: float = 0.60) -> list[SearchHit]:
    """Ranks using baseline reciprocal rank and a fixed section cue weight.

    Scores are illustrative, not probabilities. Choose and freeze strength on
    development data before evaluating a held-out test split.
    """
    if not 0 <= strength <= 1:
        raise ValueError('strength must be between 0 and 1')
    rescored = []
    for rank, hit in enumerate(hits, 1):
        signal = section_signal(query, hit)
        combined = (1 - strength) / rank + strength * signal
        rescored.append((combined, rank, hit))
    rescored.sort(key=lambda t: (-t[0], t[1]))
    return [SearchHit(chunk=hit.chunk, score=round(score, 6), method=hit.method + '+section',
                      bm25_score=hit.bm25_score, dense_score=hit.dense_score,
                      graph_score=hit.graph_score, graph_paths=hit.graph_paths)
            for score, rank, hit in rescored]
