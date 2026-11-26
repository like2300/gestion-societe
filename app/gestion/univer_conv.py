"""Conversions entre les formats Univer (Tableur / Documents) et nos exports.

- Tableur : instantané « IWorkbookData » d'Univer  ⇄  ancien format {cells} ; → Excel / CSV
- Document : instantané « IDocumentData » d'Univer  ⇄  HTML simple ; → Word (.docx)
"""

import io
import re
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Outils communs
# ---------------------------------------------------------------------------

FONCTIONS_FR = {"SOMME": "SUM", "MOYENNE": "AVERAGE", "NBVAL": "COUNTA", "NB": "COUNT",
                "ARRONDI": "ROUND", "SI": "IF", "CONCATENER": "CONCAT"}


def image_octets(source):
    """« data:image/...;base64,… » (format des images Univer) → octets, sinon None."""
    import base64

    if not isinstance(source, str) or not source.startswith("data:image/"):
        return None
    try:
        return base64.b64decode(source.split(",", 1)[1])
    except (IndexError, ValueError):
        return None


def _images_document(data):
    """Images d'un document Univer, par position dans le flux : {index: (octets, largeur_px, hauteur_px)}."""
    data = data or {}
    dessins = data.get("drawings") or {}
    out = {}
    for bloc in (data.get("body") or {}).get("customBlocks") or []:
        d = dessins.get(bloc.get("blockId")) or {}
        octets = image_octets(d.get("source"))
        if not octets:
            continue
        taille = (d.get("docTransform") or {}).get("size") or d.get("transform") or {}
        out[bloc.get("startIndex")] = (octets, float(taille.get("width") or 200), float(taille.get("height") or 150))
    return out


def _images_feuille(data, feuille_id):
    """Images flottantes d'une feuille Univer → [(octets, ligne, colonne, largeur_px, hauteur_px)]."""
    import json

    for res in (data or {}).get("resources") or []:
        if res.get("name") != "SHEET_DRAWING_PLUGIN":
            continue
        try:
            brut = json.loads(res.get("data") or "{}")
        except ValueError:
            return []
        feuille = brut.get(feuille_id) or {}
        dessins = feuille.get("data") or {}
        out = []
        for did in feuille.get("order") or list(dessins):
            d = dessins.get(did) or {}
            octets = image_octets(d.get("source"))
            if not octets:
                continue
            ancre = (d.get("sheetTransform") or {}).get("from") or {}
            t = d.get("transform") or {}
            out.append((octets, int(ancre.get("row") or 0), int(ancre.get("column") or 0),
                        float(t.get("width") or d.get("width") or 200), float(t.get("height") or d.get("height") or 150)))
        return out
    return []


def formule_excel(v):
    """=SOMME(A1;A3) → =SUM(A1,A3) (hors chaînes entre guillemets)."""
    morceaux = re.split(r'("[^"]*")', v)
    for i in range(0, len(morceaux), 2):
        m = morceaux[i].replace(";", ",")
        m = re.sub(r"\b([A-Za-zÀ-ÿ]+)(?=\s*\()",
                   lambda x: FONCTIONS_FR.get(x.group(1).upper(), x.group(1).upper()), m)
        morceaux[i] = m
    return "".join(morceaux)


def _col_num(lettres):
    n = 0
    for ch in lettres:
        n = n * 26 + (ord(ch) - 64)
    return n


def _nombre(v):
    t = str(v).replace(" ", "").replace(" ", "").replace(",", ".")
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d+", t):
        return float(t)
    return None


# ---------------------------------------------------------------------------
# Tableur
# ---------------------------------------------------------------------------

def classeur_vide(titre="Classeur", lignes=None):
    """Instantané Univer d'un classeur (lignes : liste de listes de valeurs/formules)."""
    cell_data = {}
    for r, ligne in enumerate(lignes or []):
        for c, v in enumerate(ligne):
            if v in (None, ""):
                continue
            cell_data.setdefault(str(r), {})[str(c)] = ({"f": formule_excel(v)} if str(v).startswith("=")
                                                        else {"v": _nombre(v) if _nombre(v) is not None else v})
    return {
        "id": "classeur", "name": titre, "appVersion": "1", "locale": "frFR",
        "sheetOrder": ["feuille1"], "styles": {},
        "sheets": {"feuille1": {"id": "feuille1", "name": "Feuille 1", "rowCount": 200, "columnCount": 26,
                                "defaultColumnWidth": 120, "cellData": cell_data}},
    }


