"""Assistant IA « agentique » : outils de données, graphiques et documents.

L'assistant (Groq, API compatible OpenAI) dispose d'outils en LECTURE SEULE,
bornés aux modules autorisés du compte connecté :

- ``obtenir_statistiques`` : indicateurs et séries chiffrées réels ;
- ``lister_elements``      : liste détaillée d'un module ;
- ``afficher_graphique``   : affiche un graphique (barres, courbe, anneau) ;
- ``creer_document``       : rédige un document (rapport, bilan…) affiché
  dans le panneau d'aperçu et téléchargeable en PDF.

Chaque réponse renvoie le texte, des « blocs » (graphiques, indicateurs,
documents) et les « étapes » suivies par l'agent. Sans clé Groq ou en cas
d'erreur, un mode local produit quand même graphiques et rapports à partir
des données réelles.
"""

import json
import re
import time
import unicodedata
import uuid
from datetime import timedelta

import requests
from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from . import ai
from . import ia_actions

PALETTE = ["var(--accent)", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#06b6d4", "#64748b"]
MOIS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
           "sept.", "oct.", "nov.", "déc."]
TYPES_GRAPHIQUE = {"barres", "ligne", "anneau"}
MAX_TOURS = 6


# ---------------------------------------------------------------------------
# Outils internes : dates, formats, agrégations
# ---------------------------------------------------------------------------


def _norm(texte):
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def _fmt(valeur):
    """Nombre lisible : séparateur de milliers en espace, sans décimales inutiles."""
    try:
        v = float(valeur or 0)
    except (TypeError, ValueError):
        return str(valeur)
    if abs(v - round(v)) < 1e-9:
        return f"{v:,.0f}".replace(",", " ")
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _debuts_de_mois(n=6):
    """Premier jour des `n` derniers mois, du plus ancien au mois courant."""
    jour = timezone.localdate().replace(day=1)
    mois = []
    for _ in range(n):
        mois.append(jour)
        jour = (jour.replace(day=1) - timedelta(days=1)).replace(day=1)
    return list(reversed(mois))


def _libelles_mois(mois):
    return [f"{MOIS_FR[m.month - 1]} {str(m.year)[2:]}" for m in mois]


def _par_mois(qs, champ_date, mois, champ_somme=None, datetime_champ=False):
    """Compte (ou somme) par mois, aligné sur `mois`."""
    valeurs = []
    for debut in mois:
        fin = (debut + timedelta(days=32)).replace(day=1)
        suffixe = "__date" if datetime_champ else ""
        filtre = {
            f"{champ_date}{suffixe}__gte": debut,
            f"{champ_date}{suffixe}__lt": fin,
        }
        sous = qs.filter(**filtre)
        if champ_somme:
            valeurs.append(float(sous.aggregate(t=Sum(champ_somme))["t"] or 0))
        else:
            valeurs.append(sous.count())
    return valeurs


def _repartition(qs, champ, libelles=None, limite=6, vide="Non renseigné"):
    """Répartition (libellés, valeurs) des lignes de `qs` selon `champ`."""
    lignes = list(qs.values(champ).annotate(n=Count("id")).order_by("-n"))
    labels, valeurs = [], []
    autres = 0
    for i, ligne in enumerate(lignes):
        cle = ligne[champ]
        if i >= limite:
            autres += ligne["n"]
            continue
        nom = (libelles or {}).get(cle, cle) if cle not in (None, "") else vide
        labels.append(str(nom))
        valeurs.append(ligne["n"])
    if autres:
        labels.append("Autres")
        valeurs.append(autres)
    return labels, valeurs


def _choix(model, champ):
    try:
        return dict(model._meta.get_field(champ).choices or [])
    except Exception:
        return {}


def _graphique(type_, titre, labels, series, unite=""):
    return {
        "type": "graphique",
        "graphique": type_,
        "titre": titre,
        "labels": [str(l) for l in labels],
        "series": series,
        "unite": unite,
    }


# ---------------------------------------------------------------------------
# Statistiques structurées (indicateurs + graphiques) par module
# ---------------------------------------------------------------------------


def _stats_employes(societe, mois):
    from .models import Employe

    qs = societe.employes.all()
    total = qs.count()
    sans_contrat = qs.filter(contrats__isnull=True).count()
    masse = qs.filter(statut="ACTIF").aggregate(t=Sum("salaire"))["t"] or 0
    labels, valeurs = _repartition(qs, "statut", _choix(Employe, "statut"))
    f_labels, f_valeurs = _repartition(qs, "fonction__nom", vide="Sans fonction")
    recrues = _par_mois(qs, "date_recrutement", mois)
    return {
        "label": "Employés",
        "indicateurs": [
            {"label": "Employés", "valeur": _fmt(total)},
            {"label": "Actifs", "valeur": _fmt(qs.filter(statut="ACTIF").count())},
            {"label": "Sans contrat", "valeur": _fmt(sans_contrat)},
            {"label": "Masse salariale (actifs)", "valeur": _fmt(masse)},
        ],
        "graphiques": [
            _graphique("anneau", "Employés par statut", labels,
                       [{"nom": "Employés", "valeurs": valeurs}]),
            _graphique("barres", "Employés par fonction", f_labels,
                       [{"nom": "Employés", "valeurs": f_valeurs}]),
            _graphique("barres", "Recrutements par mois", _libelles_mois(mois),
                       [{"nom": "Recrutements", "valeurs": recrues}]),
        ],
    }


