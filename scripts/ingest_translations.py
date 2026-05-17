"""
Ingestion script for translation data.

USAGE:
  # List current translation memory coverage
  python scripts/ingest_translations.py --list

  # Add a glossary file (terms map JSON)
  python scripts/ingest_translations.py --glossary path/to/uzbek_terms.json --lang uzbek

  # Add parallel examples (JSONL with {"en": "...", "<lang>": "..."} per line)
  python scripts/ingest_translations.py --examples path/to/uzbek_pairs.jsonl --lang uzbek

  # Add a single example pair from the command line
  python scripts/ingest_translations.py --lang uzbek --pair "Hello world" "Salom dunyo"

  # Bulk-add from a TSV (tab-separated: english<TAB>native)
  python scripts/ingest_translations.py --tsv path/to/pairs.tsv --lang uzbek
"""
from __future__ import annotations
import argparse, json, pathlib, sys, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.translation_memory import (
    GLOSS_DIR, EX_DIR, available_languages, _lang_key,
)


def add_glossary(lang: str, source_path: pathlib.Path):
    """Merge a glossary JSON into the existing one for this language."""
    key = _lang_key(lang)
    target = GLOSS_DIR / f"{key}.json"
    existing = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    incoming = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(incoming, dict):
        print(f"  [FAIL] {source_path}: not a JSON object")
        return
    before = len(existing)
    existing.update(incoming)
    target.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] {target.name}: {before} -> {len(existing)} entries (+{len(existing) - before})")


def add_examples_jsonl(lang: str, source_path: pathlib.Path):
    """Append parallel examples from a JSONL file."""
    key = _lang_key(lang)
    target = EX_DIR / f"{key}.jsonl"
    incoming = source_path.read_text(encoding="utf-8").splitlines()
    added = 0
    with target.open("a", encoding="utf-8") as f:
        for line in incoming:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if "en" not in rec or not any(_lang_key(k) == key for k in rec.keys() if k != "en"):
                    continue
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                added += 1
            except Exception:
                continue
    print(f"  [OK] {target.name}: appended {added} examples")


def add_single_pair(lang: str, english: str, native: str):
    """Append one example pair from the command line."""
    key = _lang_key(lang)
    target = EX_DIR / f"{key}.jsonl"
    rec = {"en": english, key: native}
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  [OK] {target.name}: appended pair  ({english[:50]} -> {native[:50]})")


def add_tsv(lang: str, source_path: pathlib.Path):
    """Bulk-add from a TSV file: 'english<TAB>native' per line."""
    key = _lang_key(lang)
    target = EX_DIR / f"{key}.jsonl"
    added = 0
    with target.open("a", encoding="utf-8") as f:
        for line in source_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            en, native = parts[0].strip(), parts[1].strip()
            if not en or not native:
                continue
            rec = {"en": en, key: native}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            added += 1
    print(f"  [OK] {target.name}: added {added} pairs from TSV")


def list_current():
    """Print current data coverage."""
    langs = available_languages()
    if not langs:
        print("  (no translation data yet)")
        return
    print(f"  Currently have data for {len(langs)} language(s):")
    print()
    print(f"  {'Language':<20} {'Glossary terms':>16} {'Example pairs':>16}")
    print(f"  {'-' * 20:<20} {'-' * 16:>16} {'-' * 16:>16}")
    for lang in sorted(langs.keys()):
        s = langs[lang]
        print(f"  {lang:<20} {s.get('gloss', 0):>16} {s.get('examples', 0):>16}")


def main():
    ap = argparse.ArgumentParser(description="Manage translation memory data")
    ap.add_argument("--list", action="store_true", help="List current data coverage")
    ap.add_argument("--lang", help="Target language (e.g. uzbek, kazakh, russian)")
    ap.add_argument("--glossary", help="Path to a JSON glossary file to add")
    ap.add_argument("--examples", help="Path to a JSONL examples file to add")
    ap.add_argument("--tsv",      help="Path to a TSV file with english<TAB>native per line")
    ap.add_argument("--pair", nargs=2, metavar=("ENGLISH", "NATIVE"),
                     help="Add one parallel pair directly from the command line")
    args = ap.parse_args()

    if args.list:
        list_current()
        return

    if not args.lang:
        ap.error("--lang is required when adding data")

    if args.glossary:
        add_glossary(args.lang, pathlib.Path(args.glossary))
    if args.examples:
        add_examples_jsonl(args.lang, pathlib.Path(args.examples))
    if args.tsv:
        add_tsv(args.lang, pathlib.Path(args.tsv))
    if args.pair:
        add_single_pair(args.lang, args.pair[0], args.pair[1])

    if not (args.glossary or args.examples or args.tsv or args.pair):
        print("No data provided. Use --list to see current coverage, or pass "
              "--glossary / --examples / --tsv / --pair to add data.")
        ap.print_help()


if __name__ == "__main__":
    main()
