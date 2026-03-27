"""
AgentLedger RAG — Seed Loader

Reads all JSON files under rag/knowledge/ and upserts them into ChromaDB.

CLI usage
─────────
  # Load everything (safe to re-run — idempotent upsert)
  python -m rag.seed_loader

  # Load only national policies
  python -m rag.seed_loader --dir national

  # Show stats only, do not write
  python -m rag.seed_loader --dry-run

How to add new slices
─────────────────────
  1. Edit the JSON file in rag/knowledge/<category>/<name>.json
     (or create a new .json file in the appropriate subfolder)
  2. Run: python -m rag.seed_loader
  3. Done — the retriever picks up new content immediately.

How to edit an existing slice
──────────────────────────────
  1. Find the slice by strategy_id in the JSON file
  2. Edit the fields you want to change
  3. Run: python -m rag.seed_loader
     (upsert overwrites by strategy_id, so edits are applied safely)

How to delete a slice
─────────────────────
  Option A: Remove the object from the JSON and re-run the loader
            (the old embedding stays in ChromaDB until you call delete)
  Option B: python -c "from rag.chroma_store import ChromaStore; ChromaStore().delete('CIT-001')"
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from rag.schema import slice_from_dict, StrategySlice
from rag.embedder import Embedder
from rag.chroma_store import ChromaStore

logger = logging.getLogger(__name__)
KNOWLEDGE_ROOT = Path(__file__).parent / "knowledge"


def load_json_files(subdir: str | None = None) -> list[StrategySlice]:
    """Load and parse all slice JSON files from the knowledge directory."""
    root = KNOWLEDGE_ROOT / subdir if subdir else KNOWLEDGE_ROOT
    slices: list[StrategySlice] = []
    errors = 0

    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Support both a single object and a list of objects in one file
            items = data if isinstance(data, list) else [data]
            for item in items:
                slices.append(slice_from_dict(item))
        except Exception as exc:
            logger.error("Failed to parse %s: %s", path, exc)
            errors += 1

    logger.info("Loaded %d slices from %s (%d errors)", len(slices), root, errors)
    return slices


def run(subdir: str | None = None, dry_run: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    slices = load_json_files(subdir)
    if not slices:
        print("No slices found. Check rag/knowledge/ directory.")
        return

    print(f"\n{'─'*50}")
    print(f"  Slices loaded from JSON : {len(slices)}")

    if dry_run:
        print("  DRY RUN — no writes to ChromaDB")
        for s in slices[:5]:
            print(f"    [{s.strategy_id}] {s.title}")
        if len(slices) > 5:
            print(f"    ... and {len(slices) - 5} more")
        print(f"{'─'*50}\n")
        return

    print("  Generating embeddings ...")
    embedder = Embedder()
    texts   = [s.embed_text() for s in slices]
    vectors = embedder.embed(texts)

    print("  Writing to ChromaDB ...")
    store = ChromaStore()
    store.upsert(slices, vectors)

    print(f"  Total slices in DB now : {store.count()}")
    print(f"{'─'*50}\n")
    print("Done. The retriever will use updated knowledge immediately.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load tax strategy slices into ChromaDB")
    parser.add_argument("--dir",     default=None, help="Subdirectory to load (national/industry/regional)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not write to ChromaDB")
    args = parser.parse_args()
    run(subdir=args.dir, dry_run=args.dry_run)
