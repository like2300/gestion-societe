"""Cartes statistiques (style tableau de bord) pour chaque page de l'app.

Chaque carte est un dict consommé par ``components/stat_row.html`` :
    label, value, icon, tone, series (6 mois), trend, trend_dir, note,
    uid, value_class.

``cartes(societe, module)`` renvoie les 4 cartes d'un module (liste vide si
le module n'a pas de cartes). Les séries couvrent les 6 derniers mois,
le mois courant en dernier.
"""

from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    ContratEmploye,
    EcheancePaiement,
    PaiementClient,
    PaiementSalaire,
)

NB_MOIS = 6
TONS = {
    "bleu": None,  # accent de la société
    "violet": "#8b5cf6",
    "vert": "#10b981",
    "ambre": "#f59e0b",
    "rouge": "#e11d48",
    "indigo": "#4f46e5",
    "cyan": "#06b6d4",
}


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------

def mois(n=NB_MOIS):
    """[(début, fin_exclusive), ...] des `n` derniers mois, le courant en dernier."""
    aujourdhui = timezone.localdate()
    out = []
    for i in range(n - 1, -1, -1):
        m, a = aujourdhui.month - i, aujourdhui.year
        while m <= 0:
            m += 12
            a -= 1
        debut = date(a, m, 1)
        fin = date(a + (m == 12), m % 12 + 1, 1)
        out.append((debut, fin))
    return out


def _somme(qs, champ):
    return float(qs.aggregate(t=Sum(champ))["t"] or 0)


def par_mois(qs, champ, somme=None, dt=False):
    """Nombre (ou somme de `somme`) par mois selon la date `champ`."""
    s = "__date" if dt else ""
    out = []
    try:
        for debut, fin in mois():
            q = qs.filter(**{f"{champ}{s}__gte": debut, f"{champ}{s}__lt": fin})
            out.append(_somme(q, somme) if somme else q.count())
    except Exception:
        return [0] * NB_MOIS
    return out


def cumul(qs, champ, somme=None, dt=False):
    """Total cumulé à la fin de chaque mois (lignes sans date comptées d'office)."""
    s = "__date" if dt else ""
    out = []
    try:
        sans = qs.filter(**{f"{champ}__isnull": True})
        base = _somme(sans, somme) if somme else sans.count()
        for _, fin in mois():
            q = qs.filter(**{f"{champ}{s}__lt": fin})
            out.append(base + (_somme(q, somme) if somme else q.count()))
    except Exception:
        return [0] * NB_MOIS
    return out


def argent(v):
    """1234567.8 -> « 1 234 568 » (espaces fines insécables)."""
    try:
        return f"{float(v):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def tendance(serie, unite="ce mois"):
    """Évolution du dernier mois en valeur absolue : (texte, sens)."""
    if len(serie) < 2:
        return "", "flat"
    d = serie[-1] - serie[-2]
    if d > 0:
        return f"+{d:g} {unite}", "up"
    if d < 0:
        return f"{d:g} {unite}", "down"
    return "Stable", "flat"


def tendance_pct(serie, inverse=False):
    """Évolution du dernier mois en % : (texte, sens). `inverse` : une baisse est positive."""
    if len(serie) < 2:
        return "", "flat"
    avant, apres = serie[-2], serie[-1]
    if not avant:
        if not apres:
            return "Stable", "flat"
        return "Nouveau ce mois", ("down" if inverse else "up")
    pct = round((apres - avant) * 100 / abs(avant))
    if pct == 0:
        return "Stable", "flat"
    sens = "up" if pct > 0 else "down"
    if inverse:
        sens = "down" if sens == "up" else "up"
    return f"{pct:+d} % vs M-1", sens


def carte(label, value, icon, uid, series=None, tone="bleu", trend=None,
          note="", value_class=""):
    trend = trend or ("Stable", "flat")
    if not series:
        # Pas de donnée datée : courbe plate pour garder un rendu uniforme (style tableau de bord).
        try:
            v = float(str(value).replace("\u202f", "").replace(" ", ""))
        except (TypeError, ValueError):
            v = 1.0
        series = [v] * NB_MOIS
    return {
        "label": label,
        "value": value,
        "icon": icon,
        "uid": uid,
        "series": series or [],
        "tone": TONS.get(tone, tone),
        "trend": trend[0],
        "trend_dir": trend[1],
        "note": note,
        "value_class": value_class,
    }


# ---------------------------------------------------------------------------
# Cartes par module
# ---------------------------------------------------------------------------