def _stats_clients(societe, mois):
    from .models import Client

    qs = societe.clients.all()
    nouveaux = _par_mois(qs, "created_at", mois, datetime_champ=True)
    s_labels, s_valeurs = _repartition(qs, "source", _choix(Client, "source"))
    st_labels, st_valeurs = _repartition(qs, "statut", _choix(Client, "statut"))
    return {
        "label": "Clients",
        "indicateurs": [
            {"label": "Clients", "valeur": _fmt(qs.count())},
            {"label": "Actifs", "valeur": _fmt(qs.filter(statut="ACTIF").count())},
            {"label": "Avec projets",
             "valeur": _fmt(qs.filter(projets__isnull=False).distinct().count())},
            {"label": "Nouveaux ce mois", "valeur": _fmt(nouveaux[-1] if nouveaux else 0)},
        ],
        "graphiques": [
            _graphique("ligne", "Nouveaux clients par mois", _libelles_mois(mois),
                       [{"nom": "Nouveaux clients", "valeurs": nouveaux}]),
            _graphique("anneau", "Clients par source", s_labels,
                       [{"nom": "Clients", "valeurs": s_valeurs}]),
            _graphique("anneau", "Clients par statut", st_labels,
                       [{"nom": "Clients", "valeurs": st_valeurs}]),
        ],
    }


def _stats_projets(societe, mois):
    from .models import ProjetClient

    qs = societe.projets.all()
    labels, valeurs = _repartition(qs, "statut", _choix(ProjetClient, "statut"))
    budget = qs.aggregate(t=Sum("budget"))["t"] or 0
    return {
        "label": "Projets",
        "indicateurs": [
            {"label": "Projets", "valeur": _fmt(qs.count())},
            {"label": "En cours", "valeur": _fmt(qs.filter(statut="EN_COURS").count())},
            {"label": "Budget total", "valeur": _fmt(budget)},
        ],
        "graphiques": [
            _graphique("anneau", "Projets par statut", labels,
                       [{"nom": "Projets", "valeurs": valeurs}]),
            _graphique("barres", "Projets démarrés par mois", _libelles_mois(mois),
                       [{"nom": "Projets", "valeurs": _par_mois(qs, "date_debut", mois)}]),
        ],
    }


def _stats_finances(societe, mois):
    lignes = {f.periode.replace(day=1): f for f in societe.finances.all()}
    recettes = [float(getattr(lignes.get(m), "total_recettes", 0) or 0) for m in mois]
    depenses = [float(getattr(lignes.get(m), "total_depenses", 0) or 0) for m in mois]
    soldes = [float(getattr(lignes.get(m), "solde", 0) or 0) for m in mois]
    cumul = sum(float(s or 0) for s in societe.finances.values_list("solde", flat=True))
    return {
        "label": "Finances",
        "indicateurs": [
            {"label": "Solde cumulé", "valeur": _fmt(cumul)},
            {"label": "Recettes (6 mois)", "valeur": _fmt(sum(recettes))},
            {"label": "Dépenses (6 mois)", "valeur": _fmt(sum(depenses))},
            {"label": "Solde du mois", "valeur": _fmt(soldes[-1] if soldes else 0)},
        ],
        "graphiques": [
            _graphique("ligne", "Recettes et dépenses par mois", _libelles_mois(mois), [
                {"nom": "Recettes", "valeurs": recettes},
                {"nom": "Dépenses", "valeurs": depenses},
            ]),
            _graphique("barres", "Solde mensuel", _libelles_mois(mois),
                       [{"nom": "Solde", "valeurs": soldes}]),
        ],
    }


def _stats_depenses(societe, mois):
    qs = societe.depenses.all()
    total = qs.aggregate(t=Sum("montant"))["t"] or 0
    t_labels, montants = [], []
    for ligne in (qs.values("type_depense__nom").annotate(t=Sum("montant"))
                  .order_by("-t")[:6]):
        t_labels.append(ligne["type_depense__nom"] or "Sans type")
        montants.append(float(ligne["t"] or 0))
    return {
        "label": "Dépenses",
        "indicateurs": [
            {"label": "Dépenses", "valeur": _fmt(qs.count())},
            {"label": "Montant total", "valeur": _fmt(total)},
            {"label": "Ce mois",
             "valeur": _fmt(_par_mois(qs, "date_depense", mois[-1:], "montant")[0])},
        ],
        "graphiques": [
            _graphique("barres", "Dépenses par mois", _libelles_mois(mois),
                       [{"nom": "Montant", "valeurs": _par_mois(qs, "date_depense", mois, "montant")}]),
            _graphique("anneau", "Dépenses par type (montant)", t_labels,
                       [{"nom": "Montant", "valeurs": montants}]),
        ],
    }


