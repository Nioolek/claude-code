#!/usr/bin/env python3
"""Convert analysis markdown report to PDF using reportlab with Chinese font support."""

import os
import re
import sys
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

REPORT_DIR = os.path.join(os.path.dirname(__file__), '..', 'analysis-reports')
FONT_DIR = 'C:/Windows/Fonts'

# Try to register Chinese font
CHINESE_FONT = 'zh'
try:
    # Extract TTF from TTC if needed
    import tempfile
    from fontTools.ttLib import TTCollection

    ttc_path = os.path.join(FONT_DIR, 'msyh.ttc')
    if os.path.exists(ttc_path):
        ttc = TTCollection(ttc_path)
        tmp = tempfile.NamedTemporaryFile(suffix='.ttf', delete=False)
        ttc[0].save(tmp.name)
        pdfmetrics.registerFont(TTFont(CHINESE_FONT, tmp.name))
        # Also try bold
        bd_ttc = os.path.join(FONT_DIR, 'msyhbd.ttc')
        if os.path.exists(bd_ttc):
            bd_ttc_obj = TTCollection(bd_ttc)
            tmp_bd = tempfile.NamedTemporaryFile(suffix='.ttf', delete=False)
            bd_ttc_obj[0].save(tmp_bd.name)
            pdfmetrics.registerFont(TTFont('zh_bold', tmp_bd.name))
        FONT_READY = True
    else:
        FONT_READY = False
except Exception:
    FONT_READY = False


def strip_markdown(text):
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[*_]{2,}', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text


def build_styles():
    styles = {}

    font_name = CHINESE_FONT if FONT_READY else 'Helvetica'
    font_bold = 'zh_bold' if FONT_READY and 'zh_bold' in [f.face.name for f in pdfmetrics._fonts.values() if hasattr(f, 'face')] else font_name  # simplified

    # Simpler approach for bold
    try:
        pdfmetrics.registerFont(TTFont('zh_bold', os.path.join(FONT_DIR, 'msyhbd.ttc')))
        font_bold = 'zh_bold'
    except:
        font_bold = font_name

    styles['title'] = ParagraphStyle(
        'Title', fontName=font_bold, fontSize=18,
        leading=24, textColor=HexColor('#1E3C78'),
        spaceAfter=8, spaceBefore=4
    )
    styles['h1'] = ParagraphStyle(
        'H1', fontName=font_bold, fontSize=14,
        leading=18, textColor=HexColor('#28508C'),
        spaceAfter=4, spaceBefore=10
    )
    styles['h2'] = ParagraphStyle(
        'H2', fontName=font_bold, fontSize=12,
        leading=15, textColor=HexColor('#3C64A0'),
        spaceAfter=3, spaceBefore=8
    )
    styles['h3'] = ParagraphStyle(
        'H3', fontName=font_bold, fontSize=10,
        leading=13, textColor=HexColor('#5078B4'),
        spaceAfter=2, spaceBefore=6
    )
    styles['body'] = ParagraphStyle(
        'Body', fontName=font_name, fontSize=9,
        leading=13, textColor=HexColor('#333333'),
        spaceAfter=2, spaceBefore=1
    )
    styles['code'] = ParagraphStyle(
        'Code', fontName='Courier', fontSize=7.5,
        leading=10, textColor=HexColor('#333333'),
        backColor=HexColor('#F2F2F2'),
        spaceAfter=2, spaceBefore=1,
        leftIndent=6
    )
    styles['bullet'] = ParagraphStyle(
        'Bullet', fontName=font_name, fontSize=9,
        leading=12, textColor=HexColor('#333333'),
        leftIndent=12, spaceAfter=1,
    )
    return styles


def parse_markdown(md_path):
    """Parse markdown into reportlab flowables."""
    from reportlab.platypus import Table, TableStyle
    styles = build_styles()
    elements = []

    in_code = False
    code_buf = []
    in_table = False

    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for raw in lines:
        line = raw.rstrip()

        if line.startswith('```'):
            if in_code:
                text = '\n'.join(code_buf)
                code_buf = []
                in_code = False
                if text.strip():
                    elements.append(Paragraph(text.replace('\n', '<br/>'), styles['code']))
            else:
                in_code = True
            continue

        if in_code:
            code_buf.append(line)
            continue

        if line.startswith('---') or line.startswith('!['):
            continue

        if line.startswith('# '):
            elements.append(Paragraph(strip_markdown(line[2:]), styles['title']))
        elif line.startswith('## '):
            elements.append(Paragraph(strip_markdown(line[3:]), styles['h1']))
        elif line.startswith('### '):
            elements.append(Paragraph(strip_markdown(line[4:]), styles['h2']))
        elif line.startswith('#### '):
            elements.append(Paragraph(strip_markdown(line[5:]), styles['h3']))
        elif line.startswith('- ') or line.startswith('* '):
            elements.append(Paragraph(f'&bull; {strip_markdown(line[2:])}', styles['bullet']))
        elif line.startswith('  - ') or line.startswith('  * '):
            elements.append(Paragraph(f'&nbsp;&nbsp;&bull; {strip_markdown(line[4:])}', styles['bullet']))
        elif line.startswith('|'):
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if cells and not all(c in set('|-: ') for c in line.replace('|', '')):
                elements.append(Paragraph(' | '.join(cells), styles['body']))
        elif not line:
            elements.append(Spacer(1, 4))
        else:
            text = strip_markdown(line)
            if text:
                elements.append(Paragraph(text, styles['body']))

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
        leftMargin=20*mm, rightMargin=20*mm
    )

    elements = parse_markdown(md_path)
    doc.build(elements)
    print(f'OK: {pdf_path}')


if __name__ == '__main__':
    main()