def _employes(societe):
    qs = societe.employes.all()
    total = cumul(qs, "date_recrutement")
    actifs_qs = qs.filter(statut="ACTIF")
    actifs = cumul(actifs_qs, "date_recrutement")
    contrats = ContratEmploye.objects.filter(employe__societe=societe)
    sous_contrat = qs.filter(contrats__statut="ACTIF").distinct().count()
    masse = cumul(actifs_qs, "date_recrutement", somme="salaire")
    absents = qs.filter(statut__in=["CONGE", "SUSPENDU"]).count()
    return [
        carte("Employés", total[-1], "users", "emp", total, "bleu",
              tendance(total), f"{absents} en congé / suspendu(s)" if absents else ""),
        carte("Employés actifs", actifs[-1], "check", "emp-act", actifs, "vert",
              tendance(actifs),
              f"{round(actifs[-1] * 100 / total[-1]) if total[-1] else 0} % de l'effectif"),
        carte("Sous contrat", sous_contrat, "file", "emp-ctr",
              cumul(contrats.filter(statut="ACTIF"), "date_debut"), "violet",
              tendance(cumul(contrats.filter(statut="ACTIF"), "date_debut")),
              f"sur {total[-1]} employé(s)"),
        carte("Masse salariale", argent(masse[-1]), "wallet", "emp-ms", masse, "ambre",
              tendance_pct(masse), "salaires des actifs / mois"),
    ]


def _clients(societe):
    qs = societe.clients.all()
    total = cumul(qs, "created_at", dt=True)
    actifs = cumul(qs.filter(statut="ACTIF"), "created_at", dt=True)
    nouveaux = par_mois(qs, "created_at", dt=True)
    prospects = societe.prospections.exclude(statut__in=["GAGNE", "PERDU"])
    pros = par_mois(societe.prospections.all(), "date_prospection")
    return [
        carte("Clients", total[-1], "briefcase", "cli", total, "bleu", tendance(total)),
        carte("Clients actifs", actifs[-1], "check", "cli-act", actifs, "vert",
              tendance(actifs),
              f"{round(actifs[-1] * 100 / total[-1]) if total[-1] else 0} % du portefeuille"),
        carte("Nouveaux ce mois", nouveaux[-1], "user", "cli-new", nouveaux, "violet",
              tendance(nouveaux, "vs M-1")),
        carte("Prospects en cours", prospects.count(), "target", "cli-pro", pros, "ambre",
              tendance(pros, "ce mois"), "hors gagnés / perdus"),
    ]


def _projets(societe):
    qs = societe.projets.all()
    total = cumul(qs, "date_debut")
    en_cours = cumul(qs.filter(statut="EN_COURS"), "date_debut")
    termines = cumul(qs.filter(statut="TERMINE"), "date_fin")
    budget = cumul(qs.exclude(statut="ANNULE"), "date_debut", somme="budget")
    return [
        carte("Projets", total[-1], "folder", "prj", total, "bleu", tendance(total)),
        carte("En cours", en_cours[-1], "clock", "prj-cours", en_cours, "ambre",
              tendance(en_cours)),
        carte("Terminés", termines[-1], "check", "prj-fin", termines, "vert",
              tendance(termines)),
        carte("Budget total", argent(budget[-1]), "wallet", "prj-bud", budget, "violet",
              tendance_pct(budget), "hors projets annulés"),
    ]


def _taches(societe):
    qs = societe.taches.all()
    total = cumul(qs, "created_at", dt=True)
    ouvertes = qs.filter(statut__in=["A_FAIRE", "EN_COURS"])
    ouv = cumul(ouvertes, "created_at", dt=True)
    finies = par_mois(qs.filter(statut="TERMINEE"), "date_terminee", dt=True)
    retard = ouvertes.filter(echeance__lt=timezone.localdate())
    retard_s = par_mois(retard, "echeance")
    return [
        carte("Tâches", total[-1], "list", "tac", total, "bleu", tendance(total)),
        carte("À faire / en cours", ouv[-1], "clock", "tac-ouv", ouv, "ambre",
              tendance(ouv)),
        carte("Terminées ce mois", finies[-1], "check", "tac-fin", finies, "vert",
              tendance(finies, "vs M-1"),
              f"{qs.filter(statut='TERMINEE').count()} au total"),
        carte("En retard", retard.count(), "alert", "tac-ret", retard_s, "rouge",
              note="échéance dépassée", value_class="neg" if retard.exists() else ""),
    ]