def _stats_salaires(societe, mois):
    from .models import PaiementSalaire

    qs = PaiementSalaire.objects.filter(employe__societe=societe)
    total = qs.aggregate(t=Sum("montant_paye"))["t"] or 0
    return {
        "label": "Salaires",
        "indicateurs": [
            {"label": "Paiements de salaire", "valeur": _fmt(qs.count())},
            {"label": "Total payé", "valeur": _fmt(total)},
            {"label": "Payés", "valeur": _fmt(qs.filter(statut="PAYE").count())},
        ],
        "graphiques": [
            _graphique("barres", "Salaires payés par mois", _libelles_mois(mois),
                       [{"nom": "Montant payé",
                         "valeurs": _par_mois(qs, "periode_mois", mois, "montant_paye")}]),
        ],
    }


def _stats_paiements(societe, mois):
    from .models import PaiementClient

    qs = PaiementClient.objects.filter(projet__societe=societe)
    total = qs.aggregate(t=Sum("montant"))["t"] or 0
    return {
        "label": "Paiements clients",
        "indicateurs": [
            {"label": "Paiements", "valeur": _fmt(qs.count())},
            {"label": "Total encaissé", "valeur": _fmt(total)},
        ],
        "graphiques": [
            _graphique("ligne", "Encaissements par mois", _libelles_mois(mois),
                       [{"nom": "Encaissé",
                         "valeurs": _par_mois(qs, "date_paiement", mois, "montant")}]),
        ],
    }


def _stats_echeances(societe, mois):
    from .models import EcheancePaiement

    qs = EcheancePaiement.objects.filter(projet__societe=societe)
    labels, valeurs = _repartition(qs, "statut", _choix(EcheancePaiement, "statut"))
    a_venir = qs.filter(statut="A_VENIR").aggregate(t=Sum("montant_prevu"))["t"] or 0
    return {
        "label": "Échéances",
        "indicateurs": [
            {"label": "Échéances", "valeur": _fmt(qs.count())},
            {"label": "Montant à venir", "valeur": _fmt(a_venir)},
        ],
        "graphiques": [
            _graphique("anneau", "Échéances par statut", labels,
                       [{"nom": "Échéances", "valeurs": valeurs}]),
        ],
    }


def _stats_taches(societe, mois):
    from .models import Tache

    qs = Tache.objects.filter(societe=societe)
    labels, valeurs = _repartition(qs, "statut", _choix(Tache, "statut"))
    p_labels, p_valeurs = _repartition(qs, "priorite", _choix(Tache, "priorite"))
    return {
        "label": "Tâches",
        "indicateurs": [
            {"label": "Tâches", "valeur": _fmt(qs.count())},
            {"label": "En cours",
             "valeur": _fmt(qs.filter(statut__in=["A_FAIRE", "EN_COURS"]).count())},
        ],
        "graphiques": [
            _graphique("anneau", "Tâches par statut", labels,
                       [{"nom": "Tâches", "valeurs": valeurs}]),
            _graphique("barres", "Tâches par priorité", p_labels,
                       [{"nom": "Tâches", "valeurs": p_valeurs}]),
        ],
    }


_STATS = {
    "employes": _stats_employes,
    "clients": _stats_clients,
    "projets": _stats_projets,
    "finances": _stats_finances,
    "depenses": _stats_depenses,
    "salaires": _stats_salaires,
    "paiements": _stats_paiements,
    "echeances": _stats_echeances,
    "taches": _stats_taches,
}

# Mots-clés (sans accents) servant à repérer les modules cités dans une question.
_MOTS_MODULES = {
    "employes": ["employ", "personnel", "equipe", "effectif", "rh", "recrut"],
    "clients": ["client"],
    "projets": ["projet"],
    "finances": ["financ", "solde", "tresorer", "recette", "chiffre d'affaire", "benefice"],
    "depenses": ["depense", "charge", "cout"],
    "salaires": ["salaire", "paie", "masse salariale"],
    "paiements": ["paiement", "encaiss", "vente"],
    "echeances": ["echeance", "facture", "impaye", "creance"],
    "taches": ["tache", "todo"],
}


def modules_statistiques(modules):
    """Modules autorisés pour lesquels des statistiques existent."""
    return [m for m in _STATS if m in set(modules)]


def stats_structurees(societe, modules, cibles=None):
    """{module: {label, indicateurs, graphiques}} pour les modules autorisés."""
    autorises = modules_statistiques(modules)
    if cibles:
        autorises = [m for m in autorises if m in set(cibles)]
    mois = _debuts_de_mois(6)
    sortie = {}
    for cle in autorises:
        try:
            sortie[cle] = _STATS[cle](societe, mois)
        except Exception:
            continue
    if "salaires" not in set(modules) and "employes" in sortie:
        # Montants de salaire réservés aux comptes ayant la permission « Salaires »
        sortie["employes"]["indicateurs"] = [i for i in sortie["employes"]["indicateurs"]
                                             if "salari" not in i["label"].lower()]
    return sortie


