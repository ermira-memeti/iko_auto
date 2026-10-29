"""Export chunk IDs for inspecting source provenance and preparing annotations."""
from pathlib import Path
import argparse
import csv
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import build_pipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", default=str(ROOT / "data" / "demo_auto"))
    parser.add_argument("--output", default=str(ROOT / "outputs" / "chunk_manifest.csv"))
    args = parser.parse_args()
    retriever = build_pipeline(args.docs)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(["chunk_id", "doc_id", "source_path", "page", "start_word", "end_word", "text"])
        for c in retriever.chunks:
            writer.writerow([c.chunk_id, c.doc_id, c.source_path, c.page, c.start_word, c.end_word, c.text])
    print(f"Exported {len(retriever.chunks)} chunks to {target}")


if __name__ == "__main__":
    main()
