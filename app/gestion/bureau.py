"""Applications bureautiques intégrées : Tableur, Documents, Présentations.

Vues (liste, éditeur, sauvegarde automatique, actions) + exports :
- Tableur      → Excel (.xlsx, formules conservées) et CSV
- Document     → Word (.docx) ; impression / PDF depuis le navigateur
- Présentation → PowerPoint (.pptx) et PDF (une diapositive par page)
"""

import csv
import io
import json
import re
from html import escape as html_escape
from html.parser import HTMLParser

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import F, Q
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import logo_societe, services
from . import univer_conv as uc
from .models import FichierBureau

TYPES = {
    "sheets": {"code": "SHEET", "nom": "Tableur", "singulier": "un classeur", "nouveau": "Nouveau classeur",
               "icone": "sheet", "couleur": "#10b981", "ext": ["xlsx", "csv"]},
    "docs": {"code": "DOC", "nom": "Documents", "singulier": "un document", "nouveau": "Nouveau document",
             "icone": "doc", "couleur": "#3b82f6", "ext": ["docx", "pdf"]},
    "slides": {"code": "SLIDES", "nom": "Présentations", "singulier": "une présentation",
               "nouveau": "Nouvelle présentation", "icone": "slides", "couleur": "#f59e0b", "ext": ["pptx", "pdf"]},
}
CODE_VERS_APP = {v["code"]: k for k, v in TYPES.items()}
TAILLE_MAX = 8_000_000  # octets de contenu JSON par fichier
# Images des présentations : data URL PNG / JPEG (compressées dans le navigateur)
IMAGE_MAX = 4_000_000
IMAGE_DATA_RE = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/]+=*")
IMAGE_POSITIONS = ("droite", "centre", "fond")


def _contexte(request, app):
    from .views import _societe_context  # import local : évite l'import circulaire

    if app not in TYPES:
        raise Http404
    societe, ctx, resp = _societe_context(request, "bureau")
    if resp:
        # Sans le module « Applications », un employé garde l'accès aux fichiers où il est invité partenaire.
        s2, c2, r2 = _societe_context(request, "planning")
        moi = services.employe_pour_utilisateur(request.user, s2) if r2 is None else None
        if moi is None or not s2.fichiers_bureau.filter(partenaires=moi).exists():
            return None, None, resp
        societe, ctx = s2, c2
        request._bx_partage_seul = True
    ctx["active"] = app
    ctx["partage_seul"] = getattr(request, "_bx_partage_seul", False)
    ctx["app"] = app
    ctx["app_conf"] = TYPES[app]
    ctx["dossiers_apps"] = dossiers_apps(request, societe, app)
    ctx["apps_bureau"] = [
        {"cle": k, **v, "count": _visibles(request, societe, societe.fichiers_bureau.filter(type_fichier=v["code"])).count()}
        for k, v in TYPES.items()
    ]
    return societe, ctx, None


def _est_admin(request, societe):
    return not services.est_employe(request.user, societe) or services.est_createur(request.user, societe)


def _visibles(request, societe, qs):
    """Fichiers privés : seulement le créateur, les partenaires invités et l'administration."""
    moi = services.employe_pour_utilisateur(request.user, societe)
    if getattr(request, "_bx_partage_seul", False):
        return qs.filter(partenaires=moi).distinct() if moi else qs.none()
    if _est_admin(request, societe):
        return qs
    filtre = Q(prive=False) | Q(cree_par=request.user)
    if moi:
        filtre |= Q(partenaires=moi)
    return qs.filter(filtre).distinct()


def _peut_partager(request, societe, f):
    return _est_admin(request, societe) or f.cree_par_id == request.user.pk


def dossiers_apps(request, societe, actif):
    """Cartes « dossier » de l'espace Applications (Planning + Tableur/Documents/Présentations), chacune à sa couleur."""
    from .models import EvenementAgenda

    debut = timezone.now()
    moi = services.employe_pour_utilisateur(request.user, societe)
    rdv = EvenementAgenda.objects.filter(societe=societe, fin__gte=debut)
    # Chacun ne compte que son propre agenda (propriétaire compris)
    filtre = Q(organisateur=request.user)
    if moi:
        filtre |= Q(participants=moi)
    rdv = rdv.filter(filtre).distinct()
    n = rdv.count()
    items = [{
        "cle": "planning", "nom": "Planning", "couleur": "#7c3aed", "count": n,
        "sous_titre": f"{n} rendez-vous à venir" if n else "Agenda & tâches",
        "url": reverse("gestion:planning"), "actif": actif == "planning",
    }]
    acces = services.peut_acceder(request.user, societe, "bureau")
    for k, v in TYPES.items():
        qs = societe.fichiers_bureau.filter(type_fichier=v["code"])
        if not acces:
            if moi is None:
                continue
            qs = qs.filter(partenaires=moi)
            if not qs.exists():
                continue
        else:
            qs = _visibles(request, societe, qs)
        c = qs.count()
        items.append({
            "cle": k, "nom": v["nom"], "couleur": v["couleur"], "count": c,
            "sous_titre": {"sheets": "Classeurs & formules", "docs": "Textes & comptes rendus", "slides": "Diaporamas"}[k],
            "url": reverse("gestion:bureau", args=[k]), "actif": actif == k,
        })
    return items


def _fichier(societe, app, pk, request=None):
    qs = societe.fichiers_bureau.filter(pk=pk, type_fichier=TYPES[app]["code"])
    if request is not None:
        qs = _visibles(request, societe, qs)
    f = qs.first()
    if f is None:
        raise Http404("Fichier introuvable.")
    return f


# ---------------------------------------------------------------------------
# Collaboration : présence (qui est dans le fichier) + versions
# ---------------------------------------------------------------------------

PRESENCE_TTL = 15  # secondes sans signal avant de considérer la personne partie
PALETTE = ["#0ea5e9", "#6366f1", "#10b981", "#f59e0b", "#e11d48", "#8b5cf6", "#14b8a6", "#ec4899"]


