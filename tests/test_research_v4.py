"""V4 research safeguards; fake data below exist only inside tests."""
import csv
import json
from pathlib import Path
import pytest

from src.real_corpus import (REGISTRY_COLUMNS, audit_corpus, registry_template,
                             read_registry, validate_registry)
from src.annotation_workflow import (create_reviewer_sheets, merge_independent_ratings,
                                     finalize_human_adjudication)
from src.research_eval import write_csv
from src.study_freeze import (create_freeze, verify_freeze, validate_question_families)


def make_fake_study(tmp_path):
    docs = tmp_path / "policies"
    docs.mkdir()
    (docs / "first.txt").write_text("Alpha insurance collision coverage includes collision loss and a deductible.", encoding="utf-8")
    (docs / "second.txt").write_text("Beta insurance claim report conditions include police notification.", encoding="utf-8")
    audit = audit_corpus(docs)
    rows = registry_template(audit)
    for i, row in enumerate(rows):
        row.update(insurer=["Alpha", "Beta"][i], policy_id=f"P{i}",
                   policy_family=f"F{i}", policy_version="2026",
                   jurisdiction="MK", license_or_permission="user-provided authorized example",
                   document_type="auto policy", dataset_split=["dev", "test"][i],
                   reviewed_by="test fixture author")
    registry_path = tmp_path / "registry.csv"
    write_csv(registry_path, rows, list(REGISTRY_COLUMNS))
    qpath = tmp_path / "questions.jsonl"
    questions = [
        {"question_id": "D1", "question": "What is Alpha collision cover?", "category": "coverage",
         "insurer": "Alpha", "policy_family": "F0", "split": "dev"},
        {"question_id": "T1", "question": "What is Beta's notification?", "category": "claim",
         "insurer": "Beta", "policy_family": "F1", "split": "test"},
    ]
    qpath.write_text("\n".join(json.dumps(q) for q in questions) + "\n", encoding="utf-8")
    pool = tmp_path / "pool.csv"
    pairs = [
        dict(question_id="D1", question=questions[0]["question"], category="coverage", split="dev",
             chunk_id="first.txt::c0001", source_path="first.txt", page="", start_word="0", end_word="10",
             text="Alpha insurance collision coverage includes collision loss and a deductible.",
             retrieved_by="bm25:1", relevance="", evidence_quote="", notes=""),
        dict(question_id="T1", question=questions[1]["question"], category="claim", split="test",
             chunk_id="second.txt::c0001", source_path="second.txt", page="", start_word="0", end_word="10",
             text="Beta insurance claim report conditions include police notification.",
             retrieved_by="bm25:1", relevance="", evidence_quote="", notes=""),
    ]
    write_csv(pool, pairs)
    return docs, registry_path, qpath, pool


def fill_rater_sheets(paths, *, disagreement=False):
    for i, path in enumerate(paths):
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            columns = reader.fieldnames
        for row in rows:
            row["relevance"] = "2"
            row["evidence_quote"] = row["text"].split(" includes ")[0]
        if i == 1 and disagreement:
            rows[0]["relevance"] = "0"
            rows[0]["evidence_quote"] = ""
        write_csv(path, rows, columns)


def test_corpus_audit_with_source_hashes(tmp_path):
    docs, registry, qs, pool = make_fake_study(tmp_path)
    audit = audit_corpus(docs)
    assert audit["n_files"] == 2
    assert audit["n_chunks"] == 2
    assert all(len(x["sha256"]) == 64 for x in audit["files"])
    assert validate_registry(audit, read_registry(registry))["passed"]


def test_missing_metadata_is_not_ready(tmp_path):
    docs, registry, _, _ = make_fake_study(tmp_path)
    rows = read_registry(registry)
    rows[0]["policy_version"] = ""
    verdict = validate_registry(audit_corpus(docs), rows)
    assert not verdict["passed"]
    assert any("policy_version" in s for s in verdict["errors"])


def test_modified_document_detected(tmp_path):
    docs, registry, _, _ = make_fake_study(tmp_path)
    (docs / "first.txt").write_text("Changed document", encoding="utf-8")
    verdict = validate_registry(audit_corpus(docs), read_registry(registry))
    assert not verdict["passed"]
    assert any("SHA-256" in s for s in verdict["errors"])


