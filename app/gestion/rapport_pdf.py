"""PDF « rapport » soigné à partir d'un document de l'assistant IA (ReportLab).

Structure produite :
- page de couverture (couleur de la société, titre généré par l'IA, méta) ;
- pages de contenu : en-tête, indicateurs clés, sections numérotées
  (Markdown : titres, gras, listes, tableaux) et graphiques vectoriels ;
- pied de page « page X / Y ».

Le document attendu est le bloc produit par ``ia_agent.construire_document`` :
{titre, sous_titre, societe, auteur, date, indicateurs[], sections[{titre, contenu, graphique}]}.
"""

import io
import re
import unicodedata
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.doughnut import Doughnut
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfgen import canvas as rl_canvas

PAGE_W, PAGE_H = A4
MARGE = 20 * mm
ENCRE = colors.HexColor("#1c1917")
GRIS = colors.HexColor("#78716c")
GRIS_CLAIR = colors.HexColor("#e7e5e4")
FOND = colors.HexColor("#f7f7f5")
PALETTE_FIXE = ["#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#06b6d4", "#64748b"]


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------


def nom_fichier(titre):
    """« Rapport d'activité — Hope » -> rapport-d-activite-hope.pdf"""
    t = unicodedata.normalize("NFD", titre or "rapport")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80]
    return (t or "rapport") + ".pdf"


def _couleur(valeur, accent):
    if not valeur or "var(" in str(valeur):
        return accent
    try:
        return colors.HexColor(valeur)
    except Exception:
        return accent


def _palette(accent):
    return [accent] + [colors.HexColor(c) for c in PALETTE_FIXE]


def _melange(c, blanc=0.85):
    """Teinte claire de la couleur `c` (mélange avec du blanc)."""
    return colors.Color(
        c.red + (1 - c.red) * blanc,
        c.green + (1 - c.green) * blanc,
        c.blue + (1 - c.blue) * blanc,
    )


def _nb(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "0"
    if abs(v - round(v)) < 1e-9:
        return f"{v:,.0f}".replace(",", " ")
    return f"{v:,.1f}".replace(",", " ").replace(".", ",")


def _nb_court(v):
    v = float(v or 0)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f} M".replace(".", ",").replace(",0 ", " ")
    if abs(v) >= 10_000:
        return f"{v / 1000:.0f} k"
    return _nb(v)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def _styles(accent):
    base = dict(fontName="Helvetica", fontSize=10.5, leading=16, textColor=ENCRE)
    return {
        "corps": ParagraphStyle("corps", spaceAfter=6, **base),
        "puce": ParagraphStyle("puce", leftIndent=14, bulletIndent=3, spaceAfter=3, **base),
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, leading=22,
                             textColor=ENCRE, spaceBefore=8, spaceAfter=10),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=12, leading=16,
                             textColor=ENCRE, spaceBefore=8, spaceAfter=4),
        "num": ParagraphStyle("num", fontName="Helvetica-Bold", fontSize=9, leading=12,
                              textColor=accent),
        "cellule": ParagraphStyle("cellule", fontName="Helvetica", fontSize=9, leading=12,
                                  textColor=ENCRE),
        "cellule_t": ParagraphStyle("cellule_t", fontName="Helvetica-Bold", fontSize=9,
                                    leading=12, textColor=ENCRE),
        "kpi_l": ParagraphStyle("kpi_l", fontName="Helvetica", fontSize=8.5, leading=11,
                                textColor=GRIS),
        "kpi_v": ParagraphStyle("kpi_v", fontName="Helvetica-Bold", fontSize=16, leading=20,
                                textColor=ENCRE),
        "legende": ParagraphStyle("legende", fontName="Helvetica", fontSize=8.5, leading=11,
                                  textColor=GRIS),
        "graph_t": ParagraphStyle("graph_t", fontName="Helvetica-Bold", fontSize=10.5,
                                  leading=14, textColor=ENCRE, spaceAfter=4),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=8.5, leading=11,
                               textColor=ENCRE, backColor=FOND, borderPadding=6),
        "titre_cv": ParagraphStyle("titre_cv", fontName="Helvetica-Bold", fontSize=32,
                                   leading=38, textColor=colors.white, alignment=TA_LEFT),
        "sous_cv": ParagraphStyle("sous_cv", fontName="Helvetica", fontSize=13, leading=18,
                                  textColor=colors.Color(1, 1, 1, 0.88)),
    }