def _nom_utilisateur(user, societe):
    emp = services.employe_pour_utilisateur(user, societe)
    if emp:
        return f"{emp.prenom} {emp.nom}".strip()
    nom = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    return nom or getattr(user, "email", "") or "Utilisateur"


def _initiales(nom):
    parts = [p for p in re.split(r"[\s@._-]+", nom) if p]
    return ((parts[0][:1] + (parts[1][:1] if len(parts) > 1 else "")) or "?").upper()


def _presence(f, request=None, societe=None, quitter=False):
    """Met à jour (si request) puis renvoie la liste des personnes présentes dans le fichier."""
    cle = f"bureau:presence:{f.pk}"
    maintenant = timezone.now().timestamp()
    pres = {k: v for k, v in (cache.get(cle) or {}).items() if maintenant - v.get("t", 0) < PRESENCE_TTL}
    if request is not None:
        uid = str(request.user.pk)
        if quitter:
            pres.pop(uid, None)
        else:
            nom = pres.get(uid, {}).get("nom") or _nom_utilisateur(request.user, societe)
            pres[uid] = {"nom": nom, "ini": _initiales(nom), "c": PALETTE[request.user.pk % len(PALETTE)], "t": maintenant}
        cache.set(cle, pres, PRESENCE_TTL * 4)
    return pres


def _etat_fichier(f, request, societe):
    pres = _presence(f, request, societe)
    moi = str(request.user.pk)
    return {
        "version": f.version,
        "titre": f.titre,
        "maj": timezone.localtime(f.updated_at).strftime("%H:%M"),
        "maj_par": _nom_utilisateur(f.modifie_par, societe) if f.modifie_par_id else "",
        "maj_par_moi": f.modifie_par_id == request.user.pk,
        "presents": [{"nom": v["nom"], "ini": v["ini"], "c": v["c"], "moi": k == moi} for k, v in pres.items()],
    }


def _partage_info(f, request, societe):
    return {
        "prive": f.prive,
        "partenaires": list(f.partenaires.values_list("pk", flat=True)),
        "peut_partager": _peut_partager(request, societe, f),
        "createur": _nom_utilisateur(f.cree_par, societe) if f.cree_par_id else "",
    }


# ---------------------------------------------------------------------------
# Nettoyage HTML des documents (liste blanche, pas de script ni d'attribut d'événement)
# ---------------------------------------------------------------------------

BALISES = {"p", "h1", "h2", "h3", "h4", "b", "strong", "i", "em", "u", "s", "strike", "ul", "ol", "li",
           "a", "blockquote", "br", "hr", "table", "thead", "tbody", "tr", "td", "th", "div", "span",
           "sub", "sup", "code", "pre", "mark"}
VIDES = {"br", "hr"}
ALIGN = re.compile(r"text-align\s*:\s*(left|right|center|justify)", re.I)
COULEUR = re.compile(r"(?:^|;)\s*(color|background-color)\s*:\s*(#[0-9a-f]{3,8}|rgb\([\d,\s.]+\))", re.I)


class _Nettoyeur(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sortie, self.pile, self.ignore = [], [], 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "iframe", "object", "embed", "svg", "math"):
            self.ignore += 1
            return
        if self.ignore or tag not in BALISES:
            return
        garde = []
        a = dict((k.lower(), v or "") for k, v in attrs)
        if tag == "a":
            href = a.get("href", "").strip()
            if re.match(r"^(https?:|mailto:|tel:|#)", href, re.I):
                garde.append(f'href="{html_escape(href)}" target="_blank" rel="noopener"')
        if tag in ("td", "th"):
            for k in ("colspan", "rowspan"):
                if a.get(k, "").isdigit():
                    garde.append(f'{k}="{a[k]}"')
        styles = []
        m = ALIGN.search(a.get("style", ""))
        if m:
            styles.append(f"text-align:{m.group(1).lower()}")
        for prop, val in COULEUR.findall(a.get("style", "")):
            styles.append(f"{prop.lower()}:{val}")
        if styles:
            garde.append(f'style="{";".join(styles)}"')
        self.sortie.append(f"<{tag}{(' ' + ' '.join(garde)) if garde else ''}>")
        if tag not in VIDES:
            self.pile.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "iframe", "object", "embed", "svg", "math"):
            self.ignore = max(0, self.ignore - 1)
            return
        if self.ignore or tag not in BALISES or tag in VIDES:
            return
        if tag in self.pile:
            while self.pile:
                t = self.pile.pop()
                self.sortie.append(f"</{t}>")
                if t == tag:
                    break

    def handle_data(self, data):
        if not self.ignore:
            self.sortie.append(html_escape(data, quote=False))

    def resultat(self):
        while self.pile:
            self.sortie.append(f"</{self.pile.pop()}>")
        return "".join(self.sortie)


def nettoyer_html(html):
    n = _Nettoyeur()
    n.feed(str(html or ""))
    n.close()
    return n.resultat()


