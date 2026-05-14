"""
File Parser — extract plain text from uploaded documents.

Supported formats:
  .pdf  — PyPDF
  .docx — python-docx
  .xlsx / .xls — openpyxl
  .csv  — stdlib csv
  anything else — UTF-8 decode (covers .txt .py .js .ts .json .md .yaml etc.)

Returns at most MAX_CHARS characters so the LLM context window stays manageable.
"""
from __future__ import annotations
import io, csv, pathlib

MAX_CHARS = 8_000  # chars per file injected into prompt


def parse_file(filename: str, data: bytes) -> str:
    """Dispatch to the right parser by file extension. Always returns a string."""
    ext = pathlib.Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            return _parse_pdf(data)
        elif ext == ".docx":
            return _parse_docx(data)
        elif ext in (".xlsx", ".xls"):
            return _parse_excel(data)
        elif ext == ".csv":
            return _parse_csv(data)
        else:
            return _parse_text(data)
    except Exception as e:
        return f"[Could not parse file: {e}]"


def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"--- Page {i + 1} ---\n{text.strip()}")
    return "\n\n".join(pages)[:MAX_CHARS]


def _parse_docx(data: bytes) -> str:
    from docx import Document  # type: ignore
    doc = Document(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    # Also pull table cells
    for table in doc.tables:
        for row in table.rows:
            paragraphs.append("\t".join(c.text for c in row.cells))
    return "\n".join(paragraphs)[:MAX_CHARS]


def _parse_excel(data: bytes) -> str:
    import openpyxl  # type: ignore
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        parts.append(f"=== Sheet: {ws.title} ===")
        for row in ws.iter_rows(values_only=True):
            if any(c is not None for c in row):
                parts.append("\t".join("" if c is None else str(c) for c in row))
    return "\n".join(parts)[:MAX_CHARS]


def _parse_csv(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = ["\t".join(row) for row in reader]
    return "\n".join(rows)[:MAX_CHARS]


def _parse_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")[:MAX_CHARS]