def _salaires(societe):
    qs = PaiementSalaire.objects.filter(employe__societe=societe)
    payes = par_mois(qs.filter(statut="PAYE"), "date_paiement", somme="montant_paye")
    non_payes = qs.exclude(statut="PAYE")
    du = par_mois(non_payes, "periode_mois", somme="montant_du")
    aujourdhui = timezone.localdate()
    retard = non_payes.filter(Q(statut="RETARD") | Q(date_prevue__lt=aujourdhui))
    bulletins = par_mois(qs, "periode_mois")
    return [
        carte("Payé ce mois", argent(payes[-1]), "wallet", "sal-pay", payes, "vert",
              tendance_pct(payes), value_class="pos"),
        carte("Reste à payer", argent(_somme(non_payes, "montant_du")), "clock",
              "sal-du", du, "ambre", note=f"{non_payes.count()} salaire(s) non soldé(s)"),
        carte("En retard", retard.count(), "alert", "sal-ret",
              par_mois(retard, "date_prevue"), "rouge", note="date prévue dépassée",
              value_class="neg" if retard.exists() else ""),
        carte("Bulletins ce mois", bulletins[-1], "file", "sal-bul", bulletins, "bleu",
              tendance(bulletins, "vs M-1"), f"{qs.count()} au total"),
    ]


def _depenses(societe):
    qs = societe.depenses.all()
    conf = qs.filter(statut="CONFIRME")
    mois_s = par_mois(conf, "date_depense", somme="montant")
    nb = par_mois(qs, "date_depense")
    attente = qs.filter(statut="EN_ATTENTE")
    total = cumul(conf, "date_depense", somme="montant")
    return [
        carte("Dépenses du mois", argent(mois_s[-1]), "card", "dep-m", mois_s, "rouge",
              tendance_pct(mois_s, inverse=True), "confirmées", "neg"),
        carte("Nombre ce mois", nb[-1], "list", "dep-nb", nb, "bleu",
              tendance(nb, "vs M-1")),
        carte("En attente", attente.count(), "clock", "dep-att",
              par_mois(attente, "date_depense"), "ambre",
              note=f"{argent(_somme(attente, 'montant'))} à valider"),
        carte("Total confirmé", argent(total[-1]), "chart", "dep-tot", total, "violet",
              tendance_pct(total, inverse=True), "toutes périodes"),
    ]


def _paiements(societe):
    qs = PaiementClient.objects.filter(projet__societe=societe)
    conf = qs.filter(statut="CONFIRME")
    mois_s = par_mois(conf, "date_paiement", somme="montant")
    nb = par_mois(qs, "date_paiement")
    attente = qs.filter(statut="EN_ATTENTE")
    total = cumul(conf, "date_paiement", somme="montant")
    return [
        carte("Encaissé ce mois", argent(mois_s[-1]), "wallet", "pai-m", mois_s, "vert",
              tendance_pct(mois_s), "paiements confirmés", "pos"),
        carte("Paiements ce mois", nb[-1], "card", "pai-nb", nb, "bleu",
              tendance(nb, "vs M-1")),
        carte("En attente", attente.count(), "clock", "pai-att",
              par_mois(attente, "date_paiement"), "ambre",
              note=f"{argent(_somme(attente, 'montant'))} à confirmer"),
        carte("Total encaissé", argent(total[-1]), "chart", "pai-tot", total, "violet",
              tendance_pct(total), "toutes périodes", "pos"),
    ]


def _contrats(societe):
    qs = ContratEmploye.objects.filter(employe__societe=societe)
    total = cumul(qs, "date_debut")
    actifs = qs.filter(statut="ACTIF")
    act = cumul(actifs, "date_debut")
    aujourdhui = timezone.localdate()
    bientot = actifs.filter(date_fin__gte=aujourdhui, date_fin__lte=aujourdhui + timedelta(days=30))
    clos = qs.filter(statut__in=["TERMINE", "RESILIE"])
    return [
        carte("Contrats", total[-1], "file", "ctr", total, "bleu", tendance(total)),
        carte("Actifs", act[-1], "check", "ctr-act", act, "vert", tendance(act)),
        carte("Expirent sous 30 j", bientot.count(), "alert", "ctr-exp",
              par_mois(actifs, "date_fin"), "ambre", note="à renouveler"),
        carte("Terminés / résiliés", clos.count(), "minus", "ctr-clos",
              cumul(clos, "date_fin"), "rouge"),
    ]