def _texte_brut(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


# ---------------------------------------------------------------------------
# Contenus par défaut, normalisation et aperçu
# ---------------------------------------------------------------------------

def contenu_defaut(app, societe=None):
    if app == "sheets":
        return {"univer": uc.classeur_vide()}
    if app == "docs":
        return {"univer": uc.html_vers_document("<h1>Titre du document</h1><p>Commencez à écrire ici…</p>")}
    return {"theme": "accent", "slides": [
        {"layout": "titre", "titre": "Titre de la présentation",
         "texte": societe.nom if societe else "Sous-titre"},
        {"layout": "contenu", "titre": "Points clés", "texte": "Premier point\nDeuxième point\nTroisième point"},
    ]}


def instantane(app, f):
    """Instantané Univer d'un fichier Tableur / Document (convertit l'ancien format au besoin)."""
    c = f.contenu or {}
    if isinstance(c.get("univer"), dict):
        return c["univer"]
    if app == "sheets":
        return uc.cellules_vers_univer(c, f.titre)
    return uc.html_vers_document(c.get("html") or "", f.titre)


def normaliser(app, brut):
    """Valide et nettoie le contenu envoyé par l'éditeur. Retourne (contenu, aperçu)."""
    if not isinstance(brut, dict):
        brut = {}
    if app == "sheets" and isinstance(brut.get("univer"), dict):
        data = brut["univer"]
        if not isinstance(data.get("sheets"), dict):
            raise ValueError("Classeur invalide.")
        return {"univer": data}, uc.apercu_classeur(data)
    if app == "docs" and isinstance(brut.get("univer"), dict):
        data = brut["univer"]
        if not isinstance(data.get("body"), dict):
            raise ValueError("Document invalide.")
        return {"univer": data}, re.sub(r"\s+", " ", uc.texte_document(data))[:300]
    if app == "sheets":
        cells = {}
        for ref, c in (brut.get("cells") or {}).items():
            if not re.fullmatch(r"[A-Z]{1,2}[0-9]{1,4}", str(ref)) or not isinstance(c, dict):
                continue
            v = str(c.get("v", ""))[:2000]
            propre = {"v": v}
            for k in ("b", "i", "u"):
                if c.get(k):
                    propre[k] = 1
            if c.get("al") in ("l", "c", "r"):
                propre["al"] = c["al"]
            if c.get("fmt") in ("num", "money", "pct"):
                propre["fmt"] = c["fmt"]
            if isinstance(c.get("bg"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c["bg"]):
                propre["bg"] = c["bg"]
            if v or len(propre) > 1:
                cells[ref] = propre
        nrows = min(max(int(brut.get("nrows") or 60), 20), 2000)
        ncols = min(max(int(brut.get("ncols") or 16), 6), 52)
        cols = {k: min(max(int(v), 40), 600) for k, v in (brut.get("cols") or {}).items()
                if re.fullmatch(r"[A-Z]{1,2}", str(k)) and str(v).isdigit()}
        valeurs = [c["v"] for _, c in sorted(cells.items())[:12] if c.get("v") and not c["v"].startswith("=")]
        return {"cells": cells, "nrows": nrows, "ncols": ncols, "cols": cols}, " · ".join(valeurs)[:300]
    if app == "docs":
        html = nettoyer_html(brut.get("html", ""))
        return {"html": html}, _texte_brut(html)[:300]
    slides = []
    for s in (brut.get("slides") or [])[:200]:
        if not isinstance(s, dict):
            continue
        diapo = {
            "layout": s.get("layout") if s.get("layout") in ("titre", "contenu", "deux", "section", "citation") else "contenu",
            "titre": str(s.get("titre", ""))[:300],
            "texte": str(s.get("texte", ""))[:5000],
            "texte2": str(s.get("texte2", ""))[:5000],
            "notes": str(s.get("notes", ""))[:5000],
        }
        image = s.get("image")
        if isinstance(image, str) and len(image) <= IMAGE_MAX and IMAGE_DATA_RE.fullmatch(image):
            diapo["image"] = image
            diapo["image_pos"] = s.get("image_pos") if s.get("image_pos") in IMAGE_POSITIONS else "droite"
        slides.append(diapo)
    if not slides:
        slides = [{"layout": "titre", "titre": "", "texte": "", "texte2": "", "notes": ""}]
    theme = brut.get("theme") if brut.get("theme") in ("accent", "clair", "sombre", "minuit", "corail") else "accent"
    apercu = " · ".join(s["titre"] for s in slides if s["titre"])[:300]
    return {"theme": theme, "slides": slides}, apercu


# ---------------------------------------------------------------------------
# Vues
# ---------------------------------------------------------------------------

@login_required
def liste(request, app):
    societe, ctx, resp = _contexte(request, app)
    if resp:
        return resp
    q = (request.GET.get("q") or "").strip()
    fichiers = _visibles(request, societe, societe.fichiers_bureau.filter(type_fichier=TYPES[app]["code"])) \
        .select_related("modifie_par", "cree_par").prefetch_related("partenaires")
    ctx["fichiers"] = [
        {
            "pk": f.pk, "titre": f.titre, "apercu": f.apercu, "favori": f.favori,
            "maj": f.updated_at, "auteur": (f.modifie_par or f.cree_par),
            "url": reverse("gestion:bureau_editeur", args=[app, f.pk]),
            "slides": (f.contenu.get("slides") or [])[:1] if app == "slides" else [],
            "theme": f.contenu.get("theme", "accent") if app == "slides" else "",
            "nb": len(f.contenu.get("slides") or []) if app == "slides" else 0,
            "prive": f.prive, "nb_partenaires": len(f.partenaires.all()),
        }
        for f in fichiers
    ]
    ctx["q"] = q
    return render(request, "gestion/bureau_liste.html", ctx)


@login_required
@require_POST
def creer(request, app):
    societe, ctx, resp = _contexte(request, app)
    if resp:
        return resp
    if ctx.get("partage_seul"):
        return redirect("gestion:bureau", app=app)
    defaut = {"sheets": "Classeur sans titre", "docs": "Document sans titre", "slides": "Présentation sans titre"}[app]
    titre = (request.POST.get("titre") or "").strip()[:200] or defaut
    contenu = contenu_defaut(app, societe)
    modele = request.POST.get("modele")
    if app == "sheets" and modele == "budget":
        contenu = {"univer": uc.cellules_vers_univer({"cells": _modele_budget(), "cols": {"A": 180, "B": 130, "C": 130, "D": 130}}, titre)}
    if app == "docs" and modele == "compte_rendu":
        contenu = {"univer": uc.html_vers_document(_modele_compte_rendu(societe), titre)}
    f = FichierBureau.objects.create(
        societe=societe, type_fichier=TYPES[app]["code"], titre=titre, contenu=contenu,
        cree_par=request.user, modifie_par=request.user,
    )
    services.journaliser(societe, "CREATION", "bureau", f.titre, TYPES[app]["nom"], request.user)
    return redirect("gestion:bureau_editeur", app=app, pk=f.pk)


@login_required
def editeur(request, app, pk):
    societe, ctx, resp = _contexte(request, app)
    if resp:
        return resp
    f = _fichier(societe, app, pk, request)
    ctx["fichier"] = f
    ctx["contenu_json"] = instantane(app, f) if app in ("sheets", "docs") else (f.contenu or contenu_defaut(app, societe))
    ctx["sauver_url"] = reverse("gestion:bureau_sauver", args=[app, f.pk])
    ctx["export_url"] = reverse("gestion:bureau_exporter", args=[app, f.pk])
    ctx["liste_url"] = reverse("gestion:bureau", args=[app])
    ctx["etat_url"] = reverse("gestion:bureau_etat", args=[app, f.pk])
    ctx["partage_url"] = reverse("gestion:bureau_partager", args=[app, f.pk])
    ctx["collab"] = {
        "etat": ctx["etat_url"], "partage": ctx["partage_url"], "version": f.version,
        **_partage_info(f, request, societe),
        "employes": [
            {"pk": e.pk, "nom": f"{e.prenom} {e.nom}".strip(), "fonction": e.fonction.nom if e.fonction_id else "",
             "compte": bool(e.compte_id)}
            for e in societe.employes.select_related("fonction").order_by("prenom", "nom")
        ],
    }
    _presence(f, request, societe)
    return render(request, f"gestion/bureau_{app}.html", ctx)


@login_required
@require_POST
def sauver(request, app, pk):
    societe, ctx, resp = _contexte(request, app)
    if resp:
        return JsonResponse({"ok": False, "erreur": "Accès refusé."}, status=403)
    f = _fichier(societe, app, pk, request)
    if len(request.body) > TAILLE_MAX:
        return JsonResponse({"ok": False, "erreur": "Fichier trop volumineux."}, status=413)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "erreur": "Données invalides."}, status=400)
    champs = ["modifie_par", "updated_at"]
    base = data.get("base")
    if "contenu" in data and base is not None and not data.get("forcer"):
        try:
            base = int(base)
        except (TypeError, ValueError):
            base = None
        if base is not None and base != f.version:
            # Quelqu'un a enregistré entre-temps : le client propose de charger sa version ou d'écraser.
            etat = _etat_fichier(f, request, societe)
            return JsonResponse({"ok": False, "conflit": True, "erreur": "Modifié par un autre utilisateur.", **etat}, status=409)
    if "titre" in data:
        f.titre = str(data["titre"]).strip()[:200] or "Sans titre"
        champs.append("titre")
    if "contenu" in data:
        try:
            f.contenu, f.apercu = normaliser(app, data["contenu"])
        except ValueError as exc:
            return JsonResponse({"ok": False, "erreur": str(exc)}, status=400)
        champs += ["contenu", "apercu"]
    f.modifie_par = request.user
    f.version = F("version") + 1
    champs.append("version")
    f.save(update_fields=champs)
    f.refresh_from_db(fields=["version", "updated_at"])
    return JsonResponse({"ok": True, "version": f.version, "maj": timezone.localtime(f.updated_at).strftime("%H:%M")})