def modules_cites(question, modules):
    q = _norm(question)
    trouves = []
    for cle, mots in _MOTS_MODULES.items():
        if cle in modules and any(m in q for m in mots):
            trouves.append(cle)
    return trouves


def _veut_document(question):
    q = _norm(question)
    return any(m in q for m in (
        "rapport", "document", "bilan", "synthese", "compte rendu", "compte-rendu",
        "note de", "memo", "pdf", "redige", "rediger",
    ))


def _veut_graphique(question):
    q = _norm(question)
    return any(m in q for m in (
        "graph", "diagram", "courbe", "statist", "evolution", "repartition",
        "chart", "visualis", "illustr", "tendance", "analyse", "compar",
    ))


# ---------------------------------------------------------------------------
# Construction des blocs (validation des données venant du modèle)
# ---------------------------------------------------------------------------


def _nombre(v):
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def valider_graphique(args):
    """Bloc graphique propre à partir d'arguments libres (ou None si invalide)."""
    if not isinstance(args, dict):
        return None
    type_ = str(args.get("graphique") or "").lower()
    if type_ not in TYPES_GRAPHIQUE:
        type_ = str(args.get("type") or "").lower()
    if type_ not in TYPES_GRAPHIQUE:
        type_ = "barres"
    labels = [str(l)[:40] for l in (args.get("labels") or [])][:24]
    if not labels:
        return None
    series = []
    for i, s in enumerate((args.get("series") or [])[:4]):
        if not isinstance(s, dict):
            continue
        valeurs = [_nombre(v) for v in (s.get("valeurs") or [])][: len(labels)]
        valeurs += [0.0] * (len(labels) - len(valeurs))
        series.append({"nom": str(s.get("nom") or f"Série {i + 1}")[:40], "valeurs": valeurs})
    if not series:
        return None
    if type_ == "anneau":
        series = series[:1]
    return _graphique(type_, str(args.get("titre") or "Graphique")[:120], labels,
                      series, str(args.get("unite") or "")[:20])


def construire_document(args, societe, user):
    """Bloc document (rapport) validé."""
    sections = []
    for s in (args.get("sections") or [])[:40]:
        if not isinstance(s, dict):
            continue
        graphique = valider_graphique(s.get("graphique")) if s.get("graphique") else None
        sections.append({
            "titre": str(s.get("titre") or "")[:150],
            "contenu": str(s.get("contenu") or "")[:6000],
            "graphique": graphique,
        })
    indicateurs = []
    for k in (args.get("indicateurs") or [])[:8]:
        if isinstance(k, dict) and k.get("label"):
            indicateurs.append({"label": str(k["label"])[:60], "valeur": str(k.get("valeur", ""))[:40]})
    auteur = f"{getattr(user, 'prenom', '')} {getattr(user, 'nom', '')}".strip()
    return {
        "type": "document",
        "id": uuid.uuid4().hex[:10],
        "titre": str(args.get("titre") or "Rapport")[:150],
        "sous_titre": str(args.get("sous_titre") or "")[:250],
        "societe": societe.nom,
        "auteur": auteur or getattr(user, "email", ""),
        "date": timezone.localdate().strftime("%d/%m/%Y"),
        "indicateurs": indicateurs,
        "sections": sections,
    }


def document_automatique(societe, user, modules, question):
    """Rapport généré localement (sans IA) à partir des données réelles."""
    cibles = modules_cites(question, modules) or None
    stats = stats_structurees(societe, modules, cibles)
    sections = [{
        "titre": "Résumé",
        "contenu": (
            f"Ce document présente la situation de **{societe.nom}** au "
            f"{timezone.localdate():%d/%m/%Y}, à partir des données enregistrées "
            "dans la plateforme."
        ),
    }]
    indicateurs = []
    for cle, bloc in stats.items():
        lignes = [f"- **{k['label']}** : {k['valeur']}" for k in bloc["indicateurs"]]
        contenu = "\n".join(lignes)
        graphique = next(
            (g for g in bloc["graphiques"] if any(any(s["valeurs"]) for s in [g["series"][0]])),
            bloc["graphiques"][0] if bloc["graphiques"] else None,
        )
        sections.append({"titre": bloc["label"], "contenu": contenu, "graphique": graphique})
        if bloc["indicateurs"]:
            indicateurs.append(bloc["indicateurs"][0])
    titre = "Rapport d'activité"
    if cibles and len(stats) == 1:
        titre = f"Rapport — {next(iter(stats.values()))['label']}"
    return construire_document(
        {
            "titre": titre,
            "sous_titre": f"{societe.nom} · situation au {timezone.localdate():%d/%m/%Y}",
            "indicateurs": indicateurs[:6],
            "sections": sections,
        },
        societe,
        user,
    )


# ---------------------------------------------------------------------------
# Images Markdown « ![Titre](#) » -> vrais graphiques
# ---------------------------------------------------------------------------

