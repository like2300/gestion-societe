"""Contrat de travail : génération automatique (à l'enregistrement d'un employé) et PDF imprimable.

- ``assurer_contrat`` crée le contrat en cours de l'employé s'il n'en a pas, ou le
  met à jour avec les valeurs saisies dans le formulaire (type, dates, salaire,
  clauses). Les valeurs manquantes sont déduites de la fiche : CDI par défaut,
  début = date de recrutement, salaire = salaire de l'employé, poste = fonction.
- ``contrat_pdf`` produit le contrat A4 (parties, articles, signatures) aux
  couleurs et au logo de la société, prêt à imprimer.
"""

import io
import re
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .facture_pdf import _melange, montant
from .models import ContratEmploye, TypeContrat

# Période d'essai usuelle (jours) quand elle n'est pas précisée
ESSAI_DEFAUT = {"CDI": 90, "CDD": 30, "STAGE": 15, "FREELANCE": 0}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def _date(d):
    return f"{d.day} {MOIS[d.month - 1]} {d.year}" if d else "—"


def assurer_contrat(employe, donnees=None):
    """Crée ou met à jour le contrat en cours de l'employé. Retourne le contrat."""
    donnees = donnees or {}
    contrat = employe.contrats.filter(statut="ACTIF").order_by("-date_debut").first()
    type_contrat = donnees.get("contrat_type") or (contrat.type_contrat if contrat else None) \
        or TypeContrat.objects.filter(code="CDI").first() or TypeContrat.objects.first()
    if type_contrat is None:
        return None
    if contrat is None:
        contrat = ContratEmploye(employe=employe, statut="ACTIF")
    contrat.type_contrat = type_contrat
    contrat.date_debut = (donnees.get("contrat_date_debut") or contrat.date_debut
                          or employe.date_recrutement or timezone.localdate())
    contrat.date_fin = donnees.get("contrat_date_fin") if "contrat_date_fin" in donnees else contrat.date_fin
    if type_contrat.code in ("CDI",):
        contrat.date_fin = None
    contrat.salaire_contractuel = (donnees.get("contrat_salaire") or contrat.salaire_contractuel
                                   or employe.salaire or 0)
    contrat.poste = employe.fonction.nom if employe.fonction_id else (contrat.poste or "")
    societe = employe.societe
    contrat.lieu_travail = (donnees.get("contrat_lieu_travail") or contrat.lieu_travail
                            or ", ".join(x for x in (societe.nom, societe.pays) if x))
    contrat.heures_hebdo = donnees.get("contrat_heures_hebdo") or contrat.heures_hebdo or 40
    essai = donnees.get("contrat_periode_essai")
    if essai is not None:
        contrat.periode_essai_jours = essai
    elif contrat.periode_essai_jours is None:
        contrat.periode_essai_jours = ESSAI_DEFAUT.get(type_contrat.code, 30)
    if donnees.get("contrat_missions") is not None:
        contrat.missions = donnees.get("contrat_missions") or ""
    contrat.save()
    return contrat


# ---------------------------------------------------------------------------
# Modèles de contrat : variables dynamiques {{ variable }}
# ---------------------------------------------------------------------------

# (variable, libellé) — affichées dans l'éditeur de modèles pour insertion en un clic
VARIABLES = [
    ("societe_nom", "Nom de la société"), ("societe_pays", "Pays de la société"),
    ("representant", "Représentant de l'employeur"),
    ("employe_nom_complet", "Prénom et nom de l'employé"), ("employe_prenom", "Prénom"), ("employe_nom", "Nom"),
    ("employe_date_naissance", "Date de naissance"), ("employe_lieu_naissance", "Lieu de naissance"),
    ("employe_nationalite", "Nationalité"), ("employe_piece_identite", "N° de pièce d'identité"),
    ("employe_adresse", "Adresse de l'employé"), ("employe_telephone", "Téléphone"), ("employe_email", "E-mail"),
    ("poste", "Poste / fonction"), ("type_contrat", "Type de contrat"),
    ("date_debut", "Date de début"), ("date_fin", "Date de fin"), ("duree", "Durée (phrase complète)"),
    ("salaire", "Salaire mensuel"), ("jour_paiement", "Jour de paie"),
    ("heures_hebdo", "Heures par semaine"), ("periode_essai", "Période d'essai (jours)"),
    ("lieu_travail", "Lieu de travail"), ("missions", "Missions (liste)"),
    ("numero_contrat", "N° du contrat"), ("date_du_jour", "Date du jour"),
]

