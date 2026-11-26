"""Abonnements SaaS : forfait choisi sur le site vitrine → société créée → paiement → activation.

Cycle de vie d'un ``AbonnementSociete`` :

- ``demarrer``  : à la création de la société. Toute demande reste EN_ATTENTE ;
                  l'équipe active l'abonnement depuis le back-office (action manuelle).
- ``activer``   : action manuelle dans le back-office uniquement
                  → ACTIF pour la durée du forfait (prolonge si déjà actif).
- ``suspendre`` / ``prolonger`` : actions du back-office.
- ``courant``   : dernier abonnement de la société ; passe à EXPIRE une fois la date dépassée.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import AbonnementSociete, Forfait, ModePaiement, PaiementAbonnement

log = logging.getLogger(__name__)


def montant_local(montant, devise, monnaie):
    """Montant (entier) à encaisser dans la monnaie de l'opérateur Mobile Money.

    Prix en USD converti avec ``settings.TAUX_USD`` ; même monnaie → inchangé.
    Retourne None si aucun taux n'est connu pour cette monnaie.
    """
    if devise == monnaie:
        return int(round(float(montant)))
    if devise == "USD":
        taux = getattr(settings, "TAUX_USD", {}).get(monnaie)
        return int(round(float(montant) * float(taux))) if taux else None
    return None


def equivalents_locaux(forfait):
    """{monnaie: montant} pour les monnaies des opérateurs Mobile Money (affichage indicatif)."""
    from .kpay import PROVIDERS

    out = {}
    for _code, _nom, _pays, monnaie in PROVIDERS:
        m = montant_local(forfait.prix, forfait.devise, monnaie)
        if m is not None:
            out[monnaie] = m
    return out


def forfaits_publics():
    return Forfait.objects.filter(actif=True).order_by("prix", "nom")


def forfait_par_defaut():
    return forfaits_publics().filter(prix=0).first() or forfaits_publics().first()


def courant(societe):
    """Abonnement le plus récent de la société (statut EXPIRE appliqué si la date est passée)."""
    abo = societe.abonnements.select_related("forfait").order_by("-created_at", "-pk").first()
    if abo and abo.statut == "ACTIF" and abo.date_fin < timezone.localdate():
        abo.statut = "EXPIRE"
        abo.save(update_fields=["statut"])
    return abo


def expirer_les_echus():
    """Passe à EXPIRE tous les abonnements actifs dont la date de fin est dépassée."""
    return AbonnementSociete.objects.filter(statut="ACTIF", date_fin__lt=timezone.localdate()).update(statut="EXPIRE")


def lien_paiement(abonnement, request=None):
    chemin = reverse("abonnement_payer", args=[abonnement.jeton])
    if request is not None:
        return request.build_absolute_uri(chemin)
    return getattr(settings, "SITE_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/") + chemin


def _envoyer(sujet, gabarit, contexte, destinataire):
    """E-mail HTML + texte ; une erreur d'envoi est journalisée sans bloquer le parcours."""
    if not destinataire:
        return False
    try:
        html = render_to_string(f"emails/{gabarit}.html", contexte)
        texte = render_to_string(f"emails/{gabarit}.txt", contexte)
        send_mail(sujet, texte, settings.DEFAULT_FROM_EMAIL, [destinataire], html_message=html)
        return True
    except Exception:  # SMTP indisponible : le lien reste accessible depuis l'application
        log.exception("Envoi de l'e-mail « %s » impossible", sujet)
        return False


def demarrer(societe, forfait, request=None, ancien=None):
    """Crée l'abonnement initial (ou une demande de changement d'offre si ``ancien``) + e-mail.

    Toute demande reste EN_ATTENTE jusqu'à son activation par l'équipe dans le back-office.
    """
    forfait = forfait or forfait_par_defaut()
    if forfait is None:
        return None
    aujourd_hui = timezone.localdate()
    gratuit = not forfait.prix
    # Aucune activation automatique, même pour un forfait gratuit.
    abo = AbonnementSociete.objects.create(
        societe=societe, forfait=forfait, prix_paye=forfait.prix, ancien_forfait=ancien,
        date_debut=aujourd_hui, date_fin=aujourd_hui, statut="EN_ATTENTE",
    )
    createur = societe.createur
    if ancien is not None:
        _envoyer(
            f"Demande de changement d'offre — {societe.nom}",
            "demande_offre",
            {"societe": societe, "abonnement": abo, "forfait": forfait, "ancien": ancien, "gratuit": gratuit,
             "lien": lien_paiement(abo, request), "prenom": getattr(createur, "prenom", "")},
            getattr(createur, "email", ""),
        )
        return abo
    _envoyer(
        f"Votre société « {societe.nom} » a été créée",
        "societe_creee",
        {"societe": societe, "abonnement": abo, "forfait": forfait, "gratuit": gratuit,
         "lien": lien_paiement(abo, request), "prenom": getattr(createur, "prenom", ""),
         "app": request.build_absolute_uri(reverse("gestion:dashboard")) if request else ""},
        getattr(createur, "email", ""),
    )
    return abo