# ---------------------------------------------------------------------------
# Markdown -> flowables
# ---------------------------------------------------------------------------


def _inline(texte):
    t = escape(re.sub(r"!\[([^\]]*)\]\([^)]*\)", "", texte or ""))
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(^|[^*])\*([^*\n]+)\*(?!\*)", r"\1<i>\2</i>", t)
    t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
    return t


def _ligne_tableau(ligne):
    return [c.strip() for c in ligne.strip().strip("|").split("|")]


def markdown_flowables(texte, st, accent, largeur):
    sortie = []
    lignes = (texte or "").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lignes):
        brute = lignes[i]
        t = brute.strip()
        if t.startswith("```"):
            code = []
            i += 1
            while i < len(lignes) and not lignes[i].strip().startswith("```"):
                code.append(lignes[i])
                i += 1
            sortie.append(Preformatted("\n".join(code), st["code"]))
            sortie.append(Spacer(1, 6))
            i += 1
            continue
        if t.startswith("|") and i + 1 < len(lignes) and re.match(r"^\|?\s*:?-{2,}", lignes[i + 1].strip()):
            entete = _ligne_tableau(t)
            i += 2
            rangs = []
            while i < len(lignes) and lignes[i].strip().startswith("|"):
                rangs.append(_ligne_tableau(lignes[i]))
                i += 1
            n = len(entete)
            data = [[Paragraph(_inline(c), st["cellule_t"]) for c in entete]]
            for r in rangs:
                r = (r + [""] * n)[:n]
                data.append([Paragraph(_inline(c), st["cellule"]) for c in r])
            tab = Table(data, colWidths=[largeur / n] * n, repeatRows=1)
            tab.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _melange(accent, 0.88)),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRIS_CLAIR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            sortie += [tab, Spacer(1, 8)]
            continue
        if not t:
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", t)
        if m:
            sortie.append(Paragraph(_inline(m.group(2)), st["h3"]))
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", t):
            sortie.append(Spacer(1, 8))
            i += 1
            continue
        m = re.match(r"^[-•*]\s+(.*)$", t)
        if m:
            sortie.append(Paragraph(_inline(m.group(1)), st["puce"],
                                    bulletText="•"))
            i += 1
            continue
        m = re.match(r"^(\d+)[.)]\s+(.*)$", t)
        if m:
            sortie.append(Paragraph(_inline(m.group(2)), st["puce"],
                                    bulletText=f"{m.group(1)}."))
            i += 1
            continue
        if t.startswith(">"):
            sortie.append(Paragraph(f'<font color="#57534e"><i>{_inline(t.lstrip("> "))}</i></font>',
                                    st["corps"]))
            i += 1
            continue
        paragraphe = [t]
        i += 1
        while i < len(lignes) and lignes[i].strip() and not re.match(
            r"^(#{1,4}\s|[-•*]\s|\d+[.)]\s|\||```|>)", lignes[i].strip()
        ):
            paragraphe.append(lignes[i].strip())
            i += 1
        sortie.append(Paragraph("<br/>".join(_inline(p) for p in paragraphe), st["corps"]))
    return sortie


# ---------------------------------------------------------------------------
# Graphiques
# ---------------------------------------------------------------------------


def _legende(noms, couleurs_, st, largeur):
    noms = [str(n) for n in noms if n is not None]
    if not noms:
        return Spacer(1, 1)
    ligne, styles_l, larges = [], [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 2),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 2)], []
    for k, nom in enumerate(noms[:6]):
        ligne += ["", Paragraph(escape(nom), st["legende"])]
        styles_l.append(("BACKGROUND", (2 * k, 0), (2 * k, 0), couleurs_[k % len(couleurs_)]))
        larges += [8, 90]
    t = Table([ligne], colWidths=larges, rowHeights=[12], hAlign="LEFT")
    t.setStyle(TableStyle(styles_l))
    return t


