"""
Multi-index RAG ingestion script.
Usage:
    python rag/ingest.py --path docs/ --index language_docs
    python rag/ingest.py --path my_project/ --index codebase --ext .py .ts .go
    python rag/ingest.py --path errors.md --index error_solutions
"""
import sys, argparse, pathlib, uuid
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from core.rag_retriever import index_texts

CODE_EXTS = {".py",".ts",".js",".go",".rs",".java",".cpp",".c",
             ".cs",".swift",".kt",".rb",".php",".lua",".r",".sh"}
DOC_EXTS  = {".md",".txt",".rst",".pdf"}


def read_file(p: pathlib.Path) -> str:
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)
    return p.read_text(encoding="utf-8", errors="ignore")


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    chunks, i = [], 0
    while i < len(text):
        chunks.append(text[i:i+size])
        i += size - overlap
    return [c for c in chunks if len(c.strip()) > 40]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path",  required=True, help="File or folder to ingest")
    ap.add_argument("--index", required=True,
                    choices=["language_docs","codebase","error_solutions","snippets"],
                    help="Which index to add to")
    ap.add_argument("--ext",   nargs="*", default=None,
                    help="File extensions to include (default: auto by index)")
    args = ap.parse_args()

    p = pathlib.Path(args.path)
    allowed = set(args.ext) if args.ext else (
        CODE_EXTS if args.index == "codebase" else DOC_EXTS)

    paths = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
    paths = [f for f in paths if f.suffix.lower() in allowed]

    all_chunks, all_meta = [], []
    for fp in paths:
        try:
            text = read_file(fp)
        except Exception as e:
            print(f"skip {fp}: {e}"); continue
        chunks = chunk_text(text)
        all_chunks.extend(chunks)
        all_meta.extend([{"source": str(fp), "index": args.index}] * len(chunks))
        print(f"  + {fp}  ({len(chunks)} chunks)")

    if not all_chunks:
        print("No content found. Check --path and --ext."); return

    n = index_texts(all_chunks, args.index, all_meta)
    print(f"\n✅ Indexed {n} chunks into [{args.index}]")


if __name__ == "__main__":
    main()