def activer(abonnement, paiement=None, request=None, encaisse=False, mode="Espèces"):
    """Active (ou prolonge) l'abonnement pour la durée de son forfait.

    Appel uniquement depuis le back-office : aucune activation automatique.
    - remplace l'abonnement actif précédent de la société (changement d'offre) ;
    - ``encaisse`` : l'équipe a reçu le paiement hors ligne → un paiement confirmé est
      enregistré (comptabilisé dans les ventes) s'il n'en existe pas déjà un.
    """
    aujourd_hui = timezone.localdate()
    (abonnement.societe.abonnements.filter(statut="ACTIF").exclude(pk=abonnement.pk)
     .update(statut="EXPIRE", date_fin=aujourd_hui))
    if encaisse and paiement is None and abonnement.forfait.prix and not abonnement.paiements.filter(
            statut="CONFIRME", date_paiement__gte=abonnement.date_debut).exists():
        paiement = declarer_paiement(abonnement, mode, reference="Encaissé (back-office)")
    base = abonnement.date_fin if abonnement.statut == "ACTIF" and abonnement.date_fin >= aujourd_hui else aujourd_hui
    if abonnement.statut != "ACTIF":
        abonnement.date_debut = aujourd_hui
    abonnement.date_fin = base + timedelta(days=abonnement.forfait.duree_jours)
    abonnement.statut = "ACTIF"
    abonnement.prix_paye = abonnement.forfait.prix
    abonnement.save(update_fields=["date_debut", "date_fin", "statut", "prix_paye"])
    if paiement is not None and paiement.statut != "CONFIRME":
        paiement.statut = "CONFIRME"
        paiement.date_paiement = aujourd_hui
        paiement.save(update_fields=["statut", "date_paiement"])
    societe = abonnement.societe
    _envoyer(
        f"Abonnement {abonnement.forfait.nom} activé — {societe.nom}",
        "abonnement_active",
        {"societe": societe, "abonnement": abonnement, "prenom": getattr(societe.createur, "prenom", ""),
         "app": request.build_absolute_uri(reverse("gestion:dashboard")) if request else ""},
        getattr(societe.createur, "email", ""),
    )
    return abonnement


def refuser(abonnement):
    """Refuse une demande (nouvelle offre ou changement) : l'abonnement actif éventuel est conservé."""
    abonnement.statut = "ANNULE"
    abonnement.save(update_fields=["statut"])
    abonnement.paiements.filter(statut="EN_ATTENTE").update(statut="ANNULE")
    return abonnement


def demandes_en_attente():
    """Demandes à traiter : toutes les offres en attente d'activation manuelle."""
    return (AbonnementSociete.objects.filter(statut="EN_ATTENTE")
            .select_related("societe", "societe__createur", "forfait", "ancien_forfait")
            .order_by("-created_at", "-pk"))


