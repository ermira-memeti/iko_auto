"""V4: read-only diagnostics and provenance verification for policy corpora.

Nothing here downloads, fabricates, OCRs, or assumes reuse permission for documents.
The application uses the existing PDF/text loader after the audit.
"""
from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path

SUPPORTED = {".pdf", ".txt", ".md"}
REGISTRY_COLUMNS = (
    "document_id", "relative_file", "sha256", "indexed_chunks", "pages_total",
    "pages_with_text", "extracted_characters", "extraction_status", "insurer",
    "policy_id", "policy_family", "policy_version", "jurisdiction",
    "source_url", "publication_date", "access_date", "license_or_permission",
    "document_type", "dataset_split", "reviewed_by", "notes",
)
REQUIRED_REAL_METADATA = (
    "insurer", "policy_id", "policy_family", "policy_version", "jurisdiction",
    "license_or_permission", "document_type", "dataset_split", "reviewed_by",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_corpus(folder: str | Path, chunk_words: int = 170, overlap_words: int = 45) -> dict:
    """Inspect *all* supported files, including unreadable PDFs, without altering them."""
    from .chunking import chunk_documents
    from .data_ingest import load_documents

    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Corpus folder does not exist: {root}")
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)
    if not files:
        raise ValueError(f"No supported .pdf, .txt or .md files in {root}")
    rows, warnings, by_hash = [], [], defaultdict(list)
    for path in files:
        relative = path.relative_to(root).as_posix()
        record = dict.fromkeys(REGISTRY_COLUMNS, "")
        record.update(document_id=relative, relative_file=relative,
                      sha256=_sha256(path), indexed_chunks=0,
                      pages_total=0, pages_with_text=0, extracted_characters=0,
                      extraction_status="ready")
        by_hash[record["sha256"]].append(relative)
        if path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                record["pages_total"] = len(reader.pages)
                for i, page in enumerate(reader.pages, 1):
                    try:
                        text = (page.extract_text() or "").strip()
                    except Exception as exc:
                        warnings.append(f"{relative} page {i}: extraction error ({type(exc).__name__})")
                        continue
                    record["extracted_characters"] += len(text)
                    record["pages_with_text"] += bool(text)
                if not record["pages_with_text"]:
                    record["extraction_status"] = "needs_ocr_or_manual_review"
                    warnings.append(f"{relative}: no extractable PDF text; perform authorized OCR and verify against original")
                elif record["pages_with_text"] < record["pages_total"]:
                    record["extraction_status"] = "partial_text_review_required"
                    warnings.append(f"{relative}: {record['pages_total'] - record['pages_with_text']} pages have no extractable text")
            except ImportError:
                record["extraction_status"] = "pypdf_not_installed"
                warnings.append(f"{relative}: install pypdf to inspect PDF text")
            except Exception as exc:
                record["extraction_status"] = "unreadable_pdf"
                warnings.append(f"{relative}: PDF cannot be read ({type(exc).__name__}: {exc})")
        else:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            record["extracted_characters"] = len(text.strip())
            record["pages_total"] = 1
            record["pages_with_text"] = 1 if text.strip() else 0
            if not text.strip():
                record["extraction_status"] = "empty_file"
                warnings.append(f"{relative}: empty text file")
        rows.append(record)
    for digest, names in by_hash.items():
        if len(names) > 1:
            warnings.append("Identical file content (potential split leakage): " + ", ".join(names))
    # Chunk IDs match the existing application by using the same loader/chunker.
    # If PDF extraction raises for one file, still return the diagnostic inventory.
    indexed_chunks = 0
    try:
        docs = load_documents(root)
        chunks = chunk_documents(docs, chunk_words, overlap_words)
        count = defaultdict(int)
        for chunk in chunks:
            count[chunk.source_path] += 1
        for record in rows:
            record["indexed_chunks"] = count[record["relative_file"]]
        indexed_chunks = len(chunks)
    except (ValueError, RuntimeError, ImportError) as exc:
        warnings.append(f"Indexing blocked; fix extraction/import issue: {exc}")
    return {"root": str(root), "n_files": len(rows), "n_chunks": indexed_chunks,
            "files": rows, "warnings": warnings,
            "n_review_required": sum(r["extraction_status"] != "ready" for r in rows),
            "synthetic_demo": "demo_auto_graph" in root.parts or "demo_auto" in root.parts}


def registry_template(audit: dict) -> list[dict]:
    return [dict(row) for row in audit["files"]]


def read_registry(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(REGISTRY_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError("Registry missing V4 columns; first export it with 'audit' then fill metadata")
        return list(reader)


def validate_registry(audit: dict, registry: list[dict], real_mode: bool = True) -> dict:
    """Check documented provenance, file integrity, and policy-family leakage."""
    errors, warnings = [], list(audit["warnings"])
    if len({r.get("relative_file", "") for r in registry}) != len(registry):
        errors.append("Duplicate relative_file entries in source registry")
    actual = {r["relative_file"]: r for r in audit["files"]}
    supplied = {r.get("relative_file", ""): r for r in registry}
    for filename in sorted(actual.keys() - supplied.keys()):
        errors.append(f"Unregistered source document: {filename}")
    for filename in sorted(supplied.keys() - actual.keys()):
        errors.append(f"Registry file is missing from corpus: {filename}")
    families = defaultdict(set)
    for filename in sorted(actual.keys() & supplied.keys()):
        observed, declared = actual[filename], supplied[filename]
        if declared.get("sha256", "").strip().lower() != observed["sha256"]:
            errors.append(f"SHA-256 mismatch: {filename}; restart pooling when source changes")
        if observed["extraction_status"] != "ready":
            errors.append(f"Document needs extraction review: {filename} ({observed['extraction_status']})")
        if real_mode:
            for key in REQUIRED_REAL_METADATA:
                if not declared.get(key, "").strip():
                    errors.append(f"{filename}: missing metadata '{key}'")
            if declared.get("dataset_split", "").strip() not in {"dev", "test"}:
                errors.append(f"{filename}: dataset_split must be 'dev' or 'test'")
            family = declared.get("policy_family", "").strip().casefold()
            insurer = declared.get("insurer", "").strip().casefold()
            if family and insurer:
                families[(insurer, family)].add(declared.get("dataset_split", "").strip())
            permission = declared.get("license_or_permission", "").strip().casefold()
            if permission in {"unknown", "pending", "not sure", "none", "n/a", "no"}:
                errors.append(f"{filename}: documentation of permitted research use is incomplete")
        if declared.get("indexed_chunks", "").strip() != str(observed["indexed_chunks"]):
            errors.append(f"Chunk count changed for {filename}; freeze chunk settings before labeling")
    for (insurer, family), splits in families.items():
        if "dev" in splits and "test" in splits:
            errors.append(f"Cross-split policy-family leakage: {insurer}/{family} appears in dev and test")
    if real_mode and audit["synthetic_demo"]:
        errors.append("Synthetic demo corpus cannot be accepted as a real study")
    if real_mode and audit["n_files"] < 2:
        warnings.append("Only one source document: not suitable for multi-insurer generalization claims")
    return {"passed": not errors, "errors": errors, "warnings": warnings,
            "documents": audit["n_files"], "indexed_chunks": audit["n_chunks"],
            "provenance_not_externally_verified": True}
