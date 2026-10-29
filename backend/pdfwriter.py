"""
Minimal, dependency-free PDF writer.

The project does not ship ReportLab, and adding a large dependency for
two export endpoints is not worth it. This module emits a small but
*valid* PDF 1.4 document: A4 pages, built-in Helvetica fonts, wrapped
text, simple tables and page numbers.

It deliberately supports only what the security reports need, so the
implementation stays auditable. If richer layout is ever required,
swap this module out; nothing else imports ReportLab-specific APIs.
"""

import zlib


PAGE_WIDTH = 595.28
PAGE_HEIGHT = 841.89
MARGIN = 50.0
CONTENT_WIDTH = PAGE_WIDTH - (2 * MARGIN)


FONT_REGULAR = "F1"
FONT_BOLD = "F2"


def _escape(text):
    """Escape a string for a PDF literal string operand."""

    text = str(text)

    replacements = {
        "\\": "\\\\",
        "(": "\\(",
        ")": "\\)",
        "\r": " ",
        "\n": " ",
        "\t": " ",
    }

    escaped = "".join(
        replacements.get(character, character)
        for character in text
    )

    return escaped.encode("latin-1", "replace").decode("latin-1")


def _available_width(font_size):
    """Conservative average character width for Helvetica."""

    return 0.52 * font_size


def wrap(text, font_size, width=CONTENT_WIDTH):
    """Greedy word wrap using an approximate Helvetica metric."""

    characters = max(8, int(width / _available_width(font_size)))

    words = str(text).split()
    lines = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"

        if len(candidate) <= characters:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines or [""]


class _Page:
    def __init__(self):
        self.operations = []

    def text(self, x, y, value, font_size=10.0, bold=False):
        font = FONT_BOLD if bold else FONT_REGULAR

        self.operations.append(
            f"BT /{font} {font_size:.2f} Tf "
            f"1 0 0 1 {x:.2f} {y:.2f} Tm "
            f"({_escape(value)}) Tj ET"
        )

    def line(self, x1, y1, x2, y2, width=0.6):
        self.operations.append(
            f"{width:.2f} w "
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"
        )

    def rect(self, x, y, width, height, fill=False):
        operator = "f" if fill else "S"
        self.operations.append(
            f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re {operator}"
        )

    def stream(self):
        return "\n".join(self.operations)