def _echeances(societe):
    qs = EcheancePaiement.objects.filter(projet__societe=societe)
    aujourdhui = timezone.localdate()
    ouvertes = qs.exclude(statut="PAYEE")
    retard = ouvertes.filter(Q(statut="RETARD") | Q(date_prevue__lt=aujourdhui))
    a_venir = ouvertes.filter(date_prevue__gte=aujourdhui).exclude(statut="RETARD")
    payees = qs.filter(statut="PAYEE")
    reste = par_mois(ouvertes, "date_prevue", somme="montant_prevu")
    return [
        carte("À venir", a_venir.count(), "calendar", "ech-av",
              par_mois(a_venir, "date_prevue"), "bleu", note="échéances ouvertes"),
        carte("En retard", retard.count(), "alert", "ech-ret",
              par_mois(retard, "date_prevue"), "rouge", note="date dépassée",
              value_class="neg" if retard.exists() else ""),
        carte("Payées", payees.count(), "check", "ech-pay",
              cumul(payees, "date_prevue"), "vert",
              tendance(cumul(payees, "date_prevue"))),
        carte("Reste à encaisser", argent(_somme(ouvertes, "montant_prevu")), "wallet",
              "ech-mt", reste, "violet", note="non payé"),
    ]


def _prospection(societe):
    qs = societe.prospections.all()
    total = cumul(qs, "created_at", dt=True)
    nego = qs.filter(statut="EN_NEGOCIATION")
    gagnes = qs.filter(statut="GAGNE")
    g = cumul(gagnes, "created_at", dt=True)
    pipe = qs.exclude(statut__in=["GAGNE", "PERDU"])
    clos = gagnes.count() + qs.filter(statut="PERDU").count()
    return [
        carte("Prospects", total[-1], "target", "pro", total, "bleu", tendance(total)),
        carte("En négociation", nego.count(), "clock", "pro-neg",
              par_mois(nego, "date_prospection"), "ambre"),
        carte("Gagnés", g[-1], "award", "pro-win", g, "vert", tendance(g),
              f"{round(gagnes.count() * 100 / clos) if clos else 0} % de conversion"),
        carte("Pipeline estimé", argent(_somme(pipe, "budget_estime")), "wallet",
              "pro-pipe", par_mois(pipe, "date_prospection", somme="budget_estime"),
              "violet", note="budgets des prospects ouverts"),
    ]


def _roles(societe):
    qs = societe.roles.all()
    actifs = qs.filter(statut="ACTIF").count()
    employes = societe.employes.all()
    avec_s = cumul(employes.filter(role__isnull=False), "date_recrutement")
    sans_s = cumul(employes.filter(role__isnull=True), "date_recrutement")
    avec = avec_s[-1]
    perms = societe.permissions_activees.filter(active=True).count()
    top = qs.annotate(n=Count("employes")).order_by("-n").first() if qs.exists() else None
    return [
        carte("Rôles", qs.count(), "shield", "rol", tone="bleu", note=f"{actifs} actif(s)"),
        carte("Employés avec un rôle", avec, "users", "rol-emp", avec_s, "vert",
              tendance(avec_s), f"sur {employes.count()} employé(s)"),
        carte("Sans rôle", sans_s[-1], "alert", "rol-sans", sans_s, "ambre",
              tendance(sans_s), "à attribuer"),
        carte("Permissions actives", perms, "check", "rol-perm", tone="violet",
              note=(f"rôle le plus utilisé : {top.nom}" if top and getattr(top, "n", 0) else "au niveau de la société")),
    ]


def _fonctions(societe):
    qs = societe.fonctions.all()
    actives = qs.filter(actif=True).count()
    employes = societe.employes.all()
    avec_s = cumul(employes.filter(fonction__isnull=False), "date_recrutement")
    sans_s = cumul(employes.filter(fonction__isnull=True), "date_recrutement")
    avec = avec_s[-1]
    top = qs.annotate(n=Count("employes")).order_by("-n").first() if qs.exists() else None
    return [
        carte("Fonctions", qs.count(), "briefcase", "fon", tone="bleu", note=f"{actives} active(s)"),
        carte("Employés affectés", avec, "users", "fon-emp", avec_s, "vert",
              tendance(avec_s), f"sur {employes.count()} employé(s)"),
        carte("Sans fonction", sans_s[-1], "alert", "fon-sans", sans_s, "ambre",
              tendance(sans_s), "à affecter"),
        carte("Poste le plus pourvu", (top.nom if top and getattr(top, "n", 0) else "—"), "award",
              "fon-top", tone="violet",
              note=(f"{top.n} employé(s)" if top and getattr(top, "n", 0) else "aucune affectation")),
    ]


