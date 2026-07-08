#!/usr/bin/env python3
"""Convert analysis markdown report to PDF using reportlab with Chinese font support."""

import os
import re
import sys
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, Frame, PageTemplate, BaseDocTemplate
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from fontTools.ttLib import TTCollection

REPORT_DIR = os.path.join(os.path.dirname(__file__), '..', 'analysis-reports')
FONT_DIR = 'C:/Windows/Fonts'

# ── Font registration ──────────────────────────────────────────────
CHINESE_FONT = 'zh'
FONT_BOLD = 'zh_bold'
FONT_MONO = 'zh_mono'
FONT_READY = False

def _register_chinese_fonts():
    global FONT_READY
    msyh_path = os.path.join(FONT_DIR, 'msyh.ttc')
    msyhbd_path = os.path.join(FONT_DIR, 'msyhbd.ttc')
    consolas_path = os.path.join(FONT_DIR, 'consola.ttf')

    if not os.path.exists(msyh_path):
        return False

    try:
        # Regular (微软雅黑)
        ttc = TTCollection(msyh_path)
        tmp = tempfile.NamedTemporaryFile(suffix='.ttf', delete=False)
        ttc[0].save(tmp.name)
        pdfmetrics.registerFont(TTFont(CHINESE_FONT, tmp.name))

        # Bold (微软雅黑粗体)
        if os.path.exists(msyhbd_path):
            ttc_bd = TTCollection(msyhbd_path)
            tmp_bd = tempfile.NamedTemporaryFile(suffix='.ttf', delete=False)
            ttc_bd[0].save(tmp_bd.name)
            pdfmetrics.registerFont(TTFont(FONT_BOLD, tmp_bd.name))
        else:
            FONT_BOLD = CHINESE_FONT

        # Monospace — use 微软雅黑 for code blocks too (no Courier alternative
        # that covers CJK). If Consolas is available, use it for ASCII art;
        # otherwise fall back to the regular Chinese font.
        if os.path.exists(consolas_path):
            pdfmetrics.registerFont(TTFont(FONT_MONO, consolas_path))
        else:
            FONT_MONO = CHINESE_FONT  # msyh can at least render the Chinese parts

        return True
    except Exception:
        return False

FONT_READY = _register_chinese_fonts()


# ── Helpers ─────────────────────────────────────────────────────────