def ventes(periode="mois", jour=None):
    """Ventes encaissées (paiements confirmés) sur un jour, un mois ou une année.

    Retourne total, nombre, panier moyen, comparaison avec la période précédente,
    série détaillée (heures / jours / mois), répartition par forfait et liste des paiements.
    """
    import calendar
    from datetime import date

    jour = jour or timezone.localdate()
    if periode == "jour":
        debut, fin = jour, jour + timedelta(days=1)
        prec_debut, prec_fin = jour - timedelta(days=1), jour
        libelle = jour.strftime("%d/%m/%Y")
    elif periode == "annee":
        debut, fin = date(jour.year, 1, 1), date(jour.year + 1, 1, 1)
        prec_debut, prec_fin = date(jour.year - 1, 1, 1), debut
        libelle = str(jour.year)
    else:
        periode = "mois"
        debut = jour.replace(day=1)
        fin = (debut + timedelta(days=32)).replace(day=1)
        prec_debut, prec_fin = (debut - timedelta(days=1)).replace(day=1), debut
        noms = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août",
                "Septembre", "Octobre", "Novembre", "Décembre"]
        libelle = f"{noms[debut.month - 1]} {debut.year}"
    qs = (PaiementAbonnement.objects.filter(statut="CONFIRME", date_paiement__gte=debut, date_paiement__lt=fin)
          .select_related("abonnement__societe", "abonnement__forfait", "mode_paiement").order_by("-date_paiement", "-pk"))
    paiements = list(qs)
    total = sum(float(p.montant) for p in paiements)
    precedent = sum(float(p.montant) for p in PaiementAbonnement.objects.filter(
        statut="CONFIRME", date_paiement__gte=prec_debut, date_paiement__lt=prec_fin))
    if periode == "annee":
        mois_c = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
        labels, valeurs = mois_c, [0.0] * 12
        for p in paiements:
            valeurs[p.date_paiement.month - 1] += float(p.montant)
    elif periode == "mois":
        n = calendar.monthrange(debut.year, debut.month)[1]
        labels, valeurs = [str(i) for i in range(1, n + 1)], [0.0] * n
        for p in paiements:
            valeurs[p.date_paiement.day - 1] += float(p.montant)
    else:
        labels, valeurs = ["Total"], [total]
    par_forfait = {}
    for p in paiements:
        nom = p.abonnement.forfait.nom
        par_forfait[nom] = par_forfait.get(nom, 0.0) + float(p.montant)
    evolution = None if not precedent else round((total - precedent) / precedent * 100)
    return {
        "periode": periode, "jour": jour, "libelle": libelle, "debut": debut, "fin": fin,
        "total": total, "nombre": len(paiements), "moyenne": total / len(paiements) if paiements else 0,
        "precedent": precedent, "evolution": evolution,
        "labels": labels, "valeurs": valeurs,
        "par_forfait": sorted(par_forfait.items(), key=lambda x: -x[1]), "paiements": paiements[:50],
        "total_global": sum(float(p.montant) for p in PaiementAbonnement.objects.filter(statut="CONFIRME")),
    }


def suspendre(abonnement):
    abonnement.statut = "SUSPENDU"
    abonnement.save(update_fields=["statut"])
    return abonnement


def declarer_paiement(abonnement, mode_nom, reference="", telephone="", kpay_id=""):
    """Paiement déclaré par le client (en attente de validation ou de confirmation Mobile Money)."""
    mode = ModePaiement.objects.filter(nom__iexact=mode_nom).first() or ModePaiement.objects.first()
    return PaiementAbonnement.objects.create(
        abonnement=abonnement, montant=abonnement.forfait.prix, date_paiement=timezone.localdate(),
        mode_paiement=mode, reference=(reference or "")[:150], telephone=(telephone or "")[:30],
        kpay_id=(kpay_id or "")[:100], statut="EN_ATTENTE",
    )


def statistiques(mois=12):
    """Indicateurs et séries pour le back-office (inscriptions, revenus, forfaits)."""
    from .models import Societe

    expirer_les_echus()
    aujourd_hui = timezone.localdate()
    debuts = []
    d = aujourd_hui.replace(day=1)
    for _ in range(mois):
        debuts.append(d)
        d = (d - timedelta(days=1)).replace(day=1)
    debuts.reverse()
    noms = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    inscriptions, revenus = [], []
    for i, debut in enumerate(debuts):
        fin = debuts[i + 1] if i + 1 < len(debuts) else (debut + timedelta(days=32)).replace(day=1)
        inscriptions.append(Societe.objects.filter(created_at__date__gte=debut, created_at__date__lt=fin).count())
        revenus.append(float(sum(p.montant for p in PaiementAbonnement.objects.filter(
            statut="CONFIRME", date_paiement__gte=debut, date_paiement__lt=fin))))
    abos = AbonnementSociete.objects.all()
    # Abonnement le plus récent de chaque société pour la répartition par forfait
    # Abonnement de référence de chaque société : l'ACTIF s'il y en a un (une demande de
    # changement d'offre en attente ne doit pas faire disparaître l'abonné), sinon le plus récent
    derniers = {}
    for a in abos.select_related("forfait").order_by("societe_id", "-created_at", "-pk"):
        actuel = derniers.get(a.societe_id)
        if actuel is None or (a.statut == "ACTIF" and actuel.statut != "ACTIF"):
            derniers[a.societe_id] = a
    repartition = {}
    for a in derniers.values():
        if a.statut == "ACTIF":
            repartition[a.forfait.nom] = repartition.get(a.forfait.nom, 0) + 1
    debut_mois = aujourd_hui.replace(day=1)
    return {
        "labels": [noms[d.month - 1] for d in debuts],
        "inscriptions": inscriptions,
        "revenus": revenus,
        "repartition": sorted(repartition.items(), key=lambda x: -x[1]),
        "kpi": {
            "societes": Societe.objects.count(),
            "actifs": sum(1 for a in derniers.values() if a.statut == "ACTIF"),
            "payants": sum(1 for a in derniers.values() if a.statut == "ACTIF" and a.prix_paye > 0),
            "en_attente": abos.filter(statut="EN_ATTENTE").count(),
            "expires": sum(1 for a in derniers.values() if a.statut in ("EXPIRE", "SUSPENDU")),
            "a_valider": PaiementAbonnement.objects.filter(statut="EN_ATTENTE").count(),
            "revenus_mois": float(sum(p.montant for p in PaiementAbonnement.objects.filter(
                statut="CONFIRME", date_paiement__gte=debut_mois))),
            "revenus_total": float(sum(p.montant for p in PaiementAbonnement.objects.filter(statut="CONFIRME"))),
            "expirent_bientot": abos.filter(statut="ACTIF", date_fin__gte=aujourd_hui,
                                            date_fin__lte=aujourd_hui + timedelta(days=7)).count(),
        },
        "sans_abonnement": Societe.objects.filter(~Q(pk__in=[s for s in derniers])).count(),
    }