def _documents(societe):
    qs = societe.documents.all()
    aujourdhui = timezone.localdate()
    expires = qs.filter(date_expiration__lt=aujourdhui).count()
    bientot = qs.filter(date_expiration__gte=aujourdhui,
                        date_expiration__lte=aujourdhui + timedelta(days=30)).count()
    valides = qs.count() - expires
    total = cumul(qs, "date_emission")
    return [
        carte("Documents", qs.count(), "file", "doc", total, "bleu", tendance(total)),
        carte("Valides", valides, "check", "doc-ok",
              cumul(qs.exclude(date_expiration__lt=aujourdhui), "date_emission"), "vert",
              note="en cours de validité"),
        carte("Expirent sous 30 j", bientot, "clock", "doc-30",
              par_mois(qs, "date_expiration"), "ambre", note="à renouveler"),
        carte("Expirés", expires, "alert", "doc-exp",
              cumul(qs.filter(date_expiration__lt=aujourdhui), "date_expiration"), "rouge",
              note="date dépassée", value_class="neg" if expires else ""),
    ]


def cartes_societe(societe):
    """Chiffres clés de la page « Ma société » (style tableau de bord)."""
    emp = cumul(societe.employes.all(), "date_recrutement")
    cli = cumul(societe.clients.all(), "created_at", dt=True)
    prj = cumul(societe.projets.all(), "date_debut")
    doc = cumul(societe.documents.all(), "date_emission")
    actifs = societe.employes.filter(statut="ACTIF").count()
    en_cours = societe.projets.filter(statut="EN_COURS").count()
    return [
        carte("Employés", emp[-1], "users", "so-emp", emp, "bleu", tendance(emp), f"{actifs} actif(s)"),
        carte("Clients", cli[-1], "briefcase", "so-cli", cli, "violet", tendance(cli), "portefeuille"),
        carte("Projets", prj[-1], "folder", "so-prj", prj, "ambre", tendance(prj), f"{en_cours} en cours"),
        carte("Documents", doc[-1], "file", "so-doc", doc, "vert", tendance(doc), "officiels"),
    ]


def cartes_globe(societe):
    """Indicateurs de la carte du monde (style tableau de bord)."""
    from .models import PointGeo
    cli = cumul(societe.clients.filter(statut="ACTIF"), "created_at", dt=True)
    pro = cumul(societe.prospections.exclude(statut__in=["GAGNE", "PERDU"]), "created_at", dt=True)
    ca = cumul(PaiementClient.objects.filter(projet__societe=societe, statut="CONFIRME"),
               "date_paiement", somme="montant")
    points = PointGeo.objects.filter(societe=societe)
    pays = points.exclude(pays="").values("pays").distinct().count()
    villes = points.exclude(ville="").values("ville").distinct().count()
    return [
        carte("Clients", cli[-1], "users", "gl-cli", cli, "bleu", tendance(cli), "clients actifs localisés"),
        carte("Pays couverts", pays, "target", "gl-pays", tone="violet", note=f"{villes} ville(s)"),
        carte("Prospects", pro[-1], "briefcase", "gl-pro", pro, "ambre", tendance(pro), "en cours"),
        carte("Chiffre d'affaires", argent(ca[-1]), "chart", "gl-ca", ca, "vert", tendance_pct(ca),
              "paiements confirmés", "pos"),
    ]


