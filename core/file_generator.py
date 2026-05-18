"""
File Generator — produce downloadable files from LLM markdown output.

Supported formats:
  txt  — plain text
  docx — Word document (headings, paragraphs, lists, tables, code)
  pdf  — PDF via fpdf2
  xlsx — Excel (markdown tables become styled sheets)
  csv  — CSV (first markdown table, or one row per line)
"""
from __future__ import annotations
import io, re, csv, unicodedata
from typing import Optional

MAX_CELL = 32_767  # Excel cell character limit

# ── Unicode → ASCII safe substitutions for PDF (latin-1 font) ────────────────
_UNICODE_MAP: dict[str, str] = {
    '—': '--',   # em dash
    '–': '-',    # en dash
    '‘': "'",    # left single quote
    '’': "'",    # right single quote
    '“': '"',    # left double quote
    '”': '"',    # right double quote
    '…': '...',  # ellipsis
    '•': '-',    # bullet
    '‣': '-',    # triangular bullet
    '●': '-',    # black circle bullet
    '−': '-',    # minus sign
    '×': 'x',    # multiplication sign
    '÷': '/',    # division sign
    '≠': '!=',   # not equal
    '≤': '<=',   # less-than or equal
    '≥': '>=',   # greater-than or equal
    ' ': ' ',    # non-breaking space
    '«': '<<',   # left guillemet
    '»': '>>',   # right guillemet
    '→': '->',   # right arrow
    '←': '<-',   # left arrow
    '✓': 'v',    # check mark
    '✗': 'x',    # ballot X
    '®': '(R)',  # registered
    '©': '(C)',  # copyright
    '™': '(TM)', # trademark
}

import os, pathlib