MODELE_DEFAUT = """**ENTRE LES SOUSSIGNÉS**

La société **{{ societe_nom }}**, établie en {{ societe_pays }}, représentée par **{{ representant }}** en qualité de gérant(e), ci-après dénommée « **l'Employeur** »,

**ET**

**{{ employe_nom_complet }}**, né(e) le {{ employe_date_naissance }} à {{ employe_lieu_naissance }}, de nationalité {{ employe_nationalite }}, titulaire de la pièce d'identité n° {{ employe_piece_identite }}, demeurant {{ employe_adresse }}, joignable au {{ employe_telephone }}, ci-après dénommé(e) « **le/la Salarié(e)** »,

Il a été convenu et arrêté ce qui suit :

# Engagement
L'Employeur engage le/la Salarié(e) dans le cadre d'un **{{ type_contrat }}** à compter du **{{ date_debut }}**, {{ duree }}.

# Fonctions
Le/la Salarié(e) occupe le poste de **{{ poste }}**. Il/elle s'engage à exercer ses fonctions avec diligence, sous l'autorité de l'Employeur.

# Missions
Ses missions principales sont notamment :
{{ missions }}

# Lieu de travail
Le/la Salarié(e) exerce ses fonctions à **{{ lieu_travail }}**, ou en tout autre lieu justifié par les besoins du service.

# Durée du travail
La durée hebdomadaire de travail est fixée à **{{ heures_hebdo }} heures**, selon les horaires en vigueur dans l'entreprise.

# Rémunération
En contrepartie de son travail, le/la Salarié(e) perçoit une rémunération mensuelle brute de **{{ salaire }}**, versée le {{ jour_paiement }} de chaque mois.

# Période d'essai
Le présent contrat ne deviendra définitif qu'à l'issue d'une période d'essai de **{{ periode_essai }} jours**, durant laquelle chacune des parties peut y mettre fin sans indemnité.

# Congés
Le/la Salarié(e) bénéficie des congés payés prévus par la législation du travail en vigueur.

# Confidentialité
Le/la Salarié(e) s'engage à garder strictement confidentielles les informations dont il/elle aurait connaissance dans l'exercice de ses fonctions, pendant et après le contrat.

# Rupture
Le présent contrat peut être rompu dans les conditions prévues par la loi et, le cas échéant, par la convention collective applicable, sous réserve du respect du préavis.

# Litiges
Tout différend relatif au présent contrat sera réglé à l'amiable ou, à défaut, porté devant la juridiction compétente.
"""


def valeurs(contrat):
    """Valeurs des variables pour un contrat donné (texte brut, « — » si non renseigné)."""
    e, societe = contrat.employe, contrat.employe.societe
    patron = societe.createur
    nom_patron = f"{getattr(patron, 'prenom', '')} {getattr(patron, 'nom', '')}".strip() if patron else ""
    code = contrat.type_contrat.code
    if contrat.date_fin:
        duree = f"jusqu'au {_date(contrat.date_fin)} inclus"
    else:
        duree = "pour une durée indéterminée" if code == "CDI" else "pour la durée de la mission"
    missions = [m.strip(" -•\t") for m in (contrat.missions or "").splitlines() if m.strip(" -•\t")]
    return {
        "societe_nom": societe.nom, "societe_pays": societe.pays or "",
        "representant": nom_patron or "son représentant légal",
        "employe_nom_complet": f"{e.prenom} {e.nom}".strip(), "employe_prenom": e.prenom, "employe_nom": e.nom,
        "employe_date_naissance": _date(e.date_naissance) if e.date_naissance else "",
        "employe_lieu_naissance": e.lieu_naissance, "employe_nationalite": e.nationalite or "",
        "employe_piece_identite": e.numero_piece_identite, "employe_adresse": e.adresse,
        "employe_telephone": e.telephone_1, "employe_email": e.email or "",
        "poste": contrat.poste or "collaborateur(trice)", "type_contrat": contrat.type_contrat.nom,
        "date_debut": _date(contrat.date_debut), "date_fin": _date(contrat.date_fin) if contrat.date_fin else "",
        "duree": duree, "salaire": montant(contrat.salaire_contractuel),
        "jour_paiement": str(e.jour_paiement or "dernier jour"),
        "heures_hebdo": str(contrat.heures_hebdo or 40), "periode_essai": str(contrat.periode_essai_jours or 0),
        "lieu_travail": contrat.lieu_travail,
        "missions": "\n".join(f"- {m}" for m in missions) or "- Toute mission relevant de son poste.",
        "numero_contrat": f"{societe.pk:03d}-{e.pk or 0:04d}-{contrat.pk or 0:03d}",
        "date_du_jour": _date(timezone.localdate()),
    }


def remplir(texte, vals):
    """Remplace {{ variable }} ; une variable inconnue reste visible pour être corrigée."""
    def rempl(m):
        cle = m.group(1)
        if cle not in vals:
            return m.group(0)
        return str(vals[cle]) if vals[cle] not in (None, "") else "—"
    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", rempl, texte or "")


def modele_pour(contrat):
    """Modèle actif de la société pour ce type de contrat, sinon son modèle général, sinon None."""
    qs = contrat.employe.societe.modeles_contrat.filter(actif=True)
    return (qs.filter(type_contrat=contrat.type_contrat).order_by("-updated_at").first()
            or qs.filter(type_contrat__isnull=True).order_by("-updated_at").first())


