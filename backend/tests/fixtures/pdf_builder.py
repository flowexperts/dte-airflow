"""Build minimal, valid PDFs in-process for tests.

Checked in rather than shipping binary fixtures: the tests assert on exact
page text, and a hand-built PDF makes the expected output visible in the test
itself instead of hidden inside a blob nobody can diff.

Deliberately minimal — one Helvetica text object per page, no compression, no
encryption. Enough for pypdf and pdfplumber to extract text and word boxes.
"""

from __future__ import annotations


def _escape(text: str) -> str:
    """PDF string literal escaping for the bytes we actually emit."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(pages: list[str], font_size: int = 12) -> bytes:
    """Return a valid single-column PDF; `\\n` in a page starts a new line.

    Object layout: 1 = catalog, 2 = page tree, 3 = font, then a
    (page, content) pair per page.
    """
    objects: list[bytes] = []

    n_pages = len(pages)
    page_obj_ids = [4 + 2 * i for i in range(n_pages)]

    kids = " ".join(f"{oid} 0 R" for oid in page_obj_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("latin-1")
    )
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding "
        b"/WinAnsiEncoding >>"
    )

    for i, text in enumerate(pages):
        content_id = page_obj_ids[i] + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("latin-1")
        )
        # One text-showing operator per line, advanced by `T*`. A newline
        # inside a single `Tj` is not a line break in PDF — it is just a byte
        # in the string, and pdfplumber surfaces it as `(cid:10)` glued into
        # the surrounding word, which destroys word segmentation and with it
        # any hope of mapping a quote back to a box.
        lines = text.split("\n") or [""]
        shown = " ".join(f"({_escape(line)}) Tj T*" for line in lines)
        stream = (
            f"BT /F1 {font_size} Tf {font_size * 1.4:.1f} TL 72 720 Td {shown} ET"
        ).encode("latin-1")
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )

    # Serialise, recording the byte offset of every object for the xref table.
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_at}\n"
    ).encode()
    out += b"%%EOF\n"
    return bytes(out)
