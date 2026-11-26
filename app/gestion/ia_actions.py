"""Actions de l'assistant IA dans les Applications (outils d'ÉCRITURE).

L'utilisateur écrit simplement sa demande dans le chat (« crée un tableau des
ventes », « ajoute une diapo », « planifie une réunion jeudi 10 h avec le groupe
Commercial », « rappelle-moi de relancer X vendredi »…) et l'agent appelle :

- ``lister_fichiers``     : fichiers Tableur / Documents / Présentations visibles ;
- ``creer_fichier``       : nouveau classeur, document ou présentation rempli ;
- ``modifier_fichier``    : ajoute ou remplace le contenu, renomme ;
- ``creer_rendez_vous``   : rendez-vous du Planning (participants, groupe, rappel) ;
- ``creer_tache``         : tâche (à soi, ou attribuée par l'administration) ;
- ``consulter_agenda``    : rendez-vous et tâches d'une période.

Les mêmes règles que l'interface s'appliquent : module « Applications » requis
pour les fichiers, fichiers privés invisibles, un employé ne s'attribue que ses
propres tâches. Chaque action est journalisée et renvoie un « bloc » action
(carte « Ouvrir ») affiché dans la conversation.
"""

import json
import re
from datetime import datetime, time, timedelta
from html import escape

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from . import services
from . import univer_conv as uc

APPS = {"sheets": "Tableur", "docs": "Documents", "slides": "Présentations"}
CREE = {"sheets": "Classeur créé", "docs": "Document créé", "slides": "Présentation créée"}
MODIFIE = {"sheets": "Classeur mis à jour", "docs": "Document mis à jour", "slides": "Présentation mise à jour"}
CODES = {"sheets": "SHEET", "docs": "DOC", "slides": "SLIDES"}
LAYOUTS = ("titre", "contenu", "deux", "section", "citation")
THEMES = ("accent", "clair", "sombre", "minuit", "corail")


# ---------------------------------------------------------------------------
# Outils communs
# ---------------------------------------------------------------------------

def _json(d):
    return json.dumps(d, ensure_ascii=False, default=str)


def _admin(ctx):
    return not services.est_employe(ctx.user, ctx.societe) or services.est_createur(ctx.user, ctx.societe)


def _moi(ctx):
    return services.employe_pour_utilisateur(ctx.user, ctx.societe)


def _peut_bureau(ctx):
    return "bureau" in ctx.modules


def _lecture_seule(ctx, module):
    return services.en_lecture_seule(ctx.user, ctx.societe, module)


REFUS_LECTURE = "Accès en lecture seule : vous ne pouvez pas créer ni modifier dans ce module."


def _fichiers_visibles(ctx):
    qs = ctx.societe.fichiers_bureau.all()
    if _admin(ctx):
        return qs
    moi = _moi(ctx)
    filtre = Q(prive=False) | Q(cree_par=ctx.user)
    if moi:
        filtre |= Q(partenaires=moi)
    return qs.filter(filtre).distinct()


def _bloc(ctx, titre, sous_titre, url, app):
    ctx.blocs.append({"type": "action", "titre": titre, "sous_titre": sous_titre, "url": url, "app": app})


def _employe_par_nom(ctx, nom):
    """Employé dont le nom complet contient tous les mots donnés (insensible à la casse)."""
    mots = [m for m in re.split(r"\s+", str(nom or "").lower()) if m]
    if not mots:
        return None
    for e in ctx.societe.employes.all():
        complet = f"{e.prenom} {e.nom}".lower()
        if all(m in complet for m in mots):
            return e
    return None


def markdown_vers_html(texte):
    """Markdown simple (titres, listes, gras, italique) → HTML pour html_vers_document."""
    def en_ligne(t):
        t = escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
        return t

    html, liste = [], None
    for ligne in str(texte or "").replace("\r", "").split("\n"):
        brut = ligne.strip()
        m_puce = re.match(r"^[-*•]\s+(.*)", brut)
        m_num = re.match(r"^\d+[.)]\s+(.*)", brut)
        voulu = "ul" if m_puce else ("ol" if m_num else None)
        if liste and voulu != liste:
            html.append(f"</{liste}>")
            liste = None
        if voulu:
            if not liste:
                html.append(f"<{voulu}>")
                liste = voulu
            html.append(f"<li>{en_ligne((m_puce or m_num).group(1))}</li>")
            continue
        m_titre = re.match(r"^(#{1,4})\s+(.*)", brut)
        if m_titre:
            n = len(m_titre.group(1))
            html.append(f"<h{n}>{en_ligne(m_titre.group(2))}</h{n}>")
        elif brut:
            html.append(f"<p>{en_ligne(brut)}</p>")
    if liste:
        html.append(f"</{liste}>")
    return "".join(html)