def _en_ligne(t):
    t = escape(t)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def corps_flowables(texte, base, art):
    """Texte du modèle → paragraphes : « # Titre » = article numéroté, « - » = puce, ligne vide = paragraphe."""
    out, n, bloc, titre_art = [], 0, [], None

    def vider():
        nonlocal bloc, titre_art
        paras = []
        for groupe in "\n".join(bloc).split("\n\n"):
            lignes = [l for l in groupe.split("\n") if l.strip()]
            if not lignes:
                continue
            html = "<br/>".join(("• " + _en_ligne(l.strip()[2:])) if l.strip().startswith(("- ", "* ")) else _en_ligne(l.strip())
                                for l in lignes)
            paras.append(Paragraph(html, base))
        if titre_art is not None:
            out.append(KeepTogether([titre_art] + paras[:1]))
            out.extend(paras[1:])
        else:
            out.extend(paras)
        bloc, titre_art = [], None

    for ligne in str(texte or "").replace("\r", "").split("\n"):
        if ligne.startswith("#"):
            vider()
            n += 1
            titre_art = Paragraph(f"Article {n} — {_en_ligne(ligne.lstrip('#').strip())}", art)
        else:
            bloc.append(ligne)
    vider()
    return out


def contrat_pdf(contrat, accent_hex="#0284c7", logo=None):
    """PDF A4 du contrat de travail (``logo`` : (ImageReader, ratio) de logo_societe.logo_reader)."""
    e = contrat.employe
    societe = e.societe
    patron = societe.createur
    accent = colors.HexColor(accent_hex)
    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=28 * mm, bottomMargin=20 * mm,
                            title=f"Contrat de travail — {e.prenom} {e.nom}", author=societe.nom)
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=10, leading=14.5, alignment=TA_JUSTIFY,
                          textColor=colors.HexColor("#1e293b"), spaceAfter=4)
    titre = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21,
                           alignment=TA_CENTER, textColor=accent, spaceAfter=2)
    sous = ParagraphStyle("s", parent=base, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"), fontSize=9.5)
    art = ParagraphStyle("a", parent=base, fontName="Helvetica-Bold", fontSize=10.5, textColor=accent,
                         spaceBefore=9, spaceAfter=3)
    P = lambda t, s=base: Paragraph(t, s)  # noqa: E731
    x = lambda v: escape(str(v or "—"))  # noqa: E731

    type_nom = contrat.type_contrat.nom
    code = contrat.type_contrat.code
    nom_emp = f"{e.prenom} {e.nom}".strip()
    nom_patron = f"{getattr(patron, 'prenom', '')} {getattr(patron, 'nom', '')}".strip() if patron else ""
    h = []
    h.append(P("CONTRAT DE TRAVAIL", titre))
    h.append(P(f"{x(type_nom)} — n° {societe.pk:03d}-{e.pk or 0:04d}-{contrat.pk or 0:03d}", sous))
    h.append(Spacer(1, 8 * mm))

    # Corps : modèle de la société (variables dynamiques) ou modèle standard
    source = getattr(contrat, "_modele_texte", None)  # aperçu d'un modèle en cours d'édition
    if source is None:
        modele = modele_pour(contrat)
        source = modele.contenu if modele else MODELE_DEFAUT
    texte = remplir(source, valeurs(contrat))
    h += corps_flowables(texte, base, art)

    h.append(Spacer(1, 7 * mm))
    h.append(P(f"Fait en deux exemplaires originaux, le {_date(timezone.localdate())}."))
    h.append(Spacer(1, 5 * mm))
    sig = Table(
        [[P("<b>L'Employeur</b><br/><font size=8 color='#64748b'>Lu et approuvé — signature et cachet</font>"),
          P("<b>Le/la Salarié(e)</b><br/><font size=8 color='#64748b'>Lu et approuvé — signature</font>")],
         [P(x(nom_patron or societe.nom)), P(x(nom_emp))],
         ["", ""]],
        colWidths=[85 * mm, 85 * mm], rowHeights=[None, None, 28 * mm],
    )
    sig.setStyle(TableStyle([
        ("BOX", (0, 0), (0, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("BOX", (1, 0), (1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, 0), _melange(accent_hex, 0.92)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    h.append(KeepTogether([sig]))

    W, H = A4

    def decor(c, d):
        c.saveState()
        c.setFillColor(accent)
        c.rect(0, H - 6 * mm, W, 6 * mm, stroke=0, fill=1)
        lecteur, ratio = logo or (None, 0)
        if lecteur:
            from .logo_societe import dessiner
            dessiner(c, lecteur, ratio, 20 * mm, H - 22 * mm, 12 * mm, 40 * mm)
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.HexColor("#0f172a"))
        c.drawRightString(W - 20 * mm, H - 15 * mm, societe.nom)
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#64748b"))
        c.drawRightString(W - 20 * mm, H - 19.5 * mm, societe.pays or "")
        c.setStrokeColor(colors.HexColor("#e2e8f0"))
        c.line(20 * mm, 13 * mm, W - 20 * mm, 13 * mm)
        c.drawString(20 * mm, 9 * mm, f"Contrat de travail — {nom_emp}")
        c.drawRightString(W - 20 * mm, 9 * mm, f"Page {d.page} · Paraphes : ______ / ______")
        c.restoreState()

    doc.build(h, onFirstPage=decor, onLaterPages=decor)
    return tampon.getvalue()