@login_required
def etat(request, app, pk):
    """Battement de présence + version courante ; renvoie le contenu si une version plus récente existe."""
    societe, ctx, resp = _contexte(request, app)
    if resp:
        return JsonResponse({"ok": False}, status=403)
    f = _fichier(societe, app, pk, request)
    if request.method == "POST" and request.POST.get("quitter"):
        _presence(f, request, societe, quitter=True)
        return JsonResponse({"ok": True})
    d = {"ok": True, **_etat_fichier(f, request, societe), **_partage_info(f, request, societe)}
    try:
        vu = int(request.GET.get("v") or 0)
    except ValueError:
        vu = 0
    if request.GET.get("tout") or (vu and f.version > vu):
        d["contenu"] = instantane(app, f) if app in ("sheets", "docs") else f.contenu
    return JsonResponse(d)


@login_required
@require_POST
def partager(request, app, pk):
    """Créateur / administration : fichier privé ou non + partenaires (employés invités)."""
    societe, ctx, resp = _contexte(request, app)
    if resp:
        return JsonResponse({"ok": False, "erreur": "Accès refusé."}, status=403)
    f = _fichier(societe, app, pk, request)
    if not _peut_partager(request, societe, f):
        return JsonResponse({"ok": False, "erreur": "Seul le créateur du fichier ou l'administration peut le partager."}, status=403)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "erreur": "Données invalides."}, status=400)
    ids = [int(x) for x in (data.get("partenaires") or []) if str(x).isdigit()]
    avant = set(f.partenaires.values_list("pk", flat=True))
    f.partenaires.set(societe.employes.filter(pk__in=ids))
    f.prive = bool(data.get("prive"))
    f.save(update_fields=["prive"])
    nouveaux = set(f.partenaires.values_list("pk", flat=True)) - avant
    if nouveaux:
        noms = ", ".join(f"{e.prenom} {e.nom}" for e in societe.employes.filter(pk__in=nouveaux))
        services.journaliser(societe, "MODIFICATION", "bureau", f.titre, f"Partagé avec {noms}", request.user)
    return JsonResponse({"ok": True, **_partage_info(f, request, societe)})


