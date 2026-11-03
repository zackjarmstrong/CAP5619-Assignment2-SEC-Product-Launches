"""Render the approved editable methodology Markdown as a two-page PDF offline.

METHODOLOGY.md is the source of truth; this command never rewrites it. The
submitted PDF may be an approved external rendering of the same text. Rebuilding
preserves its content and page split, but does not promise identical PDF bytes.
"""
import argparse
from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate


SECOND_PAGE_HEADING = "Checking results and handling problems"


def read_blocks(source):
    """Read the report's headings and blank-line-separated paragraphs."""
    blocks, paragraph = [], []

    def flush():
        if paragraph:
            blocks.append(("paragraph", " ".join(paragraph)))
            paragraph.clear()

    for line in source.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            flush()
        elif line.startswith("## "):
            flush()
            blocks.append(("heading", line[3:]))
        elif line.startswith("# "):
            flush()
            blocks.append(("title", line[2:]))
        elif line.startswith("#"):
            raise ValueError("Only title and section headings are supported")
        else:
            paragraph.append(line)
    flush()
    if not blocks or blocks[0][0] != "title":
        raise ValueError("The report must start with a Markdown title")
    if sum(kind == "title" for kind, _ in blocks) != 1:
        raise ValueError("The report must contain exactly one title")
    if sum(kind == "heading" and text == SECOND_PAGE_HEADING for kind, text in blocks) != 1:
        raise ValueError("The approved second-page heading is missing or duplicated")
    return blocks


def inline(text):
    """Escape document text, retaining Markdown bold and clickable bare URLs."""
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"https://[^\s<]+", lambda m: '<link href="' + m[0] + '">' + m[0] + "</link>", text)


def build_report(source, output):
    blocks = read_blocks(source)
    styles = getSampleStyleSheet()
    ink = colors.HexColor("#18232D")
    styles.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=18,
                              leading=22, textColor=ink, spaceAfter=9))
    styles.add(ParagraphStyle(name="ReportSubtitle", fontName="Helvetica", fontSize=9.5,
                              leading=13, textColor=colors.HexColor("#526173"), spaceAfter=22))
    styles.add(ParagraphStyle(name="ReportHeading", fontName="Helvetica-Bold", fontSize=12,
                              leading=16, textColor=ink, spaceBefore=7, spaceAfter=5,
                              keepWithNext=True))
    styles.add(ParagraphStyle(name="ReportText", fontName="Helvetica", fontSize=10.2,
                              leading=14.6, textColor=ink, spaceAfter=9))
    story = []
    for index, (kind, text) in enumerate(blocks):
        if kind == "heading" and text == SECOND_PAGE_HEADING:
            story.append(PageBreak())
        if kind == "title":
            style = styles["ReportTitle"]
        elif kind == "heading":
            style = styles["ReportHeading"]
        elif index == 1:
            style = styles["ReportSubtitle"]
        else:
            style = styles["ReportText"]
        story.append(Paragraph(inline(text), style))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#CCD5DF"))
        canvas.line(54, 42, 558, 42)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#657383"))
        canvas.drawString(54, 29, "CAP5619 | Assignment 2 | Methodology")
        canvas.drawRightString(558, 29, str(doc.page))
        canvas.restoreState()
        if doc.page > 2:
            raise ValueError("Report exceeds two pages; review the Markdown or layout")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        SimpleDocTemplate(str(temporary), pagesize=(612, 792), leftMargin=60, rightMargin=60,
                          topMargin=54, bottomMargin=57, title=blocks[0][1],
                          author="CAP5619 Assignment 2").build(
                              story, onFirstPage=footer, onLaterPages=footer)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("METHODOLOGY.md"))
    parser.add_argument("--output", type=Path, default=Path("output/pdf/methodology_report.pdf"))
    args = parser.parse_args()
    build_report(args.source, args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