def _lignes(valeur):
    """Tableau de lignes envoyé par le modèle → liste de listes de chaînes / nombres (bornée)."""
    out = []
    for ligne in (valeur or [])[:500]:
        if isinstance(ligne, (list, tuple)):
            out.append([c if isinstance(c, (int, float)) else str(c if c is not None else "")[:500] for c in ligne[:40]])
        elif ligne is not None:
            out.append([str(ligne)[:500]])
    return out


def _diapositives(valeur):
    out = []
    for s in (valeur or [])[:60]:
        if not isinstance(s, dict):
            continue
        out.append({
            "layout": s.get("layout") if s.get("layout") in LAYOUTS else "contenu",
            "titre": str(s.get("titre") or "")[:300],
            "texte": str(s.get("texte") or "")[:5000],
            "texte2": str(s.get("texte2") or "")[:5000],
            "notes": str(s.get("notes") or "")[:5000],
        })
    return out


def _ajouter_lignes(data, lignes):
    """Ajoute des lignes sous les données existantes de la première feuille d'un classeur Univer."""
    sheets = data.get("sheets") or {}
    sid = next((s for s in (data.get("sheetOrder") or []) if s in sheets), None) or next(iter(sheets), None)
    if sid is None:
        return uc.classeur_vide(data.get("name") or "Classeur", lignes)
    cd = sheets[sid].setdefault("cellData", {})
    depart = max((int(r) for r, l in cd.items() if l), default=-1) + 1
    for i, ligne in enumerate(lignes):
        for c, v in enumerate(ligne):
            if v in (None, ""):
                continue
            n = uc._nombre(v)
            cd.setdefault(str(depart + i), {})[str(c)] = (
                {"f": uc.formule_excel(str(v))} if str(v).startswith("=") else {"v": n if n is not None else v})
    sheets[sid]["rowCount"] = max(int(sheets[sid].get("rowCount") or 200), depart + len(lignes) + 20)
    return data


def _ajouter_document(data, html):
    """Ajoute du contenu (HTML simple) à la fin d'un document Univer existant."""
    neuf = uc.html_vers_document(html)
    base_body = (data or {}).get("body") or {}
    ds = base_body.get("dataStream") or "\r\n"
    base = ds[:-1] if ds.endswith("\n") else ds
    dec = len(base)
    nb = neuf["body"]
    body = dict(base_body)
    body["dataStream"] = base + nb["dataStream"]
    body["textRuns"] = list(base_body.get("textRuns") or []) + [
        {**r, "st": r["st"] + dec, "ed": r["ed"] + dec} for r in nb.get("textRuns") or []]
    body["paragraphs"] = list(base_body.get("paragraphs") or []) + [
        {**p, "startIndex": p["startIndex"] + dec} for p in nb.get("paragraphs") or []]
    body["sectionBreaks"] = [{"startIndex": len(body["dataStream"]) - 1}]
    data = dict(data or {})
    data["body"] = body
    return data


# ---------------------------------------------------------------------------
# Fichiers des Applications
# ---------------------------------------------------------------------------

def lister_fichiers(args, ctx):
    if not _peut_bureau(ctx):
        return _json({"erreur": "Vous n'avez pas accès aux Applications."})
    app = args.get("app")
    qs = _fichiers_visibles(ctx)
    if app in CODES:
        qs = qs.filter(type_fichier=CODES[app])
    from .bureau import CODE_VERS_APP

    fichiers = [{"id": f.pk, "app": CODE_VERS_APP.get(f.type_fichier), "titre": f.titre,
                 "apercu": (f.apercu or "")[:120], "modifie": timezone.localtime(f.updated_at).strftime("%d/%m/%Y %H:%M")}
                for f in qs.order_by("-updated_at")[:30]]
    ctx.etapes.append({"icone": "list", "texte": f"Fichiers consultés ({len(fichiers)})"})
    return _json({"fichiers": fichiers})


