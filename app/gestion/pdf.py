"""Génération de PDF simples (rapports rapides) sans dépendance externe.

Implémentation minimale : A4, Helvetica, encodage WinAnsi, pagination.
Suffisant pour des rapports de synthèse depuis le dashboard ou l'IA.
"""

import zlib

PAGE_W = 595.28
PAGE_H = 841.89
MARGIN_L = 42
MARGIN_R = 42
MARGIN_T = 58
MARGIN_B = 46
LINE_H = 13

FONT_F1 = ("F1", "Helvetica")
FONT_F2 = ("F2", "Helvetica-Bold")


class _Canvas(object):
    def __init__(self, max_chars):
        self.max_chars = max_chars
        self.streams = [bytearray()]
        self.y = PAGE_H - MARGIN_T

    def page(self):
        self.streams.append(bytearray())
        self.y = PAGE_H - MARGIN_T

    def _need(self):
        if self.y < MARGIN_B + LINE_H:
            self.page()

    def text(self, font, size, s, indent=0, xpos=None):
        self._need()
        if xpos is None:
            xpos = MARGIN_L + indent
        s = str(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        s = s.encode("latin-1", "replace").decode("latin-1")
        self._pe(
            "BT /{f} {sz} Tf {x:.1f} {y:.1f} Td ({s}) Tj ET\n".format(
                f=font, sz=size, x=xpos, y=self.y, s=s
            )
        )
        self.y -= size + 4

    def paragraph(self, s):
        for chunk in _wrap(s, self.max_chars):
            self.text("F1", 9, chunk)

    def _pe(self, line):
        self.streams[-1].extend(line.encode("latin-1", "replace"))


def _wrap(text, max_chars):
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def pdf_from_sections(title, subtitle, sections, paragraph=None):
    """Retourne les octets d'un PDF rapport.

    title, subtitle : en-tête.
    sections : liste de (titre_section, [lignes...]).
    paragraph : bloc de texte libre (ex. réponse IA), inséré à la fin.
    """
    max_chars = int((PAGE_W - MARGIN_L - MARGIN_R) / 5.0)
    c = _Canvas(max_chars)

    c.text("F2", 15, title)
    c.y -= 2
    c.text("F1", 9, subtitle)
    c.y -= 8

    for section_title, lines in sections:
        c.text("F2", 11, section_title)
        c.y -= 3
        for line in lines:
            c.paragraph(line)
        c.y -= 5

    if paragraph:
        c.text("F2", 11, "Synthèse de l'assistant IA")
        c.y -= 3
        c.paragraph(paragraph)

    num_pages = len(c.streams)
    total_objects = 2 + num_pages * 2 + 2
    font_f1_obj = 3 + num_pages * 2
    font_f2_obj = font_f1_obj + 1

    pages_ids = [3 + i for i in range(num_pages)]
    contents_ids = {p: 3 + num_pages + i for i, p in enumerate(pages_ids)}

    chunks = []
    obj_offset = {}

    def emit(obj_num, body):
        obj_offset[obj_num] = len(b"".join(chunks))
        chunks.append(("%d 0 obj\n" % obj_num).encode("ascii"))
        chunks.append(body)
        chunks.append(b"\nendobj\n")

    chunks.append(b"%PDF-1.4\n")
    emit(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = b" ".join(("%d 0 R" % p).encode("ascii") for p in pages_ids)
    emit(2, b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, num_pages))
    emit(
        font_f1_obj,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )
    emit(
        font_f2_obj,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    )

    for pid in pages_ids:
        i = pid - 3
        cobj = contents_ids[pid]
        data = zlib.compress(bytes(c.streams[i]))
        emit(cobj, b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
        emit(
            pid,
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> "
                b"/Contents %d 0 R >>"
            )
            % (font_f1_obj, font_f2_obj, cobj),
        )

    xref_pos = len(b"".join(chunks))
    chunks.append(b"xref\n")
    chunks.append(("%d %d\n" % (0, total_objects + 1)).encode("ascii"))
    chunks.append(b"0000000000 65535 f \n")
    for num in range(1, total_objects + 1):
        chunks.append(("%010d 00000 n \n" % obj_offset[num]).encode("ascii"))
    chunks.append(
        b"trailer\n"
        + ("<< /Size %d /Root 1 0 R >>\n" % (total_objects + 1)).encode("ascii")
        + ("startxref\n%d\n" % xref_pos).encode("ascii")
        + b"%%EOF"
    )
    return b"".join(chunks)