def cartes_profil(user, societe):
    """Activité personnelle de l'utilisateur connecté (page « Mon profil »)."""
    from .models import ActivitePlateforme, EmployePresence, Tache
    actions = par_mois(ActivitePlateforme.objects.filter(utilisateur=user), "created_at", dt=True)
    employe = getattr(user, "employe_profil", None)
    if employe is not None:
        taches = Tache.objects.filter(assignee=employe)
        connexions = par_mois(EmployePresence.objects.filter(employe=employe), "date_connexion", dt=True)
    else:
        taches = Tache.objects.filter(cree_par=user)
        connexions = None
    t_cumul = cumul(taches, "created_at", dt=True)
    finies = par_mois(taches.filter(statut="TERMINEE"), "date_terminee", dt=True)
    ouvertes = taches.filter(statut__in=["A_FAIRE", "EN_COURS"]).count()
    cartes = [
        carte("Mes actions ce mois", actions[-1], "chart", "pf-act", actions, "bleu",
              tendance(actions, "vs M-1"), "créations, modifications…"),
        carte("Tâches" if employe is not None else "Tâches créées", t_cumul[-1], "list", "pf-tac",
              t_cumul, "violet", tendance(t_cumul), f"{ouvertes} en cours"),
        carte("Terminées ce mois", finies[-1], "check", "pf-fin", finies, "vert",
              tendance(finies, "vs M-1")),
    ]
    if connexions is not None:
        cartes.append(carte("Connexions ce mois", connexions[-1], "clock", "pf-con", connexions,
                            "ambre", tendance(connexions, "vs M-1")))
    else:
        jours = (timezone.localdate() - timezone.localtime(user.created_at).date()).days if getattr(user, "created_at", None) else 0
        cartes.append(carte("Membre depuis", f"{jours} j", "calendar", "pf-mem", tone="ambre",
                            note=timezone.localtime(user.created_at).strftime("%d/%m/%Y") if getattr(user, "created_at", None) else ""))
    return cartes


MODULES = {
    "roles": _roles,
    "fonctions": _fonctions,
    "documents": _documents,
    "employes": _employes,
    "clients": _clients,
    "projets": _projets,
    "taches": _taches,
    "salaires": _salaires,
    "depenses": _depenses,
    "paiements": _paiements,
    "contrats": _contrats,
    "echeances": _echeances,
    "prospection": _prospection,
}


def cartes(societe, module):
    """Les 4 cartes du module (liste vide si aucune ou en cas d'erreur)."""
    fn = MODULES.get(module)
    if fn is None or societe is None:
        return []
    try:
        return fn(societe)
    except Exception:  # une stat ne doit jamais casser la page
        import logging

        logging.getLogger(__name__).warning("Stats %s indisponibles", module, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Finances (mois sélectionné) et activité des employés
# ---------------------------------------------------------------------------

def cartes_finances(historique, kpis, cumuls):
    """`historique` : 6 mois, le plus récent en premier (format de la vue)."""
    h = list(reversed(historique))
    rec = [float(x["recettes"]) for x in h]
    dep = [float(x["depenses"]) for x in h]
    sal = [float(x["salaires"]) for x in h]
    sol = [float(x["solde"]) for x in h]

    def courbe_cumul(serie, total):
        base = float(total) - sum(serie)
        out, acc = [], base
        for v in serie:
            acc += v
            out.append(acc)
        return out

    solde = float(kpis["solde"])
    solde_g = float(cumuls["solde"])
    du_mois = [
        carte("Recettes du mois", argent(kpis["recettes"]), "wallet", "fin-rec", rec,
              "vert", tendance_pct(rec), "paiements clients confirmés", "pos"),
        carte("Dépenses du mois", argent(kpis["depenses"]), "card", "fin-dep", dep,
              "rouge", tendance_pct(dep, inverse=True), "dépenses confirmées", "neg"),
        carte("Salaires payés", argent(kpis["salaires"]), "users", "fin-sal", sal,
              "indigo", tendance_pct(sal, inverse=True),
              f"{argent(kpis['salaires_prevus'])} encore à payer", "neg"),
        carte("Solde du mois", argent(solde), "chart", "fin-sol", sol,
              "vert" if solde >= 0 else "rouge", tendance_pct(sol),
              "recettes − dépenses − salaires", "pos" if solde >= 0 else "neg"),
    ]
    cumules = [
        carte("Recettes cumulées", argent(cumuls["recettes"]), "wallet", "fin-crec",
              courbe_cumul(rec, cumuls["recettes"]), "vert", note="toutes périodes",
              value_class="pos"),
        carte("Dépenses cumulées", argent(cumuls["depenses"]), "card", "fin-cdep",
              courbe_cumul(dep, cumuls["depenses"]), "rouge", note="toutes périodes",
              value_class="neg"),
        carte("Salaires cumulés", argent(cumuls["salaires"]), "users", "fin-csal",
              courbe_cumul(sal, cumuls["salaires"]), "indigo", note="toutes périodes",
              value_class="neg"),
        carte("Solde global", argent(solde_g), "chart", "fin-csol",
              courbe_cumul(sol, cumuls["solde"]), "vert" if solde_g >= 0 else "rouge",
              note="depuis le début", value_class="pos" if solde_g >= 0 else "neg"),
    ]
    return du_mois, cumules
