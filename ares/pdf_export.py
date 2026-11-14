"""Create a printable version of an immutable research report."""

from io import BytesIO
from threading import BoundedSemaphore, Lock

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ReportLab's dynamic font is shared across exports in this process.
PDF_EXPORT_SLOTS = BoundedSemaphore(1)
FONT_LOCK = Lock()
MAX_REPORT_CHARS = 750_000
FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def render_report(markdown):
    output = BytesIO()
    with FONT_LOCK:
        if 'ARES Sans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('ARES Sans', FONT_PATH))
    pdf = canvas.Canvas(output, pagesize=(595, 842), pageCompression=1)
    pdf.setTitle('ARES research evidence report')
    pdf.setAuthor('ARES–Noesis')

    def header():
        pdf.setFillColorRGB(.12, .19, .28)
        pdf.setFont('ARES Sans', 9)
        pdf.drawString(42, 804, 'ARES / NOESIS')
        pdf.line(42, 793, 553, 793)
        return 770

    def footer():
        pdf.setFillColorRGB(.29, .35, .44)
        pdf.setFont('ARES Sans', 8)
        pdf.drawRightString(553, 30, f'Page {pdf.getPageNumber()}')

    top = header()
    for raw_line in markdown.splitlines():
        heading = raw_line.startswith('#')
        line = raw_line.lstrip('#').lstrip() if heading else raw_line
        size = 13 if heading else 9
        if not line:
            top -= 6
            continue
        widths = pdfmetrics.getFont('ARES Sans').face.charWidths
        max_width = 511 * 1000 / size
        start = 0
        while start < len(line):
            end, last_space, width = start, start, 0
            while end < len(line):
                width += widths.get(ord(line[end]), 1000)
                if width > max_width:
                    break
                if line[end].isspace():
                    last_space = end
                end += 1
            if end < len(line) and last_space > start:
                end = last_space
            if top < 52:
                footer()
                pdf.showPage()
                top = header()
            pdf.setFillColorRGB(.12, .19, .28)
            pdf.setFont('ARES Sans', size)
            pdf.drawString(42, top, line[start:end])
            top -= size + 5
            start = end
            while start < len(line) and line[start].isspace():
                start += 1
    footer()
    pdf.save()
    return output.getvalue()