def creer_fichier(args, ctx):
    from .bureau import normaliser
    from .models import FichierBureau

    if not _peut_bureau(ctx):
        return _json({"erreur": "Vous n'avez pas accès aux Applications."})
    app = args.get("app")
    if app not in APPS:
        return _json({"erreur": "Application inconnue (sheets, docs ou slides)."})
    if _lecture_seule(ctx, "bureau"):
        return _json({"erreur": REFUS_LECTURE})
    titre = str(args.get("titre") or "").strip()[:200] or f"{APPS[app]} — Assistant IA"
    if app == "sheets":
        brut = {"univer": uc.classeur_vide(titre, _lignes(args.get("lignes")))}
    elif app == "docs":
        brut = {"univer": uc.html_vers_document(markdown_vers_html(args.get("texte")), titre)}
    else:
        brut = {"theme": args.get("theme") if args.get("theme") in THEMES else "accent",
                "slides": _diapositives(args.get("diapositives")) or [{"layout": "titre", "titre": titre}]}
    contenu, apercu = normaliser(app, brut)
    f = FichierBureau.objects.create(
        societe=ctx.societe, type_fichier=CODES[app], titre=titre, contenu=contenu, apercu=apercu,
        cree_par=ctx.user, modifie_par=ctx.user,
    )
    services.journaliser(ctx.societe, "CREATION", "bureau", f.titre, f"{APPS[app]} · Assistant IA", ctx.user)
    url = reverse("gestion:bureau_editeur", args=[app, f.pk])
    _bloc(ctx, f.titre, f"{CREE[app]} · {APPS[app]}", url, app)
    ctx.etapes.append({"icone": "doc", "texte": f"{CREE[app]} : {f.titre}"})
    return _json({"ok": True, "id": f.pk, "titre": f.titre, "lien": url})


def modifier_fichier(args, ctx):
    from .bureau import CODE_VERS_APP, instantane, normaliser

    if not _peut_bureau(ctx):
        return _json({"erreur": "Vous n'avez pas accès aux Applications."})
    if _lecture_seule(ctx, "bureau"):
        return _json({"erreur": REFUS_LECTURE})
    try:
        pk = int(args.get("id"))
    except (TypeError, ValueError):
        return _json({"erreur": "Identifiant de fichier manquant : appelle d'abord lister_fichiers."})
    f = _fichiers_visibles(ctx).filter(pk=pk).first()
    if f is None:
        return _json({"erreur": "Fichier introuvable ou non autorisé."})
    app = CODE_VERS_APP[f.type_fichier]
    remplacer = args.get("mode") == "remplacer"
    if args.get("titre"):
        f.titre = str(args["titre"]).strip()[:200] or f.titre
    if app == "sheets" and args.get("lignes") is not None:
        lignes = _lignes(args.get("lignes"))
        data = uc.classeur_vide(f.titre, lignes) if remplacer else _ajouter_lignes(instantane(app, f), lignes)
        f.contenu, f.apercu = normaliser(app, {"univer": data})
    elif app == "docs" and args.get("texte"):
        html = markdown_vers_html(args.get("texte"))
        data = uc.html_vers_document(html, f.titre) if remplacer else _ajouter_document(instantane(app, f), html)
        f.contenu, f.apercu = normaliser(app, {"univer": data})
    elif app == "slides" and (args.get("diapositives") or args.get("theme")):
        actuel = f.contenu or {}
        nouvelles = _diapositives(args.get("diapositives"))
        slides = nouvelles if remplacer else list(actuel.get("slides") or []) + nouvelles
        theme = args.get("theme") if args.get("theme") in THEMES else actuel.get("theme", "accent")
        f.contenu, f.apercu = normaliser(app, {"theme": theme, "slides": slides})
    f.modifie_par = ctx.user
    f.version = (f.version or 0) + 1
    f.save()
    services.journaliser(ctx.societe, "MODIFICATION", "bureau", f.titre, f"{APPS[app]} · Assistant IA", ctx.user)
    url = reverse("gestion:bureau_editeur", args=[app, f.pk])
    _bloc(ctx, f.titre, f"{MODIFIE[app]} · {APPS[app]}", url, app)
    ctx.etapes.append({"icone": "doc", "texte": f"{MODIFIE[app]} : {f.titre}"})
    return _json({"ok": True, "id": f.pk, "lien": url})


# ---------------------------------------------------------------------------
# Planning : rendez-vous, tâches, agenda
# ---------------------------------------------------------------------------

def _date_heure(valeur):
    if not valeur:
        return None
    d = parse_datetime(str(valeur))
    if d is None:
        j = parse_date(str(valeur))
        d = datetime.combine(j, time(9, 0)) if j else None
    if d is not None and timezone.is_naive(d):
        d = timezone.make_aware(d)
    return d


