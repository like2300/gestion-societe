"""Rapports des pages Finances : PDF (graphiques + analyse) et Excel.

Un même jeu de données sert aux deux formats :

    collecter(societe, module, periode) -> {
        titre, sous_titre, periode_label, indicateurs[{label, valeur}],
        evolution {titre, graphique, labels, series[{nom, valeurs}]},
        repartition {titre, labels, valeurs},
        analyse [phrases], colonnes [(titre, type)], lignes [[...]], total {col: valeur}
    }

Modules : finances (vue d'ensemble), paiements, echeances, depenses, salaires, contrats.
Périodes : mois, trimestre, 12m (défaut), annee.
"""

import io
from collections import OrderedDict, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import (
    ContratEmploye,
    Facture,
    DepenseSociete,
    EcheancePaiement,
    PaiementClient,
    PaiementSalaire,
)

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]
MOIS_COURT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.",
              "août", "sept.", "oct.", "nov.", "déc."]

MODULES = {
    "finances": "Synthèse financière",
    "paiements": "Rapport des paiements clients",
    "factures": "Rapport de facturation",
    "echeances": "Rapport des échéances",
    "depenses": "Rapport des dépenses",
    "salaires": "Rapport des salaires",
    "contrats": "Rapport des contrats",
}
PERIODES = OrderedDict([
    ("mois", "Ce mois"),
    ("trimestre", "3 derniers mois"),
    ("12m", "12 derniers mois"),
    ("annee", "Année en cours"),
])


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------


def D(v):
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal(0)


def fcfa(v):
    n = int(round(D(v)))
    return f"{n:,}".replace(",", " ") + " FCFA"


def pct(a, b):
    """Variation en % de b vers a (None si b nul)."""
    a, b = D(a), D(b)
    if not b:
        return None
    return float((a - b) * 100 / abs(b))