def graphique_flowable(g, st, accent, largeur):
    labels = [str(l) for l in g.get("labels") or []]
    series = g.get("series") or []
    if not labels or not series:
        return None
    pal = _palette(accent)
    type_ = g.get("graphique") or "barres"
    titre = Paragraph(escape(g.get("titre") or "Graphique"), st["graph_t"])
    elements = [titre]

    if type_ == "anneau":
        valeurs = [max(0.0, float(v or 0)) for v in (series[0].get("valeurs") or [])]
        total = sum(valeurs)
        d = Drawing(150, 150)
        if total > 0:
            dn = Doughnut()
            dn.x, dn.y, dn.width, dn.height = 10, 10, 130, 130
            dn.data = [v if v > 0 else 0.0001 for v in valeurs]
            dn.innerRadiusFraction = 0.58
            dn.slices.strokeColor = colors.white
            dn.slices.strokeWidth = 1.5
            for k in range(len(valeurs)):
                dn.slices[k].fillColor = pal[k % len(pal)]
            d.add(dn)
            d.add(String(75, 72, _nb_court(total), fontName="Helvetica-Bold", fontSize=16,
                         fillColor=ENCRE, textAnchor="middle"))
            d.add(String(75, 58, "Total", fontName="Helvetica", fontSize=8,
                         fillColor=GRIS, textAnchor="middle"))
        lignes, styles_leg = [], [
            ("LINEBELOW", (1, 0), (-1, -2), 0.3, GRIS_CLAIR),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ]
        for k, (lab, v) in enumerate(zip(labels, valeurs)):
            pct = round(v * 100 / total) if total else 0
            lignes.append([
                "",
                Paragraph(escape(lab), st["cellule"]),
                Paragraph(f"<b>{_nb(v)}</b>", st["cellule"]),
                Paragraph(f'<font color="#78716c">{pct} %</font>', st["cellule"]),
            ])
            styles_leg.append(("BACKGROUND", (0, k), (0, k), pal[k % len(pal)]))
        larg_leg = largeur - 160 - 24
        leg = Table(lignes, colWidths=[7, larg_leg - 7 - 120, 70, 50],
                    rowHeights=[18] * len(lignes))
        leg.setStyle(TableStyle(styles_leg))
        bloc = Table([[d, leg]], colWidths=[160, largeur - 160 - 24])
        bloc.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        elements.append(bloc)
    else:
        donnees = []
        for s in series:
            vals = [float(v or 0) for v in (s.get("valeurs") or [])]
            vals = (vals + [0.0] * len(labels))[: len(labels)]
            donnees.append(vals)
        tout = [v for serie in donnees for v in serie] or [0]
        bas, haut = min(0.0, min(tout)), max(0.0, max(tout))
        if haut == bas:
            haut = bas + 1
        hauteur = 190
        d = Drawing(largeur, hauteur)
        graphe = VerticalBarChart() if type_ != "ligne" else HorizontalLineChart()
        graphe.x, graphe.y = 46, 32
        graphe.width, graphe.height = largeur - 60, hauteur - 50
        graphe.data = donnees
        graphe.valueAxis.valueMin = bas
        graphe.valueAxis.valueMax = haut * 1.1 if haut > 0 else haut
        graphe.valueAxis.labelTextFormat = _nb_court
        graphe.valueAxis.labels.fontName = "Helvetica"
        graphe.valueAxis.labels.fontSize = 7.5
        graphe.valueAxis.labels.fillColor = GRIS
        graphe.valueAxis.strokeColor = colors.white
        graphe.valueAxis.visibleGrid = True
        graphe.valueAxis.gridStrokeColor = GRIS_CLAIR
        graphe.valueAxis.gridStrokeWidth = 0.5
        graphe.categoryAxis.categoryNames = [l if len(l) <= 14 else l[:13] + "…" for l in labels]
        graphe.categoryAxis.labels.fontName = "Helvetica"
        graphe.categoryAxis.labels.fontSize = 7.5
        graphe.categoryAxis.labels.fillColor = GRIS
        graphe.categoryAxis.strokeColor = GRIS_CLAIR
        if len(labels) > 8:
            graphe.categoryAxis.labels.angle = 30
            graphe.categoryAxis.labels.boxAnchor = "ne"
        if type_ == "ligne":
            graphe.joinedLines = 1
            for k in range(len(donnees)):
                graphe.lines[k].strokeColor = pal[k % len(pal)]
                graphe.lines[k].strokeWidth = 2.2
        else:
            graphe.barSpacing = 2
            graphe.groupSpacing = 10
            graphe.bars.strokeColor = None
            for k in range(len(donnees)):
                graphe.bars[k].fillColor = pal[k % len(pal)]
            if len(donnees) == 1 and len(labels) <= 12:
                graphe.barLabelFormat = _nb_court
                graphe.barLabels.fontName = "Helvetica-Bold"
                graphe.barLabels.fontSize = 7
                graphe.barLabels.fillColor = ENCRE
                graphe.barLabels.nudge = 7
        d.add(graphe)
        elements.append(d)
        if len(series) > 1:
            elements.append(_legende([s.get("nom") for s in series], pal, st, largeur))
    if g.get("unite"):
        elements.append(Paragraph(f"Unité : {escape(g['unite'])}", st["legende"]))
    cadre = Table([[elements]], colWidths=[largeur])
    cadre.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, GRIS_CLAIR),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fcfcfb")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return KeepTogether([Spacer(1, 6), cadre, Spacer(1, 10)])


