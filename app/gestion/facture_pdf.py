"""Facture client en PDF (ReportLab) : épurée, aux couleurs et au logo de la société."""

import io
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PAGE_W, PAGE_H = A4
MARGE = 17 * mm
ENCRE = colors.HexColor("#0f172a")
GRIS = colors.HexColor("#64748b")
TRAIT = colors.HexColor("#e2e8f0")
FOND = colors.HexColor("#f8fafc")

STATUTS = {
    "BROUILLON": ("BROUILLON", "#64748b"),
    "EMISE": ("À PAYER", "#d97706"),
    "PAYEE": ("PAYÉE", "#059669"),
    "ANNULEE": ("ANNULÉE", "#dc2626"),
}


def montant(v):
    try:
        d = Decimal(str(v or 0))
    except Exception:
        d = Decimal(0)
    entier = int(d.quantize(Decimal("1")))
    return f"{entier:,}".replace(",", " ") + " FCFA"


def nombre(v):
    d = Decimal(str(v or 0))
    if d == d.to_integral():
        return f"{int(d):,}".replace(",", " ")
    return f"{d:,.2f}".replace(",", " ").replace(".", ",")


def _melange(hexa, blanc=0.9):
    c = colors.HexColor(hexa)
    return colors.Color(c.red + (1 - c.red) * blanc, c.green + (1 - c.green) * blanc,
                        c.blue + (1 - c.blue) * blanc)


class _Logo(Flowable):
    """Logo (ImageReader) dessiné directement sur le canevas."""

    def __init__(self, lecteur, w, h):
        super().__init__()
        self.lecteur, self.width, self.height = lecteur, w, h

    def draw(self):
        self.canv.drawImage(self.lecteur, 0, 0, width=self.width, height=self.height, mask="auto")


