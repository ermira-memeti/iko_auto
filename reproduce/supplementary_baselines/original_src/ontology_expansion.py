"""Transparent, deterministic query expansion (research demonstration, not graph inference)."""
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / "ontology"

def load_map(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def expand_query(query: str, mode: str = "full") -> tuple[str, dict]:
    if mode not in {"none", "synonyms", "relations", "full"}:
        raise ValueError("mode must be none, synonyms, relations, full")
    if not query.strip() or mode == "none":
        return query, {"original": query, "added": [], "mode": mode}
    tokens = set(re.findall(r"[a-z]+", query.lower()))
    low = query.lower()
    added = []
    if mode in {"synonyms", "full"}:
        for key, vals in load_map("synonyms.json").items():
            if (key in tokens or (" " in key and key in low)):
                added.extend(vals)
            elif any((v in tokens or (" " in v and v in low)) for v in vals):
                added.append(key)
    if mode in {"relations", "full"}:
        for key, vals in load_map("retrieval_relations.json").items():
            if key in tokens:
                added.extend(vals)
    seen = set(tokens)
    unique = []
    for phrase in added:
        if phrase.lower() not in seen and phrase.lower() not in low:
            unique.append(phrase)
            seen.add(phrase.lower())
    return (query + (" " + " ".join(unique) if unique else "")), {"original": query, "added": unique, "mode": mode}