def _ajout_mois(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def bornes(periode, aujourdhui=None):
    """(début inclus, fin exclue, libellé) de la période demandée."""
    aujourdhui = aujourdhui or timezone.localdate()
    debut_mois = aujourdhui.replace(day=1)
    fin = _ajout_mois(debut_mois, 1)
    if periode == "mois":
        debut = debut_mois
        lib = f"{MOIS_FR[debut.month - 1].capitalize()} {debut.year}"
    elif periode == "trimestre":
        debut = _ajout_mois(debut_mois, -2)
    elif periode == "annee":
        debut = date(aujourdhui.year, 1, 1)
        lib = f"Année {aujourdhui.year}"
    else:
        debut = _ajout_mois(debut_mois, -11)
    if periode not in ("mois", "annee"):
        lib = (f"{MOIS_COURT[debut.month - 1]} {debut.year} – "
               f"{MOIS_COURT[_ajout_mois(fin, -1).month - 1]} {_ajout_mois(fin, -1).year}")
    return debut, fin, lib


def liste_mois(debut, fin):
    mois, d = [], debut
    while d < fin:
        mois.append(d)
        d = _ajout_mois(d, 1)
    return mois


def lib_mois(d, court=True):
    return f"{(MOIS_COURT if court else MOIS_FR)[d.month - 1]} {str(d.year)[2:] if court else d.year}"


def par_mois(qs, champ_date, champ_montant, mois):
    """Somme mensuelle (liste alignée sur `mois`)."""
    cumul = defaultdict(Decimal)
    for d, m in qs.values_list(champ_date, champ_montant):
        if d:
            cumul[(d.year, d.month)] += D(m)
    return [cumul[(x.year, x.month)] for x in mois]


def _top(compteur, n=6):
    """Garde les n premiers postes, le reste en « Autres »."""
    items = sorted(compteur.items(), key=lambda kv: kv[1], reverse=True)
    if len(items) > n:
        autres = sum(v for _, v in items[n - 1:])
        items = items[:n - 1] + [("Autres", autres)]
    return items


def _phrase_variation(nom, actuel, precedent):
    v = pct(actuel, precedent)
    if v is None:
        return f"{nom} : {fcfa(actuel)} sur la période (pas de point de comparaison sur la période précédente)."
    sens = "en hausse" if v > 0.5 else "en baisse" if v < -0.5 else "stable"
    detail = f" de {abs(v):.0f} %" if sens != "stable" else ""
    return f"{nom} : {fcfa(actuel)} sur la période, {sens}{detail} par rapport à la période précédente ({fcfa(precedent)})."


def _phrase_pic(nom, mois, valeurs):
    if not valeurs or not any(valeurs):
        return None
    i_max = max(range(len(valeurs)), key=lambda i: valeurs[i])
    txt = f"Le mois le plus élevé pour {nom} est {lib_mois(mois[i_max], False)} ({fcfa(valeurs[i_max])})"
    non_nuls = [i for i, v in enumerate(valeurs) if v]
    if len(non_nuls) > 1:
        i_min = min(non_nuls, key=lambda i: valeurs[i])
        txt += f", le plus faible {lib_mois(mois[i_min], False)} ({fcfa(valeurs[i_min])})"
    return txt + "."


def _phrase_part(titre, items):
    total = sum(v for _, v in items)
    if not items or not total:
        return None
    lab, v = items[0]
    return f"{titre} : « {lab} » représente {float(v * 100 / total):.0f} % du total ({fcfa(v)})."


# ---------------------------------------------------------------------------
# Collecte par module
# ---------------------------------------------------------------------------


def collecter(societe, module, periode="12m"):
    if module not in MODULES:
        module = "finances"
    if periode not in PERIODES:
        periode = "12m"
    debut, fin, lib = bornes(periode)
    duree = len(liste_mois(debut, fin))
    p_debut = _ajout_mois(debut, -duree)
    mois = liste_mois(debut, fin)
    labels = [lib_mois(m) for m in mois]
    data = globals()["_" + module](societe, debut, fin, p_debut, mois, labels)
    data.update({
        "module": module,
        "titre": MODULES[module],
        "periode": periode,
        "periode_label": lib,
        "societe": societe.nom,
        "debut": debut,
        "fin": fin - timedelta(days=1),
    })
    return data


def _finances(societe, debut, fin, p_debut, mois, labels):
    pai = PaiementClient.objects.filter(projet__societe=societe, statut="CONFIRME")
    dep = DepenseSociete.objects.filter(societe=societe).exclude(statut="ANNULE")
    rec_m = par_mois(pai.filter(date_paiement__gte=debut, date_paiement__lt=fin), "date_paiement", "montant", mois)
    dep_m = par_mois(dep.filter(date_depense__gte=debut, date_depense__lt=fin), "date_depense", "montant", mois)
    sal_m = par_mois(dep.filter(date_depense__gte=debut, date_depense__lt=fin, paiement_salaire__isnull=False),
                     "date_depense", "montant", mois)
    rec, depn = sum(rec_m), sum(dep_m)
    rec_p = D(pai.filter(date_paiement__gte=p_debut, date_paiement__lt=debut).aggregate(t=Sum("montant"))["t"])
    dep_p = D(dep.filter(date_depense__gte=p_debut, date_depense__lt=debut).aggregate(t=Sum("montant"))["t"])
    solde = rec - depn
    marge = float(solde * 100 / rec) if rec else None

    rep = defaultdict(Decimal)
    for nom, m in dep.filter(date_depense__gte=debut, date_depense__lt=fin).values_list("type_depense__nom", "montant"):
        rep[nom or "Autre"] += D(m)
    rep_items = _top(rep)

    analyse = [
        _phrase_variation("Recettes encaissées", rec, rec_p),
        _phrase_variation("Dépenses", depn, dep_p),
        (f"Le solde de la période est {'positif' if solde >= 0 else 'négatif'} : {fcfa(solde)}"
         + (f", soit une marge de {marge:.0f} % des recettes." if marge is not None else ".")),
        (f"Les salaires pèsent {float(sum(sal_m) * 100 / depn):.0f} % des dépenses ({fcfa(sum(sal_m))})."
         if depn else None),
        _phrase_part("Premier poste de dépense", rep_items),
        _phrase_pic("les recettes", mois, rec_m),
    ]
    mois_negatifs = [lib_mois(m, False) for m, r, d in zip(mois, rec_m, dep_m) if d > r]
    if mois_negatifs:
        analyse.append(f"Mois en déficit (dépenses > recettes) : {', '.join(mois_negatifs)}.")
    return {
        "sous_titre": "Recettes, dépenses et solde",
        "indicateurs": [
            {"label": "Recettes", "valeur": fcfa(rec)},
            {"label": "Dépenses", "valeur": fcfa(depn)},
            {"label": "Solde", "valeur": fcfa(solde)},
            {"label": "Marge", "valeur": f"{marge:.0f} %" if marge is not None else "—"},
        ],
        "evolution": {"titre": "Recettes et dépenses par mois", "graphique": "barres", "labels": labels,
                      "series": [{"nom": "Recettes", "valeurs": rec_m}, {"nom": "Dépenses", "valeurs": dep_m}]},
        "evolution2": {"titre": "Solde mensuel", "graphique": "ligne", "labels": labels,
                       "series": [{"nom": "Solde", "valeurs": [r - d for r, d in zip(rec_m, dep_m)]}]},
        "repartition": {"titre": "Répartition des dépenses", "labels": [k for k, _ in rep_items],
                        "valeurs": [v for _, v in rep_items]},
        "analyse": [a for a in analyse if a],
        "colonnes": [("Mois", "texte"), ("Recettes", "montant"), ("Dépenses", "montant"),
                     ("dont salaires", "montant"), ("Solde", "montant")],
        "lignes": [[lib_mois(m, False).capitalize(), r, d, s, r - d]
                   for m, r, d, s in zip(mois, rec_m, dep_m, sal_m)],
        "total": {1: rec, 2: depn, 3: sum(sal_m), 4: solde},
    }


def _paiements(societe, debut, fin, p_debut, mois, labels):
    base = PaiementClient.objects.filter(projet__societe=societe).select_related(
        "projet", "projet__client", "mode_paiement")
    qs = base.filter(date_paiement__gte=debut, date_paiement__lt=fin).order_by("-date_paiement")
    conf = qs.filter(statut="CONFIRME")
    total = D(conf.aggregate(t=Sum("montant"))["t"])
    attente = D(qs.filter(statut="EN_ATTENTE").aggregate(t=Sum("montant"))["t"])
    prec = D(base.filter(statut="CONFIRME", date_paiement__gte=p_debut, date_paiement__lt=debut)
             .aggregate(t=Sum("montant"))["t"])
    nb = conf.count()
    serie = par_mois(conf, "date_paiement", "montant", mois)
    rep = defaultdict(Decimal)
    for p in conf:
        rep[p.projet.client.nom if p.projet and p.projet.client else "—"] += D(p.montant)
    rep_items = _top(rep)
    analyse = [
        _phrase_variation("Encaissements confirmés", total, prec),
        f"{nb} paiement(s) confirmé(s), pour un montant moyen de {fcfa(total / nb if nb else 0)}.",
        _phrase_part("Premier client", rep_items),
        _phrase_pic("les encaissements", mois, serie),
        (f"{fcfa(attente)} restent en attente de confirmation." if attente else None),
    ]
    return {
        "sous_titre": "Encaissements clients",
        "indicateurs": [
            {"label": "Total encaissé", "valeur": fcfa(total)},
            {"label": "Paiements confirmés", "valeur": str(nb)},
            {"label": "Montant moyen", "valeur": fcfa(total / nb if nb else 0)},
            {"label": "En attente", "valeur": fcfa(attente)},
        ],
        "evolution": {"titre": "Encaissements par mois", "graphique": "barres", "labels": labels,
                      "series": [{"nom": "Encaissé", "valeurs": serie}]},
        "repartition": {"titre": "Répartition par client", "labels": [k for k, _ in rep_items],
                        "valeurs": [v for _, v in rep_items]},
        "analyse": [a for a in analyse if a],
        "colonnes": [("Date", "date"), ("Client", "texte"), ("Projet", "texte"), ("Mode", "texte"),
                     ("Référence", "texte"), ("Statut", "texte"), ("Montant", "montant")],
        "lignes": [[p.date_paiement, p.projet.client.nom if p.projet and p.projet.client else "—",
                    p.projet.nom if p.projet else "—", p.mode_paiement.nom if p.mode_paiement else "—",
                    p.reference or "", p.get_statut_display(), D(p.montant)] for p in qs],
        "total": {6: D(qs.aggregate(t=Sum("montant"))["t"])},
    }


def _factures(societe, debut, fin, p_debut, mois, labels):
    base = Facture.objects.filter(societe=societe).exclude(statut__in=["ANNULEE", "BROUILLON"])
    qs = base.filter(date_emission__gte=debut, date_emission__lt=fin).select_related("client").order_by("-date_emission")
    aujourdhui = timezone.localdate()
    facture = D(qs.aggregate(t=Sum("total_ttc"))["t"])
    payees = qs.filter(statut="PAYEE")
    encaisse = D(payees.aggregate(t=Sum("total_ttc"))["t"])
    attente = qs.filter(statut="EMISE")
    retard = attente.filter(date_echeance__lt=aujourdhui)
    prec = D(base.filter(date_emission__gte=p_debut, date_emission__lt=debut).aggregate(t=Sum("total_ttc"))["t"])
    s_fac = par_mois(qs, "date_emission", "total_ttc", mois)
    s_pay = par_mois(payees, "date_emission", "total_ttc", mois)
    rep = defaultdict(Decimal)
    for f in qs:
        rep[f.client_nom or (f.client.nom if f.client else "—")] += D(f.total_ttc)
    rep_items = _top(rep)
    taux = float(encaisse * 100 / facture) if facture else None
    delais = [(f.date_paiement - f.date_emission).days for f in payees if f.date_paiement and f.date_emission]
    analyse = [
        _phrase_variation("Montant facturé", facture, prec),
        (f"{payees.count()} facture(s) payée(s) pour {fcfa(encaisse)}"
         + (f" — taux d'encaissement : {taux:.0f} %." if taux is not None else ".")),
        (f"{retard.count()} facture(s) en retard pour {fcfa(retard.aggregate(t=Sum('total_ttc'))['t'])} : à relancer."
         if retard.exists() else "Aucune facture en retard de paiement."),
        (f"Délai moyen de paiement : {sum(delais) / len(delais):.0f} jour(s)." if delais else None),
        _phrase_part("Premier client facturé", rep_items),
        _phrase_pic("la facturation", mois, s_fac),
    ]
    return {
        "sous_titre": "Factures émises et encaissements",
        "indicateurs": [
            {"label": "Facturé", "valeur": fcfa(facture)},
            {"label": "Encaissé", "valeur": fcfa(encaisse)},
            {"label": "À encaisser", "valeur": fcfa(attente.aggregate(t=Sum("total_ttc"))["t"])},
            {"label": "Factures émises", "valeur": str(qs.count())},
        ],
        "evolution": {"titre": "Facturé et encaissé par mois", "graphique": "barres", "labels": labels,
                      "series": [{"nom": "Facturé", "valeurs": s_fac}, {"nom": "Payé", "valeurs": s_pay}]},
        "repartition": {"titre": "Répartition par client", "labels": [k for k, _ in rep_items],
                        "valeurs": [v for _, v in rep_items]},
        "analyse": [a for a in analyse if a],
        "colonnes": [("Numéro", "texte"), ("Date", "date"), ("Client", "texte"), ("Échéance", "date"),
                     ("Statut", "texte"), ("HT", "montant"), ("TTC", "montant")],
        "lignes": [[f.numero, f.date_emission, f.client_nom or "—", f.date_echeance,
                    "En retard" if f.en_retard else f.get_statut_display(), D(f.total_ht), D(f.total_ttc)]
                   for f in qs],
        "total": {5: D(qs.aggregate(t=Sum("total_ht"))["t"]), 6: facture},
    }


def _echeances(societe, debut, fin, p_debut, mois, labels):
    base = EcheancePaiement.objects.filter(projet__societe=societe).select_related("projet", "projet__client")
    qs = base.filter(date_prevue__gte=debut, date_prevue__lt=fin).order_by("date_prevue")
    aujourdhui = timezone.localdate()
    prevu = D(qs.aggregate(t=Sum("montant_prevu"))["t"])
    paye = D(qs.filter(statut="PAYEE").aggregate(t=Sum("montant_prevu"))["t"])
    retard_qs = qs.exclude(statut="PAYEE").filter(date_prevue__lt=aujourdhui)
    retard = D(retard_qs.aggregate(t=Sum("montant_prevu"))["t"])
    taux = float(paye * 100 / prevu) if prevu else None
    s_prevu = par_mois(qs, "date_prevue", "montant_prevu", mois)
    s_paye = par_mois(qs.filter(statut="PAYEE"), "date_prevue", "montant_prevu", mois)
    rep = defaultdict(Decimal)
    for e in qs:
        st = e.get_statut_display()
        if e.statut != "PAYEE" and e.date_prevue < aujourdhui:
            st = "Retard"
        rep[st] += D(e.montant_prevu)
    rep_items = sorted(rep.items(), key=lambda kv: kv[1], reverse=True)
    prochaines = base.exclude(statut="PAYEE").filter(date_prevue__gte=aujourdhui).order_by("date_prevue")[:3]
    analyse = [
        f"{qs.count()} échéance(s) prévue(s) sur la période pour {fcfa(prevu)}, dont {fcfa(paye)} encaissés"
        + (f" (taux de recouvrement : {taux:.0f} %)." if taux is not None else "."),
        (f"{retard_qs.count()} échéance(s) en retard pour {fcfa(retard)} : à relancer en priorité."
         if retard else "Aucune échéance en retard sur la période."),
        _phrase_pic("les échéances prévues", mois, s_prevu),
    ]
    if prochaines:
        analyse.append("Prochaines échéances : " + "; ".join(
            f"{e.projet.client.nom if e.projet and e.projet.client else e.projet} — {fcfa(e.montant_prevu)} le {e.date_prevue:%d/%m/%Y}"
            for e in prochaines) + ".")
    return {
        "sous_titre": "Plan d'encaissement des projets",
        "indicateurs": [
            {"label": "Total prévu", "valeur": fcfa(prevu)},
            {"label": "Encaissé", "valeur": fcfa(paye)},
            {"label": "Reste à encaisser", "valeur": fcfa(prevu - paye)},
            {"label": "En retard", "valeur": fcfa(retard)},
        ],
        "evolution": {"titre": "Prévu et encaissé par mois", "graphique": "barres", "labels": labels,
                      "series": [{"nom": "Prévu", "valeurs": s_prevu}, {"nom": "Encaissé", "valeurs": s_paye}]},
        "repartition": {"titre": "Répartition par statut", "labels": [k for k, _ in rep_items],
                        "valeurs": [v for _, v in rep_items]},
        "analyse": [a for a in analyse if a],
        "colonnes": [("Date prévue", "date"), ("Client", "texte"), ("Projet", "texte"), ("N°", "texte"),
                     ("Statut", "texte"), ("Montant", "montant")],
        "lignes": [[e.date_prevue, e.projet.client.nom if e.projet and e.projet.client else "—",
                    e.projet.nom if e.projet else "—", f"#{e.numero_echeance}",
                    "Retard" if e.statut != "PAYEE" and e.date_prevue < aujourdhui else e.get_statut_display(),
                    D(e.montant_prevu)] for e in qs],
        "total": {5: prevu},
    }


def _depenses(societe, debut, fin, p_debut, mois, labels):
    base = DepenseSociete.objects.filter(societe=societe).exclude(statut="ANNULE").select_related("type_depense")
    qs = base.filter(date_depense__gte=debut, date_depense__lt=fin).order_by("-date_depense")
    total = D(qs.aggregate(t=Sum("montant"))["t"])
    prec = D(base.filter(date_depense__gte=p_debut, date_depense__lt=debut).aggregate(t=Sum("montant"))["t"])
    serie = par_mois(qs, "date_depense", "montant", mois)
    rep = defaultdict(Decimal)
    for nom, m in qs.values_list("type_depense__nom", "montant"):
        rep[nom or "Autre"] += D(m)
    rep_items = _top(rep)
    plus = qs.order_by("-montant").first()
    nb_mois = len([v for v in serie if v]) or 1
    analyse = [
        _phrase_variation("Dépenses", total, prec),
        f"Moyenne mensuelle : {fcfa(total / nb_mois)} sur {nb_mois} mois actif(s).",
        _phrase_part("Premier poste", rep_items),
        (f"Plus grosse dépense : « {plus.nom} » ({fcfa(plus.montant)}) le {plus.date_depense:%d/%m/%Y}." if plus else None),
        _phrase_pic("les dépenses", mois, serie),
    ]
    return {
        "sous_titre": "Charges de la société",
        "indicateurs": [
            {"label": "Total dépensé", "valeur": fcfa(total)},
            {"label": "Nombre de dépenses", "valeur": str(qs.count())},
            {"label": "Moyenne mensuelle", "valeur": fcfa(total / nb_mois)},
            {"label": "Postes de dépense", "valeur": str(len(rep))},
        ],
        "evolution": {"titre": "Dépenses par mois", "graphique": "barres", "labels": labels,
                      "series": [{"nom": "Dépenses", "valeurs": serie}]},
        "repartition": {"titre": "Répartition par type", "labels": [k for k, _ in rep_items],
                        "valeurs": [v for _, v in rep_items]},
        "analyse": [a for a in analyse if a],
        "colonnes": [("Date", "date"), ("Libellé", "texte"), ("Type", "texte"), ("Statut", "texte"),
                     ("Montant", "montant")],
        "lignes": [[d.date_depense, d.nom, d.type_depense.nom if d.type_depense else "—",
                    d.get_statut_display(), D(d.montant)] for d in qs],
        "total": {4: total},
    }


def _salaires(societe, debut, fin, p_debut, mois, labels):
    base = PaiementSalaire.objects.filter(employe__societe=societe).select_related(
        "employe", "employe__fonction")
    qs = base.filter(periode_mois__gte=debut, periode_mois__lt=fin).order_by("-periode_mois", "employe__nom")
    du = D(qs.aggregate(t=Sum("montant_du"))["t"])
    paye = D(qs.aggregate(t=Sum("montant_paye"))["t"])
    prec = D(base.filter(periode_mois__gte=p_debut, periode_mois__lt=debut).aggregate(t=Sum("montant_paye"))["t"])
    s_du = par_mois(qs, "periode_mois", "montant_du", mois)
    s_paye = par_mois(qs, "periode_mois", "montant_paye", mois)
    rep = defaultdict(Decimal)
    for s in qs:
        rep[s.employe.fonction.nom if s.employe.fonction_id else "Sans fonction"] += D(s.montant_du)
    rep_items = _top(rep)
    nb_emp = qs.values("employe").distinct().count()
    retard = qs.exclude(statut="PAYE").filter(date_prevue__lt=timezone.localdate()).count()
    analyse = [
        f"Masse salariale due sur la période : {fcfa(du)} pour {nb_emp} employé(s) ; {fcfa(paye)} versés"
        + (f" ({float(paye * 100 / du):.0f} %)." if du else "."),
        _phrase_variation("Salaires versés", paye, prec),
        (f"{fcfa(du - paye)} restent à payer." if du > paye else "Tous les salaires de la période sont réglés."),
        (f"{retard} salaire(s) dépassent leur date prévue sans être payés." if retard else None),
        _phrase_part("Fonction la plus coûteuse", rep_items),
    ]
    return {
        "sous_titre": "Masse salariale et paiements du personnel",
        "indicateurs": [
            {"label": "Masse salariale due", "valeur": fcfa(du)},
            {"label": "Versé", "valeur": fcfa(paye)},
            {"label": "Reste à payer", "valeur": fcfa(du - paye)},
            {"label": "Employés", "valeur": str(nb_emp)},
        ],
        "evolution": {"titre": "Dû et versé par mois", "graphique": "barres", "labels": labels,
                      "series": [{"nom": "Dû", "valeurs": s_du}, {"nom": "Versé", "valeurs": s_paye}]},
        "repartition": {"titre": "Masse salariale par fonction", "labels": [k for k, _ in rep_items],
                        "valeurs": [v for _, v in rep_items]},
        "analyse": [a for a in analyse if a],
        "colonnes": [("Période", "texte"), ("Employé", "texte"), ("Fonction", "texte"), ("Date prévue", "date"),
                     ("Statut", "texte"), ("Dû", "montant"), ("Versé", "montant")],
        "lignes": [[lib_mois(s.periode_mois, False).capitalize(), f"{s.employe.prenom} {s.employe.nom}",
                    s.employe.fonction.nom if s.employe.fonction_id else "—", s.date_prevue,
                    s.get_statut_display(), D(s.montant_du), D(s.montant_paye)] for s in qs],
        "total": {5: du, 6: paye},
    }


def _contrats(societe, debut, fin, p_debut, mois, labels):
    base = ContratEmploye.objects.filter(employe__societe=societe).select_related("employe", "type_contrat")
    qs = base.filter(date_debut__lt=fin).exclude(date_fin__lt=debut).order_by("-date_debut")
    actifs = base.filter(statut="ACTIF")
    masse = D(actifs.aggregate(t=Sum("salaire_contractuel"))["t"])
    aujourdhui = timezone.localdate()
    expirent = actifs.filter(date_fin__gte=aujourdhui, date_fin__lte=aujourdhui + timedelta(days=60))
    nouveaux = [0] * len(mois)
    for c in base.filter(date_debut__gte=debut, date_debut__lt=fin):
        for i, m in enumerate(mois):
            if c.date_debut.year == m.year and c.date_debut.month == m.month:
                nouveaux[i] += 1
    rep = defaultdict(Decimal)
    for c in actifs:
        rep[c.type_contrat.nom if c.type_contrat else "—"] += 1
    rep_items = sorted(rep.items(), key=lambda kv: kv[1], reverse=True)
    analyse = [
        f"{actifs.count()} contrat(s) actif(s) pour une masse salariale contractuelle de {fcfa(masse)} par mois.",
        f"{sum(nouveaux)} nouveau(x) contrat(s) signé(s) sur la période.",
        (f"{expirent.count()} contrat(s) arrivent à échéance dans les 60 jours : "
         + ", ".join(f"{c.employe.prenom} {c.employe.nom} ({c.date_fin:%d/%m/%Y})" for c in expirent[:5]) + "."
         if expirent.exists() else "Aucun contrat n'arrive à échéance dans les 60 prochains jours."),
    ]
    if rep_items:
        lab, n = rep_items[0]
        analyse.append(f"Type de contrat le plus fréquent : {lab} ({int(n)} sur {actifs.count()}).")
    return {
        "sous_titre": "Contrats de travail du personnel",
        "indicateurs": [
            {"label": "Contrats actifs", "valeur": str(actifs.count())},
            {"label": "Masse salariale / mois", "valeur": fcfa(masse)},
            {"label": "Nouveaux (période)", "valeur": str(sum(nouveaux))},
            {"label": "Expirent < 60 j", "valeur": str(expirent.count())},
        ],
        "evolution": {"titre": "Nouveaux contrats par mois", "graphique": "barres", "labels": labels,
                      "series": [{"nom": "Nouveaux contrats", "valeurs": nouveaux}], "unite": "contrats"},
        "repartition": {"titre": "Contrats actifs par type", "labels": [k for k, _ in rep_items],
                        "valeurs": [v for _, v in rep_items]},
        "analyse": [a for a in analyse if a],
        "colonnes": [("Employé", "texte"), ("Type", "texte"), ("Début", "date"), ("Fin", "date"),
                     ("Statut", "texte"), ("Salaire", "montant")],
        "lignes": [[f"{c.employe.prenom} {c.employe.nom}", c.type_contrat.nom if c.type_contrat else "—",
                    c.date_debut, c.date_fin, c.get_statut_display(), D(c.salaire_contractuel)] for c in qs],
        "total": {},
    }


# ---------------------------------------------------------------------------
# PDF (moteur de rapport existant : couverture, indicateurs, sections, graphiques)
# ---------------------------------------------------------------------------


def _cellule_md(v, type_):
    if v is None or v == "":
        return "—"
    if type_ == "montant":
        return fcfa(v)
    if type_ == "date":
        return v.strftime("%d/%m/%Y")
    return str(v).replace("|", "/")


def _tableau_md(data, max_lignes=60):
    cols = data["colonnes"]
    lignes = data["lignes"]
    md = ["| " + " | ".join(c for c, _ in cols) + " |", "|" + "---|" * len(cols)]
    for l in lignes[:max_lignes]:
        md.append("| " + " | ".join(_cellule_md(v, t) for v, (_, t) in zip(l, cols)) + " |")
    if data.get("total"):
        tot = ["**Total**"] + [""] * (len(cols) - 1)
        for i, v in data["total"].items():
            tot[i] = f"**{fcfa(v)}**"
        md.append("| " + " | ".join(tot) + " |")
    note = ""
    if len(lignes) > max_lignes:
        note = f"\n\n_{len(lignes) - max_lignes} ligne(s) supplémentaire(s) dans l'export Excel._"
    if not lignes:
        return "_Aucune donnée sur la période._"
    return "\n".join(md) + note


def _num(v):
    return float(D(v))


def pdf(data, accent_hex, auteur="", logo=None):
    from .rapport_pdf import document_pdf

    evo = dict(data["evolution"])
    evo["series"] = [{"nom": s["nom"], "valeurs": [_num(v) for v in s["valeurs"]]} for s in evo["series"]]
    sections = [
        {"titre": "Analyse", "contenu": "\n".join(f"- {a}" for a in data["analyse"])},
        {"titre": "Évolution", "contenu": f"Période : {data['periode_label']}.", "graphique": evo},
    ]
    if data.get("evolution2"):
        e2 = dict(data["evolution2"])
        e2["series"] = [{"nom": s["nom"], "valeurs": [_num(v) for v in s["valeurs"]]} for s in e2["series"]]
        sections.append({"titre": "Tendance", "contenu": "", "graphique": e2})
    rep = data.get("repartition") or {}
    if rep.get("labels") and any(rep.get("valeurs") or []):
        sections.append({"titre": rep["titre"], "contenu": "", "graphique": {
            "titre": rep["titre"], "graphique": "anneau", "labels": rep["labels"],
            "series": [{"nom": rep["titre"], "valeurs": [_num(v) for v in rep["valeurs"]]}]}})
    sections.append({"titre": "Détail", "contenu": _tableau_md(data)})
    document = {
        "titre": data["titre"],
        "sous_titre": f"{data['sous_titre']} — {data['periode_label']}",
        "societe": data["societe"],
        "auteur": auteur,
        "date": timezone.localdate().strftime("%d/%m/%Y"),
        "indicateurs": data["indicateurs"],
        "sections": sections,
    }
    return document_pdf(document, accent_hex=accent_hex, type_document="Rapport financier",
                        redacteur="Gestionnaire de société", generateur="Rapport généré automatiquement",
                        logo=logo)


# ---------------------------------------------------------------------------
# Excel (openpyxl) : Synthèse (indicateurs + analyse + graphiques), Par mois, Détail
# ---------------------------------------------------------------------------


def excel(data, accent_hex="#0284c7", logo_png=None):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.chart.label import DataLabelList
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    acc = accent_hex.lstrip("#").upper()
    FMT = '# ##0 "FCFA";[Red]-# ##0 "FCFA"'
    titre_f = Font(name="Calibri", size=18, bold=True, color="0F172A")
    sous_f = Font(name="Calibri", size=10, color="64748B")
    th_f = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    th_fill = PatternFill("solid", fgColor=acc)
    zebra = PatternFill("solid", fgColor="F8FAFC")
    kpi_fill = PatternFill("solid", fgColor="F1F5F9")
    trait = Side(style="thin", color="E2E8F0")
    bas = Border(bottom=trait)

    wb = Workbook()

    # ---- Synthèse ----
    ws = wb.active
    ws.title = "Synthèse"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    for col in "BCDEFGHI":
        ws.column_dimensions[col].width = 16
    ws["B2"] = data["titre"]
    ws["B2"].font = titre_f
    ws["B3"] = f"{data['societe']} · {data['sous_titre']} · {data['periode_label']}"
    ws["B3"].font = sous_f
    ws["B4"] = f"Édité le {timezone.localdate():%d/%m/%Y}"
    ws["B4"].font = sous_f
    if logo_png:
        _logo_excel(ws, logo_png, "G2")
    ws.row_dimensions[2].height = 26
    for i, k in enumerate(data["indicateurs"]):
        c = 2 + i * 2
        lab = ws.cell(row=6, column=c, value=k["label"])
        val = ws.cell(row=7, column=c, value=k["valeur"])
        ws.merge_cells(start_row=6, start_column=c, end_row=6, end_column=c + 1)
        ws.merge_cells(start_row=7, start_column=c, end_row=7, end_column=c + 1)
        lab.font = Font(size=9, color="64748B")
        val.font = Font(size=14, bold=True, color="0F172A" if i else acc)
        for r in (6, 7):
            for cc in (c, c + 1):
                ws.cell(row=r, column=cc).fill = kpi_fill
        lab.alignment = val.alignment = Alignment(indent=1)
    ws.row_dimensions[7].height = 24
    ws["B9"] = "Analyse"
    ws["B9"].font = Font(size=12, bold=True, color="0F172A")
    r = 10
    for a in data["analyse"]:
        ws.cell(row=r, column=2, value="•  " + a).alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
        ws.row_dimensions[r].height = 30
        r += 1
    graph_ligne = r + 1

    # ---- Par mois ----
    wm = wb.create_sheet("Par mois")
    wm.sheet_view.showGridLines = False
    evo = data["evolution"]
    entetes = ["Mois"] + [s["nom"] for s in evo["series"]]
    if data.get("evolution2"):
        entetes += [s["nom"] for s in data["evolution2"]["series"]]
    for j, h in enumerate(entetes, start=1):
        c = wm.cell(row=1, column=j, value=h)
        c.font, c.fill = th_f, th_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        wm.column_dimensions[get_column_letter(j)].width = 20 if j > 1 else 14
    wm.row_dimensions[1].height = 22
    series = [s["valeurs"] for s in evo["series"]] + (
        [s["valeurs"] for s in data["evolution2"]["series"]] if data.get("evolution2") else [])
    montant = evo.get("unite") is None
    for i, lab in enumerate(evo["labels"], start=2):
        wm.cell(row=i, column=1, value=lab)
        for j, s in enumerate(series, start=2):
            c = wm.cell(row=i, column=j, value=float(D(s[i - 2])))
            if montant:
                c.number_format = FMT
            if i % 2:
                c.fill = zebra
        wm.cell(row=i, column=1).border = bas
    n = len(evo["labels"])
    tot_row = n + 2
    wm.cell(row=tot_row, column=1, value="Total").font = Font(bold=True)
    for j in range(2, len(entetes) + 1):
        col = get_column_letter(j)
        c = wm.cell(row=tot_row, column=j, value=f"=SUM({col}2:{col}{n + 1})")
        c.font = Font(bold=True)
        if montant:
            c.number_format = FMT
        c.border = Border(top=Side(style="medium", color="0F172A"))
    wm.freeze_panes = "B2"

    bar = BarChart()
    bar.type = "col"
    bar.style = 10
    bar.title = evo["titre"]
    bar.y_axis.title = "FCFA" if montant else (evo.get("unite") or "")
    bar.y_axis.majorGridlines = None
    bar.height, bar.width = 8, 22
    bar.add_data(Reference(wm, min_col=2, max_col=1 + len(evo["series"]), min_row=1, max_row=n + 1),
                 titles_from_data=True)
    bar.set_categories(Reference(wm, min_col=1, min_row=2, max_row=n + 1))
    palette = [acc, "F59E0B", "10B981", "EF4444"]
    for k, s in enumerate(bar.series):
        s.graphicalProperties.solidFill = palette[k % len(palette)]
        s.graphicalProperties.line.solidFill = palette[k % len(palette)]
    ws.add_chart(bar, f"B{graph_ligne}")

    if data.get("evolution2"):
        ln = LineChart()
        ln.title = data["evolution2"]["titre"]
        ln.style = 12
        ln.height, ln.width = 8, 22
        c0 = 2 + len(evo["series"])
        ln.add_data(Reference(wm, min_col=c0, max_col=c0, min_row=1, max_row=n + 1), titles_from_data=True)
        ln.set_categories(Reference(wm, min_col=1, min_row=2, max_row=n + 1))
        ln.series[0].graphicalProperties.line.solidFill = acc
        ln.series[0].graphicalProperties.line.width = 28000
        ln.series[0].smooth = True
        ws.add_chart(ln, f"B{graph_ligne + 17}")

    # ---- Répartition ----
    rep = data.get("repartition") or {}
    if rep.get("labels"):
        wr = wb.create_sheet("Répartition")
        wr.sheet_view.showGridLines = False
        for j, h in enumerate(["Poste", "Valeur", "Part"], start=1):
            c = wr.cell(row=1, column=j, value=h)
            c.font, c.fill = th_f, th_fill
        wr.column_dimensions["A"].width = 30
        wr.column_dimensions["B"].width = 20
        wr.column_dimensions["C"].width = 10
        m = len(rep["labels"])
        for i, (lab, v) in enumerate(zip(rep["labels"], rep["valeurs"]), start=2):
            wr.cell(row=i, column=1, value=lab)
            c = wr.cell(row=i, column=2, value=float(D(v)))
            if montant or data["module"] != "contrats":
                c.number_format = FMT if data["module"] != "contrats" else "0"
            p = wr.cell(row=i, column=3, value=f"=B{i}/SUM($B$2:$B${m + 1})")
            p.number_format = "0%"
        pie = PieChart()
        pie.title = rep["titre"]
        pie.height, pie.width = 9, 13
        pie.add_data(Reference(wr, min_col=2, min_row=1, max_row=m + 1), titles_from_data=True)
        pie.set_categories(Reference(wr, min_col=1, min_row=2, max_row=m + 1))
        pie.dataLabels = DataLabelList()
        pie.dataLabels.showPercent = True
        wr.add_chart(pie, "E2")
        ws.add_chart(_copie_pie(pie, wr, m, rep["titre"]), f"B{graph_ligne + (34 if data.get('evolution2') else 17)}")

    # ---- Détail ----
    wd = wb.create_sheet("Détail")
    if logo_png:
        wd.row_dimensions[1].height = 22
    wd.sheet_view.showGridLines = False
    cols = data["colonnes"]
    for j, (h, t) in enumerate(cols, start=1):
        c = wd.cell(row=1, column=j, value=h)
        c.font, c.fill = th_f, th_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        wd.column_dimensions[get_column_letter(j)].width = 18 if t != "texte" else 26
    wd.row_dimensions[1].height = 22
    for i, ligne in enumerate(data["lignes"], start=2):
        for j, (v, (_, t)) in enumerate(zip(ligne, cols), start=1):
            if t == "montant":
                v = float(D(v))
            c = wd.cell(row=i, column=j, value=v if v not in (None, "") else None)
            if t == "montant":
                c.number_format = FMT
            elif t == "date" and v:
                c.number_format = "DD/MM/YYYY"
            c.border = bas
            if i % 2:
                c.fill = zebra
    nl = len(data["lignes"])
    if nl and data.get("total"):
        r = nl + 2
        wd.cell(row=r, column=1, value="Total").font = Font(bold=True)
        for j in data["total"]:
            col = get_column_letter(j + 1)
            c = wd.cell(row=r, column=j + 1, value=f"=SUBTOTAL(9,{col}2:{col}{nl + 1})")
            c.font = Font(bold=True)
            c.number_format = FMT
            c.border = Border(top=Side(style="medium", color="0F172A"))
    if nl:
        wd.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{nl + 1}"
    wd.freeze_panes = "A2"

    for feuille in wb.worksheets:
        feuille.sheet_properties.tabColor = acc
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def _copie_pie(pie, wr, m, titre):
    from openpyxl.chart import PieChart, Reference
    from openpyxl.chart.label import DataLabelList

    p = PieChart()
    p.title = titre
    p.height, p.width = 9, 13
    p.add_data(Reference(wr, min_col=2, min_row=1, max_row=m + 1), titles_from_data=True)
    p.set_categories(Reference(wr, min_col=1, min_row=2, max_row=m + 1))
    p.dataLabels = DataLabelList()
    p.dataLabels.showPercent = True
    return p


def _logo_excel(ws, logo_png, ancre, h_max=56, w_max=170):
    """Insère le logo (PNG) dans la feuille, mis à l'échelle."""
    try:
        from openpyxl.drawing.image import Image as XLImage
        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(logo_png)) as im:
            w, h = im.size
        img = XLImage(io.BytesIO(logo_png))
        echelle = min(h_max / h, w_max / w, 1.0) if h and w else 1.0
        img.width, img.height = int(w * echelle), int(h * echelle)
        ws.add_image(img, ancre)
    except Exception:
        pass


def nom_fichier(data, ext):
    return f"rapport-{data['module']}-{data['debut']:%Y%m}-{data['fin']:%Y%m}.{ext}"