def creer_rendez_vous(args, ctx):
    from .models import TYPE_EVENEMENT_CHOICES, EvenementAgenda

    titre = str(args.get("titre") or "").strip()[:200]
    debut = _date_heure(args.get("debut"))
    if not titre or debut is None:
        return _json({"erreur": "Titre et date de début (AAAA-MM-JJTHH:MM) obligatoires."})
    journee = bool(args.get("journee"))
    fin = _date_heure(args.get("fin"))
    if journee:
        debut = timezone.make_aware(datetime.combine(timezone.localtime(debut).date(), time.min))
        fin = timezone.make_aware(datetime.combine(timezone.localtime(fin or debut).date(), time(23, 59)))
    elif fin is None or fin <= debut:
        fin = debut + timedelta(minutes=int(args.get("duree_minutes") or 60))
    participants, introuvables = [], []
    for nom in args.get("participants") or []:
        e = _employe_par_nom(ctx, nom)
        (participants.append(e) if e else introuvables.append(str(nom)))
    if args.get("groupe"):
        g = ctx.societe.equipe_groupes.filter(titre__iexact=str(args["groupe"]).strip()).first() \
            or ctx.societe.equipe_groupes.filter(titre__icontains=str(args["groupe"]).strip()).first()
        if g is None:
            introuvables.append(f"groupe {args['groupe']}")
        else:
            participants += [m.employe for m in g.membres.select_related("employe")]
    moi = _moi(ctx)
    if moi and moi not in participants and not _admin(ctx):
        participants.append(moi)
    ev = EvenementAgenda.objects.create(
        societe=ctx.societe, organisateur=ctx.user, titre=titre,
        description=str(args.get("description") or "")[:5000], lieu=str(args.get("lieu") or "")[:255],
        type_evenement=args.get("type") if args.get("type") in dict(TYPE_EVENEMENT_CHOICES) else "RDV",
        debut=debut, fin=fin, journee_entiere=journee,
        rappel_minutes=int(args["rappel_minutes"]) if str(args.get("rappel_minutes") or "").isdigit() else None,
    )
    ev.participants.set({p.pk: p for p in participants}.values())
    services.journaliser(ctx.societe, "CREATION", "planning", ev.titre,
                         f"{timezone.localtime(ev.debut):%d/%m/%Y %H:%M} · Assistant IA", ctx.user)
    quand = timezone.localtime(ev.debut).strftime("%d/%m/%Y" + ("" if journee else " à %H:%M"))
    _bloc(ctx, ev.titre, f"Rendez-vous le {quand}", reverse("gestion:planning"), "planning")
    ctx.etapes.append({"icone": "check", "texte": f"Rendez-vous planifié : {ev.titre}"})
    return _json({"ok": True, "id": ev.pk, "quand": quand,
                  "participants": [f"{p.prenom} {p.nom}" for p in participants], "introuvables": introuvables})


def creer_tache(args, ctx):
    from .models import PRIORITE_TACHE_CHOICES, Tache

    if _lecture_seule(ctx, "taches"):
        return _json({"erreur": REFUS_LECTURE})
    titre = str(args.get("titre") or "").strip()[:200]
    echeance = parse_date(str(args.get("echeance") or ""))
    if not titre or echeance is None:
        return _json({"erreur": "Titre et échéance (AAAA-MM-JJ) obligatoires."})
    moi = _moi(ctx)
    if _admin(ctx) and args.get("assigne_a"):
        assignee = _employe_par_nom(ctx, args["assigne_a"])
        if assignee is None:
            return _json({"erreur": f"Employé introuvable : {args['assigne_a']}."})
    else:
        assignee = moi
    if assignee is None:
        return _json({"erreur": "Précisez l'employé à qui attribuer la tâche (assigne_a)."})
    debut = parse_date(str(args.get("date_debut") or "")) or echeance
    t = Tache.objects.create(
        societe=ctx.societe, cree_par=ctx.user, assignee=assignee, titre=titre,
        description=str(args.get("description") or "")[:5000],
        priorite=args.get("priorite") if args.get("priorite") in dict(PRIORITE_TACHE_CHOICES) else "MOYENNE",
        echeance=echeance, date_debut=min(debut, echeance),
    )
    services.journaliser(ctx.societe, "CREATION", "taches", t.titre,
                         f"{assignee.prenom} {assignee.nom} · {echeance:%d/%m/%Y} · Assistant IA", ctx.user)
    _bloc(ctx, t.titre, f"Tâche pour {assignee.prenom} {assignee.nom} · {echeance:%d/%m/%Y}",
          reverse("gestion:planning"), "planning")
    ctx.etapes.append({"icone": "check", "texte": f"Tâche créée : {t.titre}"})
    return _json({"ok": True, "id": t.pk, "assignee": f"{assignee.prenom} {assignee.nom}"})


