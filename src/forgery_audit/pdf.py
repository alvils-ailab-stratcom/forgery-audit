"""Official-document PDF rendered from the delivered Markdown, so both formats always carry the same content."""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DOCUMENT_TITLE = "Digitālā materiāla dziļviltojuma analīzes atzinums"
ISSUER = "Forgery Audit"
FONT_DIR = Path(os.environ.get("FORGERY_AUDIT_FONT_DIR", "/usr/share/fonts/truetype/dejavu"))
INK = colors.HexColor("#1b2a38")
RULE = colors.HexColor("#8a97a3")
SHADE = colors.HexColor("#eef2f5")


def register_fonts() -> tuple[str, str]:
    regular = Path(os.environ.get("FORGERY_AUDIT_FONT", FONT_DIR / "DejaVuSans.ttf"))
    bold = Path(os.environ.get("FORGERY_AUDIT_FONT_BOLD", FONT_DIR / "DejaVuSans-Bold.ttf"))
    if not regular.is_file():
        raise RuntimeError("Install fonts-dejavu-core or set FORGERY_AUDIT_FONT to a Unicode TTF font")
    pdfmetrics.registerFont(TTFont("Doc", str(regular)))
    if bold.is_file():
        pdfmetrics.registerFont(TTFont("DocBold", str(bold)))
        return "Doc", "DocBold"
    return "Doc", "Doc"


def inline(text: str) -> str:
    """Markdown inline subset (code, bold, links) to reportlab paragraph markup."""
    out = escape(text)
    out = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8">\1</font>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<link href="\2" color="#1a4f8b"><u>\1</u></link>', out)
    return out


def parse_blocks(markdown: str) -> list[tuple[str, Any]]:
    """Blocks: ('h1', text) ('h2', text) ('table', rows) ('list', items) ('bullets', items) ('p', text)."""
    blocks: list[tuple[str, Any]] = []
    for raw in markdown.split("\n\n"):
        chunk = raw.strip("\n")
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        first = lines[0]
        if first.startswith("# "):
            blocks.append(("h1", first[2:].strip()))
        elif first.startswith("## "):
            blocks.append(("h2", first[3:].strip()))
        elif first.startswith("|"):
            rows = [
                [cell.strip() for cell in line.strip().strip("|").split("|")]
                for line in lines
                if line.strip().startswith("|") and not re.match(r"^\|\s*-+", line.strip())
            ]
            blocks.append(("table", rows))
        elif re.match(r"^\d+\. ", first):
            blocks.append(("list", [re.sub(r"^\d+\. ", "", line).strip() for line in lines if line.strip()]))
        elif first.startswith("- "):
            blocks.append(("bullets", [line[2:].strip() for line in lines if line.startswith("- ")]))
        else:
            blocks.append(("p", " ".join(line.strip() for line in lines)))
    return blocks


def story_has_section(story: list[Flowable]) -> bool:
    """True once the first subject heading (the file name) has been emitted after the title."""
    return any(getattr(getattr(f, "style", None), "name", None) == "subject" for f in story)


def write_pdf(markdown_path: Path, pdf_path: Path | None = None, subject: str | None = None) -> Path:
    pdf_path = pdf_path or markdown_path.with_suffix(".pdf")
    regular, bold = register_fonts()
    body = ParagraphStyle("body", fontName=regular, fontSize=9.5, leading=13.5, alignment=TA_JUSTIFY, spaceAfter=6)
    cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=11.5, alignment=0, spaceAfter=0)
    cell_head = ParagraphStyle("cellHead", parent=cell, fontName=bold)
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=15, leading=19, textColor=INK, spaceAfter=2)
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=11, leading=15, textColor=INK, spaceBefore=9, spaceAfter=4)
    kicker = ParagraphStyle("kicker", fontName=regular, fontSize=8.5, leading=11, textColor=RULE, spaceAfter=8)
    item = ParagraphStyle("item", parent=body, leftIndent=14, firstLineIndent=-14, spaceAfter=3)
    subject_style = ParagraphStyle("subject", parent=h2, fontSize=12.5, leading=16, spaceBefore=2, spaceAfter=6)
    blocks = parse_blocks(markdown_path.read_text(encoding="utf-8"))
    story: list[Flowable] = []
    width = A4[0] - 40 * mm
    for kind, value in blocks:
        if kind == "h1":
            story += [
                Paragraph(inline(str(value)), h1),
                Paragraph(
                    escape(f"{ISSUER} · sagatavots {datetime.now(UTC).strftime('%Y-%m-%d')} · automatizēta analīze"),
                    kicker,
                ),
            ]
        elif kind == "h2" and not story_has_section(story):
            story.append(Paragraph(inline(str(value)), subject_style))
        elif kind == "h2":
            story.append(Paragraph(inline(str(value)), h2))
        elif kind == "table":
            rows = [list(r) for r in value if isinstance(r, list)]
            if not rows:
                continue
            data = [[Paragraph(inline(c), cell_head) for c in rows[0]]]
            data += [[Paragraph(inline(c), cell) for c in row] for row in rows[1:]]
            columns = max(len(r) for r in data)
            first = min(0.34 * width, 62 * mm) if columns == 2 else width / columns
            widths = [first] + [(width - first) / (columns - 1)] * (columns - 1) if columns > 1 else [width]
            table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                    ]
                )
            )
            story += [table, Spacer(1, 4)]
        elif kind == "list":
            story.append(KeepTogether([Paragraph(f"{i}. {inline(t)}", item) for i, t in enumerate(list(value), 1)]))
        elif kind == "bullets":
            story += [Paragraph(f"• {inline(t)}", item) for t in list(value)]
        else:
            story.append(Paragraph(inline(str(value)), body))

    footer_text = subject or markdown_path.stem

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(RULE)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
        canvas.drawString(20 * mm, 11.5 * mm, f"{DOCUMENT_TITLE} · {footer_text}")
        canvas.drawRightString(A4[0] - 20 * mm, 11.5 * mm, f"{doc.page}. lpp.")
        canvas.restoreState()

    SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title=f"{DOCUMENT_TITLE}: {footer_text}",
        author=ISSUER,
        subject=footer_text,
    ).build(story, onFirstPage=decorate, onLaterPages=decorate)
    return pdf_path