def cellules_vers_univer(contenu, titre="Classeur"):
    """Ancien format {cells: {"A1": {v, b, i, al, bg, fmt}}} → instantané Univer."""
    cells = (contenu or {}).get("cells") or {}
    styles, cell_data = {}, {}
    for ref, c in cells.items():
        m = re.fullmatch(r"([A-Z]{1,2})([0-9]+)", ref)
        if not m:
            continue
        r, k = int(m.group(2)) - 1, _col_num(m.group(1)) - 1
        v = str(c.get("v", ""))
        cellule = {"f": formule_excel(v)} if v.startswith("=") else {"v": _nombre(v) if _nombre(v) is not None else v}
        st = {}
        if c.get("b"):
            st["bl"] = 1
        if c.get("i"):
            st["it"] = 1
        if c.get("u"):
            st["ul"] = {"s": 1}
        if c.get("bg"):
            st["bg"] = {"rgb": c["bg"]}
        if c.get("al"):
            st["ht"] = {"l": 1, "c": 2, "r": 3}[c["al"]]
        if c.get("fmt") == "money":
            st["n"] = {"pattern": '#,##0 "FCFA"'}
        elif c.get("fmt") == "num":
            st["n"] = {"pattern": "#,##0.00"}
        elif c.get("fmt") == "pct":
            st["n"] = {"pattern": "0%"}
        if st:
            sid = f"s{len(styles) + 1}"
            styles[sid] = st
            cellule["s"] = sid
        cell_data.setdefault(str(r), {})[str(k)] = cellule
    data = classeur_vide(titre)
    data["styles"] = styles
    data["sheets"]["feuille1"]["cellData"] = cell_data
    larg = {}
    for lettre, w in ((contenu or {}).get("cols") or {}).items():
        larg[str(_col_num(lettre) - 1)] = {"w": int(w)}
    if larg:
        data["sheets"]["feuille1"]["columnData"] = larg
    return data


def _style(data, s):
    if isinstance(s, dict):
        return s
    return (data.get("styles") or {}).get(s) or {} if s else {}


def _feuilles(data):
    sheets = data.get("sheets") or {}
    ordre = [sid for sid in (data.get("sheetOrder") or []) if sid in sheets] or list(sheets)
    return [sheets[sid] for sid in ordre]


def _valeur_cellule(c):
    if c.get("f"):
        return formule_excel(str(c["f"]))
    v = c.get("v")
    if v is None and isinstance(c.get("p"), dict):  # texte riche
        v = ((c["p"].get("body") or {}).get("dataStream") or "").rstrip("\r\n")
    return v


def apercu_classeur(data):
    vals = []
    for feuille in _feuilles(data)[:1]:
        for r in sorted((feuille.get("cellData") or {}), key=lambda x: int(x))[:10]:
            for k in sorted(feuille["cellData"][r], key=lambda x: int(x))[:6]:
                v = feuille["cellData"][r][k].get("v")
                if v not in (None, ""):
                    vals.append(str(v))
    return " · ".join(vals)[:300]