@login_required
@require_POST
def action(request, app, pk):
    societe, ctx, resp = _contexte(request, app)
    if resp:
        return resp
    f = _fichier(societe, app, pk, request)
    act = request.POST.get("action")
    if act == "favori":
        f.favori = not f.favori
        f.save(update_fields=["favori"])
    elif act == "renommer":
        f.titre = (request.POST.get("titre") or "").strip()[:200] or f.titre
        f.save(update_fields=["titre", "updated_at"])
    elif act == "dupliquer":
        copie = FichierBureau.objects.create(
            societe=societe, type_fichier=f.type_fichier, titre=f"Copie de {f.titre}"[:200],
            contenu=f.contenu, apercu=f.apercu, cree_par=request.user, modifie_par=request.user,
        )
        return redirect("gestion:bureau_editeur", app=app, pk=copie.pk)
    elif act == "supprimer":
        if not _peut_partager(request, societe, f):
            return redirect(reverse("gestion:bureau", args=[app]) + "?ok=refus")
        titre = f.titre
        f.delete()
        services.journaliser(societe, "SUPPRESSION", "bureau", titre, TYPES[app]["nom"], request.user)
    return redirect(reverse("gestion:bureau", args=[app]) + (f"?ok={act}" if act else ""))


@login_required
def exporter(request, app, pk):
    societe, ctx, resp = _contexte(request, app)
    if resp:
        return resp
    f = _fichier(societe, app, pk, request)
    fmt = (request.GET.get("format") or "").lower()
    nom = re.sub(r"[^\w\- ]+", "", f.titre).strip().replace(" ", "-")[:80] or "fichier"
    from .views import COULEUR_HEX

    accent = COULEUR_HEX.get(societe.couleur, "#0284c7")
    try:
        if app == "sheets" and fmt == "csv":
            return _reponse(uc.classeur_csv(instantane(app, f)), "text/csv; charset=utf-8", f"{nom}.csv")
        if app == "sheets":
            return _reponse(uc.classeur_xlsx(instantane(app, f), accent),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{nom}.xlsx")
        if app == "docs" and fmt == "pdf":
            return _reponse(uc.document_pdf(instantane(app, f), societe, logo_societe.logo_reader(societe), accent, f.titre),
                            "application/pdf", f"{nom}.pdf", inline=bool(request.GET.get("voir")))
        if app == "docs":
            return _reponse(uc.document_docx(instantane(app, f), societe, logo_societe.logo_png(societe), accent, f.titre),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"{nom}.docx")
        if app == "slides" and fmt == "pdf":
            return _reponse(_slides_pdf(f, societe, accent), "application/pdf", f"{nom}.pdf", inline=bool(request.GET.get("voir")))
        if app == "slides":
            return _reponse(_pptx(f, societe, accent), "application/vnd.openxmlformats-officedocument.presentationml.presentation", f"{nom}.pptx")
    except ImportError as exc:
        paquet = {"openpyxl": "openpyxl", "docx": "python-docx", "pptx": "python-pptx"}.get(getattr(exc, "name", ""), str(exc))
        return HttpResponse(
            f"Cet export nécessite le paquet « {paquet} ». Relancez lancer_serveur.bat (installation automatique) "
            f"ou exécutez : pip install {paquet}", content_type="text/plain; charset=utf-8", status=503)
    raise Http404


def _reponse(contenu, type_, nom, inline=False):
    r = HttpResponse(contenu, content_type=type_)
    from urllib.parse import quote

    r["Content-Disposition"] = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(nom)}"
    return r


# ---------------------------------------------------------------------------
# Modèles de départ
# ---------------------------------------------------------------------------

def _modele_budget():
    lignes = [("Poste", "Prévu", "Réalisé", "Écart"), ("Loyer", "250000", "250000", ""),
              ("Salaires", "1800000", "1750000", ""), ("Internet & téléphone", "80000", "95000", ""),
              ("Transport", "120000", "90000", ""), ("Fournitures", "60000", "72000", "")]
    cells = {}
    for i, l in enumerate(lignes, start=1):
        for j, v in enumerate(l):
            ref = f"{chr(65 + j)}{i}"
            if i > 1 and j == 3:
                v = f"=C{i}-B{i}"
            c = {"v": v}
            if i == 1:
                c.update({"b": 1, "bg": "#e0f2fe"})
            elif j:
                c["fmt"] = "money"
            cells[ref] = c
    n = len(lignes) + 1
    cells[f"A{n}"] = {"v": "Total", "b": 1}
    for col in "BCD":
        cells[f"{col}{n}"] = {"v": f"=SUM({col}2:{col}{n - 1})", "b": 1, "fmt": "money"}
    return cells


def _modele_compte_rendu(societe):
    jour = timezone.localdate().strftime("%d/%m/%Y")
    return (f"<h1>Compte rendu de réunion</h1><p><b>Société :</b> {html_escape(societe.nom)}<br>"
            f"<b>Date :</b> {jour}<br><b>Participants :</b> </p><h2>Ordre du jour</h2><ol><li>Point 1</li>"
            "<li>Point 2</li></ol><h2>Décisions</h2><ul><li></li></ul><h2>Actions à mener</h2>"
            "<table><thead><tr><th>Action</th><th>Responsable</th><th>Échéance</th></tr></thead>"
            "<tbody><tr><td></td><td></td><td></td></tr></tbody></table>")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def _col_num(lettres):
    n = 0
    for ch in lettres:
        n = n * 26 + (ord(ch) - 64)
    return n


def _ref(ref):
    m = re.fullmatch(r"([A-Z]{1,2})([0-9]+)", ref)
    return (int(m.group(2)), _col_num(m.group(1))) if m else (0, 0)


FONCTIONS_FR = {"SOMME": "SUM", "MOYENNE": "AVERAGE", "NBVAL": "COUNTA", "NB": "COUNT",
                "ARRONDI": "ROUND", "SI": "IF", "CONCATENER": "CONCAT"}


def _formule_excel(v):
    """Formule saisie en français (=SOMME(A1;A3)) → syntaxe Excel stockée (=SUM(A1,A3))."""
    morceaux = re.split(r'("[^"]*")', v)
    for i in range(0, len(morceaux), 2):
        m = morceaux[i].replace(";", ",")
        m = re.sub(r"\b([A-Za-zÀ-ÿ]+)(?=\s*\()",
                   lambda x: FONCTIONS_FR.get(x.group(1).upper(), x.group(1).upper()), m)
        morceaux[i] = m
    return "".join(morceaux)