def consulter_agenda(args, ctx):
    from .models import Tache

    du = parse_date(str(args.get("du") or "")) or timezone.localdate()
    au = parse_date(str(args.get("au") or "")) or du + timedelta(days=7)
    debut = timezone.make_aware(datetime.combine(du, time.min))
    fin = timezone.make_aware(datetime.combine(au, time.max))
    moi = _moi(ctx)
    evs = ctx.societe.evenements_agenda.filter(debut__lt=fin, fin__gt=debut)
    taches = Tache.objects.filter(societe=ctx.societe, echeance__gte=du, echeance__lte=au).exclude(statut="ANNULEE")
    # Uniquement l'agenda de l'utilisateur (comme le Planning)
    filtre = Q(organisateur=ctx.user)
    if moi:
        filtre |= Q(participants=moi)
    evs = evs.filter(filtre).distinct()
    filtre_t = Q(assignee=moi) if moi else Q(pk__in=[])
    if _admin(ctx):
        filtre_t |= Q(cree_par=ctx.user)
    taches = taches.filter(filtre_t).distinct()
    ctx.etapes.append({"icone": "list", "texte": f"Agenda consulté du {du:%d/%m} au {au:%d/%m}"})
    return _json({
        "rendez_vous": [{"titre": e.titre, "debut": timezone.localtime(e.debut).strftime("%d/%m/%Y %H:%M"),
                         "lieu": e.lieu, "participants": [f"{p.prenom} {p.nom}" for p in e.participants.all()]}
                        for e in evs.prefetch_related("participants").order_by("debut")[:40]],
        "taches": [{"titre": t.titre, "echeance": f"{t.echeance:%d/%m/%Y}", "statut": t.get_statut_display(),
                    "assignee": f"{t.assignee.prenom} {t.assignee.nom}" if t.assignee_id else ""}
                   for t in taches.select_related("assignee").order_by("echeance")[:40]],
    })


EXECUTEURS = {
    "lister_fichiers": lister_fichiers,
    "creer_fichier": creer_fichier,
    "modifier_fichier": modifier_fichier,
    "creer_rendez_vous": creer_rendez_vous,
    "creer_tache": creer_tache,
    "consulter_agenda": consulter_agenda,
}


