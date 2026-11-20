"""Version 4 independent annotation -> review -> human adjudication.

The module never invents final labels.  Agreement is computed only from separately
completed files with explicit reviewer identities, not synthetic placeholders.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .research_eval import cohen_kappa, rater_agreement, write_csv

SHEET_COLUMNS = ["question_id", "question", "category", "split", "chunk_id",
                 "source_path", "page", "start_word", "end_word", "text",
                 "annotator_id", "relevance", "evidence_quote", "notes"]
WORKLIST_COLUMNS = ["question_id", "chunk_id", "question", "source_path", "text",
                    "rater_a_id", "rater_a_label", "rater_a_quote", "rater_a_notes",
                    "rater_b_id", "rater_b_label", "rater_b_quote", "rater_b_notes",
                    "agreement", "final_relevance", "adjudicator_id", "decision_notes"]


def _read_csv(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"No header in {path}")
        return list(reader)


def _keys(rows: list[dict], label: str) -> dict[tuple[str, str], dict]:
    lookup = {}
    for line, row in enumerate(rows, 2):
        key = (str(row.get("question_id", "")).strip(), str(row.get("chunk_id", "")).strip())
        if not all(key) or key in lookup:
            raise ValueError(f"{label} line {line}: empty or duplicate question/chunk pair")
        lookup[key] = row
    if not lookup:
        raise ValueError(f"{label}: no rows")
    return lookup


def create_reviewer_sheets(pool_path: str | Path, out_folder: str | Path,
                           reviewer_ids: tuple[str, str] = ("reviewer_A", "reviewer_B")) -> dict:
    if reviewer_ids[0] == reviewer_ids[1] or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", x) for x in reviewer_ids):
        raise ValueError("Two distinct alphanumeric reviewer IDs required")
    pool = _read_csv(pool_path)
    _keys(pool, "Candidate pool")
    required = {"question_id", "chunk_id", "question", "text", "source_path"}
    if not all(required.issubset(row) for row in pool):
        raise ValueError("Candidate pool lacks question, source passage, or IDs")
    root = Path(out_folder)
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for reviewer in reviewer_ids:
        rows = []
        for row in pool:
            item = {key: row.get(key, "") for key in SHEET_COLUMNS}
            item.update(annotator_id=reviewer, relevance="", evidence_quote="", notes="")
            rows.append(item)
        path = root / f"independent_{reviewer}_BLINDED.csv"
        if path.exists():
            raise FileExistsError(f"Reviewer sheet exists: {path}. Use a new output folder to avoid loss.")
        write_csv(path, rows, SHEET_COLUMNS)
        paths.append(str(path))
    return {"reviewer_files": paths, "n_pairs": len(pool), "method_blinded": True,
            "note": "Give each sheet to a DIFFERENT person; never share responses until both submit independently."}


def _verify_rating(row: dict, line: int, expected_reviewer: str | None = None) -> None:
    if row.get("relevance", "").strip() not in {"0", "1", "2"}:
        raise ValueError(f"Rating line {line}: every pair requires explicit relevance 0, 1, or 2")
    reviewer = row.get("annotator_id", "").strip()
    if not reviewer or (expected_reviewer and reviewer != expected_reviewer):
        raise ValueError(f"Rating line {line}: reviewer identity missing or inconsistent")
    evidence = row.get("evidence_quote", "").strip()
    if row["relevance"].strip() in {"1", "2"}:
        if not evidence:
            raise ValueError(f"Rating line {line}: positive relevance needs an exact supporting quote")
        normalize = lambda text: " ".join(text.split()).casefold()
        if normalize(evidence) not in normalize(row.get("text", "")):
            raise ValueError(f"Rating line {line}: evidence_quote is not present in passage; review transcription")


def merge_independent_ratings(pool_path: str | Path, reviewer_a: str | Path,
                              reviewer_b: str | Path, out_folder: str | Path) -> dict:
    pool = _keys(_read_csv(pool_path), "Candidate pool")
    a = _keys(_read_csv(reviewer_a), "Reviewer A")
    b = _keys(_read_csv(reviewer_b), "Reviewer B")
    if set(pool) != set(a) or set(pool) != set(b):
        raise ValueError("Reviewer sheets must cover the exact same complete candidate pool")
    aid = {r.get("annotator_id", "").strip() for r in a.values()}
    bid = {r.get("annotator_id", "").strip() for r in b.values()}
    if len(aid) != 1 or len(bid) != 1 or not next(iter(aid)) or aid == bid:
        raise ValueError("Need two distinct, consistent reviewer identities")
    aid_value, bid_value = next(iter(aid)), next(iter(bid))
    ratings = {}
    combined = []
    worklist = []
    for key in sorted(pool):
        original, left, right = pool[key], a[key], b[key]
        for row, reviewer in ((left, aid_value), (right, bid_value)):
            if row.get("text", "") != original.get("text", "") or row.get("question", "") != original.get("question", ""):
                raise ValueError(f"Annotation source text/question was modified for {key}")
            _verify_rating(row, 0, reviewer)
            ratings[(key[0], key[1], reviewer)] = int(row["relevance"].strip())
            combined.append({"question_id": key[0], "chunk_id": key[1],
                             "annotator_id": reviewer, "relevance": int(row["relevance"].strip()),
                             "evidence_quote": row.get("evidence_quote", ""), "notes": row.get("notes", "")})
        same = left["relevance"].strip() == right["relevance"].strip()
        worklist.append({
            "question_id": key[0], "chunk_id": key[1], "question": original["question"],
            "source_path": original.get("source_path", ""), "text": original["text"],
            "rater_a_id": aid_value, "rater_a_label": left["relevance"],
            "rater_a_quote": left.get("evidence_quote", ""), "rater_a_notes": left.get("notes", ""),
            "rater_b_id": bid_value, "rater_b_label": right["relevance"],
            "rater_b_quote": right.get("evidence_quote", ""), "rater_b_notes": right.get("notes", ""),
            "agreement": "yes" if same else "no", "final_relevance": "",
            "adjudicator_id": "", "decision_notes": ""})
    agreement = rater_agreement(ratings, (aid_value, bid_value))
    root = Path(out_folder)
    root.mkdir(parents=True, exist_ok=True)
    for filename in ("two_rater_combined.csv", "human_adjudication_REQUIRED.csv"):
        if (root / filename).exists():
            raise FileExistsError(f"Output {filename} already exists; choose another output folder")
    write_csv(root / "two_rater_combined.csv", combined,
              ["question_id", "chunk_id", "annotator_id", "relevance", "evidence_quote", "notes"])
    write_csv(root / "human_adjudication_REQUIRED.csv", worklist, WORKLIST_COLUMNS)
    return {"n_pairs": len(pool), "n_disagreements": agreement["n_disagree"],
            "agreement_percent": agreement["percent_agreement"],
            "cohen_kappa_unweighted": agreement["cohen_kappa_unweighted"],
            "agreement_report": agreement, "adjudication_sheet": str(root / "human_adjudication_REQUIRED.csv"),
            "warning": "All final labels are EMPTY. A human adjudicator must explicitly decide or confirm every row."}


def finalize_human_adjudication(worklist_path: str | Path, output_csv: str | Path,
                               pool_path: str | Path | None = None) -> dict:
    rows = _read_csv(worklist_path)
    keys = _keys(rows, "Human adjudication file")
    if pool_path is not None:
        pool = _keys(_read_csv(pool_path), "Candidate pool")
        if set(keys) != set(pool):
            raise ValueError("Adjudication must match the complete candidate pool")
        for key in keys:
            if keys[key].get("text", "") != pool[key].get("text", ""):
                raise ValueError(f"Source passage was changed for {key}")
    output = []
    adjudicator_ids = set()
    for key, row in sorted(keys.items()):
        label = row.get("final_relevance", "").strip()
        reviewer = row.get("adjudicator_id", "").strip()
        if label not in {"0", "1", "2"} or not reviewer:
            raise ValueError(f"Human adjudicator must fill final_relevance and adjudicator_id for {key}")
        if row.get("agreement", "").strip() == "no" and not row.get("decision_notes", "").strip():
            raise ValueError(f"Disagreement {key} requires decision_notes explaining resolution")
        adjudicator_ids.add(reviewer)
        output.append({"question_id": key[0], "chunk_id": key[1], "relevance": int(label)})
    target = Path(output_csv)
    if target.exists():
        raise FileExistsError(f"Qrels already exist: {target}; do not overwrite judgments")
    target.parent.mkdir(parents=True, exist_ok=True)
    write_csv(target, output, ["question_id", "chunk_id", "relevance"])
    return {"n_adjudicated": len(output), "adjudicator_ids": sorted(adjudicator_ids),
            "qrels_csv": str(target), "source_worklist": str(worklist_path),
            "note": "Final qrels reflect human decisions, not automatically inferred labels."}
