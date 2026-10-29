"""Load documents while preserving filenames and PDF page provenance.

PDF extraction uses pypdf when installed; scanned/image-only PDFs require a
separate authorized OCR process and are reported as unreadable.
"""
from pathlib import Path
from .models import SourceDocument

TEXT_EXTENSIONS = {".txt", ".md"}


def load_documents(folder: str | Path, include_pdfs: bool = True, deduplicate: bool = True) -> list[SourceDocument]:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Document folder not found: {root}")
    documents: list[SourceDocument] = []
    skipped = set()
    if deduplicate:
        from .policy_catalog import scan_duplicates
        skipped = set(scan_duplicates(root)["skipped_aliases"])
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        relative = path.relative_to(root).as_posix()
        if relative in skipped:
            continue
        if ext in TEXT_EXTENSIONS:
            text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
            if text:
                documents.append(SourceDocument(relative, text, relative))
        elif ext == ".pdf" and include_pdfs:
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise RuntimeError("PDF support requires 'pypdf'. Run: pip install -r requirements.txt") from exc
            try:
                reader = PdfReader(str(path))
                for page_index, page in enumerate(reader.pages, start=1):
                    text = (page.extract_text() or "").strip()
                    if text:
                        from .section_aware import page_section
                        documents.append(SourceDocument(f"{relative}::p{page_index}", text, relative,
                                                        page_index, page_section(text)))
            except Exception as exc:
                raise RuntimeError(f"Could not read PDF {relative}: {exc}") from exc
    if not documents:
        raise ValueError(f"No extractable text found in {root}. Add .txt/.md files or text-based PDFs.")
    return documents