# ---------------------------------------------------------------------------
# Indicateurs
# ---------------------------------------------------------------------------


def indicateurs_flowable(items, st, accent, largeur):
    items = [k for k in (items or []) if k.get("label")]
    if not items:
        return None
    par_ligne = 3 if len(items) != 4 else 2
    cellules = [[Paragraph(escape(str(k["label"])), st["kpi_l"]),
                 Paragraph(escape(str(k.get("valeur", ""))), st["kpi_v"])] for k in items]
    rangs = [cellules[i:i + par_ligne] for i in range(0, len(cellules), par_ligne)]
    rangs[-1] += [""] * (par_ligne - len(rangs[-1]))
    gap = 8
    w = (largeur - gap * (par_ligne - 1)) / par_ligne
    data, larges = [], []
    for r in rangs:
        ligne = []
        for idx, c in enumerate(r):
            ligne.append(c)
            if idx < par_ligne - 1:
                ligne.append("")
        data.append(ligne)
    for idx in range(par_ligne):
        larges.append(w)
        if idx < par_ligne - 1:
            larges.append(gap)
    t = Table(data, colWidths=larges, rowHeights=None)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
             ("LEFTPADDING", (0, 0), (-1, -1), 11)]
    for ri, r in enumerate(rangs):
        for ci, c in enumerate(r):
            col = ci * 2
            if c:
                style += [("BACKGROUND", (col, ri), (col, ri), FOND),
                          ("LINEBEFORE", (col, ri), (col, ri), 2.5, accent)]
    t.setStyle(TableStyle(style))
    return KeepTogether([t, Spacer(1, 14)])


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


class _CanvasNumerote(rl_canvas.Canvas):
    """Canvas qui connaît le nombre total de pages (pied « X / Y »)."""

    def __init__(self, *args, **kwargs):
        self._infos = kwargs.pop("infos")
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for etat in self._pages:
            self.__dict__.update(etat)
            if self._pageNumber > 1:
                self._pied(total)
            super().showPage()
        super().save()

    def _pied(self, total):
        inf = self._infos
        self.setStrokeColor(GRIS_CLAIR)
        self.setLineWidth(0.5)
        self.line(MARGE, PAGE_H - 14 * mm, PAGE_W - MARGE, PAGE_H - 14 * mm)
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(inf["accent"])
        x_nom = MARGE
        lecteur, ratio = inf.get("logo") or (None, 0)
        if lecteur:
            from .logo_societe import dessiner
            w = dessiner(self, lecteur, ratio, MARGE, PAGE_H - 12.6 * mm, 7 * mm, 26 * mm)
            x_nom = MARGE + w + 2.5 * mm
        self.drawString(x_nom, PAGE_H - 11.5 * mm, inf["societe"].upper()[:60])
        self.setFont("Helvetica", 8)
        self.setFillColor(GRIS)
        self.drawRightString(PAGE_W - MARGE, PAGE_H - 11.5 * mm, inf["titre"][:80])
        self.line(MARGE, 13 * mm, PAGE_W - MARGE, 13 * mm)
        self.drawString(MARGE, 9 * mm, inf.get("generateur", "Généré par l'assistant IA") + " · " + inf["date"])
        self.drawRightString(PAGE_W - MARGE, 9 * mm, f"{self._pageNumber - 1} / {total - 1}")


