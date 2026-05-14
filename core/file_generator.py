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
import io, re, csv

MAX_CELL = 32_767  # Excel cell character limit


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

def generate_pdf(content: str) -> bytes:
    from fpdf import FPDF  # type: ignore

    class PDF(FPDF):
        def header(self):
            pass

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)

    blocks = _parse_md(content)
    PAGE_W = 210 - 36  # usable width

    for b in blocks:
        t = b['type']

        if t == 'heading':
            sizes = {1: 18, 2: 14, 3: 12}
            sz = sizes.get(b['level'], 11)
            pdf.set_font('Helvetica', 'B', sz)
            pdf.ln(4)
            pdf.multi_cell(0, sz * 0.55, b['text'].encode('latin-1', 'replace').decode('latin-1'))
            pdf.ln(2)

        elif t == 'paragraph':
            pdf.set_font('Helvetica', '', 11)
            pdf.multi_cell(0, 6, b['text'].encode('latin-1', 'replace').decode('latin-1'))
            pdf.ln(2)

        elif t == 'bullet':
            pdf.set_font('Helvetica', '', 11)
            pdf.set_x(22)
            pdf.multi_cell(0, 6, ('- ' + b['text']).encode('latin-1', 'replace').decode('latin-1'))

        elif t == 'numbered':
            pdf.set_font('Helvetica', '', 11)
            pdf.set_x(22)
            pdf.multi_cell(0, 6, (f"{b['index']}. " + b['text']).encode('latin-1', 'replace').decode('latin-1'))

        elif t == 'code':
            pdf.set_font('Courier', '', 8)
            pdf.set_fill_color(38, 42, 46)
            pdf.set_text_color(200, 210, 220)
            safe = b['code'].encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(0, 4.5, safe, fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)

        elif t == 'table' and b['headers']:
            n = len(b['headers'])
            col_w = min(45, PAGE_W // n)
            pdf.set_font('Helvetica', 'B', 8)
            pdf.set_fill_color(38, 119, 191)
            pdf.set_text_color(255, 255, 255)
            for h in b['headers']:
                pdf.cell(col_w, 7, h[:22].encode('latin-1', 'replace').decode('latin-1'), border=1, fill=True)
            pdf.ln()
            pdf.set_font('Helvetica', '', 8)
            pdf.set_fill_color(245, 247, 250)
            pdf.set_text_color(30, 30, 30)
            for ri, row in enumerate(b['rows']):
                fill = ri % 2 == 1
                for j, val in enumerate(row[:n]):
                    pdf.cell(col_w, 6, str(val)[:22].encode('latin-1', 'replace').decode('latin-1'), border=1, fill=fill)
                pdf.ln()
            pdf.ln(3)

        elif t == 'hr':
            pdf.ln(2)
            x, y = pdf.get_x(), pdf.get_y()
            pdf.line(x, y, x + PAGE_W, y)
            pdf.ln(4)

    return bytes(pdf.output())


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


def generate_file(fmt: str, content: str) -> tuple[bytes, str, str]:
    """Returns (bytes, mime_type, extension)."""
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported format '{fmt}'. Choose from: {list(FORMATS)}")
    mime, ext, fn = FORMATS[fmt]
    return fn(content), mime, ext