# ── Unicode font discovery for PDF rendering ──────────────────────────────
# fpdf2's built-in Helvetica is latin-1 only — Cyrillic/CJK/Arabic become
# "??????". To render foreign scripts we need to register a TrueType font.
# We probe a few common system fonts in order of script coverage.
_FONT_CANDIDATES = [
    # (windows path, mac path, linux path, font-key-name)
    ("C:/Windows/Fonts/arial.ttf",                                              # win
     "/Library/Fonts/Arial.ttf",                                                  # mac
     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",                          # linux
     "Unicode"),
    ("C:/Windows/Fonts/segoeui.ttf",
     "/System/Library/Fonts/SFNS.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "Unicode"),
]

def _find_unicode_font() -> Optional[str]:
    """Return a path to a Unicode-capable TTF on this OS, or None."""
    for win_p, mac_p, lin_p, _ in _FONT_CANDIDATES:
        for p in (win_p, mac_p, lin_p):
            if p and pathlib.Path(p).exists():
                return p
    return None


def _register_unicode_font(pdf, key: str = "Unicode") -> bool:
    """Register a Unicode font on the PDF object if available. Returns True
    on success. After registration use pdf.set_font(key, ...) for body text
    and Cyrillic/etc. will render correctly."""
    path = _find_unicode_font()
    if not path:
        return False
    try:
        pdf.add_font(key, "", path)
        # Try to add bold variant from same family if available
        bold_candidates = [
            path.replace("arial.ttf", "arialbd.ttf"),
            path.replace("Arial.ttf", "Arial Bold.ttf"),
            path.replace("segoeui.ttf", "segoeuib.ttf"),
            path.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
            path.replace("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
        ]
        for bp in bold_candidates:
            if pathlib.Path(bp).exists():
                pdf.add_font(key, "B", bp)
                break
        return True
    except Exception:
        return False


def _safe(text: str, unicode_ok: bool = False) -> str:
    """Prepare text for PDF rendering.

    When unicode_ok is True (a TTF Unicode font has been registered on the
    PDF), we pass text through unchanged so Cyrillic/CJK/etc. render.
    Otherwise we fall back to the latin-1 normalization used by the built-in
    Helvetica font — text in non-Latin scripts will degrade to ?? but at
    least the file generates.
    """
    if unicode_ok:
        # Still apply the symbol substitutions for fancy-quote / arrow / etc.
        for ch, sub in _UNICODE_MAP.items():
            text = text.replace(ch, sub)
        return text
    # Legacy latin-1 path
    for ch, sub in _UNICODE_MAP.items():
        text = text.replace(ch, sub)
    text = unicodedata.normalize('NFKD', text)
    return text.encode('latin-1', 'replace').decode('latin-1')


# ── Inline markdown stripping ─────────────────────────────────────────────────

def _strip_inline(text: str) -> str:
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*',     r'\1', text)
    text = re.sub(r'\*(.+?)\*',          r'\1', text)
    text = re.sub(r'`(.+?)`',            r'\1', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)',   r'\1', text)
    return text.strip()


# ── Markdown block parser ─────────────────────────────────────────────────────

def _parse_md(content: str) -> list[dict]:
    """
    Returns a list of typed block dicts:
      heading   {level, text}
      paragraph {text}
      bullet    {text}
      numbered  {index, text}
      code      {lang, code}
      table     {headers, rows}
      hr        {}
    """
    blocks: list[dict] = []
    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.strip().startswith('```'):
            lang = line.strip()[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            blocks.append({'type': 'code', 'lang': lang, 'code': '\n'.join(code_lines)})
            i += 1
            continue

        # ATX heading
        m = re.match(r'^(#{1,6})\s+(.+)', line)
        if m:
            blocks.append({'type': 'heading', 'level': len(m.group(1)), 'text': _strip_inline(m.group(2))})
            i += 1
            continue

        # HR
        if re.match(r'^[-*_]{3,}\s*$', line):
            blocks.append({'type': 'hr'})
            i += 1
            continue

        # Markdown table (line with | and next line is separator)
        if '|' in line and i + 1 < len(lines) and re.match(r'^[\s|:\-]+$', lines[i + 1]):
            headers = [_strip_inline(c) for c in line.strip().strip('|').split('|')]
            i += 2  # skip separator
            rows: list[list[str]] = []
            while i < len(lines) and '|' in lines[i]:
                row = [_strip_inline(c) for c in lines[i].strip().strip('|').split('|')]
                rows.append(row)
                i += 1
            blocks.append({'type': 'table', 'headers': headers, 'rows': rows})
            continue

        # Bullet list item
        m = re.match(r'^[ \t]*[-*+]\s+(.+)', line)
        if m:
            blocks.append({'type': 'bullet', 'text': _strip_inline(m.group(1))})
            i += 1
            continue

        # Numbered list item
        m = re.match(r'^[ \t]*(\d+)[.)]\s+(.+)', line)
        if m:
            blocks.append({'type': 'numbered', 'index': int(m.group(1)), 'text': _strip_inline(m.group(2))})
            i += 1
            continue

        # Non-empty paragraph
        if line.strip():
            blocks.append({'type': 'paragraph', 'text': _strip_inline(line.strip())})

        i += 1

    return blocks


# ── TXT ───────────────────────────────────────────────────────────────────────

def generate_txt(content: str) -> bytes:
    blocks = _parse_md(content)
    out: list[str] = []
    for b in blocks:
        t = b['type']
        if t == 'heading':
            out += ['', b['text'], '─' * len(b['text']), '']
        elif t == 'paragraph':
            out += [b['text'], '']
        elif t == 'bullet':
            out.append('  • ' + b['text'])
        elif t == 'numbered':
            out.append(f"  {b['index']}. {b['text']}")
        elif t == 'code':
            lbl = f"[{b['lang']}]" if b['lang'] else '[code]'
            out += ['', lbl, b['code'], '']
        elif t == 'table':
            if b['headers']:
                widths = [max(len(h), max((len(r[j]) for r in b['rows'] if j < len(r)), default=0))
                          for j, h in enumerate(b['headers'])]
                row_fmt = lambda cells: '  ' + '  '.join(
                    str(c).ljust(widths[j]) for j, c in enumerate(cells) if j < len(widths))
                out += ['', row_fmt(b['headers']),
                        '  ' + '  '.join('-' * w for w in widths)]
                for r in b['rows']:
                    out.append(row_fmt(r))
                out.append('')
        elif t == 'hr':
            out += ['', '─' * 60, '']
    return '\n'.join(out).encode('utf-8')


# ── DOCX ─────────────────────────────────────────────────────────────────────

def generate_docx(content: str) -> bytes:
    from docx import Document  # type: ignore
    from docx.shared import Pt, RGBColor

    doc = Document()
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(11)

    blocks = _parse_md(content)

    for b in blocks:
        t = b['type']
        if t == 'heading':
            doc.add_heading(b['text'], level=min(b['level'], 3))
        elif t == 'paragraph':
            doc.add_paragraph(b['text'])
        elif t == 'bullet':
            doc.add_paragraph(b['text'], style='List Bullet')
        elif t == 'numbered':
            doc.add_paragraph(b['text'], style='List Number')
        elif t == 'code':
            p = doc.add_paragraph()
            run = p.add_run(b['code'])
            run.font.name = 'Courier New'
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x2e, 0x86, 0xc1)
        elif t == 'table' and b['headers']:
            tbl = doc.add_table(rows=1, cols=len(b['headers']))
            tbl.style = 'Table Grid'
            for j, h in enumerate(b['headers']):
                cell = tbl.rows[0].cells[j]
                cell.text = h
                cell.paragraphs[0].runs[0].bold = True
            for row in b['rows']:
                cells = tbl.add_row().cells
                for j, val in enumerate(row[:len(b['headers'])]):
                    cells[j].text = val
            doc.add_paragraph('')
        elif t == 'hr':
            doc.add_paragraph('─' * 50)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── PDF ───────────────────────────────────────────────────────────────────────

def _new_pdf():
    """Build a configured PDF instance with a Unicode font registered when
    available. Returns (pdf, body_font, body_bold) where the font names are
    correct for the registered family (falls back to Helvetica)."""
    from fpdf import FPDF  # type: ignore

    class PDF(FPDF):
        def header(self):
            pass

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)
    if _register_unicode_font(pdf, "Unicode"):
        return pdf, "Unicode", "Unicode", True
    return pdf, "Helvetica", "Helvetica", False


def _render_blocks(pdf, blocks: list[dict], body_font: str, bold_font: str,
                    unicode_ok: bool, page_w: float = 174.0) -> None:
    """Render parsed markdown blocks onto an fpdf2 PDF. Shared between
    generate_pdf and generate_pdf_bilingual."""
    for b in blocks:
        t = b['type']

        if t == 'heading':
            sizes = {1: 18, 2: 14, 3: 12}
            sz = sizes.get(b['level'], 11)
            pdf.set_font(bold_font, 'B', sz)
            pdf.ln(4)
            pdf.multi_cell(0, max(5, sz * 0.55), _safe(b['text'], unicode_ok))
            pdf.ln(2)

        elif t == 'paragraph':
            pdf.set_font(body_font, '', 11)
            pdf.multi_cell(0, 6, _safe(b['text'], unicode_ok))
            pdf.ln(2)

        elif t == 'bullet':
            pdf.set_font(body_font, '', 11)
            pdf.set_x(22)
            pdf.multi_cell(0, 6, _safe('- ' + b['text'], unicode_ok))

        elif t == 'numbered':
            pdf.set_font(body_font, '', 11)
            pdf.set_x(22)
            pdf.multi_cell(0, 6, _safe(f"{b['index']}. " + b['text'], unicode_ok))

        elif t == 'code':
            pdf.set_font('Courier', '', 8)
            pdf.set_fill_color(38, 42, 46)
            pdf.set_text_color(200, 210, 220)
            for line in b['code'].splitlines():
                # Code rendering deliberately uses Courier (latin-1 only) for
                # monospaced look — wrap and force latin-1 since code is
                # typically ASCII anyway.
                safe_line = _safe(line[:120], unicode_ok=False)
                pdf.multi_cell(0, 4.5, safe_line, fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)

        elif t == 'table' and b['headers']:
            n = max(1, len(b['headers']))
            col_w = min(45, page_w // n)
            pdf.set_font(bold_font, 'B', 8)
            pdf.set_fill_color(38, 119, 191)
            pdf.set_text_color(255, 255, 255)
            for h in b['headers']:
                pdf.cell(col_w, 7, _safe(h[:25], unicode_ok), border=1, fill=True)
            pdf.ln()
            pdf.set_font(body_font, '', 8)
            pdf.set_fill_color(245, 247, 250)
            pdf.set_text_color(30, 30, 30)
            for ri, row in enumerate(b['rows']):
                fill = ri % 2 == 1
                for j, val in enumerate(row[:n]):
                    pdf.cell(col_w, 6, _safe(str(val)[:25], unicode_ok), border=1, fill=fill)
                pdf.ln()
            pdf.ln(3)

        elif t == 'hr':
            pdf.ln(2)
            x, y = pdf.get_x(), pdf.get_y()
            pdf.line(x, y, x + page_w, y)
            pdf.ln(4)


def generate_pdf(content: str) -> bytes:
    pdf, body_font, bold_font, unicode_ok = _new_pdf()
    blocks = _parse_md(content)
    PAGE_W = 210 - 36  # usable width (mm)
    _render_blocks(pdf, blocks, body_font, bold_font, unicode_ok, PAGE_W)
    return bytes(pdf.output())


def generate_pdf_bilingual(
    pairs: "list[tuple[dict, str]] | None" = None,
    primary_label: str = "English",
    target_label: str = "Translation",
    *,
    entries: "list[dict] | None" = None,
    target_labels: "list[str] | None" = None,
) -> bytes:
    """Generate a bilingual PDF from pre-paired (block, translated_text) tuples.

    The caller is responsible for translating each markdown block individually
    and passing the pairs in order. This avoids the structural drift problem
    where translating the whole markdown at once collapses all paragraphs
    into one (which happens with NLLB on multi-paragraph input).

    Each pair becomes:
        <primary block, rendered as markdown>
        <translation text, rendered as paragraph in a slightly lighter color>
        <thin separator>

    Two call forms supported:
      (a) Two-language (legacy):
            pairs = [(block, translation_string), ...]
            target_label = "Русский"
      (b) Multilingual:
            entries = [{"block": <block>, "translations": {"russian": "...", "uzbek": "..."}}]
            target_labels = ["Русский", "O'zbek"]
    """
    pdf, body_font, bold_font, unicode_ok = _new_pdf()

    # Normalize: convert legacy (pairs, target_label) into the multilingual
    # entries+labels shape so we only have one render path below.
    if entries is None:
        entries = []
        # Use a synthetic lang key "_t" since legacy callers don't pass lang codes
        for block, tr in (pairs or []):
            entries.append({"block": block, "translations": {"_t": tr}})
        target_labels = target_labels or [target_label]
        target_langs  = ["_t"]
    else:
        # We need keys to look up translations[block]. Derive from labels order
        # — caller is expected to pass parallel target_langs in pairs[]. Most
        # callers use the keyword `target_labels=[...]` only; in that case
        # translation keys are arbitrary strings, so iterate translations dict.
        target_labels = target_labels or []
        target_langs  = []  # filled below from first entry's translations dict

    if not target_langs and entries:
        # Stable order: take keys from the first entry that has translations
        for ent in entries:
            if ent.get("translations"):
                target_langs = list(ent["translations"].keys())
                break

    # Title block: "English ◇ Русский ◇ O'zbek"
    pdf.set_font(bold_font, 'B', 16)
    title_text = f"{primary_label}  ·  " + "  ·  ".join(target_labels) if target_labels else primary_label
    pdf.multi_cell(0, 8, _safe(title_text, unicode_ok))
    pdf.ln(1)
    pdf.set_font(body_font, '', 9)
    pdf.set_text_color(120, 120, 120)
    if len(target_labels) <= 1:
        sub = (f"Bilingual document — each {primary_label} passage is followed by "
               f"its {target_labels[0] if target_labels else ''} translation.")
    else:
        sub = (f"Multilingual document — each {primary_label} passage is followed by "
               f"its translation into {', '.join(target_labels)}.")
    pdf.multi_cell(0, 5, _safe(sub, unicode_ok))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    PAGE_W = 210 - 36
    # Per-language label color cycle — keeps each translation visually distinct
    LANG_COLORS = [
        (70,  90,  110),   # slate
        (95,  80,  130),   # plum
        (110, 95,  60),    # bronze
        (60,  100, 90),    # teal
    ]

    for ent in entries:
        block = ent.get("block", {})
        translations = ent.get("translations", {})

        # Primary version
        pdf.set_x(pdf.l_margin)
        _render_blocks(pdf, [block], body_font, bold_font, unicode_ok, PAGE_W)

        # Each translation in order, same visual style, softer color
        if block.get('type') not in ('code', 'table', 'hr'):
            for idx, lang in enumerate(target_langs):
                tr = (translations.get(lang) or "").strip()
                if not tr:
                    continue
                pdf.set_x(pdf.l_margin)
                color = LANG_COLORS[idx % len(LANG_COLORS)]
                pdf.set_text_color(*color)
                # Tiny lang tag in front of the translation for clarity when
                # multiple targets are present.
                if len(target_langs) > 1 and idx < len(target_labels):
                    pdf.set_font(bold_font, 'B', 8)
                    pdf.cell(0, 4, _safe(target_labels[idx], unicode_ok), ln=1)
                trans_block = {**block, 'text': tr}
                _render_blocks(pdf, [trans_block], body_font, bold_font, unicode_ok, PAGE_W)
            pdf.set_text_color(0, 0, 0)

        # Separator between entries
        pdf.set_x(pdf.l_margin)
        pdf.ln(1)
        x, y = pdf.get_x(), pdf.get_y()
        pdf.set_draw_color(220, 224, 230)
        pdf.line(x + 60, y, x + PAGE_W - 60, y)
        pdf.set_draw_color(0, 0, 0)
        pdf.ln(4)

    return bytes(pdf.output())


def parse_markdown_blocks(content: str) -> list[dict]:
    """Public helper — exposes the markdown block parser so callers can
    drive per-block translation when building bilingual documents."""
    return _parse_md(content)


def block_text_for_translation(block: dict) -> Optional[str]:
    """Extract the translatable text from a parsed markdown block.

    Returns None for blocks that should not be translated (code, hr, empty).
    Tables are translated cell-by-cell elsewhere — this returns None for them
    to signal that the caller should handle them specially.
    """
    t = block.get('type')
    if t in ('heading', 'paragraph', 'bullet'):
        return (block.get('text') or '').strip() or None
    if t == 'numbered':
        return (block.get('text') or '').strip() or None
    return None


# ── XLSX ─────────────────────────────────────────────────────────────────────

def generate_xlsx(content: str) -> bytes:
    import openpyxl  # type: ignore
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'MaxCoder'

    thin = Side(style='thin', color='BBBBBB')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    blue_fill = PatternFill('solid', fgColor='2677BF')
    alt_fill  = PatternFill('solid', fgColor='EEF4FB')

    row = 1
    blocks = _parse_md(content)

    for b in blocks:
        t = b['type']

        if t == 'heading':
            cell = ws.cell(row=row, column=1, value=b['text'])
            cell.font = Font(bold=True, size={1:16,2:13,3:11}.get(b['level'],11))
            row += 1

        elif t in ('paragraph', 'bullet', 'numbered'):
            prefix = '• ' if t == 'bullet' else (f"{b['index']}. " if t == 'numbered' else '')
            ws.cell(row=row, column=1, value=prefix + b['text'])
            row += 1

        elif t == 'code':
            cell = ws.cell(row=row, column=1, value=b['code'][:MAX_CELL])
            cell.font = Font(name='Courier New', size=9, color='2E86C1')
            row += 1

        elif t == 'table' and b['headers']:
            n = len(b['headers'])
            # Header
            for j, h in enumerate(b['headers'], 1):
                c = ws.cell(row=row, column=j, value=h)
                c.font = Font(bold=True, color='FFFFFF', size=10)
                c.fill = blue_fill
                c.alignment = Alignment(horizontal='center', vertical='center')
                c.border = border
            row += 1
            # Data rows
            for ri, data_row in enumerate(b['rows']):
                fill = alt_fill if ri % 2 == 1 else None
                for j, val in enumerate(data_row[:n], 1):
                    c = ws.cell(row=row, column=j, value=val[:MAX_CELL] if isinstance(val, str) else val)
                    c.border = border
                    if fill:
                        c.fill = fill
                row += 1
            row += 1  # blank gap

        elif t == 'hr':
            row += 1

    # Auto-size columns
    for col in ws.columns:
        max_len = max((len(str(c.value or '')) for c in col), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── CSV ───────────────────────────────────────────────────────────────────────

def generate_csv(content: str) -> bytes:
    blocks = _parse_md(content)
    tables = [b for b in blocks if b['type'] == 'table']

    buf = io.StringIO()
    writer = csv.writer(buf)

    if tables:
        t = tables[0]
        writer.writerow(t['headers'])
        for row in t['rows']:
            writer.writerow(row)
    else:
        for b in blocks:
            if b['type'] in ('paragraph', 'bullet', 'numbered'):
                writer.writerow([b['text']])

    return buf.getvalue().encode('utf-8')


# ── Dispatcher ────────────────────────────────────────────────────────────────

FORMATS = {
    'txt':  ('text/plain',                    '.txt',  generate_txt),
    'docx': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx', generate_docx),
    'pdf':  ('application/pdf',               '.pdf',  generate_pdf),
    'xlsx': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',       '.xlsx', generate_xlsx),
    'csv':  ('text/csv',                      '.csv',  generate_csv),
}


def _generate_pdf_bilingual_from_json(content: str) -> bytes:
    """Adapter for the generate_file() router. Accepts either:

    Multilingual envelope (preferred):
      {
        "primary_label": "English",
        "target_labels": ["Русский", "O'zbek"],
        "target_langs":  ["russian", "uzbek"],
        "entries": [
          {"block": <md block>, "translations": {"russian": "...", "uzbek": "..."}},
          ...
        ]
      }

    Legacy two-language envelope:
      {"primary_label": "English", "target_label": "Русский",
       "pairs": [{"block": <md block>, "translation": "..."}, ...]}
    """
    import json as _json
    try:
        data = _json.loads(content)
        if "entries" in data:
            return generate_pdf_bilingual(
                entries=data["entries"],
                target_labels=data.get("target_labels", []),
                primary_label=data.get("primary_label", "English"),
            )
        pairs = [(p["block"], p.get("translation", "")) for p in data.get("pairs", [])]
        return generate_pdf_bilingual(
            pairs,
            primary_label=data.get("primary_label", "English"),
            target_label=data.get("target_label",  "Translation"),
        )
    except Exception as e:
        # Fall back to a clearly-labeled error PDF rather than failing silently
        err = f"Bilingual PDF render failed: {type(e).__name__}: {e}\n\n--- raw payload ---\n{content[:1000]}"
        return generate_pdf(err)


FORMATS["pdf-bilingual"] = ("application/pdf", ".pdf", _generate_pdf_bilingual_from_json)


def generate_file(fmt: str, content: str) -> tuple[bytes, str, str]:
    """Returns (bytes, mime_type, extension)."""
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported format '{fmt}'. Choose from: {list(FORMATS)}")
    mime, ext, fn = FORMATS[fmt]
    return fn(content), mime, ext