def _couverture(c, doc_, infos, st):
    accent = infos["accent"]
    clair = _melange(accent, 0.25)
    h_bande = PAGE_H * 0.6
    c.saveState()
    c.setFillColor(accent)
    c.rect(0, PAGE_H - h_bande, PAGE_W, h_bande, stroke=0, fill=1)
    # Motif géométrique discret
    c.setFillColor(clair)
    c.setFillAlpha(0.18)
    c.circle(PAGE_W - 30 * mm, PAGE_H - 40 * mm, 70 * mm, stroke=0, fill=1)
    c.setFillAlpha(0.12)
    c.circle(PAGE_W - 5 * mm, PAGE_H - h_bande + 20 * mm, 45 * mm, stroke=0, fill=1)
    c.setFillAlpha(1)
    # En-tête de couverture (logo de la société sur une pastille blanche)
    x_nom = MARGE
    lecteur, ratio = infos.get("logo") or (None, 0)
    if lecteur:
        from .logo_societe import dessiner
        h_logo = 13 * mm
        w_logo = min(h_logo * ratio, 42 * mm)
        pad = 3 * mm
        c.setFillColor(colors.white)
        c.roundRect(MARGE - pad, PAGE_H - 22 * mm - pad - 4, w_logo + 2 * pad, h_logo + 2 * pad,
                    4 * mm, stroke=0, fill=1)
        dessiner(c, lecteur, ratio, MARGE, PAGE_H - 22 * mm - 4, h_logo, 42 * mm)
        x_nom = MARGE + w_logo + pad + 5 * mm
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_nom, PAGE_H - 22 * mm + (4 * mm if lecteur else 0), infos["societe"].upper()[:70])
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.Color(1, 1, 1, 0.75))
    c.drawRightString(PAGE_W - MARGE, PAGE_H - 22 * mm, infos["date"])
    # Titre + sous-titre (bas de la bande)
    largeur = PAGE_W - 2 * MARGE - 10 * mm
    kicker_y = PAGE_H - h_bande + 26 * mm
    blocs = [Paragraph(escape(infos["titre"]), st["titre_cv"])]
    if infos["sous_titre"]:
        blocs.append(Spacer(1, 8))
        blocs.append(Paragraph(escape(infos["sous_titre"]), st["sous_cv"]))
    hauteurs = [b.wrap(largeur, PAGE_H)[1] for b in blocs]
    y = kicker_y + sum(hauteurs)
    for b, h in zip(blocs, hauteurs):
        y -= h
        b.drawOn(c, MARGE, y)
    c.setStrokeColor(colors.white)
    c.setLineWidth(2)
    c.line(MARGE, y + sum(hauteurs) + 14, MARGE + 22 * mm, y + sum(hauteurs) + 14)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.Color(1, 1, 1, 0.85))
    c.drawString(MARGE, y + sum(hauteurs) + 22, infos["type"].upper())
    # Méta (partie blanche)
    meta = [
        ("Préparé pour", infos["societe"]),
        ("Demandé par", infos["auteur"] or "—"),
        ("Rédigé par", infos.get("redacteur", "Assistant IA")),
        ("Date", infos["date"]),
    ]
    y0 = PAGE_H - h_bande - 26 * mm
    col_w = (PAGE_W - 2 * MARGE) / 2
    for k, (label, valeur) in enumerate(meta):
        x = MARGE + (k % 2) * col_w
        yy = y0 - (k // 2) * 22 * mm
        c.setFillColor(GRIS)
        c.setFont("Helvetica", 8.5)
        c.drawString(x, yy, label.upper())
        c.setFillColor(ENCRE)
        c.setFont("Helvetica-Bold", 12.5)
        c.drawString(x, yy - 16, str(valeur)[:48])
    if infos["sommaire"]:
        yy = y0 - 2 * 22 * mm - 6 * mm
        c.setStrokeColor(GRIS_CLAIR)
        c.setLineWidth(0.6)
        c.line(MARGE, yy + 8 * mm, PAGE_W - MARGE, yy + 8 * mm)
        c.setFillColor(GRIS)
        c.setFont("Helvetica", 8.5)
        c.drawString(MARGE, yy, "SOMMAIRE")
        c.setFont("Helvetica", 10)
        c.setFillColor(ENCRE)
        for i, titre in enumerate(infos["sommaire"][:8]):
            col = i % 2
            ligne = i // 2
            c.setFillColor(accent)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(MARGE + col * col_w, yy - 16 - ligne * 15, f"{i + 1:02d}")
            c.setFillColor(ENCRE)
            c.setFont("Helvetica", 10)
            c.drawString(MARGE + col * col_w + 22, yy - 16 - ligne * 15, titre[:40])
    c.setFillColor(GRIS)
    c.setFont("Helvetica", 7.5)
    c.drawString(MARGE, 12 * mm, "Document généré automatiquement à partir des données de la plateforme. "
                 "Vérifiez les informations importantes.")
    c.restoreState()


def document_pdf(document, accent_hex="#2563eb", type_document="Rapport",
                 redacteur="Assistant IA", generateur="Généré par l'assistant IA", logo=None):
    """``logo`` : (ImageReader, ratio) issu de ``logo_societe.logo_reader(societe)``."""
    try:
        accent = colors.HexColor(accent_hex or "#2563eb")
    except Exception:
        accent = colors.HexColor("#2563eb")
    st = _styles(accent)
    infos = {
        "accent": accent,
        "titre": str(document.get("titre") or "Rapport"),
        "sous_titre": str(document.get("sous_titre") or ""),
        "societe": str(document.get("societe") or ""),
        "auteur": str(document.get("auteur") or ""),
        "date": str(document.get("date") or ""),
        "type": type_document,
        "redacteur": redacteur,
        "logo": logo,
        "generateur": generateur,
        "sommaire": [str(s.get("titre") or "") for s in document.get("sections") or [] if s.get("titre")],
    }
    tampon = io.BytesIO()
    largeur = PAGE_W - 2 * MARGE
    gabarit = BaseDocTemplate(
        tampon, pagesize=A4, title=infos["titre"], author=redacteur,
        subject=infos["sous_titre"], creator=infos["societe"],
        leftMargin=MARGE, rightMargin=MARGE, topMargin=22 * mm, bottomMargin=20 * mm,
    )
    cadre = Frame(MARGE, 20 * mm, largeur, PAGE_H - 42 * mm, id="contenu",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    gabarit.addPageTemplates([
        PageTemplate(id="couverture", frames=[cadre],
                     onPage=lambda c, d: _couverture(c, d, infos, st)),
        PageTemplate(id="contenu", frames=[cadre]),
    ])

    histoire = [NextPageTemplate("contenu"), PageBreak()]
    kpis = indicateurs_flowable(document.get("indicateurs"), st, accent, largeur)
    if kpis:
        histoire += [Paragraph("Indicateurs clés", st["h1"]), kpis]
    for n, section in enumerate(document.get("sections") or [], start=1):
        histoire.append(CondPageBreak(60 * mm))
        entete = Table(
            [[Paragraph(f"{n:02d}", st["num"]), Paragraph(escape(section.get("titre") or ""), st["h1"])]],
            colWidths=[12 * mm, largeur - 12 * mm],
        )
        entete.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("LINEBELOW", (0, 0), (-1, -1), 0.6, GRIS_CLAIR),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        histoire += [entete, Spacer(1, 8)]
        histoire += markdown_flowables(section.get("contenu"), st, accent, largeur)
        g = section.get("graphique")
        if g:
            f = graphique_flowable(g, st, accent, largeur)
            if f:
                histoire.append(f)
        histoire.append(Spacer(1, 10))
    if len(histoire) == 2:
        histoire.append(Paragraph("Aucun contenu.", st["corps"]))

    gabarit.build(histoire, canvasmaker=lambda *a, **k: _CanvasNumerote(*a, infos=infos, **k))
    return tampon.getvalue()