def test_cross_split_policy_family_is_rejected(tmp_path):
    docs, registry, _, _ = make_fake_study(tmp_path)
    rows = read_registry(registry)
    rows[1]["insurer"] = rows[0]["insurer"]
    rows[1]["policy_family"] = rows[0]["policy_family"]
    verdict = validate_registry(audit_corpus(docs), rows)
    assert not verdict["passed"]
    assert any("leakage" in s for s in verdict["errors"])


def test_duplicate_files_warn(tmp_path):
    docs = tmp_path / "documents"
    docs.mkdir()
    (docs / "one.txt").write_text("same policy")
    (docs / "two.txt").write_text("same policy")
    assert any("Identical file" in warning for warning in audit_corpus(docs)["warnings"])


def test_empty_pdf_flags_no_ocr(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    docs = tmp_path / "pdfs"
    docs.mkdir()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with (docs / "scanned.pdf").open("wb") as f:
        writer.write(f)
    audit = audit_corpus(docs)
    assert audit["n_files"] == 1
    assert audit["n_review_required"] == 1
    assert audit["files"][0]["extraction_status"] == "needs_ocr_or_manual_review"


def test_sheets_are_separate_blinded_and_blank(tmp_path):
    _, _, _, pool = make_fake_study(tmp_path)
    result = create_reviewer_sheets(pool, tmp_path / "raters")
    assert result["n_pairs"] == 2
    first = Path(result["reviewer_files"][0]).read_text(encoding="utf-8-sig")
    assert "retrieved_by" not in first
    assert "bm25:1" not in first
    assert "reviewer_A" in first
    assert "relevance" in first
    assert ",2," not in first
    with pytest.raises(FileExistsError):
        create_reviewer_sheets(pool, tmp_path / "raters")


def test_reviewer_ids_cannot_match(tmp_path):
    _, _, _, pool = make_fake_study(tmp_path)
    with pytest.raises(ValueError, match="distinct"):
        create_reviewer_sheets(pool, tmp_path / "raters", ("x", "x"))


def test_merge_requires_complete_ratings(tmp_path):
    _, _, _, pool = make_fake_study(tmp_path)
    paths = create_reviewer_sheets(pool, tmp_path / "raters")["reviewer_files"]
    with pytest.raises(ValueError, match="explicit relevance"):
        merge_independent_ratings(pool, *paths, tmp_path / "merged")


def test_positive_requires_exact_quote(tmp_path):
    _, _, _, pool = make_fake_study(tmp_path)
    paths = create_reviewer_sheets(pool, tmp_path / "raters")["reviewer_files"]
    fill_rater_sheets(paths)
    with open(paths[0], encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows, cols = list(reader), reader.fieldnames
    rows[0]["evidence_quote"] = "fabricated quote outside passage"
    write_csv(paths[0], rows, cols)
    with pytest.raises(ValueError, match="evidence_quote"):
        merge_independent_ratings(pool, *paths, tmp_path / "merged")


def test_adjudication_requires_explicit_human_decisions(tmp_path):
    _, _, _, pool = make_fake_study(tmp_path)
    paths = create_reviewer_sheets(pool, tmp_path / "raters")["reviewer_files"]
    fill_rater_sheets(paths, disagreement=True)
    result = merge_independent_ratings(pool, *paths, tmp_path / "merged")
    assert result["n_disagreements"] == 1
    worklist = Path(result["adjudication_sheet"])
    with pytest.raises(ValueError, match="Human adjudicator"):
        finalize_human_adjudication(worklist, tmp_path / "qrels.csv", pool)
    with worklist.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows, fields = list(reader), reader.fieldnames
    for row in rows:
        row.update(final_relevance="2", adjudicator_id="real_human_test_placeholder")
        if row["agreement"] == "no":
            row["decision_notes"] = "The source passage supports the requested coverage."
    write_csv(worklist, rows, fields)
    report = finalize_human_adjudication(worklist, tmp_path / "qrels.csv", pool)
    assert report["n_adjudicated"] == 2
    assert Path(report["qrels_csv"]).exists()
    with pytest.raises(FileExistsError):
        finalize_human_adjudication(worklist, tmp_path / "qrels.csv", pool)


def test_question_family_leakage_rejected(tmp_path):
    _, registry, qs, _ = make_fake_study(tmp_path)
    questions = [json.loads(x) for x in qs.read_text().splitlines()]
    questions[1]["insurer"] = "Alpha"
    questions[1]["policy_family"] = "F0"
    errors = validate_question_families(questions, read_registry(registry), True)
    assert any("leakage" in e for e in errors)


def test_real_freeze_requires_reviewer_evidence(tmp_path):
    docs, registry, questions, _ = make_fake_study(tmp_path)
    qrels = tmp_path / "qrels.csv"
    write_csv(qrels, [{"question_id": "D1", "chunk_id": "first.txt::c0001", "relevance": 2},
                     {"question_id": "T1", "chunk_id": "second.txt::c0001", "relevance": 2}])
    with pytest.raises(ValueError, match="requires both original"):
        create_freeze(docs, registry, questions, qrels, tmp_path / "freeze.json", mode="real", methods=["bm25"])


def test_demo_freeze_detects_changed_question(tmp_path):
    docs, registry, questions, _ = make_fake_study(tmp_path)
    qrels = tmp_path / "qrels.csv"
    write_csv(qrels, [{"question_id": "D1", "chunk_id": "first.txt::c0001", "relevance": 2},
                     {"question_id": "T1", "chunk_id": "second.txt::c0001", "relevance": 2}])
    manifest = create_freeze(docs, registry, questions, qrels, tmp_path / "freeze.json", mode="demo", methods=["bm25"])
    assert manifest["documents"] == 2
    assert verify_freeze(tmp_path / "freeze.json")["passed"]
    questions.write_text(questions.read_text() + "\n")
    check = verify_freeze(tmp_path / "freeze.json")
    assert not check["passed"]
    assert any(i["problem"] == "changed_sha256" for i in check["failures"])


def test_real_mode_freeze_with_complete_human_review(tmp_path):
    docs, registry, questions, pool = make_fake_study(tmp_path)
    paths = create_reviewer_sheets(pool, tmp_path / "reviewers")["reviewer_files"]
    fill_rater_sheets(paths, disagreement=True)
    result = merge_independent_ratings(pool, *paths, tmp_path / "merged")
    worklist = Path(result["adjudication_sheet"])
    with worklist.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows, fields = list(reader), reader.fieldnames
    for row in rows:
        row.update(final_relevance="2", adjudicator_id="expert_coordinator_test_fixture")
        if row["agreement"] == "no":
            row["decision_notes"] = "Adjudicator confirmed the relevant passage."
    write_csv(worklist, rows, fields)
    qrels = tmp_path / "final_qrels.csv"
    finalize_human_adjudication(worklist, qrels, pool)
    freeze = tmp_path / "study.json"
    manifest = create_freeze(docs, registry, questions, qrels, freeze, mode="real",
                             methods=["bm25"], reviewer_a=paths[0], reviewer_b=paths[1],
                             adjudication=worklist)
    assert manifest["mode"] == "real"
    assert verify_freeze(freeze)["passed"]
    # A label edit after freeze must be detected.
    Path(paths[0]).write_text(Path(paths[0]).read_text() + "\n")
    assert not verify_freeze(freeze)["passed"]


def test_verify_run_checks_protocol_and_input_hashes(tmp_path):
    from src.study_freeze import verify_evaluation_config
    from src.study_freeze import sha256
    docs, registry, questions, _ = make_fake_study(tmp_path)
    qrels = tmp_path / "qrels.csv"
    write_csv(qrels, [{"question_id": "D1", "chunk_id": "first.txt::c0001", "relevance": 2},
                     {"question_id": "T1", "chunk_id": "second.txt::c0001", "relevance": 2}])
    freeze_file = tmp_path / "freeze.json"
    create_freeze(docs, registry, questions, qrels, freeze_file, mode="demo", methods=["bm25"])
    run = {"chunk_words": 170, "overlap_words": 45, "k": 5, "pool_size": 50,
           "alpha": 0.6, "model": "sentence-transformers/all-MiniLM-L6-v2",
           "methods": ["bm25"], "docs": str(docs.resolve()),
           "questions": str(questions.resolve()), "questions_sha256": sha256(questions),
           "qrels": str(qrels.resolve()), "qrels_sha256": sha256(qrels)}
    run_file = tmp_path / "run_config.json"
    run_file.write_text(json.dumps(run))
    assert verify_evaluation_config(freeze_file, run_file)["passed"]
    run["k"] = 10
    run_file.write_text(json.dumps(run))
    bad = verify_evaluation_config(freeze_file, run_file)
    assert not bad["passed"]
    assert any(x["field"] == "top_k" for x in bad["differences"])