def _valeur_brute(v):
    if v.startswith("="):
        return _formule_excel(v)
    t = v.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return int(t) if re.fullmatch(r"-?\d+", t) else float(t) if re.fullmatch(r"-?\d+\.\d+", t) else v
    except ValueError:
        return v


def _csv(contenu):
    cells = contenu.get("cells") or {}
    if not cells:
        return "﻿"
    max_l = max(_ref(r)[0] for r in cells)
    max_c = max(_ref(r)[1] for r in cells)
    grille = [[""] * max_c for _ in range(max_l)]
    for r, c in cells.items():
        l, k = _ref(r)
        grille[l - 1][k - 1] = c.get("v", "")
    sortie = io.StringIO()
    csv.writer(sortie, delimiter=";").writerows(grille)
    return "﻿" + sortie.getvalue()


def _xlsx(f, societe, accent):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", "", f.titre)[:31] or "Feuille1"
    contenu = f.contenu or {}
    for ref, c in (contenu.get("cells") or {}).items():
        l, k = _ref(ref)
        if not l:
            continue
        cell = ws.cell(row=l, column=k, value=_valeur_brute(c.get("v", "")))
        cell.font = Font(bold=bool(c.get("b")), italic=bool(c.get("i")), underline="single" if c.get("u") else None)
        if c.get("al"):
            cell.alignment = Alignment(horizontal={"l": "left", "c": "center", "r": "right"}[c["al"]])
        if c.get("bg"):
            cell.fill = PatternFill("solid", fgColor=c["bg"].lstrip("#").upper())
        if c.get("fmt") == "money":
            cell.number_format = '# ##0 "FCFA"'
        elif c.get("fmt") == "num":
            cell.number_format = "# ##0.00"
        elif c.get("fmt") == "pct":
            cell.number_format = "0%"
    for lettre, w in (contenu.get("cols") or {}).items():
        ws.column_dimensions[lettre].width = max(6, int(w) / 7)
    for k in range(1, (contenu.get("ncols") or 16) + 1):
        lettre = get_column_letter(k)
        if lettre not in (contenu.get("cols") or {}):
            ws.column_dimensions[lettre].width = 14
    ws.sheet_properties.tabColor = accent.lstrip("#")
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


class _VersDocx(HTMLParser):
    """Convertit le HTML (nettoyé) d'un document en paragraphes python-docx."""

    def __init__(self, doc, accent):
        super().__init__(convert_charrefs=True)
        self.doc, self.accent = doc, accent
        self.par, self.styles, self.listes = None, [], []
        self.table, self.ligne, self.cellule, self.align = None, None, None, None
        self.lien = None

    def _nouveau(self, style=None):
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        cible = self.cellule if self.cellule is not None else self.doc
        if self.cellule is not None and len(self.cellule.paragraphs) == 1 and not self.cellule.paragraphs[0].text:
            self.par = self.cellule.paragraphs[0]
        else:
            self.par = cible.add_paragraph(style=style) if style else cible.add_paragraph()
        if self.align:
            self.par.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                                  "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}[self.align]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        m = ALIGN.search(a.get("style") or "")
        self.align = m.group(1).lower() if m else None
        if tag in ("h1", "h2", "h3", "h4"):
            self._nouveau(f"Heading {tag[1]}")
        elif tag in ("p", "div", "blockquote", "pre"):
            self._nouveau("Quote" if tag == "blockquote" else None)
        elif tag in ("ul", "ol"):
            self.listes.append(tag)
        elif tag == "li":
            self._nouveau("List Number" if self.listes and self.listes[-1] == "ol" else "List Bullet")
        elif tag == "br" and self.par is not None:
            self.par.add_run().add_break()
        elif tag == "hr":
            self._nouveau()
            self.par.add_run("—" * 30)
        elif tag in ("b", "strong", "i", "em", "u", "s", "strike", "mark", "code"):
            self.styles.append(tag)
        elif tag == "a":
            self.lien = a.get("href")
        elif tag == "table":
            self.table = self.doc.add_table(rows=0, cols=0)
            self.table.style = "Table Grid"
        elif tag == "tr" and self.table is not None:
            self.ligne = []
        elif tag in ("td", "th") and self.ligne is not None:
            self.ligne.append([tag, []])

    def handle_endtag(self, tag):
        if tag in ("ul", "ol") and self.listes:
            self.listes.pop()
        elif tag in ("b", "strong", "i", "em", "u", "s", "strike", "mark", "code") and tag in self.styles:
            self.styles.remove(tag)
        elif tag == "a":
            self.lien = None
        elif tag == "tr" and self.table is not None and self.ligne is not None:
            from docx.shared import RGBColor

            cols = len(self.table.columns)
            besoin = len(self.ligne)
            while cols < besoin:
                self.table.add_column(width=self.doc.sections[0].page_width // max(besoin, 1))
                cols += 1
            row = self.table.add_row()
            for i, (balise, textes) in enumerate(self.ligne):
                p = row.cells[i].paragraphs[0]
                run = p.add_run("".join(textes))
                if balise == "th":
                    run.bold = True
                    run.font.color.rgb = RGBColor.from_string(self.accent.lstrip("#").upper())
            self.ligne = None
        elif tag == "table":
            self.table = None
            self.par = None
        elif tag in ("p", "h1", "h2", "h3", "h4", "li", "div", "blockquote", "pre"):
            self.par = None

    def handle_data(self, data):
        if self.ligne is not None and self.ligne:
            self.ligne[-1][1].append(data)
            return
        if not data.strip() and self.par is None:
            return
        if self.par is None:
            self._nouveau()
        run = self.par.add_run(data)
        s = self.styles
        run.bold = any(x in s for x in ("b", "strong")) or None
        run.italic = any(x in s for x in ("i", "em")) or None
        run.underline = ("u" in s or bool(self.lien)) or None
        if "s" in s or "strike" in s:
            run.font.strike = True
        if "code" in s:
            run.font.name = "Consolas"
        if self.lien:
            from docx.shared import RGBColor

            run.font.color.rgb = RGBColor.from_string(self.accent.lstrip("#").upper())


def _docx(f, societe, accent):
    from docx import Document
    from docx.shared import Pt, RGBColor, Mm

    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Mm(20)
    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(11)
    for i in range(1, 5):
        try:
            st = styles[f"Heading {i}"]
            st.font.color.rgb = RGBColor.from_string(accent.lstrip("#").upper()) if i == 1 else RGBColor(0x0F, 0x17, 0x2A)
        except KeyError:
            pass
    png = logo_societe.logo_png(societe)
    entete = sec.header.paragraphs[0]
    if png:
        entete.add_run().add_picture(io.BytesIO(png), height=Mm(9))
        entete.add_run("   ")
    r = entete.add_run(societe.nom)
    r.bold = True
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
    pied = sec.footer.paragraphs[0]
    pr = pied.add_run(f"{f.titre} — {societe.nom}")
    pr.font.size = Pt(8)
    pr.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)
    conv = _VersDocx(doc, accent)
    conv.feed((f.contenu or {}).get("html", ""))
    conv.close()
    tampon = io.BytesIO()
    doc.save(tampon)
    return tampon.getvalue()