def strip_markdown(text):
    """Remove markdown formatting, keeping content readable."""
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Bold / italic — remove ** markers but keep content
    text = re.sub(r'[*_]{2,}', '', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # HTML entities that reportlab may not pass through
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    # restore common entities
    text = text.replace('&amp;bull;', '&bull;')
    text = text.replace('&amp;nbsp;', '&nbsp;')
    # arrows used in diagrams
    text = text.replace('→', '\u2192')
    text = text.replace('←', '\u2190')
    text = text.replace('─', '\u2500')
    text = text.replace('│', '\u2502')
    text = text.replace('┌', '\u250C')
    text = text.replace('┐', '\u2510')
    text = text.replace('└', '\u2514')
    text = text.replace('┘', '\u2518')
    text = text.replace('├', '\u251C')
    text = text.replace('┤', '\u2524')
    text = text.replace('┬', '\u252C')
    text = text.replace('┴', '\u2534')
    text = text.replace('┼', '\u253C')
    text = text.replace('▼', '\u25BC')
    text = text.replace('✓', '\u2713')
    text = text.replace('✗', '\u2717')
    text = text.replace('•', '\u2022')
    return text


def _has_cjk(text: str) -> bool:
    """Check if text contains CJK (Chinese/Japanese/Korean) characters."""
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f':
            return True
    return False

def _font_name(kind='body', text=None):
    """
    Return the correct font name based on availability.
    If text contains CJK characters, use the Chinese font instead of
    a western-only font (e.g. Consolas in code blocks).
    """
    if not FONT_READY:
        return {'body': 'Helvetica', 'bold': 'Helvetica-Bold', 'mono': 'Courier', 'heading_bold': 'Helvetica-Bold'}[kind]
    if kind == 'mono' and text is not None and _has_cjk(text):
        return CHINESE_FONT  # fall back to msyh for CJK content
    return {
        'body': CHINESE_FONT,
        'bold': FONT_BOLD,
        'mono': FONT_MONO,
        'heading_bold': FONT_BOLD,
    }[kind]


# ── Styles ──────────────────────────────────────────────────────────

def build_styles():
    styles = {}

    f_body = _font_name('body')
    f_bold = _font_name('bold')
    f_heading_bold = _font_name('heading_bold')
    f_mono = _font_name('mono')

    styles['title'] = ParagraphStyle(
        'Title', fontName=f_heading_bold, fontSize=18,
        leading=24, textColor=HexColor('#1E3C78'),
        spaceAfter=8, spaceBefore=4,
        wordWrap='CJK',
    )
    styles['h1'] = ParagraphStyle(
        'H1', fontName=f_heading_bold, fontSize=14,
        leading=18, textColor=HexColor('#28508C'),
        spaceAfter=4, spaceBefore=10,
        wordWrap='CJK',
    )
    styles['h2'] = ParagraphStyle(
        'H2', fontName=f_heading_bold, fontSize=12,
        leading=15, textColor=HexColor('#3C64A0'),
        spaceAfter=3, spaceBefore=8,
        wordWrap='CJK',
    )
    styles['h3'] = ParagraphStyle(
        'H3', fontName=f_heading_bold, fontSize=10,
        leading=13, textColor=HexColor('#5078B4'),
        spaceAfter=2, spaceBefore=6,
        wordWrap='CJK',
    )
    styles['body'] = ParagraphStyle(
        'Body', fontName=f_body, fontSize=9,
        leading=13, textColor=HexColor('#333333'),
        spaceAfter=2, spaceBefore=1,
        wordWrap='CJK',
    )
    styles['code'] = ParagraphStyle(
        'Code', fontName=f_mono, fontSize=7.5,
        leading=10, textColor=HexColor('#333333'),
        backColor=HexColor('#F2F2F2'),
        spaceAfter=2, spaceBefore=1,
        leftIndent=6,
        wordWrap='CJK',
    )
    styles['bullet'] = ParagraphStyle(
        'Bullet', fontName=f_body, fontSize=9,
        leading=12, textColor=HexColor('#333333'),
        leftIndent=12, spaceAfter=1,
        wordWrap='CJK',
    )
    styles['table_header'] = ParagraphStyle(
        'TableHeader', fontName=f_bold, fontSize=8,
        leading=11, textColor=HexColor('#FFFFFF'),
        alignment=1, wordWrap='CJK',
    )
    styles['table_cell'] = ParagraphStyle(
        'TableCell', fontName=f_body, fontSize=8,
        leading=11, textColor=HexColor('#333333'),
        wordWrap='CJK',
    )
    styles['table_cell_mono'] = ParagraphStyle(
        'TableMono', fontName=f_mono, fontSize=7.5,
        leading=10, textColor=HexColor('#333333'),
        wordWrap='CJK',
    )
    return styles


# ── Markdown Parser ────────────────────────────────────────────────

def parse_markdown(md_path):
    styles = build_styles()
    elements = []

    in_code = False
    code_buf = []
    # Table accumulation
    table_rows = []
    in_table = False

    # Track whether we are inside a diagram block (ASCII art) inside a code fence
    # Actually code fences already handle this via in_code flag.

    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    def _flush_code():
        nonlocal code_buf
        if code_buf:
            text = '\n'.join(code_buf)
            code_buf = []
            if text.strip():
                # Pick font: Consolas for pure ASCII, Chinese font for CJK content
                font_code = _font_name('mono', text)
                style_code = ParagraphStyle('Code', fontName=font_code, fontSize=7.5,
                    leading=10, textColor=HexColor('#333333'),
                    backColor=HexColor('#F2F2F2'),
                    spaceAfter=2, spaceBefore=1,
                    leftIndent=6, wordWrap='CJK')
                elements.append(Paragraph(
                    text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>'),
                    style_code
                ))

    def _flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        # table_rows: list of lists of cell text (header row and data rows)
        header = table_rows[0]
        data = table_rows[1:]
        ncols = max(len(r) for r in table_rows)

        # Build reportlab Table
        table_data = []
        for i, row in enumerate(table_rows):
            row_data = []
            for cell in row:
                # Detect if cell is mostly ASCII art / code -> use mono style
                is_mono = _is_mono_cell(cell)
                style_name = 'table_cell_mono' if is_mono else 'table_cell'
                if i == 0:
                    row_data.append(Paragraph(cell, styles['table_header']))
                elif is_mono:
                    # Use CJK-aware font if the cell contains Chinese
                    font_cell = _font_name('mono', cell)
                    style_cell = ParagraphStyle('TableMono', fontName=font_cell, fontSize=7.5,
                        leading=10, textColor=HexColor('#333333'), wordWrap='CJK')
                    row_data.append(Paragraph(cell, style_cell))
                else:
                    row_data.append(Paragraph(cell, styles[style_name]))
            # Pad row to fill missing cells
            while len(row_data) < ncols:
                row_data.append(Paragraph('', styles['table_cell']))
            table_data.append(row_data)

        # Calculate column widths (proportional)
        avail_width = A4[0] - 40 * mm  # page width minus margins
        col_widths = [avail_width / ncols] * ncols

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#28508C')),
            ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#FFFFFF')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#CCCCCC')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#FFFFFF'), HexColor('#F5F7FA')]),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]
        t.setStyle(TableStyle(style_cmds))
        elements.append(Spacer(1, 4))
        elements.append(t)
        elements.append(Spacer(1, 4))
        table_rows = []

    def _is_mono_cell(cell_text):
        """Rough heuristic: if more than half the visible chars are diagram
        characters (|, -, +, etc.), use the mono font."""
        count_special = sum(1 for c in cell_text if c in '|-+*/\\<>^v=V#@!()[]{}')
        count_total = len(cell_text.strip())
        if count_total == 0:
            return False
        return count_special / count_total > 0.3

    for raw in lines:
        line = raw.rstrip()

        # ── Code fence ──
        if line.startswith('```'):
            if in_code:
                _flush_code()
                in_code = False
            else:
                _flush_table()  # flush any pending table
                in_code = True
            continue

        if in_code:
            code_buf.append(line)
            continue

        # ── Horizontal rule / image ──
        if line.startswith('---') or line.startswith('!['):
            continue

        # ── Thematic break (separator line like only ---) ──
        if re.match(r'^\-{3,}$', line):
            elements.append(HRFlowable(width='100%', thickness=1, color=HexColor('#CCCCCC'), spaceBefore=4, spaceAfter=4))
            continue

        # ── Headings ──
        if line.startswith('# '):
            elements.append(Paragraph(strip_markdown(line[2:]), styles['title']))
        elif line.startswith('## '):
            elements.append(Paragraph(strip_markdown(line[3:]), styles['h1']))
        elif line.startswith('### '):
            elements.append(Paragraph(strip_markdown(line[4:]), styles['h2']))
        elif line.startswith('#### '):
            elements.append(Paragraph(strip_markdown(line[5:]), styles['h3']))

        # ── Bullet lists ──
        elif line.startswith('- ') or line.startswith('* '):
            elements.append(Paragraph(f'&bull; {strip_markdown(line[2:])}', styles['bullet']))
        elif line.startswith('  - ') or line.startswith('  * '):
            elements.append(Paragraph(f'&nbsp;&nbsp;&bull; {strip_markdown(line[4:])}', styles['bullet']))

        # ── Tables ──
        elif line.startswith('|'):
            # Skip separator rows (| --- | --- |)
            stripped_content = line.replace('|', '').replace('-', '').replace(':', '').strip()
            if not stripped_content:
                continue
            cells = [c.strip() for c in line.split('|')[1:-1]]
            table_rows.append(cells)

        # ── Empty line ──
        elif not line:
            _flush_table()
            elements.append(Spacer(1, 4))

        # ── Regular paragraph text ──
        else:
            text = strip_markdown(line)
            if text:
                elements.append(Paragraph(text, styles['body']))

    # Flush remaining buffers
    _flush_code()
    _flush_table()

    return elements


def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else 'todo-task-management'
    md_path = os.path.join(REPORT_DIR, f'{topic}-analysis.md')
    pdf_path = os.path.join(REPORT_DIR, f'{topic}-analysis.pdf')

    if not os.path.exists(md_path):
        print(f'Error: {md_path} not found')
        sys.exit(1)

    print(f'Converting {md_path} to PDF...')

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        topMargin=20*mm, bottomMargin=20*mm,
        leftMargin=20*mm, rightMargin=20*mm,
    )

    elements = parse_markdown(md_path)
    doc.build(elements)
    print(f'OK: {pdf_path}')


if __name__ == '__main__':
    main()