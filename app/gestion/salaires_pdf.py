"""État des salaires à payer (PDF, ReportLab).

Contenu : bandeau aux couleurs de la société, résumé (employés, total dû,
déjà versé, reste à payer), tableau détaillé des employés à payer, zone de
signatures et pied « page X / Y ».
"""

import io
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape

PAGE_W, PAGE_H = A4
MARGE = 16 * mm
ENCRE = colors.HexColor("#0f172a")
GRIS = colors.HexColor("#64748b")
TRAIT = colors.HexColor("#e2e8f0")
FOND = colors.HexColor("#f8fafc")

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]

STATUTS = {
    "PREVU": ("Prévu", "#0284c7"),
    "A_VENIR": ("À venir", "#0284c7"),
    "PARTIEL": ("Partiel", "#d97706"),
    "PARTIELLE": ("Partielle", "#d97706"),
    "RETARD": ("En retard", "#dc2626"),
    "NON_GENERE": ("Non généré", "#64748b"),
}

NOTE_SALAIRES = (
    "« Non généré » : employé actif sans fiche de salaire pour cette période — montant estimé "
    "d'après son contrat actif ou sa fiche employé. Les salaires validés comme payés sont "
    "comptabilisés automatiquement en dépenses."
)


def montant(v):
    """1250000.5 -> '1 250 001 FCFA'"""
    try:
        n = int(round(Decimal(str(v or 0))))
    except Exception:
        n = 0
    return f"{n:,}".replace(",", " ") + " FCFA"


def mois_libelle(d):
    return f"{MOIS_FR[d.month - 1]} {d.year}"


def nom_fichier(periode):
    return f"salaires-a-payer-{periode:%Y-%m}.pdf"


def _melange(hexa, blanc=0.88):
    c = colors.HexColor(hexa)
    return colors.Color(c.red + (1 - c.red) * blanc, c.green + (1 - c.green) * blanc,
                        c.blue + (1 - c.blue) * blanc)