THEMES = {
    # fond, texte, secondaire
    "accent": (None, "#FFFFFF", "#E0F2FE"),
    "clair": ("#FFFFFF", "#0F172A", "#64748B"),
    "sombre": ("#0F172A", "#F8FAFC", "#94A3B8"),
    "minuit": ("#1E1B4B", "#FFFFFF", "#C7D2FE"),
    "corail": ("#FFF1EC", "#3B0D0C", "#9A3412"),
}


def _theme(f, accent):
    fond, texte, sec = THEMES.get((f.contenu or {}).get("theme", "accent"), THEMES["accent"])
    return fond or accent, texte, sec


def _puces(texte):
    return [l.strip().lstrip("-•*").strip() for l in (texte or "").split("\n") if l.strip()]


def _image_diapo(s):
    """Image d'une diapositive → (octets, largeur, hauteur, position) ou None."""
    octets = uc.image_octets(s.get("image"))
    if not octets:
        return None
    try:
        from PIL import Image as PilImage

        with PilImage.open(io.BytesIO(octets)) as im:
            w, h = im.size
    except Exception:
        return None
    return octets, w, h, s.get("image_pos") if s.get("image_pos") in IMAGE_POSITIONS else "droite"


def _cadre_image(iw, ih, x, y, w, h, couvrir):
    """Place une image iw×ih dans le cadre (x, y, w, h) : « couvrir » (rogné) ou « contenir ».
    Retourne (x, y, w, h, rognage_h, rognage_v) ; rognage = fraction retirée de chaque côté."""
    ri, rc = iw / ih, w / h
    if couvrir:
        if ri > rc:
            return x, y, w, h, (1 - rc / ri) / 2, 0
        return x, y, w, h, 0, (1 - ri / rc) / 2
    if ri > rc:
        nh = w / ri
        return x, y + (h - nh) / 2, w, nh, 0, 0
    nw = h * ri
    return x + (w - nw) / 2, y, nw, h, 0, 0