def classeur_xlsx(data, accent="#0284c7"):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    for feuille in _feuilles(data) or [{"name": "Feuille 1"}]:
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "", str(feuille.get("name") or "Feuille"))[:31] or "Feuille")
        for r, ligne in (feuille.get("cellData") or {}).items():
            for k, c in (ligne or {}).items():
                if not isinstance(c, dict):
                    continue
                v = _valeur_cellule(c)
                st = _style(data, c.get("s"))
                if v in (None, "") and not st:
                    continue
                cell = ws.cell(row=int(r) + 1, column=int(k) + 1, value=v)
                if st:
                    fnt = {}
                    if st.get("bl"):
                        fnt["bold"] = True
                    if st.get("it"):
                        fnt["italic"] = True
                    if (st.get("ul") or {}).get("s"):
                        fnt["underline"] = "single"
                    if (st.get("st") or {}).get("s"):
                        fnt["strike"] = True
                    if st.get("fs"):
                        fnt["size"] = st["fs"]
                    if st.get("ff"):
                        fnt["name"] = st["ff"]
                    rgb = (st.get("cl") or {}).get("rgb")
                    if isinstance(rgb, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", rgb):
                        fnt["color"] = rgb.lstrip("#").upper()
                    if fnt:
                        cell.font = Font(**fnt)
                    bg = (st.get("bg") or {}).get("rgb")
                    if isinstance(bg, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", bg):
                        cell.fill = PatternFill("solid", fgColor=bg.lstrip("#").upper())
                    ht = {1: "left", 2: "center", 3: "right"}.get(st.get("ht"))
                    vt = {1: "top", 2: "center", 3: "bottom"}.get(st.get("vt"))
                    if ht or vt or st.get("tb") == 3:
                        cell.alignment = Alignment(horizontal=ht, vertical=vt, wrap_text=st.get("tb") == 3)
                    if (st.get("n") or {}).get("pattern"):
                        cell.number_format = st["n"]["pattern"]
        for k, col in (feuille.get("columnData") or {}).items():
            if isinstance(col, dict) and col.get("w"):
                ws.column_dimensions[get_column_letter(int(k) + 1)].width = max(4, float(col["w"]) / 7)
        for r, row in (feuille.get("rowData") or {}).items():
            if isinstance(row, dict) and row.get("h"):
                ws.row_dimensions[int(r) + 1].height = float(row["h"]) * 0.75
        for m in feuille.get("mergeData") or []:
            try:
                ws.merge_cells(start_row=m["startRow"] + 1, start_column=m["startColumn"] + 1,
                               end_row=m["endRow"] + 1, end_column=m["endColumn"] + 1)
            except Exception:
                pass
        if feuille.get("freeze") and feuille["freeze"].get("startRow", -1) > 0:
            fz = feuille["freeze"]
            ws.freeze_panes = ws.cell(row=fz.get("startRow", 0) + 1, column=max(fz.get("startColumn", 0), 0) + 1)
        for octets, ligne, col, w, h in _images_feuille(data, feuille.get("id")):
            try:
                from openpyxl.drawing.image import Image as XlImage

                img = XlImage(io.BytesIO(octets))
                img.width, img.height = w, h
                ws.add_image(img, f"{get_column_letter(col + 1)}{ligne + 1}")
            except Exception:
                pass
        ws.sheet_properties.tabColor = accent.lstrip("#")
    if not wb.worksheets:
        wb.create_sheet("Feuille 1")
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def classeur_csv(data):
    import csv

    feuilles = _feuilles(data)
    if not feuilles:
        return "﻿"
    cd = feuilles[0].get("cellData") or {}
    if not cd:
        return "﻿"
    max_r = max(int(r) for r in cd)
    max_c = max((int(k) for l in cd.values() for k in (l or {})), default=0)
    grille = [[""] * (max_c + 1) for _ in range(max_r + 1)]
    for r, l in cd.items():
        for k, c in (l or {}).items():
            v = c.get("v") if isinstance(c, dict) else ""
            if v is None and isinstance(c, dict) and c.get("f"):
                v = c["f"]
            grille[int(r)][int(k)] = "" if v is None else v
    sortie = io.StringIO()
    csv.writer(sortie, delimiter=";").writerows(grille)
    return "﻿" + sortie.getvalue()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

STYLE_PAR_BALISE = {"h1": 4, "h2": 5, "h3": 6, "h4": 7}  # NamedStyleType Univer (HEADING_1…)
TITRE_DOCX = {2: "Title", 3: "Subtitle", 4: "Heading 1", 5: "Heading 2", 6: "Heading 3", 7: "Heading 4", 8: "Heading 5"}
PAGE_A4 = {"pageSize": {"width": 794, "height": 1123}, "marginTop": 72, "marginBottom": 72,
           "marginLeft": 90, "marginRight": 90, "documentFlavor": 1}


class _HtmlVersDoc(HTMLParser):
    """HTML simple → paragraphes + segments stylés (gras, italique, souligné, barré, couleur)."""

    BLOCS = {"p", "div", "h1", "h2", "h3", "h4", "li", "blockquote", "pre", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras, self.courant, self.styles, self.listes = [], None, [], []
        self.lien, self.cellules = None, None

    def _ouvrir(self, balise):
        self._fermer()
        bullet = None
        if balise == "li" and self.listes:
            bullet = "ORDER_LIST" if self.listes[-1] == "ol" else "BULLET_LIST"
        self.courant = {"balise": balise, "runs": [], "bullet": bullet, "niveau": max(len(self.listes) - 1, 0)}

    def _fermer(self):
        if self.courant is not None:
            if self.courant["runs"] or self.courant["balise"] not in ("div", "tr"):
                self.paras.append(self.courant)
            self.courant = None

    def handle_starttag(self, tag, attrs):
        if tag in ("ul", "ol"):
            self._fermer()
            self.listes.append(tag)
        elif tag in self.BLOCS:
            self._ouvrir(tag)
        elif tag == "br":
            self._ouvrir("p")
        elif tag in ("td", "th") and self.courant is not None and self.courant["runs"]:
            self.courant["runs"].append(("\t", ()))
        elif tag in ("b", "strong", "i", "em", "u", "s", "strike", "th"):
            self.styles.append({"strong": "b", "em": "i", "strike": "s", "th": "b"}.get(tag, tag))

    def handle_endtag(self, tag):
        if tag in ("ul", "ol"):
            self._fermer()
            if self.listes:
                self.listes.pop()
        elif tag in self.BLOCS:
            self._fermer()
        elif tag in ("b", "strong", "i", "em", "u", "s", "strike", "th"):
            t = {"strong": "b", "em": "i", "strike": "s", "th": "b"}.get(tag, tag)
            if t in self.styles:
                self.styles.remove(t)

    def handle_data(self, data):
        texte = re.sub(r"\s+", " ", data)
        if not texte.strip() and self.courant is None:
            return
        if self.courant is None:
            self._ouvrir("p")
        self.courant["runs"].append((texte.replace("\r", "").replace("\n", " "), tuple(self.styles)))

    def resultat(self):
        self._fermer()
        return self.paras


def html_vers_document(html, titre=""):
    """HTML (ancien éditeur, modèles) → instantané Univer IDocumentData."""
    p = _HtmlVersDoc()
    p.feed(str(html or ""))
    p.close()
    paras = p.resultat() or [{"balise": "p", "runs": [], "bullet": None, "niveau": 0}]
    flux, runs, paragraphes, listes = [], [], [], {}
    pos = 0
    for para in paras:
        texte_para = ""
        for texte, styles in para["runs"]:
            if not texte:
                continue
            debut = pos + len(texte_para)
            texte_para += texte
            if styles:
                ts = {}
                if "b" in styles:
                    ts["bl"] = 1
                if "i" in styles:
                    ts["it"] = 1
                if "u" in styles:
                    ts["ul"] = {"s": 1}
                if "s" in styles:
                    ts["st"] = {"s": 1}
                runs.append({"st": debut, "ed": debut + len(texte), "ts": ts})
        texte_para = texte_para.strip("\t") if para["balise"] == "tr" else texte_para
        flux.append(texte_para)
        pos += len(texte_para)
        para_def = {"startIndex": pos}
        nst = STYLE_PAR_BALISE.get(para["balise"])
        if nst:
            para_def["paragraphStyle"] = {"namedStyleType": nst}
        if para["bullet"]:
            lid = f"liste-{para['bullet']}"
            listes[lid] = para["bullet"]
            para_def["bullet"] = {"listId": lid, "listType": para["bullet"], "nestingLevel": para["niveau"]}
        paragraphes.append(para_def)
        flux.append("\r")
        pos += 1
    flux.append("\n")
    data = {
        "id": "document", "title": titre, "locale": "frFR",
        "body": {"dataStream": "".join(flux), "textRuns": runs, "paragraphs": paragraphes,
                 "sectionBreaks": [{"startIndex": pos}]},
        "documentStyle": dict(PAGE_A4),
    }
    return data


def texte_document(data):
    flux = ((data or {}).get("body") or {}).get("dataStream") or ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", flux).replace("\r", "\n").strip()


def document_docx(data, societe=None, logo_png=None, accent="#0284c7", titre=""):
    """Instantané Univer → Word (.docx) : titres, listes, gras/italique/souligné/barré, couleurs."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Mm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(22)
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    try:
        doc.styles["Heading 1"].font.color.rgb = RGBColor.from_string(accent.lstrip("#").upper())
    except Exception:
        pass
    if societe is not None:
        ent = sec.header.paragraphs[0]
        if logo_png:
            ent.add_run().add_picture(io.BytesIO(logo_png), height=Mm(9))
            ent.add_run("   ")
        r = ent.add_run(societe.nom)
        r.bold, r.font.size = True, Pt(9)
        r.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        pr = sec.footer.paragraphs[0].add_run(f"{titre} — {societe.nom}")
        pr.font.size = Pt(8)
        pr.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)

    body = (data or {}).get("body") or {}
    flux = body.get("dataStream") or ""
    runs = sorted(body.get("textRuns") or [], key=lambda r: r.get("st", 0))
    images = _images_document(data)
    debut = 0
    for para in sorted(body.get("paragraphs") or [], key=lambda p: p.get("startIndex", 0)):
        fin = para.get("startIndex", 0)
        ps = para.get("paragraphStyle") or {}
        style = TITRE_DOCX.get(ps.get("namedStyleType"))
        bullet = para.get("bullet")
        if bullet:
            style = "List Number" if "ORDER" in str(bullet.get("listType", "")) else "List Bullet"
        p = doc.add_paragraph(style=style) if style else doc.add_paragraph()
        ha = ps.get("horizontalAlign")
        if ha in (2, 3, 4):
            p.alignment = {2: WD_ALIGN_PARAGRAPH.CENTER, 3: WD_ALIGN_PARAGRAPH.RIGHT, 4: WD_ALIGN_PARAGRAPH.JUSTIFY}[ha]
        # Découpe du paragraphe selon les segments stylés
        bornes = {debut, fin}
        for r in runs:
            if r.get("ed", 0) > debut and r.get("st", 0) < fin:
                bornes.add(max(debut, r["st"]))
                bornes.add(min(fin, r["ed"]))
        for i in images:
            if debut <= i < fin:
                bornes.update((i, i + 1))
        bornes = sorted(bornes)
        for a, b in zip(bornes, bornes[1:]):
            if a in images:
                octets, w, h = images[a]
                larg = min(w * 0.75, 165 * 72 / 25.4)  # px → pt, limité à la largeur utile (165 mm)
                try:
                    p.add_run().add_picture(io.BytesIO(octets), width=Pt(larg), height=Pt(larg * h / w))
                except Exception:
                    pass
                continue
            texte = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", flux[a:b])
            if not texte:
                continue
            run = p.add_run(texte)
            for r in runs:
                if r.get("st", 0) <= a and r.get("ed", 0) >= b:
                    ts = r.get("ts") or {}
                    if ts.get("bl"):
                        run.bold = True
                    if ts.get("it"):
                        run.italic = True
                    if (ts.get("ul") or {}).get("s"):
                        run.underline = True
                    if (ts.get("st") or {}).get("s"):
                        run.font.strike = True
                    if ts.get("fs"):
                        run.font.size = Pt(float(ts["fs"]))
                    if ts.get("ff"):
                        run.font.name = ts["ff"]
                    rgb = (ts.get("cl") or {}).get("rgb")
                    if isinstance(rgb, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", rgb):
                        run.font.color.rgb = RGBColor.from_string(rgb.lstrip("#").upper())
        debut = fin + 1
    tampon = io.BytesIO()
    doc.save(tampon)
    return tampon.getvalue()


def _segments(flux, runs, debut, fin):
    """Découpe [debut, fin[ selon les segments stylés → [(texte, ts)]."""
    bornes = {debut, fin}
    for r in runs:
        if r.get("ed", 0) > debut and r.get("st", 0) < fin:
            bornes.add(max(debut, r["st"]))
            bornes.add(min(fin, r["ed"]))
    bornes = sorted(bornes)
    out = []
    for a, b in zip(bornes, bornes[1:]):
        texte = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", flux[a:b])
        if not texte:
            continue
        ts = {}
        for r in runs:
            if r.get("st", 0) <= a and r.get("ed", 0) >= b:
                ts.update(r.get("ts") or {})
        out.append((texte, ts))
    return out


def document_pdf(data, societe=None, lecteur_logo=None, accent="#0284c7", titre=""):
    """Instantané Univer → PDF A4 (titres, listes, gras/italique/souligné/barré, couleurs)."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    W, H = A4
    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=24 * mm, bottomMargin=20 * mm, title=titre,
                            author=getattr(societe, "nom", ""))
    base = ParagraphStyle("n", fontName="Helvetica", fontSize=10.5, leading=15, spaceAfter=5,
                          textColor=colors.HexColor("#1e293b"))
    tailles = {2: 24, 3: 15, 4: 19, 5: 15, 6: 13, 7: 12, 8: 11}
    body = (data or {}).get("body") or {}
    flux = body.get("dataStream") or ""
    runs = sorted(body.get("textRuns") or [], key=lambda r: r.get("st", 0))
    images = _images_document(data)
    histoire, debut, numeros = [], 0, {}
    for para in sorted(body.get("paragraphs") or [], key=lambda p: p.get("startIndex", 0)):
        fin = para.get("startIndex", 0)
        ps = para.get("paragraphStyle") or {}
        nst = ps.get("namedStyleType")
        # Images du paragraphe : placées avant son texte
        for i in sorted(k for k in images if debut <= k < fin):
            octets, w, h = images[i]
            larg = min(w * 0.75, W - 44 * mm)
            try:
                from reportlab.platypus import Image as PdfImage

                histoire.append(PdfImage(io.BytesIO(octets), width=larg, height=larg * h / w))
            except Exception:
                pass
        html = ""
        for texte, ts in _segments(flux, runs, debut, fin):
            t = escape(texte)
            if ts.get("bl"):
                t = f"<b>{t}</b>"
            if ts.get("it"):
                t = f"<i>{t}</i>"
            if (ts.get("ul") or {}).get("s"):
                t = f"<u>{t}</u>"
            if (ts.get("st") or {}).get("s"):
                t = f"<strike>{t}</strike>"
            rgb = (ts.get("cl") or {}).get("rgb")
            if isinstance(rgb, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", rgb):
                t = f'<font color="#{rgb.lstrip("#")}">{t}</font>'
            if ts.get("fs") and not nst:
                t = f'<font size="{float(ts["fs"]):.0f}">{t}</font>'
            html += t
        st = ParagraphStyle("p", parent=base)
        if nst in tailles and nst != 1:
            st.fontName, st.fontSize = "Helvetica-Bold", tailles[nst]
            st.leading, st.spaceBefore, st.spaceAfter = tailles[nst] * 1.25, 8, 6
            if nst in (2, 4):
                st.textColor = colors.HexColor(accent)
        st.alignment = {2: TA_CENTER, 3: TA_RIGHT, 4: TA_JUSTIFY}.get(ps.get("horizontalAlign"), TA_LEFT)
        bullet = para.get("bullet")
        if bullet:
            niv = int(bullet.get("nestingLevel") or 0)
            st.leftIndent, st.bulletIndent = 16 + niv * 14, 4 + niv * 14
            if "ORDER" in str(bullet.get("listType", "")):
                cle = (bullet.get("listId"), niv)
                numeros[cle] = numeros.get(cle, 0) + 1
                histoire.append(Paragraph(html or "&nbsp;", st, bulletText=f"{numeros[cle]}."))
            else:
                histoire.append(Paragraph(html or "&nbsp;", st, bulletText="•"))
        else:
            histoire.append(Paragraph(html, st) if html else Spacer(1, 8))
        debut = fin + 1

    def decor(c, d):
        c.saveState()
        c.setStrokeColor(colors.HexColor("#e2e8f0"))
        c.line(22 * mm, 13 * mm, W - 22 * mm, 13 * mm)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#94a3b8"))
        c.drawString(22 * mm, 9 * mm, f"{titre} — {getattr(societe, 'nom', '')}")
        c.drawRightString(W - 22 * mm, 9 * mm, f"Page {d.page}")
        lecteur, ratio = lecteur_logo or (None, 0)
        if lecteur:
            from .logo_societe import dessiner
            dessiner(c, lecteur, ratio, 22 * mm, H - 16 * mm, 8 * mm, 30 * mm)
        c.restoreState()

    doc.build(histoire or [Spacer(1, 1)], onFirstPage=decor, onLaterPages=decor)
    return tampon.getvalue()