# ---------------------------------------------------------------------------
# Alertes de fin d'abonnement (créateur) et restriction de l'accès (employés)
# ---------------------------------------------------------------------------

JOURS_ALERTE = 7  # le créateur est prévenu à partir de 7 jours avant la fin


def etat(societe):
    """État de l'abonnement d'une société pour l'interface.

    Retourne None pour une société sans aucun abonnement (anciennes sociétés : rien ne change),
    sinon un dict : abonnement, forfait, jours_restants, niveau parmi
    « ok » / « bientot » (≤ 7 jours) / « expire » / « suspendu » / « en_attente », restreinte (bool).
    """
    if societe is None:
        return None
    aujourd_hui = timezone.localdate()
    abos = list(societe.abonnements.select_related("forfait").order_by("-created_at", "-pk")[:10])
    if not abos:
        return None
    actif = next((a for a in abos if a.statut == "ACTIF"), None)
    if actif and actif.date_fin < aujourd_hui:
        actif.statut = "EXPIRE"
        actif.save(update_fields=["statut"])
        actif = None
    if actif:
        jours = (actif.date_fin - aujourd_hui).days
        return {"abonnement": actif, "forfait": actif.forfait, "jours_restants": jours,
                "niveau": "bientot" if jours <= JOURS_ALERTE else "ok", "restreinte": False}
    dernier = next((a for a in abos if a.statut in ("EXPIRE", "SUSPENDU")), None)
    if dernier is None:
        # Jamais activé : la demande attend une validation manuelle de l'équipe.
        return {"abonnement": abos[0], "forfait": abos[0].forfait, "jours_restants": None,
                "niveau": "en_attente", "restreinte": True}
    # Un renouvellement en attente de paiement : le lien de paiement à proposer est le sien
    renouvellement = next((a for a in abos if a.statut == "EN_ATTENTE"), None)
    return {"abonnement": renouvellement or dernier, "forfait": dernier.forfait,
            "jours_restants": (dernier.date_fin - aujourd_hui).days,
            "niveau": "suspendu" if dernier.statut == "SUSPENDU" else "expire", "restreinte": True}


def notifier_fin(societe, e=None):
    """Ajoute dans la cloche du créateur (module « abonnement », invisible des employés)
    une notification par palier : 7 jours, 3 jours, veille, jour J, expiré. Sans doublon."""
    e = e or etat(societe)
    if not e or e["niveau"] not in ("bientot", "expire", "suspendu"):
        return None
    from .models import ActivitePlateforme
    from .services import journaliser

    jours = e["jours_restants"]
    if e["niveau"] == "suspendu":
        libelle = f"Abonnement {e['forfait'].nom} suspendu"
    elif e["niveau"] == "expire":
        libelle = f"Abonnement {e['forfait'].nom} expiré"
    else:
        palier = 7 if jours > 3 else (3 if jours > 1 else jours)
        libelle = {7: "se termine dans 7 jours", 3: "se termine dans 3 jours", 1: "se termine demain",
                   0: "se termine aujourd'hui"}.get(palier, f"se termine dans {jours} jours")
        libelle = f"Abonnement {e['forfait'].nom} : {libelle}"
    depuis = e["abonnement"].date_debut
    if ActivitePlateforme.objects.filter(societe=societe, module="abonnement", libelle=libelle,
                                         created_at__date__gte=depuis).exists():
        return None
    return journaliser(societe, "VALIDATION", "abonnement", libelle,
                       "Réabonnez-vous pour continuer à profiter de tous nos services.")