def _pptx(f, societe, accent):
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Emu, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    W, H = prs.slide_width, prs.slide_height
    fond, texte, sec = _theme(f, accent)
    rgb = lambda h: RGBColor.from_string(h.lstrip("#").upper())  # noqa: E731
    png = logo_societe.logo_png(societe)
    vide = prs.slide_layouts[6]
    for s in (f.contenu or {}).get("slides") or []:
        sl = prs.slides.add_slide(vide)
        bg = sl.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(fond)
        marge = Emu(int(W * 0.07))
        img = _image_diapo(s)
        pos = img[3] if img else None
        if img:
            if pos == "droite":
                cadre = (W * 0.58, 0, W * 0.42, H, True)
            elif pos == "fond":
                cadre = (0, 0, W, H, True)
            else:
                cadre = (marge, H * 0.3, W - 2 * marge, H * 0.57, False)
            x, y, w, h, rh, rv = _cadre_image(img[1], img[2], *cadre)
            pic = sl.shapes.add_picture(io.BytesIO(img[0]), Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
            pic.crop_left = pic.crop_right = rh
            pic.crop_top = pic.crop_bottom = rv
            if pos == "fond":
                texte, sec = "#FFFFFF", "#E2E8F0"
        else:
            texte, sec = _theme(f, accent)[1:]
        if pos == "droite":
            W_txt = Emu(int(W * 0.58))
        else:
            W_txt = W

        def zone(x, y, w, h, contenu, taille, gras=False, couleur=texte, puces=False):
            tb = sl.shapes.add_textbox(x, y, w, h)
            tf = tb.text_frame
            tf.word_wrap = True
            lignes = _puces(contenu) if puces else [contenu]
            for i, ligne in enumerate(lignes or [""]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                run = p.add_run()
                run.text = ("•  " + ligne) if puces else ligne
                run.font.size = Pt(taille)
                run.font.bold = gras
                run.font.color.rgb = rgb(couleur)
                p.space_after = Pt(10 if puces else 4)
            return tb

        lay = s.get("layout")
        larg = W_txt - 2 * marge
        if pos == "centre":
            # Titre en haut, grande image dessous (le texte de liste n'est pas affiché)
            zone(marge, Emu(int(H * 0.07)), larg, Emu(int(H * 0.13)), s.get("titre", "") if lay != "citation" else s.get("texte", ""), 30, True)
            if lay in ("titre", "section"):
                zone(marge, Emu(int(H * 0.19)), larg, Emu(int(H * 0.09)), s.get("texte", ""), 16, False, sec)
        elif lay in ("titre", "section"):
            zone(marge, Emu(int(H * 0.36)), larg, Emu(int(H * 0.2)), s.get("titre", ""), 44 if lay == "titre" else 38, True)
            zone(marge, Emu(int(H * 0.56)), larg, Emu(int(H * 0.2)), s.get("texte", ""), 20, False, sec)
        elif lay == "citation":
            zone(marge, Emu(int(H * 0.3)), larg, Emu(int(H * 0.3)), "« " + s.get("texte", "") + " »", 30, True)
            zone(marge, Emu(int(H * 0.64)), larg, Emu(int(H * 0.1)), s.get("titre", ""), 18, False, sec)
        else:
            zone(marge, Emu(int(H * 0.08)), larg, Emu(int(H * 0.15)), s.get("titre", ""), 32, True)
            if lay == "deux":
                demi = Emu(int(larg / 2 - W * 0.02))
                zone(marge, Emu(int(H * 0.27)), demi, Emu(int(H * 0.6)), s.get("texte", ""), 18, puces=True)
                zone(Emu(int(marge + larg / 2 + W * 0.02)), Emu(int(H * 0.27)), demi, Emu(int(H * 0.6)), s.get("texte2", ""), 18, puces=True)
            else:
                zone(marge, Emu(int(H * 0.27)), larg, Emu(int(H * 0.6)), s.get("texte", ""), 20, puces=True)
        if png:
            sl.shapes.add_picture(io.BytesIO(png), W - marge - Emu(int(W * 0.1)), Emu(int(H * 0.88)), height=Emu(int(H * 0.07)))
        if s.get("notes"):
            sl.notes_slide.notes_text_frame.text = s["notes"]
    tampon = io.BytesIO()
    prs.save(tampon)
    return tampon.getvalue()


def _slides_pdf(f, societe, accent):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph

    W, H = 960, 540
    fond, texte, sec = _theme(f, accent)
    lecteur, ratio = logo_societe.logo_reader(societe)
    tampon = io.BytesIO()
    c = canvas.Canvas(tampon, pagesize=(W, H))
    c.setTitle(f.titre)
    slides = (f.contenu or {}).get("slides") or []

    def bloc(txt, x, y_haut, w, taille, couleur, gras=False, puces=False):
        st = ParagraphStyle("s", fontName="Helvetica-Bold" if gras else "Helvetica", fontSize=taille,
                            leading=taille * 1.3, textColor=colors.HexColor(couleur))
        lignes = _puces(txt) if puces else [txt]
        y = y_haut
        for l in lignes:
            p = Paragraph(("•&nbsp;&nbsp;" if puces else "") + html_escape(l), st)
            _, h = p.wrap(w, H)
            y -= h
            p.drawOn(c, x, y)
            y -= taille * (0.6 if puces else 0.2)
        return y

    def image(img, cadre):
        from reportlab.lib.utils import ImageReader

        octets, iw, ih, _ = img
        x, y_haut, w, h, couvrir = cadre
        y = H - y_haut - h  # repère PDF : origine en bas
        c.saveState()
        p = c.beginPath()
        p.rect(x, y, w, h)
        c.clipPath(p, stroke=0, fill=0)
        if couvrir:
            r = max(w / iw, h / ih)
            dw, dh = iw * r, ih * r
        else:
            r = min(w / iw, h / ih)
            dw, dh = iw * r, ih * r
        c.drawImage(ImageReader(io.BytesIO(octets)), x + (w - dw) / 2, y + (h - dh) / 2, dw, dh, mask="auto")
        c.restoreState()

    for n, s in enumerate(slides, start=1):
        c.setFillColor(colors.HexColor(fond))
        c.rect(0, 0, W, H, stroke=0, fill=1)
        m = W * 0.07
        lay = s.get("layout")
        img = _image_diapo(s)
        pos = img[3] if img else None
        txt, sc = texte, sec
        larg = (W * 0.58 if pos == "droite" else W) - 2 * m
        if pos == "droite":
            image(img, (W * 0.58, 0, W * 0.42, H, True))
        elif pos == "fond":
            image(img, (0, 0, W, H, True))
            c.saveState()
            c.setFillColor(colors.Color(0.01, 0.02, 0.09, alpha=0.5))
            c.rect(0, 0, W, H, stroke=0, fill=1)
            c.restoreState()
            txt, sc = "#FFFFFF", "#E2E8F0"
        elif pos == "centre":
            image(img, (m, H * 0.3, W - 2 * m, H * 0.57, False))
        if pos == "centre":
            y = bloc(s.get("titre", "") if lay != "citation" else s.get("texte", ""), m, H - H * 0.07, larg, 28, txt, True)
            if lay in ("titre", "section"):
                bloc(s.get("texte", ""), m, y - 4, larg, 15, sc)
        elif lay in ("titre", "section"):
            y = bloc(s.get("titre", ""), m, H * 0.62, larg, 42 if lay == "titre" else 36, txt, True)
            bloc(s.get("texte", ""), m, y - 10, larg, 20, sc)
        elif lay == "citation":
            y = bloc("« " + s.get("texte", "") + " »", m, H * 0.68, larg, 28, txt, True)
            bloc(s.get("titre", ""), m, y - 14, larg, 16, sc)
        else:
            bloc(s.get("titre", ""), m, H - H * 0.1, larg, 30, txt, True)
            if lay == "deux":
                demi = larg / 2 - 15
                bloc(s.get("texte", ""), m, H * 0.72, demi, 18, txt, puces=True)
                bloc(s.get("texte2", ""), m + larg / 2 + 15, H * 0.72, demi, 18, txt, puces=True)
            else:
                bloc(s.get("texte", ""), m, H * 0.72, larg, 20, txt, puces=True)
        if lecteur:
            logo_societe.dessiner(c, lecteur, ratio, W - m, 18, 30, 110, "droite")
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor(sec))
        c.drawString(m, 22, f"{societe.nom}  ·  {n} / {len(slides)}")
        c.showPage()
    c.save()
    return tampon.getvalue()