_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MOTS_VIDES = {"de", "des", "du", "la", "le", "les", "par", "et", "en", "au", "aux", "l", "d"}


def _jetons(texte):
    return {m for m in re.findall(r"[a-z0-9]+", _norm(texte)) if m not in _MOTS_VIDES and len(m) > 1}


def _tous_les_graphiques(ctx):
    if getattr(ctx, "_graphiques", None) is None:
        ctx._graphiques = [
            g for bloc in stats_structurees(ctx.societe, ctx.modules).values()
            for g in bloc["graphiques"]
        ]
    return ctx._graphiques


def graphique_pour_titre(titre, ctx):
    """Graphique réel dont le titre correspond le mieux à `titre` (ou None)."""
    cible = _norm(titre)
    jetons = _jetons(titre)
    meilleur, score_max = None, 0
    for g in _tous_les_graphiques(ctx):
        nom = _norm(g["titre"])
        if nom == cible or nom in cible or (cible and cible in nom):
            return g
        score = len(jetons & _jetons(g["titre"]))
        if score > score_max:
            meilleur, score_max = g, score
    return meilleur if score_max >= 2 else None


def nettoyer_images(texte, ctx=None, blocs=None):
    """Retire les images Markdown ; ajoute (si `blocs`) les graphiques réels
    correspondants. Retourne le texte nettoyé et la liste des graphiques trouvés."""
    trouves = []
    if not texte or "![" not in texte:
        return texte, trouves
    if ctx is not None:
        deja = {b.get("titre") for b in (blocs or []) if b.get("type") == "graphique"}
        for alt in _IMAGE_MD.findall(texte):
            g = graphique_pour_titre(alt, ctx)
            if g is not None and g["titre"] not in deja:
                deja.add(g["titre"])
                trouves.append(g)
    propre = []
    for ligne in texte.split("\n"):
        if _IMAGE_MD.search(ligne):
            ligne = _IMAGE_MD.sub("", ligne).rstrip()
            if not re.sub(r"^[\s>*•\-\d.)]*", "", ligne).strip(" :.-—"):
                continue
        propre.append(ligne)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(propre)).strip(), trouves


# ---------------------------------------------------------------------------
# Outils exposés au modèle
# ---------------------------------------------------------------------------


def _outils(modules):
    stat_mods = modules_statistiques(modules)
    liste_mods = [m for m in ai._LISTES_IA if m in set(modules)]
    schema_graphique = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": sorted(TYPES_GRAPHIQUE),
                     "description": "barres (comparaison), ligne (évolution), anneau (répartition)"},
            "titre": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
            "series": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nom": {"type": "string"},
                        "valeurs": {"type": "array", "items": {"type": "number"}},
                    },
                    "required": ["nom", "valeurs"],
                },
            },
            "unite": {"type": "string"},
        },
        "required": ["type", "titre", "labels", "series"],
    }
    outils = []
    if stat_mods:
        outils.append({"type": "function", "function": {
            "name": "obtenir_statistiques",
            "description": "Indicateurs et séries chiffrées réels (6 derniers mois, répartitions) "
                           "des modules demandés. À appeler avant tout chiffre ou graphique.",
            "parameters": {"type": "object", "properties": {
                "modules": {"type": "array", "items": {"type": "string", "enum": stat_mods}},
            }, "required": ["modules"]},
        }})
    if liste_mods:
        outils.append({"type": "function", "function": {
            "name": "lister_elements",
            "description": "Liste détaillée des éléments d'un module (noms, statuts, montants…).",
            "parameters": {"type": "object", "properties": {
                "module": {"type": "string", "enum": liste_mods},
                "limite": {"type": "integer", "minimum": 1, "maximum": 30},
            }, "required": ["module"]},
        }})
    outils.append({"type": "function", "function": {
        "name": "afficher_graphique",
        "description": "Affiche un graphique dans la réponse, avec des données réelles déjà obtenues.",
        "parameters": schema_graphique,
    }})
    outils.append({"type": "function", "function": {
        "name": "creer_document",
        "description": "Crée un document (rapport, bilan, compte rendu, note) structuré, "
                       "affiché dans le panneau d'aperçu et téléchargeable en PDF.",
        "parameters": {"type": "object", "properties": {
            "titre": {"type": "string"},
            "sous_titre": {"type": "string"},
            "indicateurs": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "valeur": {"type": "string"},
            }, "required": ["label", "valeur"]}},
            "sections": {"type": "array", "items": {"type": "object", "properties": {
                "titre": {"type": "string"},
                "contenu": {"type": "string", "description": "Texte Markdown (listes, gras, tableaux)."},
                "graphique": schema_graphique,
            }, "required": ["titre", "contenu"]}},
        }, "required": ["titre", "sections"]},
    }})
    return outils + ia_actions.outils(modules)


def _stats_pour_modele(stats):
    """Version compacte des statistiques renvoyée au modèle."""
    sortie = {}
    for cle, bloc in stats.items():
        sortie[cle] = {
            "indicateurs": {k["label"]: k["valeur"] for k in bloc["indicateurs"]},
            "series": [
                {"titre": g["titre"], "type_conseille": g["graphique"], "labels": g["labels"],
                 "series": g["series"]}
                for g in bloc["graphiques"]
            ],
        }
    return sortie