class PdfBuilder:
    """Build a PDF document incrementally, one block at a time."""

    def __init__(self, title="EduShield AI report"):
        self.title = title
        self.pages = []
        self.page = None
        self.cursor_y = 0.0

    # -- page lifecycle --------------------------------------------

    def new_page(self):
        if self.page is not None:
            self.pages.append(self.page)

        self.page = _Page()
        self.cursor_y = PAGE_HEIGHT - MARGIN
        return self.page

    def ensure_page(self):
        if self.page is None:
            self.new_page()

    def remaining(self):
        return self.cursor_y - MARGIN

    def space(self, height):
        self.cursor_y -= height

    # -- blocks ----------------------------------------------------

    def heading(self, text, level=1):
        self.ensure_page()

        size = 17.0 if level == 1 else 12.5
        spacing = 26.0 if level == 1 else 20.0

        if self.remaining() < spacing + 30:
            self.new_page()

        self.space(spacing)
        self.page.text(MARGIN, self.cursor_y, text, size, bold=True)
        self.space(6)

        if level == 1:
            self.page.line(
                MARGIN,
                self.cursor_y,
                PAGE_WIDTH - MARGIN,
                self.cursor_y,
                0.8
            )
            self.space(8)

    def paragraph(self, text, size=10.0, bold=False, indent=0.0):
        self.ensure_page()

        line_height = size * 1.45

        for line in wrap(text, size, CONTENT_WIDTH - indent):
            if self.remaining() < line_height:
                self.new_page()

            self.space(line_height)
            self.page.text(
                MARGIN + indent,
                self.cursor_y,
                line,
                size,
                bold=bold
            )

    def key_value(self, label, value):
        self.ensure_page()

        line_height = 15.0

        if self.remaining() < line_height:
            self.new_page()

        self.space(line_height)
        self.page.text(MARGIN, self.cursor_y, label, 10.0, bold=True)
        self.page.text(MARGIN + 170, self.cursor_y, value, 10.0)

    def table(self, headers, rows, widths=None, size=8.5):
        """
        Draw a simple grid table.

        ``widths`` are fractions of the content width and must sum to
        roughly 1. Long cells wrap inside their column.
        """

        self.ensure_page()

        if not headers:
            return

        columns = len(headers)

        if widths is None:
            widths = [1.0 / columns] * columns

        column_widths = [
            CONTENT_WIDTH * fraction for fraction in widths
        ]

        line_height = size * 1.35

        def draw_row(values, bold=False, shade=False):
            wrapped = []

            for index, value in enumerate(values):
                wrapped.append(
                    wrap(
                        value,
                        size,
                        column_widths[index] - 6
                    )
                )

            row_height = (
                max(len(cell) for cell in wrapped) * line_height
            ) + 6

            if self.remaining() < row_height:
                self.new_page()
                draw_row(headers, bold=True)

            top = self.cursor_y

            if shade:
                self.page.rect(
                    MARGIN,
                    top - row_height,
                    CONTENT_WIDTH,
                    row_height,
                    fill=True
                )

            column_x = MARGIN

            for index, cell in enumerate(wrapped):
                text_y = top - line_height

                for line in cell:
                    self.page.text(
                        column_x + 3,
                        text_y,
                        line,
                        size,
                        bold=bold
                    )
                    text_y -= line_height

                column_x += column_widths[index]

            self.page.line(
                MARGIN,
                top - row_height,
                PAGE_WIDTH - MARGIN,
                top - row_height
            )

            self.cursor_y -= row_height

        draw_row(headers, bold=True, shade=True)

        for row in rows:
            draw_row(row)

    def footer(self):
        """Page numbers, written once every page is known."""

        total = len(self.pages) + (1 if self.page is not None else 0)

        if self.page is not None:
            self.pages.append(self.page)
            self.page = None

        for index, page in enumerate(self.pages, start=1):
            page.text(
                MARGIN,
                30,
                "EduShield AI — security report",
                8,
                bold=False
            )
            page.text(
                PAGE_WIDTH - MARGIN - 55,
                30,
                f"Page {index} of {total}",
                8,
                bold=False
            )

    # -- serialisation ---------------------------------------------

    def build(self):
        if self.page is not None:
            self.footer()

        objects = []

        def add(body):
            objects.append(body)
            return len(objects)

        catalog_id = add("<< /Type /Catalog /Pages 2 0 R >>")
        pages_id = add("PLACEHOLDER")

        font_regular_id = add(
            "<< /Type /Font /Subtype /Type1 "
            "/BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        )
        font_bold_id = add(
            "<< /Type /Font /Subtype /Type1 "
            "/BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
        )

        page_ids = []

        for page in self.pages:
            data = page.stream().encode("latin-1", "replace")
            compressed = zlib.compress(data)

            content_id = add(
                f"<< /Length {len(compressed)} /Filter /FlateDecode >>"
                f"\nstream\n".encode("latin-1")
                + compressed
                + b"\nendstream"
            )

            page_id = add(
                f"<< /Type /Page /Parent {pages_id} 0 R "
                f"/MediaBox [0 0 {PAGE_WIDTH:.2f} {PAGE_HEIGHT:.2f}] "
                f"/Resources << /Font << "
                f"/{FONT_REGULAR} {font_regular_id} 0 R "
                f"/{FONT_BOLD} {font_bold_id} 0 R "
                f">> >> "
                f"/Contents {content_id} 0 R >>"
            )

            page_ids.append(page_id)

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)

        objects[pages_id - 1] = (
            f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>"
        )

        info_id = add(
            f"<< /Title ({_escape(self.title)}) "
            f"/Producer (EduShield AI) >>"
        )

        objects[0] = (
            f"<< /Type /Catalog /Pages {pages_id} 0 R >>"
        )

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

        offsets = [0]

        for index, body in enumerate(objects, start=1):
            offsets.append(len(output))

            if isinstance(body, str):
                body = body.encode("latin-1", "replace")

            output += f"{index} 0 obj\n".encode("latin-1")
            output += body
            output += b"\nendobj\n"

        xref_offset = len(output)

        output += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
        output += b"0000000000 65535 f \n"

        for offset in offsets[1:]:
            output += f"{offset:010d} 00000 n \n".encode("latin-1")

        output += (
            f"trailer\n<< /Size {len(objects) + 1} "
            f"/Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin-1")

        return bytes(output)


def render(title, blocks):
    """
    Convenience helper: build a PDF from a list of block tuples.

    Supported blocks:
        ("heading", text)
        ("subheading", text)
        ("paragraph", text)
        ("kv", label, value)
        ("table", headers, rows, widths)
        ("space", points)
    """

    builder = PdfBuilder(title)
    builder.new_page()
    builder.heading(title)

    for block in blocks:
        kind = block[0]

        if kind == "heading":
            builder.heading(block[1])
        elif kind == "subheading":
            builder.heading(block[1], level=2)
        elif kind == "paragraph":
            builder.paragraph(block[1])
        elif kind == "kv":
            builder.key_value(block[1], block[2])
        elif kind == "table":
            builder.table(block[1], block[2], widths=block[3])
        elif kind == "space":
            builder.space(block[1])

    builder.footer()

    return builder.build()