class _Canvas(rl_canvas.Canvas):
    def __init__(self, *a, infos=None, **k):
        super().__init__(*a, **k)
        self._pages, self._infos = [], infos or {}

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for etat in self._pages:
            self.__dict__.update(etat)
            self._decor(total)
            super().showPage()
        super().save()

    def _decor(self, total):
        i = self._infos
        accent = colors.HexColor(i["accent"])
        self.setFillColor(accent)
        self.rect(0, PAGE_H - 5, PAGE_W, 5, stroke=0, fill=1)
        # Filigrane de statut (payée / annulée / brouillon)
        lib, coul = STATUTS.get(i.get("statut"), ("", "#64748b"))
        if i.get("statut") in ("PAYEE", "ANNULEE", "BROUILLON"):
            self.saveState()
            self.setFillColor(colors.HexColor(coul))
            self.setFillAlpha(0.07)
            self.setFont("Helvetica-Bold", 92)
            self.translate(PAGE_W / 2, PAGE_H / 2 - 40)
            self.rotate(28)
            self.drawCentredString(0, 0, lib)
            self.restoreState()
        self.setStrokeColor(TRAIT)
        self.setLineWidth(0.6)
        self.line(MARGE, 15 * mm, PAGE_W - MARGE, 15 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(GRIS)
        self.drawString(MARGE, 10.5 * mm, f"{i['societe']} — Facture {i['numero']}")
        self.drawRightString(PAGE_W - MARGE, 10.5 * mm, f"Page {self._pageNumber} / {total}")


def facture_pdf(facture, societe, accent_hex="#0284c7", logo=None, contact=""):
    """Octets PDF de la facture. ``logo`` : (ImageReader, ratio) de logo_societe."""
    accent = colors.HexColor(accent_hex)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGE, rightMargin=MARGE,
                            topMargin=16 * mm, bottomMargin=22 * mm,
                            title=f"Facture {facture.numero}", author=societe.nom)
    L = doc.width
    st = {
        "soc": ParagraphStyle("soc", fontName="Helvetica-Bold", fontSize=13, textColor=ENCRE, leading=16),
        "socs": ParagraphStyle("socs", fontName="Helvetica", fontSize=8.5, textColor=GRIS, leading=12),
        "titre": ParagraphStyle("titre", fontName="Helvetica-Bold", fontSize=26, textColor=accent, leading=30,
                                alignment=TA_RIGHT),
        "num": ParagraphStyle("num", fontName="Helvetica-Bold", fontSize=10.5, textColor=ENCRE, leading=14,
                              alignment=TA_RIGHT),
        "lab": ParagraphStyle("lab", fontName="Helvetica-Bold", fontSize=7.5, textColor=GRIS, leading=10),
        "val": ParagraphStyle("val", fontName="Helvetica", fontSize=9.5, textColor=ENCRE, leading=13),
        "valb": ParagraphStyle("valb", fontName="Helvetica-Bold", fontSize=11, textColor=ENCRE, leading=14),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.8, textColor=colors.white, leading=10),
        "thr": ParagraphStyle("thr", fontName="Helvetica-Bold", fontSize=7.8, textColor=colors.white, leading=10,
                              alignment=TA_RIGHT),
        "td": ParagraphStyle("td", fontName="Helvetica", fontSize=9, textColor=ENCRE, leading=12),
        "tdr": ParagraphStyle("tdr", fontName="Helvetica", fontSize=9, textColor=ENCRE, leading=12,
                              alignment=TA_RIGHT),
        "tot": ParagraphStyle("tot", fontName="Helvetica", fontSize=9.5, textColor=GRIS, leading=13),
        "totr": ParagraphStyle("totr", fontName="Helvetica", fontSize=9.5, textColor=ENCRE, leading=13,
                               alignment=TA_RIGHT),
        "ttc": ParagraphStyle("ttc", fontName="Helvetica-Bold", fontSize=11.5, textColor=colors.white, leading=15),
        "ttcr": ParagraphStyle("ttcr", fontName="Helvetica-Bold", fontSize=13, textColor=colors.white, leading=16,
                               alignment=TA_RIGHT),
        "note_t": ParagraphStyle("note_t", fontName="Helvetica-Bold", fontSize=8.5, textColor=ENCRE, leading=11),
        "note": ParagraphStyle("note", fontName="Helvetica", fontSize=8.5, textColor=GRIS, leading=12),
    }
    flow = []

    # ---- En-tête : émetteur (logo + société) | FACTURE + numéro ----
    gauche = []
    lecteur, ratio = logo or (None, 0)
    if lecteur:
        h = 16 * mm
        w = min(h * ratio, 50 * mm)
        h = w / ratio if ratio else h
        gauche += [_Logo(lecteur, w, h), Spacer(1, 3 * mm)]
    gauche.append(Paragraph(escape(societe.nom), st["soc"]))
    infos_soc = [x for x in [getattr(societe, "slogan", "") or "", getattr(societe, "pays", "") or "", contact] if x]
    if infos_soc:
        gauche.append(Paragraph("<br/>".join(escape(x) for x in infos_soc), st["socs"]))
    lib, coul = STATUTS.get(facture.statut, ("", "#64748b"))
    droite = [
        Paragraph("FACTURE", st["titre"]),
        Spacer(1, 2),
        Paragraph(escape(facture.numero), st["num"]),
        Spacer(1, 4),
        Paragraph(f"<font color='{coul}'><b>{lib}</b></font>",
                  ParagraphStyle("st", parent=st["num"], fontSize=8.5)),
    ]
    t = Table([[gauche, droite]], colWidths=[L * 0.58, L * 0.42])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    flow += [t, Spacer(1, 9 * mm)]

    # ---- Bloc client + dates ----
    client = facture.client
    lignes_client = [Paragraph("FACTURÉ À", st["lab"]), Spacer(1, 3),
                     Paragraph(escape(facture.client_nom or (client.nom if client else "—")), st["valb"])]
    if client:
        details = [client.adresse or "", " ".join(x for x in [client.ville or "", client.pays or ""] if x),
                   client.telephone_1 or "", client.email or ""]
        details = [d for d in details if d]
        if details:
            lignes_client.append(Paragraph("<br/>".join(escape(d) for d in details), st["val"]))
    dates = [
        ("DATE D'ÉMISSION", facture.date_emission.strftime("%d/%m/%Y") if facture.date_emission else "—"),
        ("ÉCHÉANCE", facture.date_echeance.strftime("%d/%m/%Y") if facture.date_echeance else "À réception"),
    ]
    if facture.projet_id:
        dates.append(("PROJET", facture.projet.nom))
    if facture.statut == "PAYEE" and facture.date_paiement:
        dates.append(("PAYÉE LE", facture.date_paiement.strftime("%d/%m/%Y")))
    bloc_dates = []
    for k, v in dates:
        bloc_dates += [Paragraph(k, st["lab"]), Paragraph(escape(str(v)), st["val"]), Spacer(1, 4)]
    t = Table([[lignes_client, bloc_dates]], colWidths=[L * 0.58, L * 0.42])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, 0), FOND),
        ("LEFTPADDING", (0, 0), (0, 0), 12), ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, 0), (0, 0), 12), ("LEFTPADDING", (1, 0), (1, 0), 18),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    flow += [t, Spacer(1, 7 * mm)]
    if facture.objet:
        flow += [Paragraph(f"<b>Objet :</b> {escape(facture.objet)}", st["val"]), Spacer(1, 4 * mm)]

    # ---- Lignes ----
    larg = [L - 22 * mm - 30 * mm - 32 * mm, 22 * mm, 30 * mm, 32 * mm]
    data = [[Paragraph("DÉSIGNATION", st["th"]), Paragraph("QTÉ", st["thr"]),
             Paragraph("PRIX UNITAIRE", st["thr"]), Paragraph("MONTANT", st["thr"])]]
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]
    lignes = list(facture.lignes.all())
    for n, l in enumerate(lignes, start=1):
        data.append([Paragraph(escape(l.designation), st["td"]), Paragraph(nombre(l.quantite), st["tdr"]),
                     Paragraph(montant(l.prix_unitaire), st["tdr"]), Paragraph(montant(l.montant), st["tdr"])])
        styles.append(("LINEBELOW", (0, n), (-1, n), 0.4, TRAIT))
        if n % 2 == 0:
            styles.append(("BACKGROUND", (0, n), (-1, n), FOND))
    if not lignes:
        data.append([Paragraph("Aucune ligne.", st["td"]), "", "", ""])
    t = Table(data, colWidths=larg, repeatRows=1)
    t.setStyle(TableStyle(styles))
    flow += [t, Spacer(1, 5 * mm)]

    # ---- Totaux ----
    tot = []
    sous_total = facture.total_ht + (facture.remise or 0)
    tot.append([Paragraph("Sous-total", st["tot"]), Paragraph(montant(sous_total), st["totr"])])
    if facture.remise:
        tot.append([Paragraph("Remise", st["tot"]), Paragraph("− " + montant(facture.remise), st["totr"])])
    tot.append([Paragraph("Total HT", st["tot"]), Paragraph(montant(facture.total_ht), st["totr"])])
    taux = nombre(facture.taux_tva)
    tot.append([Paragraph(f"TVA ({taux} %)", st["tot"]), Paragraph(montant(facture.total_tva), st["totr"])])
    tot.append([Paragraph("TOTAL TTC", st["ttc"]), Paragraph(montant(facture.total_ttc), st["ttcr"])])
    tt = Table(tot, colWidths=[38 * mm, 42 * mm])
    tt.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -3), 0.4, TRAIT),
        ("BACKGROUND", (0, -1), (-1, -1), accent),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, -1), (-1, -1), 9), ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [0, 0, 6, 6]),
    ]))
    bloc = Table([["", tt]], colWidths=[L - 80 * mm, 80 * mm])
    bloc.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    flow += [KeepTogether([bloc]), Spacer(1, 9 * mm)]

    # ---- Notes / conditions ----
    for titre, texte in (("Conditions de paiement", facture.conditions), ("Notes", facture.notes)):
        if texte:
            flow += [Paragraph(titre, st["note_t"]), Spacer(1, 2),
                     Paragraph(escape(texte).replace("\n", "<br/>"), st["note"]), Spacer(1, 5 * mm)]
    flow.append(Paragraph("Merci pour votre confiance.", ParagraphStyle(
        "merci", parent=st["note"], textColor=accent, fontName="Helvetica-Bold")))

    infos = {"accent": accent_hex, "societe": societe.nom, "numero": facture.numero, "statut": facture.statut}
    doc.build(flow, canvasmaker=lambda *a, **k: _Canvas(*a, infos=infos, **k))
    return buf.getvalue()