class _Contexte(object):
    def __init__(self, societe, user, modules):
        self.societe = societe
        self.user = user
        self.modules = list(modules)
        self.blocs = []
        self.etapes = []


def executer_outil(nom, args, ctx):
    """Exécute un outil et retourne le résultat (texte JSON) pour le modèle."""
    if nom == "obtenir_statistiques":
        demandes = [m for m in (args.get("modules") or []) if isinstance(m, str)]
        stats = stats_structurees(ctx.societe, ctx.modules, demandes or None)
        noms = ", ".join(b["label"] for b in stats.values()) or "aucun module"
        ctx.etapes.append({"icone": "chart", "texte": f"Statistiques consultées : {noms}"})
        return json.dumps(_stats_pour_modele(stats), ensure_ascii=False)
    if nom == "lister_elements":
        module = args.get("module")
        if module not in ai._LISTES_IA or module not in ctx.modules:
            return json.dumps({"erreur": "Module non autorisé."}, ensure_ascii=False)
        _mots, label, fn, cnt = ai._LISTES_IA[module]
        limite = max(1, min(30, int(args.get("limite") or 15)))
        try:
            lignes = fn(ctx.societe, limite)
        except TypeError:
            lignes = fn(ctx.societe)[:limite]
        if "salaires" not in ctx.modules and module in ("employes", "contrats"):
            # Montants de salaire réservés aux comptes ayant la permission « Salaires »
            lignes = [re.sub(r"( · salaire [\d.,]+|, [\d.,]+$)", "", str(l)) for l in lignes]
        ctx.etapes.append({"icone": "list", "texte": f"Liste consultée : {label}"})
        return json.dumps({"module": label, "total": cnt(ctx.societe), "elements": lignes},
                          ensure_ascii=False)
    if nom == "afficher_graphique":
        bloc = valider_graphique(args)
        if bloc is None:
            return json.dumps({"erreur": "Données de graphique invalides."}, ensure_ascii=False)
        ctx.blocs.append(bloc)
        ctx.etapes.append({"icone": "chart", "texte": f"Graphique créé : {bloc['titre']}"})
        return json.dumps({"ok": True, "affiche": bloc["titre"]}, ensure_ascii=False)
    if nom == "creer_document":
        for section in args.get("sections") or []:
            if not isinstance(section, dict):
                continue
            contenu, graphs = nettoyer_images(str(section.get("contenu") or ""), ctx)
            section["contenu"] = contenu
            if graphs and not section.get("graphique"):
                section["graphique"] = graphs[0]
        bloc = construire_document(args, ctx.societe, ctx.user)
        ctx.blocs.append(bloc)
        ctx.etapes.append({"icone": "doc", "texte": f"Document rédigé : {bloc['titre']}"})
        return json.dumps({"ok": True, "document": bloc["titre"]}, ensure_ascii=False)
    if nom in ia_actions.EXECUTEURS:
        return ia_actions.EXECUTEURS[nom](args, ctx)
    return json.dumps({"erreur": f"Outil inconnu : {nom}"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Appel Groq avec outils + boucle agent
# ---------------------------------------------------------------------------


def _appel_groq(messages, outils):
    key = getattr(settings, "GROQ_API_KEY", "")
    if not key:
        raise ValueError("GROQ_API_KEY manquante.")
    url = getattr(settings, "GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
    corps = {
        "model": getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    if outils:
        corps["tools"] = outils
        corps["tool_choice"] = "auto"
    for essai in range(2):
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=corps,
            timeout=60,
        )
        if resp.status_code != 429 or essai:
            break
        # Limite de débit (offre gratuite) : on patiente le délai indiqué (20 s max) puis on réessaie une fois
        m = re.search(r"try again in ([\d.]+)s", resp.text)
        time.sleep(min(float(m.group(1)) + 0.5 if m else 5.0, 20.0))
    if resp.status_code >= 400:
        raise ValueError(f"Groq {resp.status_code}")
    return resp.json()["choices"][0]["message"]


def _prompt_agent(societe, modules):
    return ai.build_system_prompt(societe, modules) + (
        "\n\nTu es un assistant AGENTIQUE : tu disposes d'outils pour lire les données "
        "réelles, afficher des graphiques et créer des documents. Méthode :\n"
        "1. Pour toute question chiffrée, appelle d'abord `obtenir_statistiques` (ou "
        "`lister_elements` pour une liste). N'invente jamais de chiffres.\n"
        "2. Dès qu'une évolution, une comparaison ou une répartition aide à comprendre, "
        "appelle `afficher_graphique` avec les données réelles obtenues (ligne = évolution, "
        "barres = comparaison, anneau = répartition). 1 à 3 graphiques maximum.\n"
        "3. Si l'utilisateur demande un rapport, un bilan, une synthèse écrite, un compte "
        "rendu, une note ou un PDF, appelle `creer_document` : titre clair, sous-titre, "
        "indicateurs clés, 3 à 7 sections en Markdown (constats, analyse, recommandations) "
        "avec des graphiques pertinents. Ensuite, réponds par 2 à 4 phrases résumant le "
        "document, sans le recopier.\n"
        "4. Réponse finale en Markdown soigné : titres ###, listes, **gras**, tableaux si utile. "
        "Ton professionnel, clair et concis, en français. Ne mentionne pas les noms des outils.\n"
        "5. N'écris JAMAIS d'image Markdown (« ![titre](lien) ») ni de lien vers un graphique : "
        "un graphique s'affiche uniquement en appelant `afficher_graphique` (ou dans la section "
        "`graphique` de `creer_document`)."
    ) + ia_actions.consignes(societe)


def repondre(societe, user, modules, historique, message):
    """Réponse de l'agent : dict(reply, blocs, etapes, offline)."""
    ctx = _Contexte(societe, user, modules)
    outils = _outils(modules)
    messages = [{"role": "system", "content": _prompt_agent(societe, modules)}]
    messages += historique
    messages.append({"role": "user", "content": message[:4000]})
    ctx.etapes.append({"icone": "search", "texte": "Analyse de la demande"})

    texte = None
    try:
        for _ in range(MAX_TOURS):
            reponse = _appel_groq(messages, outils)
            appels = reponse.get("tool_calls") or []
            if not appels:
                texte = (reponse.get("content") or "").strip()
                break
            messages.append({
                "role": "assistant",
                "content": reponse.get("content") or "",
                "tool_calls": appels,
            })
            for appel in appels:
                fonction = appel.get("function") or {}
                try:
                    args = json.loads(fonction.get("arguments") or "{}")
                except ValueError:
                    args = {}
                try:
                    resultat = executer_outil(fonction.get("name"), args, ctx)
                except Exception as exc:  # outil en échec : le modèle est prévenu
                    resultat = json.dumps({"erreur": str(exc)[:200]}, ensure_ascii=False)
                messages.append({
                    "role": "tool",
                    "tool_call_id": appel.get("id"),
                    "content": resultat[:12000],
                })
        if texte is None:
            texte = "Voici le résultat de mon analyse."
        offline = False
    except Exception:
        actions = [b for b in ctx.blocs if b["type"] == "action"]
        if not actions:
            return reponse_locale(societe, user, modules, message)
        # Des actions ont déjà été exécutées : on les rapporte plutôt que de répondre « hors ligne »
        texte = ("Voici ce que j'ai déjà fait :\n" + "\n".join(f"- **{b['titre']}** — {b['sous_titre']}" for b in actions)
                 + "\n\nL'assistant a ensuite été interrompu (limite de requêtes atteinte) : "
                   "renvoyez la suite de votre demande dans quelques secondes.")
        offline = False

    texte, graphs = nettoyer_images(texte, ctx, ctx.blocs)
    if graphs:
        ctx.blocs += graphs
        ctx.etapes.append({"icone": "chart", "texte": f"{len(graphs)} graphique(s) ajouté(s) à partir des données"})
    _completer(ctx, message)
    if not texte and ctx.blocs:
        texte = "Voici le résultat de mon analyse."
    ctx.etapes.append({"icone": "check", "texte": "Réponse rédigée"})
    return {"reply": texte, "blocs": ctx.blocs, "etapes": ctx.etapes, "offline": offline}


def _completer(ctx, message):
    """Garantit un document / des graphiques si la demande l'exige explicitement."""
    types = {b["type"] for b in ctx.blocs}
    if "action" in types:
        return  # la demande a été exécutée dans les Applications (fichier, rendez-vous, tâche)
    if _veut_document(message) and "document" not in types:
        ctx.blocs.append(document_automatique(ctx.societe, ctx.user, ctx.modules, message))
        ctx.etapes.append({"icone": "doc", "texte": "Document rédigé à partir des données"})
    elif _veut_graphique(message) and "graphique" not in types and "document" not in types:
        cibles = modules_cites(message, ctx.modules)
        if cibles:
            for bloc in stats_structurees(ctx.societe, ctx.modules, cibles).values():
                if bloc["graphiques"]:
                    ctx.blocs.append(bloc["graphiques"][0])
            ctx.etapes.append({"icone": "chart", "texte": "Graphiques générés à partir des données"})


def reponse_locale(societe, user, modules, message):
    """Mode local (sans IA) : texte + graphiques / document à partir des données."""
    ctx = _Contexte(societe, user, modules)
    ctx.etapes.append({"icone": "search", "texte": "Analyse de la demande (mode local)"})
    cibles = modules_cites(message, modules)
    if _veut_document(message):
        doc = document_automatique(societe, user, modules, message)
        ctx.blocs.append(doc)
        ctx.etapes.append({"icone": "chart", "texte": "Statistiques consultées"})
        ctx.etapes.append({"icone": "doc", "texte": f"Document rédigé : {doc['titre']}"})
        texte = (
            f"J'ai préparé le document **{doc['titre']}** à partir de vos données "
            f"({len(doc['sections']) - 1} rubrique(s)). Ouvrez-le pour le consulter ou le "
            "télécharger en PDF."
        )
    else:
        texte = ai.repondre_hors_ligne(societe, modules, message)
        if cibles and (_veut_graphique(message) or len(cibles) <= 2):
            stats = stats_structurees(societe, modules, cibles)
            for bloc in stats.values():
                ctx.blocs.append({"type": "indicateurs", "titre": bloc["label"],
                                  "items": bloc["indicateurs"]})
                if bloc["graphiques"]:
                    ctx.blocs.append(bloc["graphiques"][0])
            if stats:
                ctx.etapes.append({"icone": "chart", "texte": "Statistiques et graphiques générés"})
    ctx.etapes.append({"icone": "check", "texte": "Réponse rédigée"})
    return {"reply": texte, "blocs": ctx.blocs, "etapes": ctx.etapes, "offline": True}


# ---------------------------------------------------------------------------
# Export PDF : titre généré par l'IA et documents construits à partir du fil
# ---------------------------------------------------------------------------

_LIBELLES_MODULES = {
    "employes": "Équipe", "clients": "Clients", "projets": "Projets",
    "finances": "Finances", "depenses": "Dépenses", "salaires": "Salaires",
    "paiements": "Encaissements", "echeances": "Échéances", "taches": "Tâches",
}


def titre_rapport(texte, defaut, modules=None, indice=None):
    """Titre court et professionnel proposé par l'IA (repli : titre déduit)."""
    if modules is not None and not defaut.startswith("Rapport"):
        cites = [m for m in modules_cites(indice or texte, modules) if m in _LIBELLES_MODULES]
        if cites:
            defaut = "Rapport — " + " & ".join(_LIBELLES_MODULES[m] for m in cites[:3])
        else:
            defaut = "Synthèse de l'assistant IA"
    if not getattr(settings, "GROQ_API_KEY", ""):
        return defaut
    try:
        reponse = _appel_groq([
            {"role": "system", "content": (
                "Tu proposes le titre d'un rapport professionnel d'entreprise, en français. "
                "Réponds uniquement par le titre : 3 à 8 mots, sans guillemets, sans "
                "ponctuation finale, sans le mot « Titre »."
            )},
            {"role": "user", "content": (texte or "")[:3500]},
        ], None)
        titre = (reponse.get("content") or "").strip().strip("\"'«» .:*#").strip()
        titre = titre.splitlines()[0] if titre else ""
        return titre[:110] or defaut
    except Exception:
        return defaut


def _sections_reponse(question, reponse, blocs):
    """Sections de document correspondant à un échange question / réponse."""
    sections = []
    graphiques = [b for b in blocs or [] if b.get("type") == "graphique"]
    documents = [b for b in blocs or [] if b.get("type") == "document"]
    titre = (question or "Réponse de l'assistant").strip()
    if len(titre) > 110:
        titre = titre[:107] + "…"
    sections.append({
        "titre": titre,
        "contenu": reponse or "",
        "graphique": graphiques[0] if graphiques else None,
    })
    for g in graphiques[1:]:
        sections.append({"titre": g.get("titre") or "Graphique", "contenu": "", "graphique": g})
    for d in documents:
        for s in d.get("sections") or []:
            sections.append(s)
    return sections


def _indicateurs_de(blocs):
    for b in blocs or []:
        if b.get("type") == "document" and b.get("indicateurs"):
            return b["indicateurs"]
        if b.get("type") == "indicateurs" and b.get("items"):
            return b["items"]
    return []


def document_depuis_echanges(societe, user, echanges, titre_defaut, modules=None):
    """Document exportable à partir d'échanges [(question, reponse, blocs)].

    - Un seul échange contenant un document : ce document tel quel.
    - Sinon : un document qui reprend chaque échange en section.
    Le titre est proposé par l'IA (ou déduit des modules cités).
    """
    if len(echanges) == 1:
        docs = [b for b in echanges[0][2] or [] if b.get("type") == "document"]
        if docs:
            return construire_document(docs[-1], societe, user)
    sections, indicateurs, texte = [], [], []
    for question, reponse, blocs in echanges:
        sections += _sections_reponse(question, reponse, blocs)
        indicateurs = indicateurs or _indicateurs_de(blocs)
        texte.append(f"Question : {question}\nRéponse : {reponse}")
    docs = [b for _q, _r, blocs in echanges for b in blocs or [] if b.get("type") == "document"]
    defaut = docs[-1]["titre"] if docs else titre_defaut
    if docs:
        modules = None  # le titre du document de l'assistant est conservé
    questions = " ".join(q or "" for q, _r, _b in echanges)
    titre = titre_rapport("\n\n".join(texte), defaut, modules, indice=questions)
    return construire_document(
        {
            "titre": titre,
            "sous_titre": f"{societe.nom} · synthèse établie par l'assistant IA",
            "indicateurs": indicateurs,
            "sections": sections,
        },
        societe,
        user,
    )
