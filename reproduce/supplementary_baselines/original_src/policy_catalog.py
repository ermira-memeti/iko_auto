"""V5 document provenance, exact-content deduplication, and insurer scope.

Metadata recognition is a deterministic convenience for five known UK brands,
not an ontology result or a policy-specific rights determination. Unknown
insurers must be registered manually for scientific use.
"""
from __future__ import annotations
from collections import defaultdict
import hashlib
from pathlib import Path
import re

INSURER_ALIASES = {
    "AXA": ("axa",),
    "Admiral": ("admiral",),
    "Aviva": ("aviva",),
    "Direct Line": ("direct line", "directline", "direct_line"),
    "esure": ("esure",),
}
EXTENSIONS = {".pdf", ".txt", ".md"}


def insurer_from_name(source_path: str) -> str | None:
    # Explicit file/directory metadata only. Never use policy wording as a
    # classifier: e.g. a policy might mention another insurer in complaints.
    source = re.sub(r"[_\\/\-.]+", " ", source_path).lower()
    for insurer, aliases in INSURER_ALIASES.items():
        if any(re.search(r"(?<!\w)" + re.escape(a.replace("_", " ")) + r"(?!\w)", source)
               for a in aliases):
            return insurer
    return None


def named_insurers(query: str) -> list[str]:
    q = re.sub(r"[_-]+", " ", query.lower())
    return [insurer for insurer, aliases in INSURER_ALIASES.items()
            if any(re.search(r"(?<!\w)" + re.escape(a.replace("_", " ")) + r"(?!\w)", q)
                   for a in aliases)]


def allowed_sources(chunks, insurer: str) -> set[str]:
    return {c.source_path for c in chunks if insurer_from_name(c.source_path) == insurer}


def scan_duplicates(folder: str | Path) -> dict:
    """Detect identical raw files, and PDF/text with the same normalized content.

    PDF text fingerprints are an additional warning only; no fuzzy or
    near-duplicate identification is implied. One canonical file per fingerprint
    is selected deterministically by relative path.
    """
    root = Path(folder).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    paths = sorted((p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS),
                   key=lambda p: p.relative_to(root).as_posix().casefold())
    by_bytes, by_text, records = defaultdict(list), defaultdict(list), []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        by_bytes[sha].append(rel)
        text_digest = None
        try:
            if path.suffix.lower() == '.pdf':
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                txt = ' '.join(' '.join((page.extract_text() or '').split()) for page in reader.pages)
            else:
                txt = path.read_text(encoding='utf-8-sig')
            normalized = re.sub(r'\s+', ' ', txt).strip().casefold()
            if normalized:
                text_digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
                by_text[text_digest].append(rel)
        except Exception as ex:
            # Audit and loader provide more specific readability diagnostics.
            text_digest = None
        records.append({'relative_file': rel, 'sha256': sha,
                        'text_sha256': text_digest or '',
                        'insurer_guess': insurer_from_name(rel) or '',
                        'classification_source': 'filename_or_folder_only'})
    same_bytes = [v for v in by_bytes.values() if len(v) > 1]
    same_text = [v for v in by_text.values() if len(v) > 1]
    aliases = {}
    for groups in (same_bytes, same_text):
        for group in groups:
            canonical = sorted(group, key=str.casefold)[0]
            for item in group:
                aliases[item] = canonical
    skipped = sorted([rel for rel, canonical in aliases.items() if rel != canonical])
    return {'root': str(root), 'files': records, 'identical_file_groups': same_bytes,
            'same_extracted_text_groups': same_text, 'skipped_aliases': skipped,
            'indexed_canonical_files': len(records) - len(skipped),
            'limitations': 'Exact byte or normalized full-text duplicates only; not near-duplicates or version detection.'}