def outils(modules):
    """Définitions (format OpenAI / Groq) des outils d'action."""
    diapo = {"type": "object", "properties": {
        "layout": {"type": "string", "enum": list(LAYOUTS)},
        "titre": {"type": "string"},
        "texte": {"type": "string", "description": "Une puce par ligne (layout contenu / deux)."},
        "texte2": {"type": "string", "description": "Colonne de droite (layout deux)."},
        "notes": {"type": "string"},
    }, "required": ["titre"]}
    contenu = {
        "lignes": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                   "description": "Tableur : lignes de cellules, 1re ligne = en-têtes. Formules acceptées (=SOMME(B2:B5))."},
        "texte": {"type": "string", "description": "Documents : contenu Markdown (# titres, listes, **gras**)."},
        "diapositives": {"type": "array", "items": diapo, "description": "Présentations : diapositives."},
        "theme": {"type": "string", "enum": list(THEMES)},
    }
    sortie = []
    if "bureau" in modules:
        sortie += [
            {"type": "function", "function": {
                "name": "lister_fichiers",
                "description": "Liste les fichiers existants du Tableur, de Documents et de Présentations (id, titre).",
                "parameters": {"type": "object", "properties": {"app": {"type": "string", "enum": list(APPS)}}},
            }},
            {"type": "function", "function": {
                "name": "creer_fichier",
                "description": "Crée un fichier dans les Applications : classeur (sheets), document (docs) ou "
                               "présentation (slides), déjà rempli avec le contenu demandé.",
                "parameters": {"type": "object", "properties": {
                    "app": {"type": "string", "enum": list(APPS)}, "titre": {"type": "string"}, **contenu,
                }, "required": ["app", "titre"]},
            }},
            {"type": "function", "function": {
                "name": "modifier_fichier",
                "description": "Modifie un fichier existant (id obtenu via lister_fichiers) : ajoute du contenu "
                               "à la fin (mode ajouter, par défaut) ou le remplace (mode remplacer), ou le renomme.",
                "parameters": {"type": "object", "properties": {
                    "id": {"type": "integer"}, "mode": {"type": "string", "enum": ["ajouter", "remplacer"]},
                    "titre": {"type": "string"}, **contenu,
                }, "required": ["id"]},
            }},
        ]
    sortie += [
        {"type": "function", "function": {
            "name": "creer_rendez_vous",
            "description": "Planifie un rendez-vous / une réunion dans le Planning, avec participants "
                           "(noms d'employés) ou un groupe entier, et un rappel.",
            "parameters": {"type": "object", "properties": {
                "titre": {"type": "string"},
                "debut": {"type": "string", "description": "AAAA-MM-JJTHH:MM (heure locale)"},
                "fin": {"type": "string", "description": "AAAA-MM-JJTHH:MM (facultatif)"},
                "duree_minutes": {"type": "integer"},
                "journee": {"type": "boolean"},
                "type": {"type": "string", "enum": ["RDV", "REUNION", "APPEL", "VISITE", "FORMATION", "CONGE", "AUTRE"]},
                "lieu": {"type": "string"}, "description": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "string"}},
                "groupe": {"type": "string", "description": "Nom d'un groupe d'équipe : tous ses membres sont invités."},
                "rappel_minutes": {"type": "integer", "description": "Rappel X minutes avant (10, 30, 60…)."},
            }, "required": ["titre", "debut"]},
        }},
        {"type": "function", "function": {
            "name": "creer_tache",
            "description": "Crée une tâche avec échéance (rappel « À ne pas oublier »). L'administration peut "
                           "l'attribuer à un employé ; sinon elle est pour l'utilisateur.",
            "parameters": {"type": "object", "properties": {
                "titre": {"type": "string"}, "description": {"type": "string"},
                "echeance": {"type": "string", "description": "AAAA-MM-JJ"},
                "date_debut": {"type": "string", "description": "AAAA-MM-JJ"},
                "priorite": {"type": "string", "enum": ["FAIBLE", "MOYENNE", "HAUTE"]},
                "assigne_a": {"type": "string", "description": "Nom de l'employé (administration)."},
            }, "required": ["titre", "echeance"]},
        }},
        {"type": "function", "function": {
            "name": "consulter_agenda",
            "description": "Rendez-vous et tâches d'une période (par défaut les 7 prochains jours).",
            "parameters": {"type": "object", "properties": {
                "du": {"type": "string", "description": "AAAA-MM-JJ"}, "au": {"type": "string", "description": "AAAA-MM-JJ"},
            }},
        }},
    ]
    return sortie


def consignes(societe):
    """Consignes ajoutées au prompt de l'agent pour les actions."""
    maintenant = timezone.localtime()
    groupes = ", ".join(societe.equipe_groupes.values_list("titre", flat=True)[:20]) or "aucun"
    return (
        f"\n\nACTIONS DANS L'APPLICATION (nous sommes le {maintenant:%A %d/%m/%Y}, il est {maintenant:%H:%M}). "
        "Quand l'utilisateur demande de CRÉER, AJOUTER, MODIFIER, PLANIFIER ou de lui RAPPELER quelque chose, "
        "fais-le réellement avec les outils au lieu d'expliquer comment faire :\n"
        "- tableau / classeur / budget → `creer_fichier` app=sheets (lignes avec en-têtes, formules =SOMME…) ;\n"
        "- document / courrier / compte rendu modifiable → `creer_fichier` app=docs (texte Markdown) ;\n"
        "- présentation / diapos → `creer_fichier` app=slides (5 à 10 diapositives, 1re en layout titre) ;\n"
        "- modifier un fichier existant → `lister_fichiers` puis `modifier_fichier` ;\n"
        "- réunion / rendez-vous → `creer_rendez_vous` (dates calculées depuis aujourd'hui, rappel 30 min par défaut) ;\n"
        "- « rappelle-moi de… », « à faire » → `creer_tache` ;\n"
        "- « qu'est-ce que j'ai cette semaine ? » → `consulter_agenda`.\n"
        f"Groupes d'équipe existants : {groupes}. Utilise des données réelles (statistiques) pour remplir les "
        "fichiers quand c'est pertinent. Après l'action, confirme en une ou deux phrases ce qui a été fait, en nommant les applications internes (Tableur, Documents, Présentations, Planning) — jamais Google Sheets, Word ou PowerPoint."
    )