class _CanvasNumerote(rl_canvas.Canvas):
    """Canvas qui connaît le nombre total de pages (pied « page X / Y »)."""

    def __init__(self, *args, infos=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []
        self._infos = infos or {}

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
        accent = colors.HexColor(i.get("accent", "#0284c7"))
        # Liseré haut
        self.setFillColor(accent)
        self.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
        # Logo de la société (en haut à droite ; plus grand sur la 1re page)
        lecteur, ratio = i.get("logo") or (None, 0)
        if lecteur:
            from .logo_societe import dessiner
            if self._pageNumber == 1:
                dessiner(self, lecteur, ratio, PAGE_W - MARGE, PAGE_H - 30 * mm, 15 * mm, 45 * mm, "droite")
            else:
                dessiner(self, lecteur, ratio, PAGE_W - MARGE, PAGE_H - 13 * mm, 6 * mm, 24 * mm, "droite")
        # Pied
        self.setStrokeColor(TRAIT)
        self.setLineWidth(0.6)
        self.line(MARGE, 14 * mm, PAGE_W - MARGE, 14 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(GRIS)
        self.drawString(MARGE, 9.5 * mm,
                        f"{i.get('societe', '')} — {i.get('titre', '')} — {i.get('mois', '')}")
        self.drawRightString(PAGE_W - MARGE, 9.5 * mm,
                             f"Page {self._pageNumber} / {total}")


def etat_salaires_pdf(societe_nom, periode, lignes, accent_hex="#0284c7",
                      genere_par="", genere_le=None, titre="État des salaires à payer",
                      col_nom="EMPLOYÉ", col_tel="TÉLÉPHONE", kpi_nb="Employés à payer",
                      kpi_paye="Déjà versé", note=NOTE_SALAIRES, vide="Tous les salaires de la période sont réglés.",
                      logo=None):
    """Construit le PDF et renvoie ses octets.

    lignes : liste de dicts {employe, fonction, telephone, date_prevue (date|None),
             statut, montant_du, montant_paye, reste}.
    """
    accent = colors.HexColor(accent_hex)
    genere_le = genere_le or date.today()
    buf = io.BytesIO()
    infos = {"societe": societe_nom, "mois": mois_libelle(periode), "accent": accent_hex, "titre": titre,
             "logo": logo}

    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=MARGE, rightMargin=MARGE,
        topMargin=14 * mm, bottomMargin=20 * mm,
        title=f"{titre} — {mois_libelle(periode)}", author=societe_nom,
    )
    L = doc.width

    st = {
        "sur": ParagraphStyle("sur", fontName="Helvetica-Bold", fontSize=8, textColor=accent,
                              leading=10, spaceAfter=2),
        "titre": ParagraphStyle("titre", fontName="Helvetica-Bold", fontSize=19, textColor=ENCRE,
                                leading=23),
        "sous": ParagraphStyle("sous", fontName="Helvetica", fontSize=9, textColor=GRIS, leading=13),
        "kpi_l": ParagraphStyle("kpi_l", fontName="Helvetica", fontSize=7.5, textColor=GRIS, leading=9),
        "kpi_v": ParagraphStyle("kpi_v", fontName="Helvetica-Bold", fontSize=12.5, textColor=ENCRE,
                                leading=15),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.5, textColor=GRIS, leading=9),
        "thr": ParagraphStyle("thr", fontName="Helvetica-Bold", fontSize=7.5, textColor=GRIS, leading=9,
                              alignment=TA_RIGHT),
        "td": ParagraphStyle("td", fontName="Helvetica", fontSize=8.5, textColor=ENCRE, leading=11),
        "tdb": ParagraphStyle("tdb", fontName="Helvetica-Bold", fontSize=8.8, textColor=ENCRE, leading=11),
        "tds": ParagraphStyle("tds", fontName="Helvetica", fontSize=7.5, textColor=GRIS, leading=9.5),
        "tdr": ParagraphStyle("tdr", fontName="Helvetica-Bold", fontSize=8.8, textColor=ENCRE,
                              leading=11, alignment=TA_RIGHT),
        "note": ParagraphStyle("note", fontName="Helvetica", fontSize=7.8, textColor=GRIS, leading=11),
        "sig": ParagraphStyle("sig", fontName="Helvetica-Bold", fontSize=8.5, textColor=ENCRE, leading=11),
    }
    flow = []

    # ---- En-tête ----
    flow.append(Paragraph(escape(societe_nom.upper()), st["sur"]))
    flow.append(Paragraph(escape(titre), st["titre"]))
    flow.append(Paragraph(
        f"Période : <b>{escape(mois_libelle(periode).capitalize())}</b> &nbsp;·&nbsp; "
        f"Édité le {genere_le:%d/%m/%Y}"
        + (f" par {escape(genere_par)}" if genere_par else ""), st["sous"]))
    flow.append(Spacer(1, 7 * mm))

    # ---- Indicateurs ----
    total_du = sum(Decimal(str(l["montant_du"] or 0)) for l in lignes)
    total_paye = sum(Decimal(str(l["montant_paye"] or 0)) for l in lignes)
    total_reste = sum(Decimal(str(l["reste"] or 0)) for l in lignes)
    kpis = [
        (kpi_nb, str(len(lignes))),
        ("Total dû", montant(total_du)),
        (kpi_paye, montant(total_paye)),
        ("Reste à payer", montant(total_reste)),
    ]
    cellules = [[Paragraph(escape(k), st["kpi_l"]), Paragraph(escape(v), st["kpi_v"])] for k, v in kpis]
    blocs = []
    for i, (lbl, val) in enumerate(cellules):
        t = Table([[lbl], [val]], colWidths=[L / 4 - 3 * mm])
        fond = _melange(accent_hex, 0.9) if i == 3 else FOND
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), fond),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
            ("TOPPADDING", (0, 1), (-1, 1), 2),
            ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ]))
        blocs.append(t)
    kt = Table([blocs], colWidths=[L / 4] * 4)
    kt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow.append(kt)
    flow.append(Spacer(1, 7 * mm))

    # ---- Tableau ----
    largeurs = [8 * mm, None, 30 * mm, 22 * mm, 22 * mm, 32 * mm]
    fixe = sum(w for w in largeurs if w)
    largeurs[1] = L - fixe
    entete = [Paragraph("N°", st["th"]), Paragraph(escape(col_nom), st["th"]), Paragraph(escape(col_tel), st["th"]),
              Paragraph("DATE PRÉVUE", st["th"]), Paragraph("STATUT", st["th"]),
              Paragraph("RESTE À PAYER", st["thr"])]
    donnees = [entete]
    styles = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ENCRE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if not lignes:
        donnees.append(["", Paragraph(escape(vide), st["td"]), "", "", "", ""])
    for n, l in enumerate(lignes, start=1):
        lib, coul = STATUTS.get(l["statut"], (l["statut"], "#64748b"))
        nom = f"<b>{escape(l['employe'])}</b>"
        if l.get("fonction"):
            nom += f"<br/><font size='7.5' color='#64748b'>{escape(l['fonction'])}</font>"
        reste = montant(l["reste"])
        if Decimal(str(l["montant_paye"] or 0)) > 0:
            reste += f"<br/><font size='7' color='#64748b'>sur {montant(l['montant_du'])}</font>"
        donnees.append([
            Paragraph(str(n), st["tds"]),
            Paragraph(nom, st["td"]),
            Paragraph(escape(l.get("telephone") or "—"), st["td"]),
            Paragraph(l["date_prevue"].strftime("%d/%m/%Y") if l.get("date_prevue") else "—", st["td"]),
            Paragraph(f"<font color='{coul}'><b>{escape(lib)}</b></font>", st["td"]),
            Paragraph(reste, st["tdr"]),
        ])
        if n % 2 == 0:
            styles.append(("BACKGROUND", (0, n), (-1, n), FOND))
        styles.append(("LINEBELOW", (0, n), (-1, n), 0.4, TRAIT))
    # Ligne de total
    donnees.append(["", Paragraph("<b>TOTAL</b>", st["td"]), "", "", "",
                    Paragraph(montant(total_reste), st["tdr"])])
    styles += [
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, ENCRE),
        ("BACKGROUND", (0, -1), (-1, -1), _melange(accent_hex, 0.9)),
        ("TOPPADDING", (0, -1), (-1, -1), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]
    table = Table(donnees, colWidths=largeurs, repeatRows=1)
    table.setStyle(TableStyle(styles))
    flow.append(table)

    # ---- Notes + signatures ----
    flow.append(Spacer(1, 6 * mm))
    if note:
        flow.append(Paragraph(escape(note), st["note"]))
    flow.append(Spacer(1, 10 * mm))
    sig = Table([
        [Paragraph("Établi par", st["sig"]), "", Paragraph("Visa de la direction", st["sig"])],
        [Paragraph("Nom, date et signature", st["note"]), "", Paragraph("Nom, date et signature", st["note"])],
        ["", "", ""],
    ], colWidths=[L * 0.44, L * 0.12, L * 0.44], rowHeights=[None, None, 18 * mm])
    sig.setStyle(TableStyle([
        ("BOX", (0, 0), (0, -1), 0.6, TRAIT), ("BOX", (2, 0), (2, -1), 0.6, TRAIT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, 0), 7),
    ]))
    flow.append(KeepTogether([sig]))

    doc.build(flow, canvasmaker=lambda *a, **k: _CanvasNumerote(*a, infos=infos, **k))
    return buf.getvalue()
