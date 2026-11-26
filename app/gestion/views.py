import json
import logging
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db.models import Count, Prefetch, Q, Sum
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.functional import SimpleLazyObject
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import ai
from . import abonnements as abonnements_service
from . import contrat_pdf
from . import fichiers_prives
from . import ia_agent
from . import google_workspace
from . import stats
from .ai import build_system_prompt, call_groq, get_module_stats, user_module_keys
from .connecteurs import (
    AuthType,
    CATEGORIE_LABELS,
    charger_json,
    get_connecteur_class,
    tout_connecteurs,
)
from .connecteurs.providers import GoogleMeet
from .crud import CRUD_CONFIG
from .forms import (
    ClientForm,
    EmployeForm,
    ProjetForm,
    ReunionForm,
    SalaireForm,
    SocieteConfigForm,
    SocieteCreationForm,
    UserProfilForm,
)
from .models import (
    ClientDocument,
    Connecteur,
    Fonction,
    TypeClient,
    ConnecteurEvenement,
    ConnecteurSyncLog,
    ContratEmploye,
    DemandeAdhesion,
    DepenseSociete,
    EcheancePaiement,
    Employe,
    EmployeDocument,
    EquipeConversation,
    EquipeGroupe,
    EquipeGroupeMembre,
    EquipeMessage,
    EmployePresence,
    Finance,
    IaConversation,
    IaMessage,
    KpayOperation,
    Facture,
    LigneFacture,
    ModePaiement,
    PaiementClient,
    PaiementSalaire,
    PROSPECTION_STATUT_CHOICES,
    ProjetChef,
    ProspectionClient,
    Reunion,
    Role,
    Societe,
    SocieteDocument,
    STATUT_TACHE_CHOICES,
    PRIORITE_TACHE_CHOICES,
    Tache,
    TacheEvolution,
    TacheLivrable,
    TacheObjectif,
    Rappel,
)
from . import services
from . import kpay
from .pdf import pdf_from_sections
from . import logo_societe
from . import geographie
from . import rapport_pdf

COULEUR_HEX = {
    "SKY": "#0284c7",
    "BLUE": "#2563eb",
    "INDIGO": "#4f46e5",
    "VIOLET": "#7c3aed",
    "EMERALD": "#059669",
    "ORANGE": "#ea580c",
    "ROSE": "#e11d48",
    "SLATE": "#334155",
}

from .perm import DEFAULT_EMPLOYE_PERMS, EMPLOYE_PERM_MODULES


def _store_upload(upload, folder, base_name):
    ext = os.path.splitext(upload.name)[1].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base_name.lower()).strip("-") or "fichier"
    return default_storage.save(
        f"{folder}/{slug}-{uuid.uuid4().hex[:8]}{ext}",
        upload,
    )


def _bounce_inactive(request):
    """Déconnecte un compte non ACTIF et le renvoie vers la connexion."""
    logout(request)
    return redirect(reverse("account_login") + "?inactive=1")


def _est_compte_social(user):
    """Vrai si le compte est relié à un fournisseur social (Google…)."""
    manager = getattr(user, "socialaccount_set", None)
    if manager is None:
        return False
    return manager.exists()


def _url_sans_societe(user):
    """Destination d'un compte connecté qui n'a pas encore de société.

    - Une demande/invitation d'équipe en attente → écran « rejoindre ».
    - Compte « employé »                        → écran « rejoindre une
      société » : il rejoint une société existante, il n'en crée pas.
    - Compte social (Google…)                   → son profil, sans imposer la
      création d'une société.
    - Sinon (inscription email)                 → création de la société.
    """
    if DemandeAdhesion.objects.filter(user=user, statut="EN_ATTENTE").exists():
        return "gestion:rejoindre_equipe"
    if services.est_compte_employe(user):
        return "gestion:rejoindre_equipe"
    if _est_compte_social(user):
        return "gestion:profil"
    return "gestion:societe_create"


def _accepter_invitation_adhesion(request, demande):
    """Un compte accepte une invitation d'équipe (fiche employé existante)."""
    employe = demande.employe
    if employe is not None and employe.compte_id not in (None, request.user.pk):
        # Fiche déjà reliée à un autre compte : invitation caduque.
        demande.statut = "REFUSEE"
        demande.save(update_fields=["statut", "updated_at"])
        return redirect("gestion:rejoindre_equipe")

    if employe is not None:
        employe.compte = request.user
        employe.save(update_fields=["compte"])
        services.rattacher_conversations_employe(employe, request.user)
        champs = []
        if not request.user.nom and employe.nom:
            request.user.nom = employe.nom
            champs.append("nom")
        if not request.user.prenom and employe.prenom:
            request.user.prenom = employe.prenom
            champs.append("prenom")
        if not request.user.telephone_1 and employe.telephone_1:
            request.user.telephone_1 = employe.telephone_1
            champs.append("telephone_1")
        if champs:
            request.user.save(update_fields=champs)

    demande.statut = "ACCEPTEE"
    demande.save(update_fields=["statut", "updated_at"])
    # Les autres demandes/invitations en attente sont closes.
    DemandeAdhesion.objects.filter(
        user=request.user, statut="EN_ATTENTE"
    ).exclude(pk=demande.pk).update(statut="REFUSEE")
    services.journaliser(
        demande.societe,
        "VALIDATION",
        "employes",
        f"{request.user.prenom} {request.user.nom}".strip() or request.user.email,
        "Nouvel employé a rejoint l'équipe",
        request.user,
    )
    return redirect("gestion:dashboard")


def _accepter_demande_adhesion(societe, demande, valideur=None):
    """Le créateur accepte une demande d'adhésion : crée/lie la fiche employé."""
    user = demande.user
    employe = demande.employe
    if employe is None:
        employe = Employe.objects.filter(
            societe=societe, email__iexact=user.email, compte__isnull=True
        ).first()
        if employe is None:
            employe = Employe(societe=societe)
        employe.nom = employe.nom or user.nom or ""
        employe.prenom = employe.prenom or user.prenom or ""
        employe.telephone_1 = employe.telephone_1 or user.telephone_1 or ""
        employe.email = employe.email or user.email
        if not employe.permissions:
            employe.permissions = list(DEFAULT_EMPLOYE_PERMS)
        employe.compte = user
        employe.save()
        services.rattacher_conversations_employe(employe, user)
        demande.employe = employe
        demande.save(update_fields=["employe"])
    else:
        employe.compte = user
        employe.save(update_fields=["compte"])
        services.rattacher_conversations_employe(employe, user)

    demande.statut = "ACCEPTEE"
    demande.save(update_fields=["statut", "updated_at"])
    # Le compte ne peut appartenir qu'à une seule société.
    DemandeAdhesion.objects.filter(user=user, statut="EN_ATTENTE").exclude(
        pk=demande.pk
    ).update(statut="REFUSEE")
    services.journaliser(
        societe,
        "VALIDATION",
        "employes",
        f"{user.prenom} {user.nom}".strip() or user.email,
        "Adhésion à l'équipe validée",
        valideur,
    )
    return redirect("gestion:dashboard")


def _month_bounds(periode):
    """Retourne (début, fin) du mois contenant `periode` (fin exclusive)."""
    debut = periode.replace(day=1)
    if debut.month == 12:
        fin = debut.replace(year=debut.year + 1, month=1, day=1)
    else:
        fin = debut.replace(month=debut.month + 1, day=1)
    return debut, fin


def _recalculer_finances(societe, periode):
    """Met à jour la synthèse financière du mois contenant `periode`."""
    if periode is None:
        return
    finance, _ = Finance.objects.get_or_create(
        societe=societe, periode=periode.replace(day=1)
    )
    finance.recalculer()


def _sync_depense_salaire(societe, salaire):
    """Comptabilise un salaire payé en dépense automatiquement (délégué aux services)."""
    services.sync_depense_salaire(societe, salaire)


@login_required
def societe_create(request):
    """Page de création de la première société après connexion."""
    if services.societe_pour_utilisateur(request.user) is not None:
        return redirect("gestion:dashboard")
    if services.est_compte_employe(request.user):
        # Un employé rejoint une société existante, il n'en crée pas.
        return redirect("gestion:rejoindre_equipe")
    if DemandeAdhesion.objects.filter(
        user=request.user, statut="EN_ATTENTE"
    ).exists():
        return redirect("gestion:rejoindre_equipe")
    form = SocieteCreationForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        societe = Societe.objects.create(
            nom=data["nom"],
            pays=data["pays"],
            slogan=data.get("slogan") or "",
            couleur=data["couleur"],
            logo=_store_upload(data["logo"], "societes/logos", data["nom"]),
            createur=request.user,
        )
        SocieteDocument.objects.create(
            societe=societe,
            type_document="PIECES_AUTHENTIQUES",
            numero_document=data["nom"],
            fichier=fichiers_prives.stocker(data["document"], "societes/documents", data["nom"]
            ),
        )
        services.journaliser(
            societe, "CREATION", "societe", societe.nom, "Création de la société", request.user
        )
        # Abonnement du forfait choisi sur le site (gratuit par défaut) + e-mail de confirmation
        from . import abonnements, site_public

        abo = abonnements.demarrer(societe, site_public.forfait_en_session(request), request)
        if abo is not None and abo.statut == "EN_ATTENTE":
            return redirect("abonnement_payer", jeton=abo.jeton)
        return redirect("gestion:dashboard")
    return render(request, "gestion/societe_create.html", {"form": form})


@login_required
def post_login_redirect(request):
    """Après connexion : super admin → /admin/, sinon société puis dashboard."""
    if getattr(request.user, "statut", "ACTIF") != "ACTIF":
        return _bounce_inactive(request)
    if request.user.is_superuser:
        if request.user.societes_creees.first() is not None:
            return redirect("gestion:dashboard")
        return redirect("backoffice:index")
    if services.societe_pour_utilisateur(request.user) is None:
        return redirect(_url_sans_societe(request.user))
    return redirect("gestion:dashboard")


@login_required
def rejoindre_equipe(request):
    """Écran « rejoindre une société » : invitations reçues et demandes envoyées.

    Un compte sans société y accède : il peut accepter/refuser une invitation
    ou demander à rejoindre une société existante de la plateforme. Un compte
    « employé » ne peut jamais créer de société.
    """
    if services.societe_pour_utilisateur(request.user) is not None:
        return redirect("gestion:dashboard")

    invitations = list(
        DemandeAdhesion.objects.filter(
            user=request.user, statut="EN_ATTENTE", origine="INVITATION"
        ).select_related("societe", "employe")
    )
    mes_demandes = list(
        DemandeAdhesion.objects.filter(user=request.user, origine="DEMANDE")
        .select_related("societe")
        .order_by("-created_at")
    )

    if request.method == "POST":
        action = request.POST.get("action")
        demande_id = request.POST.get("demande_id") or ""

        if action in ("rejoindre", "refuser"):
            demande = next(
                (d for d in invitations if str(d.pk) == demande_id), None
            )
            if demande is None:
                return redirect("gestion:rejoindre_equipe")
            if action == "refuser":
                demande.statut = "REFUSEE"
                demande.save(update_fields=["statut", "updated_at"])
                return redirect("gestion:rejoindre_equipe")
            return _accepter_invitation_adhesion(request, demande)

        if action == "demander":
            societe = Societe.objects.filter(
                pk=request.POST.get("societe_id") or 0
            ).first()
            if societe is not None and not DemandeAdhesion.objects.filter(
                user=request.user, societe=societe, statut="EN_ATTENTE"
            ).exists():
                demande, created = DemandeAdhesion.objects.get_or_create(
                    user=request.user,
                    societe=societe,
                    defaults={"statut": "EN_ATTENTE", "origine": "DEMANDE"},
                )
                if not created:
                    # Une demande refusée peut être renvoyée.
                    demande.origine = "DEMANDE"
                    demande.statut = "EN_ATTENTE"
                    demande.save(update_fields=["origine", "statut", "updated_at"])
            return redirect("gestion:rejoindre_equipe")

        if action == "annuler":
            demande = next(
                (
                    d
                    for d in mes_demandes
                    if str(d.pk) == demande_id and d.statut == "EN_ATTENTE"
                ),
                None,
            )
            if demande is not None:
                demande.statut = "REFUSEE"
                demande.save(update_fields=["statut", "updated_at"])
            return redirect("gestion:rejoindre_equipe")

        return redirect("gestion:rejoindre_equipe")

    deja_demande = {d.societe_id for d in mes_demandes if d.statut == "EN_ATTENTE"}
    deja_invite = {d.societe_id for d in invitations}
    societes = (
        Societe.objects.exclude(pk__in=deja_demande)
        .exclude(pk__in=deja_invite)
        .order_by("nom")
    )

    context = {
        "invitations": invitations,
        "mes_demandes": mes_demandes,
        "societes": societes,
        "est_compte_employe": services.est_compte_employe(request.user),
        "peut_creer_societe": not services.est_compte_employe(request.user),
    }
    return render(request, "gestion/rejoindre_equipe.html", context)


def _fins_de_mois(n=6):
    """Dernier jour de chacun des `n` derniers mois (le mois courant en dernier)."""
    aujourdhui = timezone.localdate()
    fins = []
    for i in range(n - 1, -1, -1):
        mois = aujourdhui.month - i
        annee = aujourdhui.year
        while mois <= 0:
            mois += 12
            annee -= 1
        suivant = date(annee + (1 if mois == 12 else 0), (mois % 12) + 1, 1)
        fins.append(suivant - timedelta(days=1))
    return fins


def _serie_cumulee(qs, champ, fins, datetime_champ=False):
    """Effectif cumulé de `qs` à la fin de chaque mois (pour les mini-courbes).

    Les lignes sans date sont comptées comme déjà présentes.
    """
    try:
        sans_date = qs.filter(**{champ + "__isnull": True}).count()
        suffixe = "__date__lte" if datetime_champ else "__lte"
        return [sans_date + qs.filter(**{champ + suffixe: fin}).count() for fin in fins]
    except Exception:
        return [0] * len(fins)


def _tendance(serie, unite="ce mois"):
    """(texte, sens) décrivant l'évolution du dernier mois d'une série."""
    if len(serie) < 2:
        return "", "flat"
    delta = serie[-1] - serie[-2]
    if delta > 0:
        return f"+{delta} {unite}", "up"
    if delta < 0:
        return f"{delta} {unite}", "down"
    return "Stable", "flat"


def _series_dashboard(societe, fins):
    """Séries mensuelles pour les cartes statistiques du tableau de bord."""
    employes = _serie_cumulee(societe.employes.all(), "date_recrutement", fins)
    clients = _serie_cumulee(societe.clients.all(), "created_at", fins, True)
    projets = _serie_cumulee(societe.projets.all(), "date_debut", fins)
    soldes = {f.periode.replace(day=1): float(f.solde or 0) for f in societe.finances.all()}
    solde = [soldes.get(fin.replace(day=1), 0.0) for fin in fins]
    return {"employes": employes, "clients": clients, "projets": projets, "solde": solde}


def _donut_familles(activite):
    """Segments d'anneau (somme = 100) : répartition de l'activité par famille."""
    familles = {}
    for barre in activite["bars"]:
        f = familles.setdefault(
            barre["family"],
            {"label": barre["family"], "color": barre["color"], "value": 0},
        )
        f["value"] += barre["value"]
    total = sum(f["value"] for f in familles.values())
    segments, decalage = [], 25.0
    for f in familles.values():
        part = f["value"] * 100 / total if total else 0
        segments.append(
            {
                **f,
                "pct": round(part),
                # Chaînes : évite la virgule décimale française dans le SVG.
                "dash": f"{part:.2f}",
                "gap": f"{100 - part:.2f}",
                "offset": f"{decalage:.2f}",
            }
        )
        decalage -= part
    return {"segments": segments, "total": total}


def _mon_espace(request, societe, modules):
    """Bloc personnel du tableau de bord : mes tâches, mes rendez-vous, mes groupes, mes raccourcis."""
    from .models import EvenementAgenda, Tache

    moi = services.employe_pour_utilisateur(request.user, societe)
    aujourd_hui = timezone.localdate()
    filtre_t = Q(assignee=moi) if moi else Q(pk__in=[])
    if services.est_createur(request.user, societe):
        filtre_t |= Q(cree_par=request.user)
    ouvertes = (Tache.objects.filter(societe=societe).filter(filtre_t)
                .exclude(statut__in=("TERMINEE", "ANNULEE")).select_related("assignee").distinct())
    retard = ouvertes.filter(echeance__lt=aujourd_hui)
    du_jour = ouvertes.filter(echeance=aujourd_hui)
    semaine = ouvertes.filter(echeance__gt=aujourd_hui, echeance__lte=aujourd_hui + timedelta(days=7))
    filtre_ev = Q(organisateur=request.user)
    if moi:
        filtre_ev |= Q(participants=moi)
    rdv = (EvenementAgenda.objects.filter(societe=societe, fin__gte=timezone.now()).filter(filtre_ev)
           .distinct().order_by("debut")[:4])
    groupes = services.groupes_visibles(request.user, societe).order_by("titre")[:4]
    peut_discuter = "employes" in modules
    raccourcis = [
        (cle, label, url) for cle, label, url in (
            ("taches", "Mes tâches", reverse("gestion:taches")),
            ("clients", "Clients", reverse("gestion:clients")),
            ("projets", "Projets", reverse("gestion:projets")),
            ("bureau", "Documents", reverse("gestion:bureau", args=["docs"])),
            ("finances", "Finances", reverse("gestion:finances")),
            ("factures", "Factures", reverse("gestion:factures")),
        ) if cle in modules
    ]
    return {
        "retard": retard.count(), "jour": du_jour.count(), "semaine": semaine.count(),
        "taches": list(ouvertes.order_by("echeance")[:5]),
        "rdv": [{"titre": e.titre, "debut": timezone.localtime(e.debut), "journee": e.journee_entiere, "lieu": e.lieu}
                for e in rdv],
        "groupes": [{"titre": g.titre, "url": (f"{reverse('gestion:employes')}?groupe={g.pk}" if peut_discuter
                                                else reverse("gestion:groupes_page"))} for g in groupes],
        "raccourcis": [{"label": "Planning", "url": reverse("gestion:planning")}]
                      + [{"label": label, "url": url} for _, label, url in raccourcis],
        "aujourd_hui": aujourd_hui,
    }


@login_required
def dashboard(request):
    """Tableau de bord de l'utilisateur connecté (tous les modules)."""
    if getattr(request.user, "statut", "ACTIF") != "ACTIF":
        return _bounce_inactive(request)
    if request.user.is_superuser:
        societe = request.user.societes_creees.first()
        if societe is None:
            return redirect("admin:index")
    else:
        societe = services.societe_pour_utilisateur(request.user)
        if societe is None:
            return redirect(_url_sans_societe(request.user))

    # Le créateur de la société (et lui seul) valide les demandes d'adhésion.
    est_proprietaire = not services.est_employe(request.user, societe)

    if request.method == "POST" and est_proprietaire:
        action = request.POST.get("action")
        if action in ("adhesion_accepter", "adhesion_refuser"):
            demande = (
                DemandeAdhesion.objects.filter(
                    pk=request.POST.get("demande_id") or 0,
                    societe=societe,
                    origine="DEMANDE",
                )
                .select_related("user", "employe")
                .first()
            )
            if demande is not None and demande.statut == "EN_ATTENTE":
                if action == "adhesion_refuser":
                    demande.statut = "REFUSEE"
                    demande.save(update_fields=["statut", "updated_at"])
                else:
                    _accepter_demande_adhesion(societe, demande, request.user)
            return redirect("gestion:dashboard")

    demandes_adhesion = (
        DemandeAdhesion.objects.filter(
            societe=societe, statut="EN_ATTENTE", origine="DEMANDE"
        )
        .select_related("user")
        .order_by("-created_at")
        if est_proprietaire
        else DemandeAdhesion.objects.none()
    )

    recettes = (
        PaiementClient.objects.filter(
            projet__societe=societe, statut="CONFIRME"
        ).aggregate(total=Sum("montant"))["total"]
        or 0
    )
    # Les dépenses générées par un salaire payé sont déjà comptées via
    # « salaires » (montant_paye) : on les exclut ici pour ne pas les doubler.
    depenses = (
        DepenseSociete.objects.filter(
            societe=societe, statut="CONFIRME", paiement_salaire__isnull=True
        ).aggregate(total=Sum("montant"))["total"]
        or 0
    )
    salaires = (
        PaiementSalaire.objects.filter(
            employe__societe=societe, statut="PAYE"
        ).aggregate(total=Sum("montant_paye"))["total"]
        or 0
    )
    solde = recettes - depenses - salaires
    nav_counts = _nav_counts(societe)
    modules_autorises = services.modules_autorises(request.user, societe)
    activite = _activite_plateforme(nav_counts, modules_autorises)
    fins = _fins_de_mois(6)
    series = _series_dashboard(societe, fins)
    tendances = {}
    for cle in ("employes", "clients", "projets"):
        texte, sens = _tendance(series[cle])
        tendances[cle] = {"texte": texte, "sens": sens}
    delta_solde = series["solde"][-1] - series["solde"][-2]
    tendances["solde"] = {
        "texte": f"{delta_solde:+,.0f}".replace(",", " ") + " ce mois",
        "sens": "up" if delta_solde > 0 else ("down" if delta_solde < 0 else "flat"),
    }
    return render(
        request,
        "gestion/dashboard.html",
        {
            "societe": societe,
            "accent": COULEUR_HEX.get(societe.couleur, "#0284c7"),
            "active": "dashboard",
            "nav_counts": nav_counts,
            "modules_autorises": modules_autorises,
            "est_employe": services.est_employe(request.user, societe),
            "est_proprietaire": est_proprietaire,
            **_espace_finances(modules_autorises, nav_counts, "dashboard"),
            "demandes_adhesion": demandes_adhesion,
            "mon_espace": _mon_espace(request, societe, modules_autorises),
            "abonnement": abonnements_service.courant(societe) if est_proprietaire else None,
            "activite": activite,
            "donut": _donut_familles(activite),
            "series": series,
            "tendances": tendances,
            "counts": {
                "employes": societe.employes.count(),
                "employes_actifs": societe.employes.filter(statut="ACTIF").count(),
                "employes_sans_contrat": sum(
                    1
                    for e in societe.employes.only("id")
                    if not e.contrats.exists()
                ),
                "employes_avec_contrat": societe.employes.filter(
                    contrats__isnull=False
                )
                .distinct()
                .count(),
                "clients": societe.clients.count(),
                "projets": societe.projets.count(),
                "projets_en_cours": societe.projets.filter(statut="EN_COURS").count(),
                "depenses": societe.depenses.count(),
                "documents": societe.documents.count(),
                "solde": solde,
            },
        },
    )


def _nav_counts(societe):
    """Compteurs pour les badges de la barre latérale."""
    return {
        "employes": societe.employes.count(),
        "clients": societe.clients.count(),
        "prospection": societe.prospections.count(),
        "projets": societe.projets.count(),
        "depenses": societe.depenses.count(),
        "salaires": PaiementSalaire.objects.filter(employe__societe=societe).count(),
        "paiements": PaiementClient.objects.filter(projet__societe=societe).count(),
        "factures": societe.factures.exclude(statut="ANNULEE").count(),
        "roles": societe.roles.count(),
        "fonctions": societe.fonctions.count(),
        "documents": societe.documents.count(),
        "contrats": ContratEmploye.objects.filter(employe__societe=societe).count(),
        "echeances": EcheancePaiement.objects.filter(projet__societe=societe).count(),
        "taches": Tache.objects.filter(
            societe=societe, statut__in=["A_FAIRE", "EN_COURS"]
        ).count(),
    }


def _activite_plateforme(nav_counts, autorises=None):
    """Données du diagramme en bâtons « Activité de la plateforme ».

    Une barre par module, alimentée par exactement les mêmes compteurs que
    la barre latérale (`_nav_counts`) : une seule source de vérité.
    Couleurs regroupées par famille pour donner du sens au graphique.
    Le paramètre `autorises` restreint le graphique aux modules accessibles
    au compte connecté (barre latérale identique).
    """
    familles = {
        "commercial": {"label": "Commercial", "color": "var(--accent)"},
        "rh": {"label": "Ressources humaines", "color": "#4f46e5"},
        "finance": {"label": "Dépenses", "color": "#e11d48"},
        "admin": {"label": "Administration", "color": "#64748b"},
    }
    modules = [
        ("employes", "Employés", "Employés", reverse("gestion:employes"), nav_counts["employes"], "rh"),
        ("clients", "Clients", "Clients", reverse("gestion:clients"), nav_counts["clients"], "commercial"),
        ("prospection", "Prospection", "Prospection", reverse("gestion:crud", args=["prospection"]), nav_counts["prospection"], "commercial"),
        ("projets", "Projets", "Projets", reverse("gestion:projets"), nav_counts["projets"], "commercial"),
        ("depenses", "Dépenses", "Dépenses", reverse("gestion:crud", args=["depenses"]), nav_counts["depenses"], "finance"),
        ("salaires", "Salaires", "Salaires", reverse("gestion:crud", args=["salaires"]), nav_counts["salaires"], "finance"),
        ("contrats", "Contrats", "Contrats", reverse("gestion:crud", args=["contrats"]), nav_counts["contrats"], "rh"),
        ("echeances", "Échéances", "Échéances", reverse("gestion:crud", args=["echeances"]), nav_counts["echeances"], "commercial"),
        ("paiements", "Paiements", "Paiements", reverse("gestion:crud", args=["paiements"]), nav_counts["paiements"], "commercial"),
        ("roles", "Rôles", "Rôles", reverse("gestion:crud", args=["roles"]), nav_counts["roles"], "admin"),
        ("fonctions", "Fonctions", "Fonctions", reverse("gestion:crud", args=["fonctions"]), nav_counts["fonctions"], "admin"),
        ("documents", "Documents", "Documents", reverse("gestion:crud", args=["documents"]), nav_counts["documents"], "admin"),
    ]
    if autorises is not None:
        autorises = set(autorises)
        modules = [m for m in modules if m[0] in autorises]
    max_valeur = max((m[4] for m in modules), default=0)
    # Échelle « propre » multiple de 4 → 4 intervalles toujours entiers.
    scale_max = max(4, -(-max_valeur // 4) * 4)
    bars = []
    for cle, label, short, url, valeur, famille in modules:
        pct = round(valeur * 100 / scale_max) if valeur else 0
        if valeur and pct < 3:
            pct = 3
        bars.append(
            {
                "label": label,
                "short": short,
                "url": url,
                "value": valeur,
                "pct": pct,
                "color": familles[famille]["color"],
                "family": familles[famille]["label"],
            }
        )
    ticks = [
        {"value": scale_max * p // 100, "pct": p}
        for p in (100, 75, 50, 25, 0)
    ]
    return {
        "bars": bars,
        "max": max_valeur,
        "scale_max": scale_max,
        "ticks": ticks,
        "familles": list(familles.values()),
        "total": sum(m[4] for m in modules),
    }


def _refus_lecture_seule(request):
    """Réponse à une tentative de modification sur un module ouvert en lecture seule."""
    msg = "Accès en lecture seule : vous ne pouvez pas modifier ce module."
    attend_json = ("json" in (request.headers.get("Accept", "") + request.content_type)
                   or request.headers.get("X-Requested-With") == "XMLHttpRequest")
    if attend_json:
        return JsonResponse({"ok": False, "error": msg, "erreur": msg}, status=403)
    messages.error(request, msg)
    retour = request.META.get("HTTP_REFERER") or reverse("gestion:dashboard")
    return redirect(retour)


def _societe_context(request, active, ecriture=None):
    """Retourne (societe, context) ou une réponse de redirection.

    ``ecriture`` : la requête modifie-t-elle le module ? Par défaut, toute requête
    autre que GET / HEAD / OPTIONS. Une écriture sur un module ouvert en lecture
    seule (permission « Lecture » de l'employé) est refusée ici, pour TOUTES les vues.
    Les vues qui envoient un POST sans modifier le module (messagerie, aperçu…)
    passent ``ecriture=False``.
    """
    if getattr(request.user, "statut", "ACTIF") != "ACTIF":
        return None, None, _bounce_inactive(request)
    if request.user.is_superuser:
        # Le superuser garde /admin/, sauf s'il est propriétaire d'une société :
        # il passe alors par l'application (créateur = accès complet).
        societe = request.user.societes_creees.first()
        if societe is None:
            return None, None, redirect("admin:index")
    else:
        # Rattachement automatique (session déjà ouverte) des fiches au même email.
        services.lier_comptes_utilisateur(request.user)
        societe = services.societe_pour_utilisateur(request.user)
        if societe is None:
            return None, None, redirect(_url_sans_societe(request.user))
    if not services.peut_acceder(request.user, societe, active):
        return None, None, redirect("gestion:dashboard")
    lecture_seule = services.en_lecture_seule(request.user, societe, active)
    if ecriture is None:
        ecriture = request.method not in ("GET", "HEAD", "OPTIONS")
    if lecture_seule and ecriture:
        return None, None, _refus_lecture_seule(request)
    context = {
        "lecture_seule": lecture_seule,
        "societe": societe,
        "accent": COULEUR_HEX.get(societe.couleur, "#0284c7"),
        "active": active,
        "nav_counts": _nav_counts(societe),
        "modules_autorises": services.modules_autorises(request.user, societe),
        "est_employe": services.est_employe(request.user, societe),
        "est_createur": services.est_createur(request.user, societe),
        "kpay_configuree": kpay.configuree(),
        "kpay_providers": kpay.PROVIDERS if kpay.configuree() else [],
        # Cartes statistiques du module (calculées seulement si la page les affiche).
        "stats_cartes": SimpleLazyObject(lambda: stats.cartes(societe, active)),
    }
    context.update(_espace_finances(context["modules_autorises"], context["nav_counts"], active))
    return societe, context, None


# Espace « Finances » : une seule entrée de menu, des onglets pour chaque page.
FINANCES_ONGLETS = (
    # (clé, onglet, route, argument, nom du dossier, icône, sous-titre)
    ("finances", "Vue d'ensemble", "gestion:finances", None, "Finances", "chart", "Synthèse & soldes"),
    ("paiements", "Paiements", "gestion:crud", "paiements", "Paiements", "wallet", "Encaissements clients"),
    ("factures", "Factures", "gestion:factures", None, "Factures", "list", "Facturation clients"),
    ("echeances", "Échéances", "gestion:crud", "echeances", "Échéances", "calendar", "À venir & encaissées"),
    ("depenses", "Dépenses", "gestion:crud", "depenses", "Dépenses", "card", "Charges enregistrées"),
    ("salaires", "Salaires", "gestion:crud", "salaires", "Salaires", "users", "Paiements du personnel"),
    # Onglet « Contrats » retiré : le contrat se gère dans la fiche employé (généré et imprimable).
)


# Espace « Équipe & clients » : employés, tâches, clients, projets.
EQUIPE_DOSSIERS = (
    ("employes", "Employés", "gestion:employes", None, "Employés", "users", "L'équipe de la société"),
    ("taches", "Tâches", "gestion:taches", None, "Tâches", "list", "À faire & en cours"),
    ("clients", "Clients", "gestion:clients", None, "Clients", "briefcase", "Portefeuille clients"),
    ("projets", "Projets", "gestion:projets", None, "Projets", "folder", "Réalisations clients"),
)


# Espace « Organisation » : rôles, fonctions, globe, profil.
ORGANISATION_DOSSIERS = (
    ("roles", "Rôles", "gestion:crud", "roles", "Rôles", "shield", "Permissions de l'équipe"),
    ("fonctions", "Fonctions", "gestion:crud", "fonctions", "Fonctions", "user", "Postes de travail"),
    ("globe", "Globe", "gestion:globe", None, "Globe", "target", "Activité dans le monde"),
    ("profil", "Mon profil", "gestion:profil", None, "Mon profil", "user", "Vos informations"),
)

# Espace « Ma société » : profil de l'entreprise + ses documents officiels.
SOCIETE_DOSSIERS = (
    ("societe", "Profil", "gestion:societe_profil", None, "Ma société", "building", "Identité & paramètres"),
    ("documents", "Documents", "gestion:crud", "documents", "Documents", "file", "Statuts, RCCM, attestations…"),
    ("modeles_contrat", "Modèles de contrat", "gestion:modeles_contrat", None, "Modèles de contrat", "file",
     "Contrats de travail à variables"),
    ("abonnement", "Mon abonnement", "gestion:mon_abonnement", None, "Mon abonnement", "card",
     "Offre, paiements, changement d'offre"),
)
# Dossiers dont l'accès suit la permission d'un autre module
PERMISSION_DOSSIER = {"modeles_contrat": "societe", "abonnement": "societe"}
PAGES_TOUJOURS = {"profil"}


def _dossiers(definition, autorises, nav_counts, active, sans_compteur=()):
    """Cartes « dossier » d'un espace, filtrées selon les permissions du compte."""
    out = []
    for cle, label, route, arg, nom, icone, sous_titre in definition:
        if PERMISSION_DOSSIER.get(cle, cle) not in (autorises or []) and cle not in PAGES_TOUJOURS:
            continue
        out.append({
            "key": cle,
            "label": label,
            "url": reverse(route, args=[arg]) if arg else reverse(route),
            "count": None if cle in sans_compteur else (nav_counts or {}).get(cle),
            "actif": cle == active,
            "nom": nom,
            "icone": icone,
            "sous_titre": sous_titre,
        })
    return out


def _espace_finances(autorises, nav_counts, active):
    """Dossiers des espaces Finances et Équipe & clients (+ lien du menu Finances)."""
    onglets = _dossiers(FINANCES_ONGLETS, autorises, nav_counts, active, ("finances",))
    equipe = _dossiers(EQUIPE_DOSSIERS, autorises, nav_counts, active)
    organisation = _dossiers(
        ORGANISATION_DOSSIERS, autorises, nav_counts, active, ("globe", "profil")
    )
    societe = _dossiers(SOCIETE_DOSSIERS, autorises, nav_counts, active, ("societe", "modeles_contrat", "abonnement"))
    finances_actif = any(o["actif"] for o in onglets)
    equipe_actif = any(o["actif"] for o in equipe)
    organisation_actif = any(o["actif"] for o in organisation)
    societe_actif = any(o["actif"] for o in societe)
    return {
        "finances_onglets": onglets,
        "finances_url": onglets[0]["url"] if onglets else "",
        "finances_actif": finances_actif,
        "equipe_dossiers": equipe,
        # Dossiers de l'espace de la page courante (composant espace_dossiers.html).
        "espace_dossiers": (
            onglets if finances_actif
            else equipe if equipe_actif
            else organisation if organisation_actif
            else societe if societe_actif
            else []
        ),
        # Entrée « Ma société » de la barre latérale (profil et/ou documents selon les droits)
        "societe_nav_url": societe[0]["url"] if societe else "",
        "societe_actif": societe_actif,
    }


@login_required
def employes(request):
    """Liste + création / modification des employés (drawer droit)."""
    societe, ctx, resp = _societe_context(request, "employes")
    if resp:
        return resp

    est_createur = services.est_createur(request.user, societe)
    if request.method == "POST" and not est_createur:
        return HttpResponseForbidden("Action réservée au propriétaire.")

    contrat_pour = request.POST.get("contrat_employee_id")
    if request.method == "POST" and contrat_pour:
        emp = societe.employes.filter(pk=contrat_pour).first()
        if emp and request.POST.get("contrat_type"):
            debut = parse_date(request.POST.get("contrat_date_debut") or "")
            fin = parse_date(request.POST.get("contrat_date_fin") or "")
            try:
                salaire = Decimal(request.POST.get("contrat_salaire") or 0)
            except (TypeError, ValueError):
                salaire = Decimal(0)
            ContratEmploye.objects.create(
                employe=emp,
                type_contrat_id=request.POST["contrat_type"],
                date_debut=debut or timezone.localdate(),
                date_fin=fin,
                salaire_contractuel=salaire or emp.salaire or 0,
            )
            services.journaliser(
                societe,
                "CREATION",
                "contrats",
                f"{emp.prenom} {emp.nom}",
                "Nouveau contrat",
                request.user,
            )
        return redirect(reverse("gestion:employes") + "?ok=1")

    perm_pour = request.POST.get("perm_employee_id")
    if request.method == "POST" and perm_pour:
        emp = societe.employes.filter(pk=perm_pour).first()
        if emp:
            granted = [
                m["key"]
                for m in EMPLOYE_PERM_MODULES
                if request.POST.get("perm_" + m["key"])
            ]
            emp.permissions = granted
            emp.permissions_lecture = [
                k for k in granted if request.POST.get("niveau_" + k) == "lecture"
            ]
            emp.save(update_fields=["permissions", "permissions_lecture"])
            services.journaliser(
                societe,
                "CONFIGURATION",
                "employes",
                f"{emp.prenom} {emp.nom}",
                f"{len(granted)} permission(s) dont {len(emp.permissions_lecture)} en lecture seule",
                request.user,
            )
        return redirect(reverse("gestion:employes") + "?ok=1")

    obj_id = request.POST.get("id") or None
    instance = (
        societe.employes.filter(pk=obj_id).first() if obj_id else None
    )
    form = EmployeForm(
        request.POST or None,
        request.FILES or None,
        instance=instance,
        societe=societe,
    )
    if request.method == "POST" and form.is_valid():
        form.instance.societe = societe
        employe = form.save()
        if not obj_id:
            role_employe, _ = Role.objects.get_or_create(
                societe=societe,
                nom="Employé",
                defaults={"description": "Rôle par défaut des employés."},
            )
            employe.role = role_employe
            employe.permissions = list(DEFAULT_EMPLOYE_PERMS)
            employe.save(update_fields=["role", "permissions"])
        # Contrat de travail généré automatiquement (créé ou mis à jour avec la section « Contrat »)
        contrat_pdf.assurer_contrat(
            employe, {k: v for k, v in form.cleaned_data.items() if k.startswith("contrat_")}
        )
        if "logo" in request.FILES:
            employe.photo_profil = _store_upload(
                request.FILES["logo"],
                "employes/photos",
                f"{employe.prenom} {employe.nom}",
            )
            employe.save(update_fields=["photo_profil"])
        if form.cleaned_data.get("document"):
            EmployeDocument.objects.create(
                employe=employe,
                type_document="DOCUMENT",
                fichier=fichiers_prives.stocker(form.cleaned_data["document"], "employes/documents",
                    f"{employe.prenom} {employe.nom}",
                ),
            )
        # Compte de connexion automatique pour que l'employé accède au chat.
        services.assurer_compte_employe(employe)
        services.journaliser(
            societe,
            "MODIFICATION" if obj_id else "CREATION",
            "employes",
            f"{employe.prenom} {employe.nom}",
            "",
            request.user,
        )
        return redirect(reverse("gestion:employes") + "?ok=1")

    items = []
    sans_contrat = 0
    employes = list(societe.employes.select_related("role", "fonction"))
    employes_par_compte = {e.compte_id: e.pk for e in employes if e.compte_id}
    en_ligne = services.etats_connexion_en_ligne(societe)
    mon_employe = services.employe_pour_utilisateur(request.user, societe)
    mon_employe_pk = mon_employe.pk if mon_employe else None
    msg_counts = {}
    for conv in (
        EquipeConversation.objects.filter(societe=societe, participants=request.user)
        .prefetch_related("participants")
        .annotate(n=Count("messages"))
    ):
        autres = [p for p in conv.participants.all() if p.pk != request.user.pk]
        if not autres:
            row_pk = (
                EquipeMessage.objects.filter(
                    conversation=conv, employe__isnull=False
                )
                .values_list("employe_id", flat=True)
                .first()
            )
        else:
            autre = autres[0]
            if not est_createur and autre.pk == societe.createur_id:
                row_pk = mon_employe_pk
            else:
                row_pk = employes_par_compte.get(autre.pk)
        if row_pk:
            msg_counts[row_pk] = msg_counts.get(row_pk, 0) + conv.n
    if est_createur:
        for c in (
            EquipeMessage.objects.filter(
                societe=societe, conversation__isnull=True, employe__isnull=False
            )
            .values("employe_id")
            .annotate(n=Count("id"))
        ):
            msg_counts[c["employe_id"]] = msg_counts.get(c["employe_id"], 0) + c["n"]
    createur = societe.createur
    # Messagerie : quand un employé consulte sa propre fiche, c'est avec le
    # propriétaire qu'il échange. Son profil d'entête est donc celui du
    # propriétaire, pas le sien ; sinon c'est le profil de l'employé.
    # On identifie la fiche du visiteur par compte lié (pk), puis à défaut par
    # email identique (fiches anciennes sans compte lié).
    employe_visiteur = None
    if not est_createur:
        email_visiteur = (request.user.email or "").strip().lower()
        for e in employes:
            if e.compte_id == request.user.pk:
                employe_visiteur = e
                break
            if (
                employe_visiteur is None
                and e.email
                and e.email.strip().lower() == email_visiteur
            ):
                employe_visiteur = e
    # Documents (livrables) fournis par chaque employé dans ses tâches.
    livrables_par_employe = {}
    for liv in (
        TacheLivrable.objects.filter(tache__societe=societe)
        .select_related("tache")
        .order_by("-date_depot")
    ):
        info = {
            "pk": liv.pk,
            "nom_fichier": liv.nom_fichier,
            "type_fichier": liv.type_fichier,
            "est_pdf": (
                liv.type_fichier == "application/pdf"
                or (liv.nom_fichier or "").lower().endswith(".pdf")
            ),
            "statut": liv.statut,
            "statut_label": liv.get_statut_display(),
            "message": liv.message,
            "tache_titre": liv.tache.titre,
            "date_depot": liv.date_depot.strftime("%d/%m/%Y %H:%M"),
        }
        livrables_par_employe.setdefault(liv.employe_id, []).append(info)
    for e in employes:
        dernier_contrat = (
            e.contrats.order_by("-date_debut").first()
            if e.contrats.exists()
            else None
        )
        if dernier_contrat is None:
            sans_contrat += 1
        est_soi = employe_visiteur is not None and e.pk == employe_visiteur.pk
        if est_soi:
            chat_photo = createur.photo_profil or ""
            chat_nom = f"{createur.prenom} {createur.nom}".strip()
        else:
            chat_photo = ""
            chat_nom = ""
        livrables_e = livrables_par_employe.get(e.pk, [])
        peut_voir_livrables = est_createur or (
            mon_employe is not None and e.pk == mon_employe.pk
        )
        items.append(
            {
                "pk": e.pk,
                "nom": e.nom,
                "prenom": e.prenom,
                "date_naissance": e.date_naissance.isoformat() if e.date_naissance else "",
                "lieu_naissance": e.lieu_naissance,
                "nationalite": e.nationalite or "",
                "numero_piece_identite": e.numero_piece_identite,
                "adresse": e.adresse,
                # Section « Contrat de travail » du formulaire (contrat en cours)
                "contrat_type": dernier_contrat.type_contrat_id if dernier_contrat else "",
                "contrat_date_debut": dernier_contrat.date_debut.isoformat() if dernier_contrat else "",
                "contrat_date_fin": dernier_contrat.date_fin.isoformat() if dernier_contrat and dernier_contrat.date_fin else "",
                "contrat_salaire": str(dernier_contrat.salaire_contractuel) if dernier_contrat else "",
                "contrat_lieu_travail": dernier_contrat.lieu_travail if dernier_contrat else "",
                "contrat_heures_hebdo": (dernier_contrat.heures_hebdo or "") if dernier_contrat else 40,
                "contrat_periode_essai": (dernier_contrat.periode_essai_jours or "") if dernier_contrat else "",
                "contrat_missions": dernier_contrat.missions if dernier_contrat else "",
                "contrat_url": reverse("gestion:employe_contrat_pdf", args=[e.pk]),
                "telephone_1": e.telephone_1,
                "telephone_2": e.telephone_2 or "",
                "email": e.email or "",
                "salaire": str(e.salaire) if e.salaire is not None else "",
                "fonction": e.fonction_id or "",
                "fonction_nom": e.fonction.nom if e.fonction else "",
                "role": e.role_id or "",
                "role_nom": e.role.nom if e.role else "",
                "statut": e.statut,
                "date_recrutement": e.date_recrutement.isoformat() if e.date_recrutement else "",
                "jour_paiement": e.jour_paiement or "",
                "photo": e.photo_profil or "",
                "chat_photo": chat_photo,
                "chat_nom": chat_nom,
                "contrat_statut": (
                    dernier_contrat.statut if dernier_contrat else "SANS"
                ),
                "contrat_code": (
                    dernier_contrat.type_contrat.code if dernier_contrat else ""
                ),
                "del_url": "{}".format(e.pk),
                "del_name": f"{e.prenom} {e.nom}",
                "permissions": e.permissions or [],
                "permissions_lecture": e.permissions_lecture or [],
                "nb_permissions": len(e.permissions or []),
                "a_compte": e.compte_id is not None,
                "n_messages": msg_counts.get(e.pk, 0),
                "en_ligne": en_ligne.get(e.pk, False),
                "livrables": livrables_e if peut_voir_livrables else [],
                "n_livrables": len(livrables_e) if peut_voir_livrables else 0,
                "n_pdf_livrables": (
                    sum(1 for x in livrables_e if x["est_pdf"])
                    if peut_voir_livrables else 0
                ),
                "peut_voir_livrables": peut_voir_livrables,
            }
        )
    # Confidentialité RH : un employé ne reçoit les données personnelles et salariales que pour
    # lui-même ; les montants de salaire restent visibles aux comptes ayant la permission « Salaires ».
    voit_salaires = est_createur or "salaires" in ctx["modules_autorises"]
    if not est_createur:
        prives = ("date_naissance", "lieu_naissance", "nationalite", "numero_piece_identite", "adresse",
                  "jour_paiement", "contrat_date_debut", "contrat_date_fin", "contrat_lieu_travail",
                  "contrat_heures_hebdo", "contrat_periode_essai", "contrat_missions", "telephone_2")
        for it in items:
            if mon_employe is not None and it["pk"] == mon_employe.pk:
                continue
            for cle in prives:
                it[cle] = ""
            it["permissions"], it["nb_permissions"], it["permissions_lecture"] = [], 0, []
            if not voit_salaires:
                it["salaire"] = it["contrat_salaire"] = ""
    ctx["voit_salaires"] = voit_salaires
    ctx["form"] = form
    ctx["items"] = items
    ordre_cat = ["Général", "Équipe & clients", "Finances", "Applications", "Organisation"]
    ctx["perm_modules"] = sorted(EMPLOYE_PERM_MODULES, key=lambda m: ordre_cat.index(m.get("cat", "Organisation")))
    ctx["sans_contrat"] = sans_contrat
    ctx["sans_fonction"] = sum(1 for e in items if not e["fonction_nom"])
    groupes_visibles = services.groupes_visibles(request.user, societe).prefetch_related("membres")
    ctx["peut_creer_groupe"] = services.peut_creer_groupe(request.user, societe)
    ctx["groupes"] = [
        {
            "pk": g.pk,
            "titre": g.titre,
            "nb_membres": g.membres.count(),
            "nb_messages": g.messages.count(),
            "logo": g.logo,
            "logo_url": (
                reverse("gestion:chat_groupe_logo", args=[g.pk]) if g.logo else ""
            ),
            "url": reverse("gestion:groupe_messages", args=[g.pk]),
        }
        for g in groupes_visibles
    ]
    ctx["est_createur"] = est_createur
    ctx["mdp_defaut_employe"] = (
        getattr(settings, "EMPLOYE_MOT_DE_PASSE_DEFAUT", "") if est_createur else ""
    )

    ctx["module_reunions"] = services.module_actif("reunions")
    ctx["acces_reunions"] = services.module_actif("reunions") and (
        est_createur or "reunions" in (ctx["modules_autorises"] or [])
    )
    ctx["form_reunion"] = ReunionForm(societe=societe)
    meet = societe.connecteurs.filter(type_connecteur="google_meet").first()
    ctx["meet"] = {
        "connecte": bool(meet is not None and meet.est_connecte),
        "compte": (meet.compte_externe if meet else "") or "",
        "pret": GoogleMeet.oauth_configure(),
        "hub_url": reverse("gestion:connecteurs"),
        "connecter_url": reverse("gestion:connecteur_connecter", args=["google_meet"]),
    }
    reunion_rows = []
    for r in (
        societe.reunions.prefetch_related("participants")
        .select_related("cree_par")
        .order_by("-date", "-heure")[:60]
    ):
        reunion_rows.append(
            {
                "pk": r.pk,
                "titre": r.titre,
                "date_aff": r.date_aff,
                "heure_aff": r.heure_aff,
                "duree": r.duree,
                "description": r.description,
                "lien_meet": r.lien_meet,
                "evenement_google_id": r.evenement_google_id,
                "passee": r.est_passee,
                "participants": [
                    {"pk": p.pk, "nom": f"{p.prenom} {p.nom}".strip()}
                    for p in r.participants.all()
                ],
                "cree_par_nom": (
                    f"{r.cree_par.prenom} {r.cree_par.nom}".strip()
                    if r.cree_par_id
                    else ""
                ),
            }
        )
    ctx["reunions"] = reunion_rows
    return render(request, "gestion/crud_employes.html", ctx)


@login_required
def reunions_creer(request):
    """Crée une réunion : formulaire intégré → événement Google Meet + partage.

    Dispositif de sécurité : tout passe par POST+CSRF ; la permission
    « réunions » (ou le statut de créateur) est requise ; les jetons Google
    restent chiffrés dans le connecteur (jamais exposés). En cas d'échec du
    connecteur ou de l'API, la ligne de réunion est annulée et l'erreur est
    affichée proprement sur la page Employés.
    """
    societe, _, resp = _societe_context(request, "employes")
    if resp:
        return resp
    est_createur = services.est_createur(request.user, societe)
    if not services.module_actif("reunions") or not (
        est_createur or "reunions" in services.modules_autorises(request.user, societe)
    ):
        return HttpResponseForbidden("Action non autorisée.")
    base_retour = (
        reverse("gestion:reunions")
        if request.POST.get("retour") == "reunions"
        else reverse("gestion:employes")
    )
    if request.method != "POST":
        return redirect(base_retour)
    form = ReunionForm(request.POST, societe=societe)
    if not form.is_valid():
        msgs = "; ".join(
            f"{form.fields[champ].label if champ in form.fields else champ} : {', '.join(err)}"
            for champ, err in form.errors.items()
        )
        retour = base_retour + "?reunion_erreur=" + quote(msgs[:220])
        return redirect(retour)
    reunion = form.save(commit=False)
    reunion.societe = societe
    reunion.duree = form.cleaned_data.get("duree") or 60
    reunion.cree_par = request.user
    reunion.save()
    form.save_m2m()

    meet = (
        societe.connecteurs.filter(type_connecteur="google_meet", statut="CONNECTE")
        .first()
    )
    if meet is None:
        reunion.delete()
        message = (
            "Connectez d'abord Google Meet (connecteurs → Google Meet), "
            "puis reprogrammez la réunion."
        )
        return redirect(base_retour + "?reunion_erreur=" + quote(message))
    ok, lien, evenement_id, message = google_workspace.creer_reunion(meet, reunion)
    if not ok:
        reunion.delete()
        return redirect(base_retour + "?reunion_erreur=" + quote(message[:220]))
    reunion.lien_meet = lien
    reunion.evenement_google_id = evenement_id
    reunion.compte_externe = meet.compte_externe
    reunion.save(update_fields=["lien_meet", "evenement_google_id", "compte_externe"])
    services.partager_reunion(societe, reunion, request.user)
    services.journaliser(
        societe, "CREATION", "reunions", reunion.titre, lien, request.user
    )
    return redirect(base_retour + "?reunion=ok")


@login_required
def reunions_partager(request, pk):
    """Re-partage le lien Meet d'une réunion vers les participants (chat)."""
    societe, _, resp = _societe_context(request, "employes")
    if resp:
        return resp
    est_createur = services.est_createur(request.user, societe)
    if not services.module_actif("reunions") or not (
        est_createur or "reunions" in services.modules_autorises(request.user, societe)
    ):
        return HttpResponseForbidden("Action non autorisée.")
    base_retour = (
        reverse("gestion:reunions")
        if request.POST.get("retour") == "reunions"
        else reverse("gestion:employes")
    )
    reunion = societe.reunions.filter(pk=pk).first()
    if request.method != "POST" or not reunion or not reunion.lien_meet:
        return redirect(base_retour)
    services.partager_reunion(societe, reunion, request.user)
    services.journaliser(
        societe,
        "MODIFICATION",
        "reunions",
        reunion.titre,
        "Lien re-partagé aux participants.",
        request.user,
    )
    return redirect(base_retour + "?reunion=partage")


def _formater_duree(secondes):
    """« 2 h 05 min », « 12 min », « 45 s »…"""
    secondes = int(secondes or 0)
    if secondes <= 0:
        return "—"
    if secondes < 60:
        return f"{secondes} s"
    h, rest = divmod(secondes, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min"
    return f"{s} s"


@login_required
def mdp_premiere_connexion(request):
    """Définit le mot de passe personnalisé d'un employé (première connexion).

    Appelé en AJAX par la fenêtre modale affichée tant que le compte porte
    l'indicateur ``doit_changer_mdp`` (mot de passe par défaut encore actif).
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "erreur": "Méthode non autorisée."}, status=405)
    user = request.user
    if not getattr(user, "doit_changer_mdp", False):
        return JsonResponse({"ok": True})
    mdp1 = request.POST.get("password1") or ""
    mdp2 = request.POST.get("password2") or ""
    if mdp1 != mdp2:
        return JsonResponse(
            {"ok": False, "erreur": "Les deux mots de passe ne correspondent pas."},
            status=400,
        )
    if user.check_password(mdp1):
        return JsonResponse(
            {
                "ok": False,
                "erreur": "Choisissez un mot de passe différent de celui par défaut.",
            },
            status=400,
        )
    try:
        validate_password(mdp1, user)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "erreur": " ".join(exc.messages)}, status=400)
    user.set_password(mdp1)
    user.doit_changer_mdp = False
    user.save(update_fields=["password", "doit_changer_mdp"])
    update_session_auth_hash(request, user)
    return JsonResponse({"ok": True})


def presence_ping(request):
    """Cœur de battement : l'onglet ouvert rafraîchit l'activité de présence.

    Appelé régulièrement par le navigateur pendant la navigation (et stoppé
    dès que la page est fermée/masquée). Une présence dont l'activité devient
    trop ancienne bascule automatiquement en « hors ligne ».

    Avec `?quit=1`, l'onglet annonce qu'il se ferme : on vieillit l'activité
    instantanément (hors ligne immédiat) sans fermer la présence — une
    navigation interne vers une autre page du site réactualisera l'activité au
    prochain ping.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False})
    employe = getattr(request.user, "employe_profil", None)
    if employe is None:
        return JsonResponse({"ok": False})
    depart = request.GET.get("quit") == "1"
    maintenant = timezone.now()
    if depart:
        # Vieillit immédiatement : l'activité devient périmée (hors ligne).
        maintenant = maintenant - timedelta(seconds=services.EN_LIGNE_DELAI)
    presence_id = request.session.get("_presence_id") if hasattr(request, "session") else None
    maj = 0
    if presence_id:
        maj = EmployePresence.objects.filter(
            pk=presence_id, employe=employe, date_deconnexion__isnull=True,
        ).update(derniere_activite=maintenant)
    if depart:
        return JsonResponse({"ok": True})
    if not maj:
        # Présence introuvable (nettoyage, restauration de base...) : l'ouvrir
        # à nouveau pour que l'employé connecté reste bien « en ligne ».
        from .signals import _ouvrir_presence

        try:
            _ouvrir_presence(request.user, employe.societe, request)
        except Exception:
            return JsonResponse({"ok": False})
    return JsonResponse({"ok": True})


def _sessions_employe(employe, limit=8):
    """Dernières présences d'un employé, formatées pour l'affichage."""
    sessions = []
    for p in employe.presences.all()[:limit]:
        sessions.append(
            {
                "connexion": p.date_connexion.strftime("%d/%m/%Y %H:%M"),
                "connexion_iso": p.date_connexion.isoformat(),
                "deconnexion": (
                    p.date_deconnexion.strftime("%d/%m/%Y %H:%M")
                    if p.date_deconnexion
                    else "en cours"
                ),
                "duree": _formater_duree(p.duree_secondes or _duree_brute(p)),
                "en_cours": p.en_cours,
            }
        )
    return sessions


def _duree_brute(p):
    if p.duree_secondes:
        return p.duree_secondes
    if p.date_deconnexion is None:
        return max(0, int((timezone.now() - p.date_connexion).total_seconds()))
    return max(0, int((p.date_deconnexion - p.date_connexion).total_seconds()))


@login_required
def employes_activite(request):
    """Tracage de l'activite des employes : temps passe, connexions."""
    societe, ctx, resp = _societe_context(request, "activite")
    if resp:
        return resp
    if not services.est_createur(request.user, societe):
        return redirect("gestion:dashboard")

    maintenant = timezone.now()
    debut_hier = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    debut_7j = debut_hier - timedelta(days=6)
    debut_30j = debut_hier - timedelta(days=29)

    def duree_periode(p_res, debut):
        if p_res.date_deconnexion and p_res.date_deconnexion < debut:
            return 0
        if p_res.date_connexion > maintenant:
            return 0
        d = max(debut, p_res.date_connexion)
        f = p_res.date_deconnexion or maintenant
        f = min(f, maintenant)
        return max(0, int((f - d).total_seconds()))

    items = []
    tot_today = tot_7j = tot_30j = nbr_session_auj = 0
    presences_par_employe = {}
    for p in societe.presences.select_related("employe"):
        presences_par_employe.setdefault(p.employe_id, []).append(p)
    en_ligne = services.etats_connexion_en_ligne(societe)

    for e in societe.employes.select_related("compte").order_by("prenom", "nom"):
        ps = presences_par_employe.get(e.pk) or []
        d_today = sum(duree_periode(p2, debut_hier) for p2 in ps)
        d_7j = sum(duree_periode(p2, debut_7j) for p2 in ps)
        d_30j = sum(duree_periode(p2, debut_30j) for p2 in ps)
        d_tot = sum(_duree_brute(p2) for p2 in ps)
        tot_today += d_today
        tot_7j += d_7j
        tot_30j += d_30j
        nbr_session_auj += sum(1 for p2 in ps if p2.date_connexion >= debut_hier)
        connecte = bool(e.compte_id and en_ligne.get(e.pk, False))
        items.append(
            {
                "pk": e.pk,
                "nom": f"{e.prenom} {e.nom}",
                "statut": e.statut,
                "has_compte": e.compte_id is not None,
                "connecte": connecte,
                "derniere_connexion": (
                    e.presences.first().date_connexion.strftime("%d/%m/%Y %H:%M")
                    if e.presences.exists()
                    else "jamais"
                ),
                "duree_aujourdhui": _formater_duree(d_today),
                "duree_7j": _formater_duree(d_7j),
                "duree_30j": _formater_duree(d_30j),
                "duree_total": _formater_duree(d_tot),
                "nb_sessions": len(ps),
                "sessions": _sessions_employe(e),
            }
        )

    # Séries pour les cartes statistiques : 7 jours (durée, sessions) et 5 semaines.
    toutes = [p2 for ps in presences_par_employe.values() for p2 in ps]
    jours = [(debut_hier - timedelta(days=i)) for i in range(6, -1, -1)]
    s_duree = [sum(duree_periode(p2, j) - duree_periode(p2, j + timedelta(days=1)) for p2 in toutes) for j in jours]
    s_sessions = [sum(1 for p2 in toutes if j <= p2.date_connexion < j + timedelta(days=1)) for j in jours]
    semaines = [(debut_hier - timedelta(days=7 * i + 6)) for i in range(4, -1, -1)]
    s_semaines = [sum(duree_periode(p2, w) - duree_periode(p2, w + timedelta(days=7)) for p2 in toutes) for w in semaines]
    nb_en_ligne = sum(1 for i in items if i["connecte"])
    ctx["activite_cartes"] = [
        stats.carte("En ligne maintenant", nb_en_ligne, "users", "act-on", s_sessions, "vert",
                    note=f"{nbr_session_auj} connexion(s) aujourd'hui"),
        stats.carte("Temps aujourd'hui", _formater_duree(tot_today), "clock", "act-j", s_duree, "bleu",
                    stats.tendance_pct(s_duree), "toute l'équipe"),
        stats.carte("7 derniers jours", _formater_duree(tot_7j), "chart", "act-7", s_duree, "violet",
                    note="temps cumulé"),
        stats.carte("30 derniers jours", _formater_duree(tot_30j), "calendar", "act-30", s_semaines, "ambre",
                    stats.tendance_pct(s_semaines), "temps cumulé, par semaine"),
    ]

    ctx.update(
        {
            "items": items,
            "total_today": _formater_duree(tot_today),
            "total_7j": _formater_duree(tot_7j),
            "total_30j": _formater_duree(tot_30j),
            "nb_connexions_auj": nbr_session_auj,
            "nb_connectes": nb_en_ligne,
            "est_createur": True,
        }
    )
    return render(request, "gestion/employes_activite.html", ctx)


@login_required
def taches(request):
    """Onglet Tâches : assignation par l'admin + suivi d'évolution."""
    societe, ctx, resp = _societe_context(request, "taches")
    if resp:
        return resp

    est_createur = services.est_createur(request.user, societe)
    mon_employe = None if est_createur else services.employe_pour_utilisateur(request.user, societe)

    if request.method == "POST":
        if request.POST.get("ajouter_tache"):
            if not est_createur:
                return HttpResponseForbidden("Action réservée au propriétaire.")
            titre = (request.POST.get("titre") or "").strip()
            assignee_id = request.POST.get("assignee_id")
            priorite = request.POST.get("priorite") or "MOYENNE"
            assignee = societe.employes.filter(pk=assignee_id).first()
            if not (titre and assignee):
                return redirect(reverse("gestion:taches") + "?err=1")
            tache = Tache.objects.create(
                societe=societe,
                titre=titre,
                description=(request.POST.get("description") or "").strip(),
                assignee=assignee,
                cree_par=request.user,
                priorite=priorite,
                echeance=parse_date(request.POST.get("echeance") or "") or None,
                projet=societe.projets.filter(
                    pk=request.POST.get("projet_id") or None
                ).first(),
            )
            # Objectifs à atteindre : l'avancement est calculé automatiquement
            # à partir d'eux (poids égal par objectif).
            objectifs = [
                (o or "").strip()
                for o in request.POST.getlist("objectifs")
            ]
            objectifs = [o for o in objectifs if o]
            for i, libelle in enumerate(objectifs, start=1):
                TacheObjectif.objects.create(tache=tache, libelle=libelle, ordre=i)
            if objectifs:
                tache.recalculer_progres(auteur=request.user)
            services.journaliser(
                societe, "CREATION", "taches",
                tache.titre,
                (
                    f"Assignée à {assignee.prenom} {assignee.nom} — "
                    f"{len(objectifs)} objectif(s) à atteindre"
                    if objectifs else f"Assignée à {assignee.prenom} {assignee.nom}"
                ),
                request.user,
            )
            return redirect(reverse("gestion:taches") + "?ok=1")

        if request.POST.get("supprimer_tache"):
            if not est_createur:
                return HttpResponseForbidden("Action réservée au propriétaire.")
            tache = Tache.objects.filter(
                pk=request.POST["supprimer_tache"], societe=societe
            ).first()
            if tache:
                titre = tache.titre
                tache.delete()
                services.journaliser(
                    societe, "SUPPRESSION", "taches", titre, "", request.user
                )
            return redirect(reverse("gestion:taches") + "?ok=2")

        if request.POST.get("modifier_tache"):
            if not est_createur:
                return HttpResponseForbidden("Action réservée au propriétaire.")
            tache = Tache.objects.filter(
                pk=request.POST.get("tache_id"), societe=societe
            ).first()
            if tache is None:
                return redirect(reverse("gestion:taches") + "?err=1")
            titre = (request.POST.get("titre") or "").strip()
            assignee_id = request.POST.get("assignee_id")
            assignee = societe.employes.filter(pk=assignee_id).first()
            if not (titre and assignee):
                return redirect(reverse("gestion:taches") + "?err=1")
            tache.titre = titre
            tache.description = (request.POST.get("description") or "").strip()
            tache.assignee = assignee
            tache.priorite = request.POST.get("priorite") or "MOYENNE"
            tache.echeance = parse_date(request.POST.get("echeance") or "") or None
            tache.projet = societe.projets.filter(
                pk=request.POST.get("projet_id") or None
            ).first()
            tache.save(
                update_fields=[
                    "titre", "description", "assignee", "priorite", "echeance",
                    "projet",
                ]
            )
            # Objectifs : on remplace la liste envoyée par le formulaire.
            libelles = [
                (x or "").strip() for x in request.POST.getlist("objectifs")
            ]
            ids = request.POST.getlist("objectif_ids")
            gardes = []
            ordre_ = 0
            for i, libelle in enumerate(libelles):
                if not libelle:
                    continue
                ordre_ += 1
                oid = (ids[i] if i < len(ids) else "") or ""
                obj = None
                if oid:
                    obj = tache.objectifs.filter(pk=oid).first()
                if obj is None:
                    obj = TacheObjectif.objects.create(
                        tache=tache, libelle=libelle, ordre=ordre_
                    )
                else:
                    obj.libelle = libelle
                    obj.ordre = ordre_
                    obj.save(update_fields=["libelle", "ordre"])
                gardes.append(obj.pk)
            tache.objectifs.exclude(pk__in=gardes).delete()
            tache.recalculer_progres(auteur=request.user)
            services.journaliser(
                societe, "MODIFICATION", "taches", tache.titre,
                "Modification des détails de la tâche", request.user,
            )
            return redirect(reverse("gestion:taches") + "?ok=4")

        objectif_id = request.POST.get("objectif_id")
        if objectif_id:
            if not est_createur:
                return HttpResponseForbidden(
                    "La validation des objectifs est réservée à l'administrateur."
                )
            obj = TacheObjectif.objects.filter(
                pk=objectif_id, tache__societe=societe
            ).select_related("tache").first()
            if obj is None:
                return redirect(reverse("gestion:taches") + "?err=1")
            tache = obj.tache
            if tache.statut == "ANNULEE":
                return redirect(reverse("gestion:taches") + "?err=2")
            actif = request.POST.get("termine") == "1"
            if obj.termine != actif:
                obj.termine = actif
                obj.date_termine = timezone.now() if actif else None
                obj.save(update_fields=["termine", "date_termine"])
                if tache.recalculer_progres(auteur=request.user):
                    services.journaliser(
                        societe, "MODIFICATION", "taches", tache.titre,
                        (
                            f"Objectif atteint : {obj.libelle}"
                            if actif else f"Objectif rouvert : {obj.libelle}"
                        ),
                        request.user,
                    )
            return redirect(reverse("gestion:taches") + "?ok=3")

        evo_id = request.POST.get("evo_tache_id")
        if evo_id:
            tache = Tache.objects.filter(pk=evo_id, societe=societe).first()
            if tache is None:
                return redirect(reverse("gestion:taches") + "?err=1")
            ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
            if not est_createur:
                if tache.assignee_id != (mon_employe.pk if mon_employe else None):
                    if ajax:
                        return JsonResponse({"ok": False, "erreur": "Vous ne pouvez déplacer que vos propres tâches."}, status=403)
                    return HttpResponseForbidden(
                        "Vous ne pouvez faire évoluer que vos propres tâches."
                    )
            nouveau_statut = (request.POST.get("statut") or "").strip()
            if nouveau_statut:
                if nouveau_statut not in dict(
                    Tache._meta.get_field("statut").choices
                ):
                    nouveau_statut = ""
                if not est_createur and nouveau_statut == "ANNULEE":
                    nouveau_statut = ""
                if nouveau_statut:
                    tache.changer_statut(nouveau_statut, auteur=request.user)
            if nouveau_statut:
                services.journaliser(
                    societe, "MODIFICATION", "taches",
                    tache.titre, "Évolution du travail", request.user,
                )
            if ajax:
                if not nouveau_statut:
                    return JsonResponse({"ok": False, "erreur": "Statut non autorisé."}, status=400)
                tache.refresh_from_db()
                return JsonResponse({
                    "ok": True, "statut": tache.statut,
                    "statut_label": tache.get_statut_display(), "progres": tache.progres,
                })
            return redirect(reverse("gestion:taches") + "?ok=3")

        if request.POST.get("livrable_depot"):
            tache = Tache.objects.filter(
                pk=request.POST["livrable_depot"], societe=societe
            ).first()
            if tache is None:
                return redirect(reverse("gestion:taches") + "?err=1")
            if not est_createur:
                if tache.assignee_id != (mon_employe.pk if mon_employe else None):
                    return HttpResponseForbidden(
                        "Vous ne pouvez déposer un livrable que sur vos propres tâches."
                    )
            fichier = request.FILES.get("fichier")
            if fichier is None:
                return redirect(reverse("gestion:taches") + "?err=3")
            try:
                rel, nom_original, mime = _store_tache_livrable(
                    fichier, societe.pk, tache.pk
                )
            except ValueError:
                return redirect(reverse("gestion:taches") + "?err=3")
            employe_connecte = services.employe_pour_utilisateur(request.user, societe)
            TacheLivrable.objects.create(
                tache=tache,
                employe=employe_connecte or tache.assignee,
                fichier=rel,
                nom_fichier=nom_original,
                type_fichier=mime,
                message=(request.POST.get("livrable_note") or "").strip(),
            )
            TacheEvolution.objects.create(
                tache=tache,
                auteur=request.user,
                commentaire=f"Fichier soumis : {nom_original}",
            )
            services.journaliser(
                societe, "VALIDATION", "taches", tache.titre,
                f"Fichier livrable soumis : {nom_original}", request.user,
            )
            return redirect(reverse("gestion:taches") + "?ok=5")

        livrable_traite = (
            request.POST.get("livrable_valider") or request.POST.get("livrable_corriger")
        )
        if livrable_traite:
            if not est_createur:
                return HttpResponseForbidden(
                    "La validation des livrables est réservée au propriétaire."
                )
            livrable = TacheLivrable.objects.filter(
                pk=livrable_traite, tache__societe=societe
            ).select_related("tache").first()
            if livrable is None:
                return redirect(reverse("gestion:taches") + "?err=1")
            if request.POST.get("livrable_valider"):
                livrable.statut = "VALIDE"
                evo_texte = f"Livrable validé : {livrable.nom_fichier}"
                action_journal = "VALIDATION"
            else:
                correction = (request.POST.get("livrable_correction") or "").strip()
                if not correction:
                    return redirect(reverse("gestion:taches") + "?err=4")
                livrable.statut = "CORRIGER"
                livrable.commentaire_admin = correction
                evo_texte = f"Correction demandée : {correction}"
                action_journal = "MODIFICATION"
            livrable.repondu_par = request.user
            livrable.date_reponse = timezone.now()
            livrable.save(
                update_fields=[
                    "statut", "commentaire_admin", "repondu_par", "date_reponse",
                ]
            )
            TacheEvolution.objects.create(
                tache=livrable.tache, auteur=request.user, commentaire=evo_texte
            )
            services.journaliser(
                societe, action_journal, "taches",
                livrable.tache.titre, evo_texte, request.user,
            )
            return redirect(reverse("gestion:taches") + "?ok=5")

        if request.POST.get("livrable_supprimer"):
            livrable = TacheLivrable.objects.filter(
                pk=request.POST["livrable_supprimer"], tache__societe=societe
            ).first()
            if livrable is None:
                return redirect(reverse("gestion:taches") + "?err=1")
            if livrable.statut != "SOUMIS":
                return redirect(reverse("gestion:taches") + "?err=5")
            if not est_createur:
                employe_connecte = services.employe_pour_utilisateur(request.user, societe)
                if livrable.employe_id != (employe_connecte.pk if employe_connecte else None):
                    return HttpResponseForbidden("Suppression non autorisée.")
            _delete_tache_livrable_fichier(livrable.fichier)
            livrable.delete()
            services.journaliser(
                societe, "SUPPRESSION", "taches",
                livrable.tache.titre,
                f"Fichier livrable retiré : {livrable.nom_fichier}", request.user,
            )
            return redirect(reverse("gestion:taches") + "?ok=5")

        return redirect(reverse("gestion:taches") + "?err=1")

    filtres_employe = (request.GET.get("employe") or "").strip()
    base = Tache.objects.filter(societe=societe).select_related("assignee")
    if not est_createur and mon_employe is not None:
        base = base.filter(assignee=mon_employe)
    if est_createur and filtres_employe:
        base = base.filter(assignee__pk=filtres_employe)
    base = base.prefetch_related("evolutions", "objectifs", "livrables")

    colonnes = {}
    rapport = []
    taches_edit = []
    historique = []
    livrables_rapport = []
    for statut in ("A_FAIRE", "EN_COURS", "TERMINEE", "ANNULEE"):
        colonnes[statut] = []
    labels_statut = dict(Tache._meta.get_field("statut").choices)
    labels_livrable = dict(TacheLivrable._meta.get_field("statut").choices)
    for t in base:
        evolutions = [
            {
                "statut_label": (
                    labels_statut.get(e.statut_apres, e.statut_apres)
                    if e.statut_apres
                    else ""
                ),
                "progres_avant": e.progres_avant,
                "progres_apres": e.progres_apres,
                "commentaire": e.commentaire,
                "auteur": f"{e.auteur.prenom} {e.auteur.nom}" if e.auteur else "",
                "date": e.created_at.strftime("%d/%m/%Y %H:%M"),
            }
            for e in t.evolutions.all()[:12]
        ]
        objectifs = [
            {
                "pk": o.pk,
                "libelle": o.libelle,
                "ordre": o.ordre,
                "termine": o.termine,
                "date_termine": o.date_termine.isoformat()
                if o.date_termine else "",
            }
            for o in t.objectifs.all()
        ]
        nb_atteints = sum(1 for o in objectifs if o["termine"])
        livrables = [
            {
                "pk": l.pk,
                "nom_fichier": l.nom_fichier,
                "type_fichier": l.type_fichier,
                "est_pdf": (
                    l.type_fichier == "application/pdf"
                    or (l.nom_fichier or "").lower().endswith(".pdf")
                ),
                "statut": l.statut,
                "statut_label": labels_livrable.get(l.statut, l.statut),
                "message": l.message,
                "commentaire_admin": l.commentaire_admin,
                "employe_nom": f"{l.employe.prenom} {l.employe.nom}",
                "date_depot": l.date_depot.strftime("%d/%m/%Y %H:%M"),
                "date_depot_iso": l.date_depot.isoformat() if l.date_depot else "",
                "date_reponse": (
                    l.date_reponse.strftime("%d/%m/%Y %H:%M")
                    if l.date_reponse else ""
                ),
                "peut_retirer": (
                    l.statut == "SOUMIS"
                    and (est_createur or (mon_employe and l.employe_id == mon_employe.pk))
                ),
            }
            for l in t.livrables.all()
        ]
        livrables_rapport.extend(
            {**liv, "tache_pk": t.pk, "tache_titre": t.titre} for liv in livrables
        )
        can_depot = est_createur or (
            mon_employe is not None and t.assignee_id == mon_employe.pk
        )
        colonnes[t.statut].append(
            {
                "pk": t.pk,
                "titre": t.titre,
                "description": t.description,
                "priorite": t.priorite,
                "priorite_label": t.get_priorite_display(),
                "assignee_id": t.assignee_id,
                "assignee_nom": f"{t.assignee.prenom} {t.assignee.nom}",
                "echeance": t.echeance.isoformat() if t.echeance else "",
                "statut": t.statut,
                "progres": t.progres,
                "date_terminee": t.date_terminee.isoformat() if t.date_terminee else "",
                "evolutions": evolutions,
                "objectifs": objectifs,
                "livrables": livrables,
                "can_depot": can_depot,
                "nb_objectifs": len(objectifs),
                "nb_atteints": nb_atteints,
            }
        )
        rapport.append(
            {
                "pk": t.pk,
                "titre": t.titre,
                "assignee_nom": f"{t.assignee.prenom} {t.assignee.nom}",
                "priorite_label": t.get_priorite_display(),
                "statut": t.statut,
                "statut_label": labels_statut.get(t.statut, t.statut),
                "progres": t.progres,
                "objectifs": objectifs,
                "nb_objectifs": len(objectifs),
                "nb_atteints": nb_atteints,
            }
        )
        if t.statut in ("TERMINEE", "ANNULEE"):
            # Espace historique : tâches clôturées (terminées ou annulées).
            date_cloture = t.date_terminee or t.updated_at
            historique.append(
                {
                    "pk": t.pk,
                    "titre": t.titre,
                    "description": t.description,
                    "assignee_nom": f"{t.assignee.prenom} {t.assignee.nom}",
                    "priorite_label": t.get_priorite_display(),
                    "projet_nom": t.projet.nom if t.projet_id else "",
                    "statut": t.statut,
                    "statut_label": labels_statut.get(t.statut, t.statut),
                    "progres": t.progres,
                    "date_cloture": (
                        date_cloture.strftime("%d/%m/%Y %H:%M") if date_cloture else ""
                    ),
                    "date_cloture_iso": (
                        date_cloture.isoformat() if date_cloture else ""
                    ),
                    "echeance": t.echeance.isoformat() if t.echeance else "",
                    "nb_objectifs": len(objectifs),
                    "nb_atteints": nb_atteints,
                    "objectifs": objectifs,
                    "nb_livrables": len(livrables),
                    "livrables": livrables,
                    "evolutions": evolutions,
                    "auteur_nom": (
                        f"{t.cree_par.prenom} {t.cree_par.nom}"
                        if t.cree_par_id else ""
                    ),
                }
            )
        taches_edit.append(
            {
                "pk": t.pk,
                "titre": t.titre,
                "description": t.description,
                "assignee_id": t.assignee_id,
                "projet_id": t.projet_id,
                "priorite": t.priorite,
                "echeance": t.echeance.isoformat() if t.echeance else "",
                "statut": t.statut,
                "objectifs": [
                    {"pk": o.pk, "libelle": o.libelle} for o in t.objectifs.all()
                ],
            }
        )

    charge = dict(
        Tache.objects.filter(societe=societe, statut__in=["A_FAIRE", "EN_COURS"])
        .values_list("assignee").annotate(n=Count("id"))
    )
    employees = [
        {"pk": e.pk, "nom": f"{e.prenom} {e.nom}",
         "fonction": e.fonction.nom if e.fonction_id else "",
         "statut": e.statut, "charge": charge.get(e.pk, 0)}
        for e in societe.employes.select_related("fonction").order_by("prenom", "nom")
    ]
    colonnes_liste = [
        {"key": cle, "label": label, "taches": colonnes[cle]}
        for cle, label in STATUT_TACHE_CHOICES
        if cle in ("A_FAIRE", "EN_COURS", "TERMINEE") or (cle == "ANNULEE" and est_createur)
    ]
    nb_total_taches = sum(len(v) for v in colonnes.values())
    # Espace historique : filtre « terminées / annulées », tri par clôture.
    hstatut = (request.GET.get("hstatut") or "").strip().upper()
    if hstatut not in ("TERMINEE", "ANNULEE"):
        hstatut = ""
    historique_visibles = [
        h for h in historique if (not hstatut or h["statut"] == hstatut)
    ]
    historique_visibles.sort(key=lambda x: x["date_cloture_iso"], reverse=True)
    # Le rapport et le kanban ne montrent que les tâches en cours ; les tâches
    # clôturées (terminées / annulées) vivent uniquement dans l'historique.
    rapport_actif = [r for r in rapport if r["statut"] in ("A_FAIRE", "EN_COURS")]
    ctx.update(
        {
            "colonnes": colonnes_liste,
            "employes": employees,
            "projets": [
                {
                    "pk": p.pk,
                    "nom": p.nom,
                    "client_nom": p.client.nom if p.client_id else "",
                }
                for p in societe.projets.select_related("client").order_by("nom")
            ],
            "priorites": PRIORITE_TACHE_CHOICES,
            "statuts": STATUT_TACHE_CHOICES,
            "rapport": rapport_actif,
            "historique": historique_visibles,
            "hstatut": hstatut,
            "nb_histo_terminees": sum(1 for h in historique if h["statut"] == "TERMINEE"),
            "nb_histo_annulees": sum(1 for h in historique if h["statut"] == "ANNULEE"),
            "avancement_moyen": (
                round(sum(r["progres"] for r in rapport_actif) / len(rapport_actif))
                if rapport_actif else 0
            ),
            "nb_rapport_actives": len(rapport_actif),
            "livrables_rapport": sorted(
                livrables_rapport,
                key=lambda x: x["date_depot_iso"],
                reverse=True,
            ),
            "nb_pdf_rapport": sum(1 for x in livrables_rapport if x["est_pdf"]),
            "taches_edit": taches_edit,
            "est_createur": est_createur,
            "nb_a_faire": len(colonnes["A_FAIRE"]),
            "nb_en_cours": len(colonnes["EN_COURS"]),
            "nb_terminees": len(colonnes["TERMINEE"]),
            "nb_annulees": len(colonnes["ANNULEE"]),
            "nb_total": nb_total_taches,
            "filtre_employe": filtres_employe,
            "my_employe_pk": mon_employe.pk if mon_employe else "",
            "est_employe": not est_createur,
        }
    )
    return render(request, "gestion/taches.html", ctx)


@login_required
def tache_livrable_fichier(request, pk):
    """Téléchargement protégé d'un livrable de tâche.

    Seuls le déposant, l'employé attributaire de la tâche et le propriétaire de
    la société peuvent lire le fichier. Il vit hors de MEDIA_ROOT (dans
    TACHE_MEDIA_ROOT) et n'est donc jamais exposé via MEDIA_URL.
    """
    societe, _, resp = _societe_context(request, "taches")
    if resp:
        return resp
    livrable = TacheLivrable.objects.filter(
        pk=pk, tache__societe=societe
    ).select_related("tache", "employe", "tache__assignee").first()
    if livrable is None or not livrable.fichier:
        raise Http404("Fichier introuvable.")
    if not services.est_createur(request.user, societe):
        moi = services.employe_pour_utilisateur(request.user, societe)
        if moi is None or (
            moi.pk != livrable.employe_id and moi.pk != livrable.tache.assignee_id
        ):
            raise Http404("Fichier introuvable.")
    full = os.path.join(str(settings.TACHE_MEDIA_ROOT), livrable.fichier)
    if not os.path.isfile(full):
        raise Http404("Fichier introuvable.")
    ftype = livrable.type_fichier or "application/octet-stream"
    fh = open(full, "rb")
    resp = FileResponse(fh, content_type=ftype)
    inline = ftype.startswith("image/") or ftype.startswith("audio/")
    resp["Content-Disposition"] = (
        ("inline" if inline else "attachment")
        + f"; filename*=UTF-8''{quote(livrable.nom_fichier)}"
    )
    return resp


def _equipe_message_dict(msg):
    """Sérialisation d'un message d'équipe (JSON)."""
    return {
        "pk": msg.pk,
        "employe": msg.employe_id,
        "conversation": msg.conversation_id,
        "groupe": msg.groupe_id,
        "auteur": msg.auteur_id,
        "auteur_nom": f"{msg.auteur.prenom} {msg.auteur.nom}".strip(),
        "contenu": msg.contenu,
        "fichier": msg.fichier,
        "fichier_nom": msg.fichier_nom,
        "fichier_type": msg.fichier_type,
        "fichier_url": reverse("gestion:chat_fichier", args=[msg.pk]) if msg.fichier else "",
        "lu": msg.lu,
        "created_at": timezone.localtime(msg.created_at).isoformat(),
    }


ALLOWED_CHAT_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    # Notes vocales (MediaRecorder : webm/ogg sur Chrome/Firefox, mp4 sur Safari).
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
}
MAX_CHAT_FILE_MB = 15


def _chat_fichier_mime(ext):
    return ALLOWED_CHAT_EXT.get(ext, "")


def _store_chat_fichier(upload, societe_id):
    """Enregistre une pièce jointe dans CHAT_MEDIA_ROOT. Retourne (rel, nom, mime)."""
    nom_original = os.path.basename(upload.name or "")
    ext = os.path.splitext(nom_original.lower())[1]
    mime = _chat_fichier_mime(ext)
    if not mime:
        raise ValueError("Type de fichier non autorisé.")
    upload.seek(0, os.SEEK_END)
    taille = upload.tell()
    upload.seek(0)
    if taille > MAX_CHAT_FILE_MB * 1024 * 1024:
        raise ValueError(f"Fichier trop volumineux (maximum {MAX_CHAT_FILE_MB} Mo).")
    rel = os.path.join("chat", str(societe_id), f"{uuid.uuid4().hex}{ext}")
    full = os.path.join(str(settings.CHAT_MEDIA_ROOT), rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)
    return rel, nom_original[:150], mime


def _store_tache_livrable(upload, societe_id, tache_id):
    """Enregistre un livrable de tâche dans TACHE_MEDIA_ROOT. Retourne (rel, nom, mime)."""
    nom_original = os.path.basename(upload.name or "")
    ext = os.path.splitext(nom_original.lower())[1]
    mime = _chat_fichier_mime(ext)
    if not mime:
        raise ValueError("Type de fichier non autorisé.")
    upload.seek(0, os.SEEK_END)
    taille = upload.tell()
    upload.seek(0)
    if taille > MAX_CHAT_FILE_MB * 1024 * 1024:
        raise ValueError(f"Fichier trop volumineux (maximum {MAX_CHAT_FILE_MB} Mo).")
    rel = os.path.join(
        "livrables", str(societe_id), str(tache_id), f"{uuid.uuid4().hex}{ext}"
    )
    full = os.path.join(str(settings.TACHE_MEDIA_ROOT), rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)
    return rel, nom_original[:150], mime


def _delete_tache_livrable_fichier(rel):
    """Supprime physiquement un fichier livrable (best-effort)."""
    if not rel:
        return
    full = os.path.join(str(settings.TACHE_MEDIA_ROOT), rel)
    try:
        if os.path.isfile(full):
            os.remove(full)
    except OSError:
        pass


def _parse_message_request(request):
    """Retourne (contenu, fichier) depuis un POST JSON ou multipart."""
    if (request.content_type or "").startswith("application/json"):
        try:
            data = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            data = {}
        return (data.get("contenu") or "").strip(), None
    return (request.POST.get("contenu") or "").strip(), request.FILES.get("fichier")


def _contrepartie_conversation(request, societe, employe):
    """Compte avec qui discuter quand on ouvre la fiche d'un employé.

    Un employé qui ouvre sa propre fiche discute avec le propriétaire. Sinon
    on discute avec le compte relié à l'employé. Retourne (compte, est_soi).
    """
    cible = employe.compte
    if (
        cible is not None
        and cible.pk == request.user.pk
        and societe.createur_id != request.user.pk
    ):
        return societe.createur, True
    return cible, False


@login_required
def employe_messages(request, pk):
    """Messagerie d'un employé : conversation privée à deux participants."""
    societe, _, resp = _societe_context(request, "employes", ecriture=False)  # messagerie : pas une modification du module
    if resp:
        return resp
    employe = societe.employes.filter(pk=pk).first()
    if employe is None:
        return JsonResponse({"error": "Employé introuvable."}, status=404)

    # Chat ouvert à tous les employés : avec une fiche sans compte, le fil reste
    # « en attente » et sera délivré dès que la fiche reçoit un compte.
    contrepartie, _ = _contrepartie_conversation(request, societe, employe)
    if contrepartie is not None:
        conversation = services.conversation_entre(
            societe, request.user, contrepartie
        )
    else:
        conversation = services.conversation_pour_fiche(
            societe, request.user, employe, creer=(request.method == "POST")
        )
    if conversation is not None:
        filtre = {"conversation": conversation}
    else:
        filtre = {"societe": societe, "employe": employe, "pk__in": []}

    if request.method == "POST":
        if conversation is None:
            conversation = services.conversation_pour_fiche(
                societe, request.user, employe, creer=True
            )
        contenu, fichier = _parse_message_request(request)
        if not contenu and not fichier:
            return JsonResponse({"error": "Message vide."}, status=400)
        fichier_path, fichier_nom, fichier_mime = "", "", ""
        if fichier:
            try:
                fichier_path, fichier_nom, fichier_mime = _store_chat_fichier(
                    fichier, societe_id=societe.pk
                )
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)
        msg = EquipeMessage.objects.create(
            societe=societe,
            employe=employe,
            conversation=conversation,
            auteur=request.user,
            contenu=contenu[:4000],
            fichier=fichier_path,
            fichier_nom=fichier_nom,
            fichier_type=fichier_mime,
        )
        services.journaliser(
            societe,
            "MESSAGE",
            "equipe",
            f"{employe.prenom} {employe.nom}",
            "",
            request.user,
        )
        return JsonResponse({"message": _equipe_message_dict(msg)})

    msgs = EquipeMessage.objects.filter(**filtre)
    return JsonResponse(
        {
            "employe": {
                "pk": employe.pk,
                "nom": f"{employe.prenom} {employe.nom}".strip(),
                "photo": employe.photo_profil or "",
            },
            "messages": [_equipe_message_dict(m) for m in msgs],
        }
    )


def _groupe_dict(groupe, request=None):
    peut_admin = bool(request) and services.peut_administrer_groupe(request.user, groupe.societe, groupe)
    return {
        "peut_admin": peut_admin,
        "description": groupe.description,
        "admins": list(groupe.membres.filter(est_admin=True).values_list("employe_id", flat=True)),
        "pk": groupe.pk,
        "titre": groupe.titre,
        "nb_membres": groupe.membres.count(),
        "nb_messages": groupe.messages.count(),
        "logo": groupe.logo,
        "logo_url": (
            reverse("gestion:chat_groupe_logo", args=[groupe.pk]) if groupe.logo else ""
        ),
        "membres": list(groupe.membres.values_list("employe_id", flat=True)),
    }


@login_required
def groupes(request):
    """Groupes de discussion : GET = liste, POST = création (JSON)."""
    societe, _, resp = _societe_context(request, "groupes")
    if resp:
        return resp

    if request.method == "POST" and not services.peut_creer_groupe(request.user, societe):
        return JsonResponse(
            {"error": "Vous n'avez pas la permission de créer un groupe."}, status=403
        )

    if request.method == "POST":
        try:
            data = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            data = {}
        titre = (data.get("titre") or "").strip()
        if not titre:
            return JsonResponse({"error": "Le titre du groupe est requis."}, status=400)
        if len(titre) > 120:
            titre = titre[:120]
        membres = data.get("membres") or []
        if not isinstance(membres, list):
            return JsonResponse({"error": "Liste de membres invalide."}, status=400)
        disponibles = {
            e.pk
            for e in societe.employes.filter(
                pk__in=[int(pk) for pk in membres if str(pk).isdigit()]
            )
        }
        if not disponibles:
            return JsonResponse(
                {"error": "Sélectionnez au moins un employé."}, status=400
            )
        groupe = EquipeGroupe.objects.create(
            societe=societe, titre=titre, cree_par=request.user,
            description=str(data.get("description") or "").strip()[:255],
        )
        # Le créateur (employé) fait partie du groupe et l'administre
        moi = services.employe_pour_utilisateur(request.user, societe)
        if moi is not None and not services.est_createur(request.user, societe):
            disponibles.add(moi.pk)
        admins = {int(a) for a in (data.get("admins") or []) if str(a).isdigit()}
        if moi is not None:
            admins.add(moi.pk)
        EquipeGroupeMembre.objects.bulk_create(
            [
                EquipeGroupeMembre(groupe=groupe, employe_id=pk, est_admin=pk in admins)
                for pk in sorted(disponibles)
            ]
        )
        services.journaliser(
            societe,
            "CREATION",
            "equipe",
            f"Groupe — {groupe.titre}",
            f"{len(disponibles)} membre(s)",
            request.user,
        )
        return JsonResponse({"groupe": _groupe_dict(groupe, request)})

    groupes = services.groupes_visibles(request.user, societe).prefetch_related("membres")
    return JsonResponse({"groupes": [_groupe_dict(g, request) for g in groupes]})


@login_required
def groupe_messages(request, pk):
    """Messages d'un groupe : GET = historique, POST = envoi (JSON)."""
    societe, _, resp = _societe_context(request, "employes")
    if resp:
        return resp
    groupe = societe.equipe_groupes.filter(pk=pk).first()
    if groupe is None:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)
    if not services.est_membre_groupe(request.user, societe, groupe):
        return JsonResponse({"error": "Accès non autorisé."}, status=403)

    if request.method == "POST":
        contenu, fichier = _parse_message_request(request)
        if not contenu and not fichier:
            return JsonResponse({"error": "Message vide."}, status=400)
        fichier_path, fichier_nom, fichier_mime = "", "", ""
        if fichier:
            try:
                fichier_path, fichier_nom, fichier_mime = _store_chat_fichier(
                    fichier, societe_id=societe.pk
                )
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)
        msg = EquipeMessage.objects.create(
            societe=societe,
            groupe=groupe,
            auteur=request.user,
            contenu=contenu[:4000],
            fichier=fichier_path,
            fichier_nom=fichier_nom,
            fichier_type=fichier_mime,
        )
        services.journaliser(
            societe,
            "MESSAGE",
            "equipe",
            f"Groupe — {groupe.titre}",
            "",
            request.user,
        )
        return JsonResponse({"message": _equipe_message_dict(msg)})

    return JsonResponse(
        {
            "groupe": _groupe_dict(groupe, request),
            "messages": [
                _equipe_message_dict(m)
                for m in EquipeMessage.objects.filter(societe=societe, groupe=groupe)
            ],
        }
    )


@login_required
def employe_delete(request, pk):
    if request.method == "POST":
        societe, _, resp = _societe_context(request, "employes")
        if resp:
            return resp
        if not services.est_createur(request.user, societe):
            return HttpResponseForbidden("Action réservée au propriétaire.")
        emp = societe.employes.filter(pk=pk).first()
        periods = set()
        if emp:
            for s in emp.paiements_salaire.all():
                if s.periode_mois:
                    periods.add(s.periode_mois)
                if s.date_paiement:
                    periods.add(s.date_paiement)
            # Les dépenses générées par les salaires de l'employé partent avec lui.
            DepenseSociete.objects.filter(paiement_salaire__employe=emp).delete()
            emp.delete()
            services.journaliser(
                societe,
                "SUPPRESSION",
                "employes",
                f"{emp.prenom} {emp.nom}",
                "",
                request.user,
            )
            for p in periods:
                services.recalculer_finances(societe, p)
    return redirect(reverse("gestion:employes") + "?deleted=1")


@login_required
def clients(request):
    """Liste + création / modification des clients (drawer droit)."""
    societe, ctx, resp = _societe_context(request, "clients")
    if resp:
        return resp

    obj_id = request.POST.get("id") or None
    instance = societe.clients.filter(pk=obj_id).first() if obj_id else None
    form = ClientForm(
        request.POST or None,
        request.FILES or None,
        instance=instance,
        societe=societe,
    )
    if request.method == "POST" and form.is_valid():
        client = form.save(commit=False)
        client.societe = societe
        if instance is None and client.cree_par_id is None:
            client.cree_par = request.user
        client.save()
        if form.cleaned_data.get("logo"):
            client.logo = _store_upload(
                form.cleaned_data["logo"], "clients/logos", client.nom
            )
            client.save(update_fields=["logo"])
        if form.cleaned_data.get("document"):
            ClientDocument.objects.create(
                client=client,
                type_document="DOCUMENT",
                fichier=fichiers_prives.stocker(form.cleaned_data["document"], "clients/documents", client.nom
                ),
            )
        services.journaliser(
            societe,
            "MODIFICATION" if obj_id else "CREATION",
            "clients",
            client.nom,
            "",
            request.user,
        )
        return redirect(reverse("gestion:clients") + "?ok=1")

    items = []
    sans_logo = 0
    autorises = set(ctx["modules_autorises"] or [])
    clients_liste = list(societe.clients.select_related("type_client"))
    suivi = {}
    for c in clients_liste:
        suivi[c.pk] = services.suivi_client(c, autorises)
    for c in clients_liste:
        if not c.logo:
            sans_logo += 1
        sx = suivi.get(c.pk, {})
        items.append(
            {
                "pk": c.pk,
                "nom": c.nom,
                "logo": c.logo or "",
                "type_client": c.type_client_id if c.type_client else "",
                "type_nom": c.type_client.nom if c.type_client else "",
                "email": c.email or "",
                "telephone_1": c.telephone_1,
                "telephone_2": c.telephone_2 or "",
                "adresse": c.adresse or "",
                "ville": c.ville or "",
                "pays": geographie.nom_fr(c.pays) if c.pays and geographie.est_connu(c.pays) else (c.pays or ""),
                "statut": c.statut,
                "source": c.source or "",
                "responsable": c.responsable_id or "",
                "responsable_nom": (
                    f"{c.responsable.prenom} {c.responsable.nom}".strip()
                    if c.responsable_id else ""
                ),
                "n_documents": c.documents.count(),
                "del_url": "{}".format(c.pk),
                "del_name": c.nom,
                "acces_projets": bool(sx.get("acces", {}).get("projets")),
                "acces_taches": bool(sx.get("acces", {}).get("taches")),
                "acces_employes": bool(sx.get("acces", {}).get("employes")),
                "acces_echeances": bool(sx.get("acces", {}).get("echeances")),
                "acces_prospection": bool(sx.get("acces", {}).get("prospection")),
                "n_projets": sx.get("n_projets", 0),
                "n_taches": sx.get("n_taches", 0),
                "progression": sx.get("progression", 0),
                "suivi": sx,
            }
        )
    items_js = [
        {
            "pk": it["pk"],
            "nom": it["nom"],
            "logo": it["logo"],
            "type_client": it["type_client"],
            "type_nom": it["type_nom"],
            "email": it["email"],
            "telephone_1": it["telephone_1"],
            "telephone_2": it["telephone_2"],
            "adresse": it["adresse"],
            "ville": it["ville"],
            "pays": it["pays"],
            "statut": it["statut"],
            "source": it["source"],
            "responsable": it["responsable"],
            "n_documents": it["n_documents"],
            "del_url": it["del_url"],
            "del_name": it["del_name"],
        }
        for it in items
    ]
    ctx["form"] = form
    ctx["items"] = items
    ctx["items_js"] = items_js
    ctx["villes_par_pays"] = geographie.villes_par_pays()
    ctx["sans_logo"] = sans_logo
    ctx["acces_prospection"] = "prospection" in autorises
    if ctx["acces_prospection"]:
        pros_qs = societe.prospections.select_related("responsable")
        prospect_objs = list(pros_qs)
        compteurs = {st[0]: 0 for st in PROSPECTION_STATUT_CHOICES}
        for p in prospect_objs:
            compteurs[p.statut] = compteurs.get(p.statut, 0) + 1
        ctx["prospection"] = {
            "url": reverse("gestion:crud", args=["prospection"]),
            "total": len(prospect_objs),
            "statuts": [
                {
                    "code": code,
                    "label": str(label),
                    "count": compteurs.get(code, 0),
                }
                for code, label in PROSPECTION_STATUT_CHOICES
            ],
            "prospects": [
                {
                    "nom": p.nom,
                    "statut": p.statut,
                    "statut_label": p.get_statut_display(),
                    "responsable_nom": f"{p.responsable.prenom} {p.responsable.nom}".strip()
                    if p.responsable else "",
                    "budget": services.montant_display(p.budget_estime) if p.budget_estime else "",
                }
                for p in prospect_objs[:6]
            ],
        }
    return render(request, "gestion/crud_clients.html", ctx)


@login_required
def client_delete(request, pk):
    if request.method == "POST":
        societe, _, resp = _societe_context(request, "clients")
        if resp:
            return resp
        obj = societe.clients.filter(pk=pk).first()
        nom = obj.nom if obj else ""
        societe.clients.filter(pk=pk).delete()
        if nom:
            services.journaliser(
                societe, "SUPPRESSION", "clients", nom, "", request.user
            )
    return redirect(reverse("gestion:clients") + "?deleted=1")


@login_required
def client_creer_mini(request):
    """Création rapide d'un client depuis le tiroir Projets (réponse JSON)."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST requis."}, status=405)
    societe, _, resp = _societe_context(request, "clients")
    if resp:
        return JsonResponse({"ok": False, "message": "Accès refusé."}, status=403)
    form = ClientForm(request.POST, request.FILES, societe=societe)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": form.errors.get_json_data()}, status=400
        )
    client = form.save(commit=False)
    client.societe = societe
    if client.cree_par_id is None:
        client.cree_par = request.user
    client.save()
    if form.cleaned_data.get("logo"):
        client.logo = _store_upload(
            form.cleaned_data["logo"], "clients/logos", client.nom
        )
        client.save(update_fields=["logo"])
    if form.cleaned_data.get("document"):
        ClientDocument.objects.create(
            client=client,
            type_document="DOCUMENT",
            fichier=fichiers_prives.stocker(form.cleaned_data["document"], "clients/documents", client.nom
            ),
        )
    services.journaliser(
        societe, "CREATION", "clients", client.nom, "", request.user
    )
    return JsonResponse({"ok": True, "pk": client.pk, "nom": client.nom})


@login_required
def fonction_creer(request):
    """Création rapide d'une fonction depuis un sélecteur (réponse JSON)."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST requis."}, status=405)
    societe, _, resp = _societe_context(request, "employes")
    if resp:
        return JsonResponse({"ok": False, "message": "Accès refusé."}, status=403)
    nom = (request.POST.get("nom") or "").strip()[:150]
    if not nom:
        return JsonResponse({"ok": False, "message": "Le nom est obligatoire."}, status=400)
    fonction = Fonction.objects.filter(societe=societe, nom__iexact=nom).first()
    if fonction is None:
        fonction = Fonction.objects.create(societe=societe, nom=nom)
        services.journaliser(
            societe,
            "CREATION",
            "employes",
            f"Fonction « {fonction.nom} »",
            "",
            request.user,
        )
    return JsonResponse({"ok": True, "pk": fonction.pk, "label": fonction.nom})


@login_required
def type_client_creer(request):
    """Création rapide d'un type de client depuis un sélecteur (réponse JSON)."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST requis."}, status=405)
    societe, _, resp = _societe_context(request, "clients")
    if resp:
        return JsonResponse({"ok": False, "message": "Accès refusé."}, status=403)
    nom = (request.POST.get("nom") or "").strip()[:100]
    if not nom:
        return JsonResponse({"ok": False, "message": "Le nom est obligatoire."}, status=400)
    type_client, created = TypeClient.objects.get_or_create(nom=nom)
    if created:
        services.journaliser(
            societe,
            "CREATION",
            "clients",
            f"Type de client « {type_client.nom} »",
            "",
            request.user,
        )
    return JsonResponse({"ok": True, "pk": type_client.pk, "label": type_client.nom})


@login_required
def projets(request):
    """Liste + création / modification des projets (drawer droit)."""
    societe, ctx, resp = _societe_context(request, "projets")
    if resp:
        return resp

    obj_id = request.POST.get("id") or None
    instance = societe.projets.filter(pk=obj_id).first() if obj_id else None
    form = ProjetForm(
        request.POST or None,
        instance=instance,
        societe=societe,
    )
    if request.method == "POST" and form.is_valid():
        form.instance.societe = societe
        projet = form.save()
        services.journaliser(
            societe,
            "MODIFICATION" if obj_id else "CREATION",
            "projets",
            projet.nom,
            "",
            request.user,
        )
        return redirect(reverse("gestion:projets") + "?ok=1")

    items = []
    projs = societe.projets.select_related("client").prefetch_related(
        Prefetch(
            "chefs",
            queryset=ProjetChef.objects.select_related("employe").filter(
                principal=True
            ),
            to_attr="_chefs_principaux",
        )
    )
    for p in projs:
        chef = p._chefs_principaux[0] if p._chefs_principaux else None
        chef_nom = ""
        chef_pk = ""
        chef_sigle = ""
        if chef is not None:
            chef_nom = f"{chef.employe.prenom} {chef.employe.nom}".strip()
            chef_pk = str(chef.employe_id)
            chef_sigle = (
                f"{chef.employe.prenom[:1]}{chef.employe.nom[:1]}".upper()
                if chef.employe
                else ""
            )
        items.append(
            {
                "pk": p.pk,
                "nom": p.nom,
                "client": p.client_id if p.client else "",
                "client_nom": p.client.nom if p.client else "",
                "description": p.description or "",
                "date_debut": p.date_debut.isoformat() if p.date_debut else "",
                "date_fin": p.date_fin.isoformat() if p.date_fin else "",
                "budget": str(p.budget),
                "statut": p.statut,
                "responsable": chef_pk,
                "responsable_nom": chef_nom,
                "responsable_sigle": chef_sigle,
                "del_url": "{}".format(p.pk),
                "del_name": p.nom,
            }
        )
    ctx["form"] = form
    ctx["items"] = items
    mini_form = ClientForm(societe=societe)
    for fname in ("nom", "type_client", "source", "responsable", "telephone_1", "email", "statut"):
        mini_form.fields[fname].widget.attrs["id"] = f"mini_{fname}"
    ctx["mini_client_form"] = mini_form
    return render(request, "gestion/crud_projets.html", ctx)


@login_required
def projet_delete(request, pk):
    if request.method == "POST":
        societe, _, resp = _societe_context(request, "projets")
        if resp:
            return resp
        obj = societe.projets.filter(pk=pk).first()
        nom = obj.nom if obj else ""
        societe.projets.filter(pk=pk).delete()
        if nom:
            services.journaliser(
                societe, "SUPPRESSION", "projets", nom, "", request.user
            )
    return redirect(reverse("gestion:projets") + "?deleted=1")


@login_required
def finances(request):
    """Finances : tableau de bord récap (recettes, dépenses, salaires, solde)."""
    societe, ctx, resp = _societe_context(request, "finances")
    if resp:
        return resp

    # Mois sélectionné (défaut : mois courant), format « YYYY-MM ».
    periode = timezone.localdate().replace(day=1)
    mois_param = (request.GET.get("m") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", mois_param):
        try:
            y, m = mois_param.split("-")
            periode = periode.replace(year=int(y), month=int(m))
        except (TypeError, ValueError):
            pass
    debut, fin = _month_bounds(periode)

    def _sum_montant(qs, champ="montant"):
        return qs.aggregate(total=Sum(champ))["total"] or 0

    recettes_qs = PaiementClient.objects.filter(
        projet__societe=societe,
        date_paiement__gte=debut,
        date_paiement__lt=fin,
        statut="CONFIRME",
    )
    depenses_qs = DepenseSociete.objects.filter(
        societe=societe,
        date_depense__gte=debut,
        date_depense__lt=fin,
        statut="CONFIRME",
        paiement_salaire__isnull=True,
    )
    salaires_payes_qs = PaiementSalaire.objects.filter(
        employe__societe=societe,
        date_paiement__gte=debut,
        date_paiement__lt=fin,
        statut="PAYE",
    )
    salaires_prevus_qs = PaiementSalaire.objects.filter(
        employe__societe=societe,
        periode_mois__gte=debut,
        periode_mois__lt=fin,
    ).exclude(statut="PAYE")

    recettes = _sum_montant(recettes_qs)
    depenses = _sum_montant(depenses_qs)
    salaires = _sum_montant(salaires_payes_qs, "montant_paye")
    salaires_prevus = _sum_montant(salaires_prevus_qs, "montant_du")
    solde = recettes - depenses - salaires

    # Totaux cumulés (toutes périodes)
    recettes_cumul = _sum_montant(
        PaiementClient.objects.filter(projet__societe=societe, statut="CONFIRME")
    )
    depenses_cumul = _sum_montant(
        DepenseSociete.objects.filter(
            societe=societe, statut="CONFIRME", paiement_salaire__isnull=True
        )
    )
    salaires_cumul = _sum_montant(
        PaiementSalaire.objects.filter(employe__societe=societe, statut="PAYE"),
        "montant_paye",
    )

    # Historique des 6 derniers mois (jusqu'au mois sélectionné)
    historique = []
    annee, mois = periode.year, periode.month
    for _ in range(6):
        debut_m, fin_m = _month_bounds(date(annee, mois, 1))
        r = _sum_montant(
            PaiementClient.objects.filter(
                projet__societe=societe,
                date_paiement__gte=debut_m,
                date_paiement__lt=fin_m,
                statut="CONFIRME",
            )
        )
        d = _sum_montant(
            DepenseSociete.objects.filter(
                societe=societe,
                date_depense__gte=debut_m,
                date_depense__lt=fin_m,
                statut="CONFIRME",
                paiement_salaire__isnull=True,
            )
        )
        s = _sum_montant(
            PaiementSalaire.objects.filter(
                employe__societe=societe,
                date_paiement__gte=debut_m,
                date_paiement__lt=fin_m,
                statut="PAYE",
            ),
            "montant_paye",
        )
        historique.append(
            {
                "label": debut_m.strftime("%m/%Y"),
                "recettes": r,
                "depenses": d,
                "salaires": s,
                "solde": r - d - s,
            }
        )
        mois -= 1
        if mois == 0:
            mois = 12
            annee -= 1

    # Graphique « Flux sur 6 mois » (entrées vs sorties) et répartition des sorties.
    MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    flux = []
    for h in reversed(historique):
        m, a = (int(x) for x in h["label"].split("/"))
        flux.append({
            "label": f"{MOIS_COURTS[m - 1]} {str(a)[2:]}",
            "entrees": float(h["recettes"]),
            "sorties": float(h["depenses"]) + float(h["salaires"]),
            "solde": float(h["solde"]),
            "courant": (a, m) == (periode.year, periode.month),
        })
    haut = max([1.0] + [max(f["entrees"], f["sorties"]) for f in flux])
    for f in flux:
        # Chaînes : évite la virgule décimale française dans le CSS.
        f["pct_e"] = f"{f['entrees'] * 100 / haut:.1f}"
        f["pct_s"] = f"{f['sorties'] * 100 / haut:.1f}"
        f["entrees_aff"] = stats.argent(f["entrees"])
        f["sorties_aff"] = stats.argent(f["sorties"])
    fin_flux = {
        "mois": flux,
        "ticks": [{"pct": p, "value": stats.argent(haut * p / 100)} for p in (100, 75, 50, 25, 0)],
        "total_e": stats.argent(sum(f["entrees"] for f in flux)),
        "total_s": stats.argent(sum(f["sorties"] for f in flux)),
    }
    parts = [
        ("Dépenses", float(depenses), "#e11d48"),
        ("Salaires payés", float(salaires), "#4f46e5"),
        ("Salaires à payer", float(salaires_prevus), "#f59e0b"),
    ]
    total_parts = sum(v for _, v, _ in parts)
    segments, decalage = [], 25.0
    for label, v, couleur in parts:
        part = v * 100 / total_parts if total_parts else 0
        segments.append({
            "label": label, "color": couleur, "value": v, "value_aff": stats.argent(v),
            "pct": round(part), "dash": f"{part:.2f}", "gap": f"{100 - part:.2f}",
            "offset": f"{decalage:.2f}",
        })
        decalage -= part
    fin_donut = {"segments": segments, "total": stats.argent(total_parts)}

    fin_cartes = stats.cartes_finances(
        historique,
        {"recettes": recettes, "depenses": depenses, "salaires": salaires,
         "salaires_prevus": salaires_prevus, "solde": solde},
        {"recettes": recettes_cumul, "depenses": depenses_cumul,
         "salaires": salaires_cumul,
         "solde": recettes_cumul - depenses_cumul - salaires_cumul},
    )

    # Synthèse mensuelle matérialisée (utilisée par l'admin et le solde)
    _recalculer_finances(societe, periode)

    # Portefeuille KPay (soldes des wallets) + opérations Mobile Money récentes.
    # Lecture seule : la page reste fonctionnelle si KPay est indisponible.
    kpay_soldes = []
    kpay_erreur = ""
    if kpay.configuree():
        ok, data = kpay.solde_wallets()
        if ok and isinstance(data, list):
            kpay_soldes = data
        elif isinstance(data, dict):
            kpay_erreur = data.get("message") or ""
    kpay_operations = list(
        societe.kpay_operations.select_related(
            "paiement", "echeance", "salaire", "salaire__employe"
        )[:12]
    )

    mois_prec = (debut - timedelta(days=1)).replace(day=1)
    mois_suiv = fin

    ctx.update(
        {
            "periode": periode,
            "mois_value": periode.strftime("%Y-%m"),
            "mois_label": "{} {}".format(
                ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                 "septembre", "octobre", "novembre", "décembre"][periode.month - 1],
                periode.year,
            ),
            "mois_prec": mois_prec.strftime("%Y-%m"),
            "mois_suiv": mois_suiv.strftime("%Y-%m"),
            "kpis": {
                "recettes": recettes,
                "depenses": depenses,
                "salaires": salaires,
                "salaires_prevus": salaires_prevus,
                "solde": solde,
            },
            "cumuls": {
                "recettes": recettes_cumul,
                "depenses": depenses_cumul,
                "salaires": salaires_cumul,
                "solde": recettes_cumul - depenses_cumul - salaires_cumul,
            },
            "historique": historique,
            "fin_cartes_mois": fin_cartes[0],
            "fin_flux": fin_flux,
            "fin_donut": fin_donut,
            "fin_cartes_cumul": fin_cartes[1],
            "kpay_configuree": kpay.configuree(),
            "kpay_soldes": kpay_soldes,
            "kpay_erreur": kpay_erreur,
            "kpay_operations": kpay_operations,
            "recettes_recentes": recettes_qs.select_related("projet", "mode_paiement")[
                :8
            ],
            "depenses_recentes": depenses_qs.select_related("type_depense")[:8],
            "salaires_mois": PaiementSalaire.objects.filter(
                employe__societe=societe,
                periode_mois__gte=debut,
                periode_mois__lt=fin,
            ).select_related("employe"),
        }
    )
    return render(request, "gestion/finances.html", ctx)


@login_required
def salaire_payer(request, pk):
    """Valide un salaire comme payé : statut PAYE + comptabilisation en dépense."""
    if request.method != "POST":
        return redirect(reverse("gestion:crud", args=["salaires"]))
    societe, _, resp = _societe_context(request, "salaires")
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return HttpResponseForbidden("Action non autorisée.")
    salaire = PaiementSalaire.objects.filter(
        pk=pk, employe__societe=societe
    ).first()
    if salaire:
        date_paiement = parse_date(request.POST.get("date_paiement") or "") or None
        salaire.date_paiement = date_paiement or timezone.localdate()
        salaire.statut = "PAYE"
        if not salaire.montant_paye:
            salaire.montant_paye = salaire.montant_du
        salaire.save(update_fields=["date_paiement", "statut", "montant_paye"])
        services.sync_depense_salaire(societe, salaire)
        services.journaliser(
            societe,
            "VALIDATION",
            "salaires",
            f"{salaire.employe.prenom} {salaire.employe.nom}",
            f"Montant payé : {salaire.montant_paye}",
            request.user,
        )
        return redirect(reverse("gestion:crud", args=["salaires"]) + "?paye=1")
    return redirect(reverse("gestion:crud", args=["salaires"]))


@login_required
def echeance_payer(request, pk):
    """Valide une échéance comme payée : statut PAYEE + encaissement enregistré."""
    if request.method != "POST":
        return redirect(reverse("gestion:crud", args=["echeances"]))
    societe, _, resp = _societe_context(request, "echeances")
    if resp:
        return resp
    echeance = EcheancePaiement.objects.filter(
        pk=pk, projet__societe=societe
    ).first()
    if echeance:
        date_paiement = parse_date(request.POST.get("date_paiement") or "") or None
        echeance.statut = "PAYEE"
        echeance.save(update_fields=["statut"])
        services.sync_paiement_from_echeance(
            societe, echeance, date_paiement=date_paiement
        )
        services.journaliser(
            societe,
            "PAIEMENT",
            "echeances",
            str(echeance),
            f"Encaissement validé : {echeance.montant_prevu}",
            request.user,
        )
        return redirect(reverse("gestion:crud", args=["echeances"]) + "?paye=1")
    return redirect(reverse("gestion:crud", args=["echeances"]))


# ---------------------------------------------------------------------------
# KPay (Mobile Money) — encaissements, retraits, suivi et webhooks
# ---------------------------------------------------------------------------


def _appliquer_statut_kpay(societe, operation, data, utilisateur=None):
    """Rejoue le statut renvoyé par KPay sur une opération et comptabilise."""
    statut = str(data.get("status") or operation.statut).upper()
    operation.reference = data.get("reference") or operation.reference
    operation.provider_reference = (
        data.get("providerReference") or operation.provider_reference
    )
    operation.montant = data.get("amount") or operation.montant
    operation.montant_net = data.get("netAmount") or operation.montant_net
    operation.frais = data.get("feeAmount") or operation.frais
    operation.devise = data.get("currency") or operation.devise
    operation.provider = data.get("provider") or operation.provider
    operation.pays = data.get("country") or operation.pays
    operation.telephone = data.get("phoneNumber") or operation.telephone
    operation.motif_echec = (
        data.get("failureReason")
        or data.get("failureCode")
        or operation.motif_echec
    )
    operation.statut = statut
    operation.save()
    if statut == "COMPLETED":
        if operation.type_operation == "DEPOSIT":
            services.finaliser_depot_kpay(societe, operation, utilisateur)
        else:
            services.finaliser_retrait_kpay(societe, operation, utilisateur)
    elif statut in ("FAILED", "CANCELLED") and operation.type_operation == "DEPOSIT":
        # L'encaissement en attente ne devient pas une recette : il reste réservé.
        if operation.paiement_id and operation.paiement.statut == "CONFIRME":
            operation.paiement.statut = "EN_ATTENTE"
            operation.paiement.save(update_fields=["statut"])
    return operation


@login_required
def kpay_depot_echeance(request, pk):
    """Initie un encaissement Mobile Money (KPay, USSD push) pour une échéance.

    Le client reçoit une demande de validation sur son téléphone. La
    confirmation arrive par webhook (source d'autorité) ou via le bouton
    « Rafraîchir » du suivi (page Finances).
    """
    if request.method != "POST":
        return redirect(reverse("gestion:crud", args=["echeances"]))
    societe, _, resp = _societe_context(request, "echeances")
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return HttpResponseForbidden("Action non autorisée.")
    if not kpay.configuree():
        return redirect(reverse("gestion:crud", args=["echeances"]) + "?kpay_err=1")
    echeance = (
        EcheancePaiement.objects.filter(pk=pk, projet__societe=societe)
        .select_related("projet", "projet__client")
        .first()
    )
    if not echeance or echeance.statut == "PAYEE":
        return redirect(reverse("gestion:crud", args=["echeances"]))
    telephone = kpay.normaliser_telephone(request.POST.get("telephone") or "")
    provider = (request.POST.get("provider") or "").strip()
    if not telephone or not provider:
        return redirect(reverse("gestion:crud", args=["echeances"]) + "?kpay_champs=1")

    external_id = f"DEP-{societe.pk}-{echeance.pk}"  # idempotence KPay
    active = societe.kpay_operations.filter(
        type_operation="DEPOSIT",
        external_id=external_id,
        statut__in=("PENDING", "PROCESSING"),
    ).exists()
    if active:
        return redirect(reverse("gestion:crud", args=["echeances"]) + "?kpay_deja=1")

    # Encaissement EN_ATTENTE (recette en devenir) : réutilise l'existant,
    # sinon le crée — la confirmation le passera CONFIRME.
    paiement = PaiementClient.objects.filter(echeance=echeance).order_by("pk").first()
    if paiement is None:
        paiement = PaiementClient(
            projet=echeance.projet,
            echeance=echeance,
            montant=echeance.montant_prevu,
            date_paiement=timezone.localdate(),
            mode_paiement=services.mode_mobile_money(),
            reference=f"Échéance #{echeance.numero_echeance} — Mobile Money",
            statut="EN_ATTENTE",
        )
        paiement.save()

    ok, data = kpay.init_depot(
        montant=round(echeance.montant_prevu or 0),
        provider=provider,
        telephone=telephone,
        external_id=external_id,
        description=f"Échéance #{echeance.numero_echeance} — {echeance.projet.nom}",
        metadata={"societe": societe.pk, "echeance": echeance.pk},
    )
    if not ok:
        return redirect(
            reverse("gestion:crud", args=["echeances"])
            + "?kpay_erreur=" + quote(str(data.get("message") or "Erreur KPay"))
        )
    KpayOperation.objects.create(
        societe=societe,
        type_operation="DEPOSIT",
        paiement=paiement,
        echeance=echeance,
        kpay_id=str(data.get("id") or ""),
        reference=data.get("reference") or "",
        provider_reference=data.get("providerReference") or "",
        external_id=data.get("externalId") or external_id,
        statut=data.get("status") or "PENDING",
        montant=data.get("amount") or echeance.montant_prevu,
        montant_net=data.get("netAmount") or 0,
        frais=data.get("feeAmount") or 0,
        devise=data.get("currency") or "XAF",
        provider=data.get("provider") or provider,
        pays=data.get("country") or "",
        telephone=data.get("phoneNumber") or telephone,
        mode="USSD",
        is_test=bool(data.get("isTest", kpay.est_test())),
        message=data.get("message") or "",
        cree_par=request.user,
    )
    services.journaliser(
        societe,
        "PAIEMENT",
        "echeances",
        str(echeance),
        f"Encaissement Mobile Money initié ({telephone}) : {echeance.montant_prevu}",
        request.user,
    )
    return redirect(reverse("gestion:crud", args=["echeances"]) + "?kpay_dep=1")


@login_required
def kpay_payout_salaire(request, pk):
    """Initie un virement Mobile Money (KPay, USSD) pour payer un salaire."""
    if request.method != "POST":
        return redirect(reverse("gestion:crud", args=["salaires"]))
    societe, _, resp = _societe_context(request, "salaires")
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return HttpResponseForbidden("Action non autorisée.")
    if not kpay.configuree():
        return redirect(reverse("gestion:crud", args=["salaires"]) + "?kpay_err=1")
    salaire = (
        PaiementSalaire.objects.filter(pk=pk, employe__societe=societe)
        .select_related("employe")
        .first()
    )
    if not salaire or salaire.statut == "PAYE":
        return redirect(reverse("gestion:crud", args=["salaires"]))
    telephone = kpay.normaliser_telephone(
        request.POST.get("telephone") or salaire.employe.telephone_1 or ""
    )
    provider = (request.POST.get("provider") or "").strip()
    if not telephone or not provider:
        return redirect(reverse("gestion:crud", args=["salaires"]) + "?kpay_champs=1")

    external_id = f"PAY-{societe.pk}-{salaire.pk}"  # idempotence KPay
    active = societe.kpay_operations.filter(
        type_operation="PAYOUT",
        external_id=external_id,
        statut__in=("PENDING", "PROCESSING"),
    ).exists()
    if active:
        return redirect(reverse("gestion:crud", args=["salaires"]) + "?kpay_deja=1")

    montant = salaire.montant_du or salaire.montant_paye or 0
    ok, data = kpay.init_retrait(
        montant=round(montant),
        provider=provider,
        telephone=telephone,
        external_id=external_id,
        description=(
            f"Salaire {salaire.employe.prenom} {salaire.employe.nom}"
            f" — {salaire.periode_mois:%m/%Y}"
        ),
        metadata={"societe": societe.pk, "salaire": salaire.pk},
    )
    if not ok:
        return redirect(
            reverse("gestion:crud", args=["salaires"])
            + "?kpay_erreur=" + quote(str(data.get("message") or "Erreur KPay"))
        )
    KpayOperation.objects.create(
        societe=societe,
        type_operation="PAYOUT",
        salaire=salaire,
        kpay_id=str(data.get("id") or ""),
        reference=data.get("reference") or "",
        provider_reference=data.get("providerReference") or "",
        external_id=data.get("externalId") or external_id,
        statut=data.get("status") or "PENDING",
        montant=data.get("amount") or montant,
        montant_net=data.get("netAmount") or 0,
        frais=data.get("feeAmount") or 0,
        devise=data.get("currency") or "XAF",
        provider=data.get("provider") or provider,
        pays=data.get("country") or "",
        telephone=data.get("phoneNumber") or telephone,
        mode="USSD",
        is_test=bool(data.get("isTest", kpay.est_test())),
        message=data.get("message") or "",
        cree_par=request.user,
    )
    services.journaliser(
        societe,
        "VALIDATION",
        "salaires",
        f"{salaire.employe.prenom} {salaire.employe.nom}",
        f"Virement Mobile Money initié ({telephone}) : {montant}",
        request.user,
    )
    return redirect(reverse("gestion:crud", args=["salaires"]) + "?kpay_pay=1")


@login_required
def kpay_actualiser(request, pk):
    """Interroge KPay pour rafraîchir le statut d'une opération non terminale."""
    if request.method != "POST":
        return redirect(reverse("gestion:finances"))
    societe, _, resp = _societe_context(request, "finances")
    if resp:
        return resp
    operation = societe.kpay_operations.filter(pk=pk).first()
    if not operation or operation.terminal or not kpay.configuree():
        return redirect(reverse("gestion:finances") + "?kpay_ok=0")
    if operation.type_operation == "DEPOSIT":
        ok, data = kpay.statut_depot(operation.kpay_id)
    else:
        ok, data = kpay.statut_retrait(operation.kpay_id)
    if not ok:
        return redirect(reverse("gestion:finances") + "?kpay_ok=0")
    _appliquer_statut_kpay(societe, operation, data, request.user)
    return redirect(reverse("gestion:finances") + "?kpay_ok=1")


@csrf_exempt
def kpay_webhook(request):
    """Endpoint de notification KPay (payment.* et payout.*).

    - Signature HMAC-SHA256 vérifiée sur le corps BRUT (X-KPAY-Signature).
    - Met à jour l'opération puis comptabilise les statuts terminaux.
    - Répond 200 immédiatement (le traitement reste court).
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST requis."}, status=405)
    if not kpay.verifier_signature(request.body, request.headers.get("X-KPAY-Signature", "")):
        return JsonResponse({"ok": False, "message": "Signature invalide."}, status=400)
    data = kpay.charger_webhook(request.body)
    if not data:
        return JsonResponse({"ok": False, "message": "Corps JSON invalide."}, status=400)

    event = data.get("event") or ""
    kpay_id = data.get("paymentId") or data.get("payoutId") or ""
    if event.startswith("payment."):
        operation = (
            KpayOperation.objects.filter(type_operation="DEPOSIT")
            .filter(Q(kpay_id=kpay_id) | Q(external_id=data.get("externalId") or ""))
            .order_by("-created_at")
            .first()
        )
    elif event.startswith("payout."):
        operation = (
            KpayOperation.objects.filter(type_operation="PAYOUT")
            .filter(Q(kpay_id=kpay_id) | Q(external_id=data.get("externalId") or ""))
            .order_by("-created_at")
            .first()
        )
    else:
        # refund.* ou inconnu : informatif, aucune action requise.
        return JsonResponse({"ok": True, "event": event}, status=200)

    if operation is None:
        # Statut tardif ou opération hors plateforme : rien à faire, on accuse réception.
        return JsonResponse({"ok": True, "event": event, "seen": False}, status=200)

    statut = (data.get("status") or "").upper() or {
        "payment.completed": "COMPLETED",
        "payment.failed": "FAILED",
        "payment.cancelled": "CANCELLED",
        "payout.completed": "COMPLETED",
        "payout.failed": "FAILED",
        "payout.cancelled": "CANCELLED",
    }.get(event, operation.statut)
    _appliquer_statut_kpay(operation.societe, operation, {**data, "status": statut})
    return JsonResponse({"ok": True, "event": event, "seen": True}, status=200)


@login_required
def salaire_generer_mois(request):
    """Génère les salaires PREVU du mois choisi pour tous les employés actifs."""
    if request.method != "POST":
        return redirect(reverse("gestion:crud", args=["salaires"]))
    societe, _, resp = _societe_context(request, "salaires")
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return HttpResponseForbidden("Action non autorisée.")
    periode = timezone.localdate().replace(day=1)
    mois_param = (request.POST.get("mois") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", mois_param):
        try:
            y, m = mois_param.split("-")
            periode = periode.replace(year=int(y), month=int(m))
        except (TypeError, ValueError):
            pass
    crees, doublons = services.generer_salaires_mois(societe, periode)
    if crees:
        services.journaliser(
            societe,
            "CREATION",
            "salaires",
            f"{crees} salaire(s)",
            f"Période {periode:%m/%Y}",
            request.user,
        )
        return redirect(
            reverse("gestion:crud", args=["salaires"])
            + f"?generes={crees}&doublons={doublons}"
        )
    return redirect(
        reverse("gestion:crud", args=["salaires"]) + f"?doublons={doublons}"
    )


def _periode_param(valeur):
    """'2026-10' -> date(2026, 10, 1) ; défaut : mois courant."""
    periode = timezone.localdate().replace(day=1)
    valeur = (valeur or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", valeur):
        try:
            y, m = valeur.split("-")
            periode = date(int(y), int(m), 1)
        except (TypeError, ValueError):
            pass
    return periode


def _salaires_a_payer(societe, periode):
    """Employés restant à payer pour le mois : salaires non soldés + actifs sans fiche."""
    debut, fin = services._month_bounds(periode)
    salaires = (
        PaiementSalaire.objects.filter(
            employe__societe=societe, periode_mois__gte=debut, periode_mois__lt=fin
        )
        .select_related("employe", "employe__fonction")
        .order_by("date_prevue", "employe__nom", "employe__prenom")
    )
    aujourdhui = timezone.localdate()
    lignes, deja = [], set()
    for s in salaires:
        deja.add(s.employe_id)
        if s.statut == "PAYE":
            continue
        du = s.montant_du or Decimal("0")
        paye = s.montant_paye or Decimal("0")
        statut = s.statut
        if statut == "PREVU" and s.date_prevue and s.date_prevue < aujourdhui:
            statut = "RETARD"
        e = s.employe
        lignes.append({
            "salaire_pk": s.pk,
            "employe_pk": e.pk,
            "employe": f"{e.prenom} {e.nom}".strip(),
            "fonction": e.fonction.nom if e.fonction else "",
            "telephone": e.telephone_1 or "",
            "date_prevue": s.date_prevue,
            "statut": statut,
            "montant_du": du,
            "montant_paye": paye,
            "reste": max(du - paye, Decimal("0")),
        })
    actifs = (
        societe.employes.filter(statut="ACTIF")
        .exclude(pk__in=deja)
        .select_related("fonction")
        .order_by("nom", "prenom")
    )
    for e in actifs:
        du = Decimal(str(services.montant_du_pour(e, None, periode) or 0))
        lignes.append({
            "salaire_pk": None,
            "employe_pk": e.pk,
            "employe": f"{e.prenom} {e.nom}".strip(),
            "fonction": e.fonction.nom if e.fonction else "",
            "telephone": e.telephone_1 or "",
            "date_prevue": services.date_prevue_pour(e, periode),
            "statut": "NON_GENERE",
            "montant_du": du,
            "montant_paye": Decimal("0"),
            "reste": du,
        })
    return lignes


@login_required
def salaires_a_payer(request):
    """Liste (JSON) des employés à payer pour un mois : ?mois=AAAA-MM."""
    societe, _, resp = _societe_context(request, "salaires")
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return JsonResponse({"error": "interdit"}, status=403)
    periode = _periode_param(request.GET.get("mois"))
    lignes = _salaires_a_payer(societe, periode)
    total = sum((l["reste"] for l in lignes), Decimal("0"))
    return JsonResponse({
        "mois": f"{periode:%Y-%m}",
        "total": str(total),
        "nb": len(lignes),
        "pdf": reverse("gestion:salaires_a_payer_pdf") + f"?mois={periode:%Y-%m}",
        "lignes": [
            {
                **{k: v for k, v in l.items() if k not in ("date_prevue", "montant_du", "montant_paye", "reste")},
                "date_prevue": l["date_prevue"].isoformat() if l["date_prevue"] else "",
                "montant_du": str(l["montant_du"]),
                "montant_paye": str(l["montant_paye"]),
                "reste": str(l["reste"]),
                "payer_url": reverse("gestion:salaire_payer", args=[l["salaire_pk"]]) if l["salaire_pk"] else "",
            }
            for l in lignes
        ],
    })


@login_required
def salaires_a_payer_pdf(request):
    """PDF « État des salaires à payer » du mois : ?mois=AAAA-MM (&dl=1 pour télécharger)."""
    from . import salaires_pdf

    societe, _, resp = _societe_context(request, "salaires")
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return HttpResponseForbidden("Action non autorisée.")
    periode = _periode_param(request.GET.get("mois"))
    lignes = _salaires_a_payer(societe, periode)
    u = request.user
    auteur = (f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name', '')}".strip()
              or getattr(u, "email", "") or "")
    contenu = salaires_pdf.etat_salaires_pdf(
        societe.nom, periode, lignes,
        accent_hex=COULEUR_HEX.get(societe.couleur, "#0284c7"),
        genere_par=auteur, genere_le=timezone.localdate(),
        logo=logo_societe.logo_reader(societe),
    )
    reponse = HttpResponse(contenu, content_type="application/pdf")
    mode = "attachment" if request.GET.get("dl") else "inline"
    reponse["Content-Disposition"] = f'{mode}; filename="{salaires_pdf.nom_fichier(periode)}"'
    return reponse


def _echeances_a_encaisser(societe, periode):
    """Échéances non soldées du mois (+ retards des mois précédents)."""
    debut, fin = services._month_bounds(periode)
    aujourdhui = timezone.localdate()
    qs = (
        EcheancePaiement.objects.filter(projet__societe=societe)
        .exclude(statut="PAYEE")
        .filter(Q(date_prevue__gte=debut, date_prevue__lt=fin) | Q(date_prevue__lt=debut))
        .select_related("projet", "projet__client")
        .order_by("date_prevue")
    )
    lignes = []
    for e in qs:
        du = e.montant_prevu or Decimal("0")
        paye = Decimal(str(
            e.paiements.filter(statut="CONFIRME").aggregate(t=Sum("montant"))["t"] or 0
        )) if hasattr(e, "paiements") else Decimal("0")
        statut = e.statut
        if e.date_prevue < aujourdhui:
            statut = "RETARD"
        client = e.projet.client if e.projet else None
        if du and paye >= du:
            continue
        lignes.append({
            "ech_pk": e.pk,
            "employe": client.nom if client else "—",
            "fonction": f"{e.projet.nom if e.projet else ''} · échéance #{e.numero_echeance}",
            "telephone": (client.telephone_1 if client else "") or "",
            "date_prevue": e.date_prevue,
            "statut": statut,
            "montant_du": du,
            "montant_paye": paye,
            "reste": max(du - paye, Decimal("0")),
            "anterieure": e.date_prevue < debut,
        })
    return lignes


@login_required
def echeances_a_encaisser(request):
    """JSON (?mois=AAAA-MM) ou PDF (&format=pdf) des échéances à encaisser."""
    from . import salaires_pdf

    societe, _, resp = _societe_context(request, "echeances")
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return HttpResponseForbidden("Action non autorisée.")
    periode = _periode_param(request.GET.get("mois"))
    lignes = _echeances_a_encaisser(societe, periode)
    if request.GET.get("format") == "pdf":
        u = request.user
        auteur = (f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name', '')}".strip()
                  or getattr(u, "email", "") or "")
        contenu = salaires_pdf.etat_salaires_pdf(
            societe.nom, periode, lignes,
            accent_hex=COULEUR_HEX.get(societe.couleur, "#0284c7"),
            genere_par=auteur, genere_le=timezone.localdate(),
            titre="Échéances à encaisser", col_nom="CLIENT / PROJET", col_tel="TÉLÉPHONE",
            kpi_nb="Échéances", kpi_paye="Déjà encaissé",
            note=("Inclut les échéances en retard des mois précédents. Les échéances validées "
                  "comme payées sont enregistrées automatiquement dans Paiements."),
            vide="Aucune échéance à encaisser pour cette période.",
            logo=logo_societe.logo_reader(societe),
        )
        reponse = HttpResponse(contenu, content_type="application/pdf")
        mode = "attachment" if request.GET.get("dl") else "inline"
        reponse["Content-Disposition"] = f'{mode}; filename="echeances-a-encaisser-{periode:%Y-%m}.pdf"'
        return reponse
    total = sum((l["reste"] for l in lignes), Decimal("0"))
    base_pdf = reverse("gestion:echeances_a_encaisser") + f"?mois={periode:%Y-%m}&format=pdf"
    return JsonResponse({
        "mois": f"{periode:%Y-%m}",
        "total": str(total),
        "nb": len(lignes),
        "pdf": base_pdf,
        "lignes": [
            {
                "employe": l["employe"], "fonction": l["fonction"], "telephone": l["telephone"],
                "statut": l["statut"], "anterieure": l["anterieure"],
                "date_prevue": l["date_prevue"].isoformat(),
                "montant_du": str(l["montant_du"]), "montant_paye": str(l["montant_paye"]),
                "reste": str(l["reste"]),
                "payer_url": reverse("gestion:echeance_payer", args=[l["ech_pk"]]),
            }
            for l in lignes
        ],
    })


# ---------------------------------------------------------------------------
# Facturation (espace Finances)
# ---------------------------------------------------------------------------

def _dec(v, defaut="0"):
    try:
        return Decimal(str(v).replace(" ", "").replace(" ", "").replace(",", ".") or defaut)
    except Exception:
        return Decimal(defaut)


def _facture_depuis_post(request, societe, facture):
    """Remplit la facture depuis le POST du tiroir. Retourne (lignes, erreurs)."""
    erreurs = []
    client = societe.clients.filter(pk=request.POST.get("client") or 0).first()
    if client is None:
        erreurs.append("Choisissez un client.")
    projet = societe.projets.filter(pk=request.POST.get("projet") or 0).first()
    echeance = EcheancePaiement.objects.filter(
        projet__societe=societe, pk=request.POST.get("echeance") or 0
    ).first()
    if echeance and not projet:
        projet = echeance.projet
    try:
        lignes_brutes = json.loads(request.POST.get("lignes_json") or "[]")
    except (TypeError, ValueError):
        lignes_brutes = []
    lignes = []
    for i, l in enumerate(lignes_brutes):
        desig = str(l.get("designation") or "").strip()[:255]
        qte = _dec(l.get("quantite"), "1")
        pu = _dec(l.get("prix_unitaire"), "0")
        if not desig and not pu:
            continue
        if not desig:
            erreurs.append(f"Ligne {i + 1} : la désignation est obligatoire.")
        if qte <= 0 or pu < 0:
            erreurs.append(f"Ligne {i + 1} : quantité et prix doivent être positifs.")
        lignes.append(LigneFacture(designation=desig, quantite=qte, prix_unitaire=pu, ordre=i))
    if not lignes:
        erreurs.append("Ajoutez au moins une ligne à la facture.")
    facture.client = client
    facture.client_nom = client.nom if client else ""
    facture.projet = projet
    facture.echeance = echeance
    facture.objet = (request.POST.get("objet") or "").strip()[:255]
    facture.date_emission = parse_date(request.POST.get("date_emission") or "") or timezone.localdate()
    facture.date_echeance = parse_date(request.POST.get("date_echeance") or "") or None
    facture.taux_tva = min(max(_dec(request.POST.get("taux_tva")), Decimal("0")), Decimal("100"))
    facture.remise = max(_dec(request.POST.get("remise")), Decimal("0"))
    facture.notes = (request.POST.get("notes") or "").strip()
    facture.conditions = (request.POST.get("conditions") or "").strip()
    if facture.date_echeance and facture.date_echeance < facture.date_emission:
        erreurs.append("La date d'échéance doit suivre la date d'émission.")
    return lignes, erreurs


@login_required
def factures(request):
    """Liste des factures + création / modification (tiroir avec lignes dynamiques)."""
    societe, ctx, resp = _societe_context(request, "factures")
    if resp:
        return resp
    lecture_seule = services.est_employe(request.user, societe) and not services.est_createur(request.user, societe)

    erreurs = []
    if request.method == "POST":
        if lecture_seule:
            return HttpResponseForbidden("Action réservée à l'administration.")
        fid = request.POST.get("id")
        facture = societe.factures.filter(pk=fid).first() if fid else None
        nouvelle = facture is None
        if nouvelle:
            facture = Facture(societe=societe, cree_par=request.user)
        if facture.statut in ("PAYEE", "ANNULEE"):
            return redirect(reverse("gestion:factures") + "?verrou=1")
        lignes, erreurs = _facture_depuis_post(request, societe, facture)
        if not erreurs:
            if nouvelle:
                facture.numero = services.prochain_numero_facture(societe, facture.date_emission)
            if request.POST.get("emettre") == "1" and facture.statut == "BROUILLON":
                facture.statut = "EMISE"
            facture.save()
            facture.lignes.all().delete()
            for l in lignes:
                l.facture = facture
            LigneFacture.objects.bulk_create(lignes)
            facture.recalculer()
            services.journaliser(
                societe, "CREATION" if nouvelle else "MODIFICATION", "factures",
                facture.numero, f"{facture.client_nom} — {facture.total_ttc} FCFA", request.user,
            )
            return redirect(reverse("gestion:factures") + f"?ok={'cree' if nouvelle else 'maj'}&f={facture.pk}")

    qs = societe.factures.select_related("client", "projet", "echeance").prefetch_related("lignes")
    aujourdhui = timezone.localdate()
    items = []
    for f in qs:
        statut = "RETARD" if f.en_retard else f.statut
        items.append({
            "pk": f.pk,
            "numero": f.numero,
            "client": f.client_nom or (f.client.nom if f.client else "—"),
            "client_id": f.client_id or "",
            "projet": f.projet.nom if f.projet else "",
            "projet_id": f.projet_id or "",
            "echeance_id": f.echeance_id or "",
            "objet": f.objet,
            "date_emission": f.date_emission.isoformat() if f.date_emission else "",
            "date_echeance": f.date_echeance.isoformat() if f.date_echeance else "",
            "emission_aff": f.date_emission.strftime("%d/%m/%Y") if f.date_emission else "—",
            "echeance_aff": f.date_echeance.strftime("%d/%m/%Y") if f.date_echeance else "—",
            "statut": statut,
            "statut_label": "En retard" if statut == "RETARD" else f.get_statut_display(),
            "total_ttc": str(f.total_ttc),
            "total_aff": f"{int(f.total_ttc):,}".replace(",", " "),
            "taux_tva": str(f.taux_tva),
            "remise": str(f.remise),
            "notes": f.notes,
            "conditions": f.conditions,
            "lignes": [
                {"designation": l.designation, "quantite": str(l.quantite), "prix_unitaire": str(l.prix_unitaire)}
                for l in f.lignes.all()
            ],
            "pdf": reverse("gestion:facture_pdf", args=[f.pk]),
            "action": reverse("gestion:facture_action", args=[f.pk]),
            "modifiable": f.statut in ("BROUILLON", "EMISE"),
        })

    # Indicateurs
    actives = qs.exclude(statut__in=["ANNULEE", "BROUILLON"])
    def somme(q):
        return q.aggregate(t=Sum("total_ttc"))["t"] or Decimal("0")
    a_encaisser = actives.filter(statut="EMISE")
    retard = a_encaisser.filter(date_echeance__lt=aujourdhui)
    debut_mois = aujourdhui.replace(day=1)
    factures_mois = actives.filter(date_emission__gte=debut_mois)
    payees_mois = qs.filter(statut="PAYEE", date_paiement__gte=debut_mois)
    serie = []
    for k in range(5, -1, -1):
        m = debut_mois
        for _ in range(k):
            m = (m - timedelta(days=1)).replace(day=1)
        fin_m = (m + timedelta(days=32)).replace(day=1)
        serie.append(float(somme(actives.filter(date_emission__gte=m, date_emission__lt=fin_m))))
    def fm(v):
        return f"{int(v):,}".replace(",", " ")
    ctx["stats_cartes"] = [
        stats.carte("Facturé ce mois", fm(somme(factures_mois)), "file", "fac-mois", serie, "bleu",
                    note=f"{factures_mois.count()} facture(s)"),
        stats.carte("À encaisser", fm(somme(a_encaisser)), "clock", "fac-att", None, "ambre",
                    note=f"{a_encaisser.count()} facture(s) émise(s)"),
        stats.carte("En retard", fm(somme(retard)), "alert", "fac-ret", None, "rouge",
                    note=f"{retard.count()} facture(s)"),
        stats.carte("Encaissé ce mois", fm(somme(payees_mois)), "check", "fac-pay", None, "vert",
                    note=f"{payees_mois.count()} payée(s)"),
    ]
    ctx.update({
        "items": items,
        "items_js": items,
        "lecture_seule": lecture_seule,
        "erreurs": erreurs,
        "post": request.POST if erreurs else None,
        "clients_js": [{"pk": c.pk, "nom": c.nom} for c in societe.clients.order_by("nom")],
        "projets_js": [{"pk": p.pk, "nom": p.nom, "client_id": p.client_id}
                       for p in societe.projets.order_by("nom")],
        "echeances_js": [
            {"pk": e.pk, "label": f"{e.projet.nom} — échéance #{e.numero_echeance} ({e.date_prevue:%d/%m/%Y})",
             "projet_id": e.projet_id, "client_id": e.projet.client_id, "montant": str(e.montant_prevu),
             "numero": e.numero_echeance, "projet": e.projet.nom}
            for e in EcheancePaiement.objects.filter(projet__societe=societe).exclude(statut="PAYEE")
            .select_related("projet").order_by("date_prevue")
        ],
        "numero_suivant": services.prochain_numero_facture(societe),
        "aujourdhui_iso": aujourdhui.isoformat(),
        "echeance_defaut": (aujourdhui + timedelta(days=30)).isoformat(),
        "nb_par_statut": {
            k: sum(1 for i in items if i["statut"] == k)
            for k in ("BROUILLON", "EMISE", "RETARD", "PAYEE", "ANNULEE")
        },
    })
    return render(request, "gestion/factures.html", ctx)


@login_required
def facture_action(request, pk):
    """Actions : emettre, payer, rouvrir, annuler, dupliquer, supprimer (POST)."""
    if request.method != "POST":
        return redirect(reverse("gestion:factures"))
    societe, _, resp = _societe_context(request, "factures")
    if resp:
        return resp
    if services.est_employe(request.user, societe) and not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée à l'administration.")
    f = societe.factures.filter(pk=pk).first()
    if f is None:
        raise Http404
    action = request.POST.get("action")
    msg = ""
    if action == "emettre" and f.statut == "BROUILLON":
        f.statut = "EMISE"
        f.save(update_fields=["statut", "updated_at"])
        msg = "emise"
    elif action == "payer" and f.statut in ("EMISE", "BROUILLON"):
        services.payer_facture(societe, f, parse_date(request.POST.get("date_paiement") or "") or None)
        msg = "payee"
    elif action == "rouvrir" and f.statut in ("PAYEE", "ANNULEE"):
        if f.statut == "PAYEE":
            services.annuler_paiement_facture(societe, f)
        f.statut, f.date_paiement = "EMISE", None
        f.save(update_fields=["statut", "date_paiement", "updated_at"])
        msg = "rouverte"
    elif action == "annuler" and f.statut != "ANNULEE":
        if f.statut == "PAYEE":
            services.annuler_paiement_facture(societe, f)
        f.statut = "ANNULEE"
        f.save(update_fields=["statut", "updated_at"])
        msg = "annulee"
    elif action == "dupliquer":
        lignes = list(f.lignes.all())
        copie = Facture.objects.create(
            societe=societe, numero=services.prochain_numero_facture(societe), client=f.client,
            client_nom=f.client_nom, projet=f.projet, objet=f.objet, taux_tva=f.taux_tva, remise=f.remise,
            notes=f.notes, conditions=f.conditions, cree_par=request.user,
            date_echeance=timezone.localdate() + timedelta(days=30),
        )
        LigneFacture.objects.bulk_create([
            LigneFacture(facture=copie, designation=l.designation, quantite=l.quantite,
                         prix_unitaire=l.prix_unitaire, ordre=l.ordre) for l in lignes
        ])
        copie.recalculer()
        f = copie
        msg = "dupliquee"
    elif action == "supprimer" and f.statut == "BROUILLON":
        numero = f.numero
        f.delete()
        services.journaliser(societe, "SUPPRESSION", "factures", numero, "Brouillon supprimé", request.user)
        return redirect(reverse("gestion:factures") + "?ok=supprimee")
    if msg:
        services.journaliser(
            societe, "PAIEMENT" if msg == "payee" else "MODIFICATION", "factures",
            f.numero, f"Facture {msg} — {f.total_ttc} FCFA", request.user,
        )
    return redirect(reverse("gestion:factures") + f"?ok={msg or 'rien'}&f={f.pk}")


@login_required
def facture_pdf(request, pk):
    from . import facture_pdf as fpdf

    societe, _, resp = _societe_context(request, "factures")
    if resp:
        return resp
    f = societe.factures.filter(pk=pk).select_related("client", "projet").first()
    if f is None:
        raise Http404
    createur = getattr(societe, "createur", None)
    contact = getattr(createur, "email", "") if createur else ""
    contenu = fpdf.facture_pdf(
        f, societe, COULEUR_HEX.get(societe.couleur, "#0284c7"),
        logo=logo_societe.logo_reader(societe), contact=contact,
    )
    reponse = HttpResponse(contenu, content_type="application/pdf")
    mode = "attachment" if request.GET.get("dl") else "inline"
    reponse["Content-Disposition"] = f'{mode}; filename="facture-{f.numero}.pdf"'
    return reponse


@login_required
def facture_depuis_echeance(request, pk):
    """Crée un brouillon de facture pré-rempli depuis une échéance, puis l'ouvre."""
    if request.method != "POST":
        return redirect(reverse("gestion:crud", args=["echeances"]))
    societe, _, resp = _societe_context(request, "factures")
    if resp:
        return resp
    if services.est_employe(request.user, societe) and not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée à l'administration.")
    e = EcheancePaiement.objects.filter(projet__societe=societe, pk=pk).select_related(
        "projet", "projet__client").first()
    if e is None:
        raise Http404
    existante = e.factures.exclude(statut="ANNULEE").first()
    if existante:
        return redirect(reverse("gestion:factures") + f"?edit={existante.pk}")
    f = Facture.objects.create(
        societe=societe, numero=services.prochain_numero_facture(societe),
        client=e.projet.client, client_nom=e.projet.client.nom if e.projet.client_id else "",
        projet=e.projet, echeance=e, objet=f"{e.projet.nom} — échéance #{e.numero_echeance}",
        date_echeance=e.date_prevue if e.date_prevue >= timezone.localdate() else timezone.localdate() + timedelta(days=15),
        cree_par=request.user,
    )
    LigneFacture.objects.create(
        facture=f, designation=f"{e.projet.nom} — échéance #{e.numero_echeance}",
        quantite=1, prix_unitaire=e.montant_prevu,
    )
    f.recalculer()
    services.journaliser(societe, "CREATION", "factures", f.numero, f"Depuis l'échéance #{e.numero_echeance}", request.user)
    return redirect(reverse("gestion:factures") + f"?edit={f.pk}")


@login_required
def finances_rapport(request, module):
    """Rapport d'une page Finances : ?format=pdf|xlsx&periode=mois|trimestre|12m|annee."""
    from . import rapport_finances as rf

    if module not in rf.MODULES:
        raise Http404
    societe, _, resp = _societe_context(request, module)
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return HttpResponseForbidden("Rapports réservés à l'administration.")
    data = rf.collecter(societe, module, request.GET.get("periode") or "12m")
    accent = COULEUR_HEX.get(societe.couleur, "#0284c7")
    fmt = (request.GET.get("format") or "pdf").lower()
    if fmt == "xlsx":
        try:
            contenu = rf.excel(data, accent, logo_societe.logo_png(societe))
        except ImportError:
            return HttpResponse(
                "L'export Excel nécessite le paquet « openpyxl ». Relancez lancer_serveur.bat "
                "(il l'installe automatiquement) ou exécutez : pip install openpyxl",
                content_type="text/plain; charset=utf-8", status=503,
            )
        reponse = HttpResponse(
            contenu,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        reponse["Content-Disposition"] = f'attachment; filename="{rf.nom_fichier(data, "xlsx")}"'
        return reponse
    u = request.user
    auteur = (f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name', '')}".strip()
              or getattr(u, "email", "") or "")
    reponse = HttpResponse(rf.pdf(data, accent, auteur, logo_societe.logo_reader(societe)),
                           content_type="application/pdf")
    mode = "attachment" if request.GET.get("dl") else "inline"
    reponse["Content-Disposition"] = f'{mode}; filename="{rf.nom_fichier(data, "pdf")}"'
    return reponse


@login_required
def salaire_employe_options(request):
    """Recherche instantanée d'employé (JSON) + rechargement du salaire dû.

    ?q=...         : filtre nom/prénom/fonction (max 8 résultats).
    ?employe=<pk>  : renvoie le salaire dû et la date de paie prévue.
    """
    societe, _, resp = _societe_context(request, "salaires")
    if resp:
        return resp
    if services.est_employe(request.user, societe):
        return JsonResponse({"error": "interdit"}, status=403)
    employes = Employe.objects.filter(societe=societe).select_related("fonction")

    employe_pk = request.GET.get("employe")
    if employe_pk:
        try:
            e = employes.get(pk=employe_pk)
        except (Employe.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "employe_inconnu"}, status=404)
        contrat = (
            ContratEmploye.objects.filter(employe=e, statut="ACTIF")
            .order_by("-date_debut")
            .first()
        )
        periode = timezone.localdate().replace(day=1)
        return JsonResponse(
            {
                "montant_du": str(services.montant_du_pour(e, contrat, periode)),
                "date_prevue": services.date_prevue_pour(e, periode).isoformat(),
                "contrat": contrat.pk if contrat else None,
                "contrat_code": contrat.type_contrat.code if contrat else "",
            }
        )

    q = (request.GET.get("q") or "").strip()
    if q:
        employes = employes.filter(
            Q(nom__icontains=q)
            | Q(prenom__icontains=q)
            | Q(fonction__nom__icontains=q)
        )
    results = [
        {
            "pk": e.pk,
            "label": f"{e.prenom} {e.nom}",
            "fonction": e.fonction.nom if e.fonction else "",
            "salaire": str(e.salaire) if e.salaire is not None else "",
        }
        for e in employes.order_by("nom", "prenom")[:8]
    ]
    return JsonResponse({"results": results})


@login_required
def crud_page(request, module):
    """Page CRUD générique (liste + drawer) pour un module du registre."""
    conf = CRUD_CONFIG.get(module)
    if conf is None:
        raise Http404("Module inconnu.")
    societe, ctx, resp = _societe_context(request, module)
    if resp:
        return resp

    # Un employé (fiche reliée, non propriétaire) consulte ses paiements de
    # salaire en LECTURE SEULE et ne voit que les siens.
    est_createur = services.est_createur(request.user, societe)
    employe_courant = services.employe_pour_utilisateur(request.user, societe)
    lecture_seule = bool(
        module == "salaires" and employe_courant is not None and not est_createur
    )
    if request.method == "POST" and lecture_seule:
        return HttpResponseForbidden("Action non autorisée.")

    obj_id = request.POST.get("id") or None
    instance = (
        conf["queryset"](societe).filter(pk=obj_id).first() if obj_id else None
    )
    ancien_fichier = getattr(instance, "fichier", "") if module == "documents" and instance else ""
    form = conf["form"](
        request.POST or None,
        request.FILES or None,
        instance=instance,
        societe=societe,
    )
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if "societe" in {f.name for f in conf["model"]._meta.local_fields}:
            obj.societe = societe
        if module == "documents":
            # Le formulaire ne fait que lire le fichier : on l'enregistre dans le stockage PRIVÉ
            televerse = request.FILES.get("fichier")
            obj.fichier = (fichiers_prives.stocker(televerse, "societes/documents", societe.nom)
                           if televerse else ancien_fichier)
        if module == "salaires":
            # Création : toujours un « prévu », le paiement se valide via ✓.
            # Le montant dû est recalculé depuis le contrat actif / la fiche employé.
            if instance is None:
                obj.statut = "PREVU"
                obj.montant_paye = Decimal("0")
            # Champs facultatifs du formulaire : ne jamais laisser un NULL passer.
            if not obj.statut:
                obj.statut = instance.statut if instance else "PREVU"
            if obj.montant_paye is None:
                obj.montant_paye = obj.montant_du or Decimal("0")
            obj.montant_du = services.montant_du_pour(
                obj.employe, obj.contrat, obj.periode_mois
            )
            if not obj.date_prevue:
                obj.date_prevue = services.date_prevue_pour(obj.employe, obj.periode_mois)
        obj.save()
        if module == "salaires":
            _sync_depense_salaire(societe, obj)
        elif module == "depenses":
            # Dépense de type « Salaires » → crée / met à jour le paiement de salaire lié.
            services.sync_salaire_from_depense(societe, obj)
            services.recalculer_finances(societe, obj.date_depense)
        elif module == "echeances":
            # Échéance payée → encaissement créé / mis à jour côté « Paiements ».
            services.sync_paiement_from_echeance(societe, obj)
        elif module == "paiements":
            # Paiement confirmé → statut de l'échéance liée recalculé.
            services.sync_echeance_from_paiement(societe, obj)
            services.recalculer_finances(societe, obj.date_paiement)
        elif module == "prospection":
            # Prospect gagné (case « Convertir en client ») → fiche client liée.
            if request.POST.get("convertir_en_client"):
                services.convertir_prospection(
                    societe,
                    obj,
                    type_client_id=request.POST.get("type_client") or None,
                    utilisateur=request.user,
                )
        try:
            libelle = str(obj)
        except Exception:
            libelle = ""
        services.journaliser(
            societe,
            "MODIFICATION" if obj_id else "CREATION",
            module,
            libelle,
            "",
            request.user,
        )
        return redirect(reverse("gestion:crud", args=[module]) + "?ok=1")

    extra = dict(conf.get("extra") or {})
    for cle in list(extra):
        if callable(extra[cle]):
            extra[cle] = extra[cle](societe)
    base_qs = conf["queryset"](societe)
    items = conf["rows"](societe)
    if lecture_seule:
        # Seuls les paiements de l'employé connecté sont visibles.
        base_qs = base_qs.filter(employe=employe_courant)
        mes_pk = set(base_qs.values_list("pk", flat=True))
        items = [it for it in items if it["pk"] in mes_pk]
        extra.pop("employes", None)
    if module == "echeances":
        # Centre d'échéances : toutes les sources (paiements projet, tâches,
        # paies prévues, contrats, projets, objectifs, documents) regroupées
        # par horizon, sous les permissions de modules du compte.
        services.assurer_echeances_registre(societe, user=request.user)
        autorises = set(services.modules_autorises(request.user, societe))
        aujourdhui = timezone.localdate()
        par_groupe = {g: [] for g in services.GROUPES_CENTRE}
        for s in services.registre_echeances(societe):
            if s["module"] not in autorises:
                continue
            jalon, _jours, priorite = services.jalon_echeance(
                s["date_prevue"], aujourdhui
            )
            groupe = services.groupe_centre(s["date_prevue"], aujourdhui)
            par_groupe[groupe].append(
                {
                    "module": s["module"],
                    "module_label": services.journal_module_label(s["module"]),
                    "libelle": s["libelle"],
                    "element": s["element"],
                    "montant": s["montant"],
                    "montant_aff": services.montant_display(s["montant"]),
                    "date_prevue": s["date_prevue"],
                    "statut": s["statut"],
                    "statut_label": services.statut_label(s["statut"]),
                    "jalon": jalon,
                    "jalon_label": services.jalon_label(jalon),
                    "priorite": priorite,
                    "temps": services.temps_restant(s["date_prevue"], aujourdhui),
                    "lien": s["lien"],
                    "payer": bool(
                        s["module"] == "echeances"
                        and s["cible"].startswith("ech:")
                        and s["statut"] != "PAYEE"
                    ),
                    "ech_pk": int(s["cible"][4:]) if s["cible"].startswith("ech:") else None,
                }
            )
        ctx["centre"] = [
            {"groupe": g, "items": par_groupe[g]}
            for g in services.GROUPES_CENTRE
            if par_groupe[g]
        ]
        ctx["centre_total"] = sum(len(g["items"]) for g in ctx["centre"])
        compte = {g["groupe"]: len(g["items"]) for g in ctx["centre"]}
        ctx["centre_counts"] = {
            "total": ctx["centre_total"],
            "en_retard": compte.get("En retard", 0),
            "aujourdhui": compte.get("Aujourd'hui", 0),
            "bientot": compte.get("Demain", 0) + compte.get("Cette semaine", 0),
            "apres": ctx["centre_total"]
            - compte.get("En retard", 0)
            - compte.get("Aujourd'hui", 0)
            - compte.get("Demain", 0)
            - compte.get("Cette semaine", 0),
        }
        ctx["aujourdhui_iso"] = timezone.localdate().isoformat()
        ctx["aujourdhui_aff"] = timezone.localdate().strftime("%d/%m/%Y")
    ctx["conf"] = conf
    ctx["module"] = module
    ctx["form"] = form
    ctx["columns"] = conf["columns"]
    ctx["wide"] = conf["wide"]
    ctx["items"] = items
    ctx["count"] = base_qs.count()
    ctx["lecture_seule"] = lecture_seule
    ctx["espace_employe"] = lecture_seule
    if conf.get("payable"):
        nb_payes = base_qs.filter(statut="PAYE").count()
        ctx["nb_payes"] = nb_payes
        ctx["nb_non_payes"] = ctx["count"] - nb_payes
        ctx["mois_courant"] = timezone.localdate().strftime("%Y-%m")
    ctx.setdefault("mois_courant", timezone.localdate().strftime("%Y-%m"))
    ctx["extra"] = extra
    return render(request, conf.get("template", "gestion/crud_generic.html"), ctx)


@login_required
def crud_delete(request, module, pk):
    if module not in CRUD_CONFIG:
        raise Http404("Module inconnu.")
    if request.method == "POST":
        conf = CRUD_CONFIG[module]
        societe, _, resp = _societe_context(request, module)
        if resp:
            return resp
        if module == "salaires" and services.est_employe(request.user, societe):
            return HttpResponseForbidden("Action non autorisée.")
        objs = list(conf["queryset"](societe).filter(pk=pk))
        periods = []
        echeances_a_resynchroniser = []
        if module == "salaires":
            # La dépense générée par un salaire payé est supprimée avec lui.
            DepenseSociete.objects.filter(paiement_salaire__in=objs).delete()
            for o in objs:
                if o.periode_mois:
                    periods.append(o.periode_mois)
                if o.date_paiement:
                    periods.append(o.date_paiement)
        elif module == "depenses":
            # Une dépense « Salaires » supprimée retire aussi le paiement lié.
            for o in objs:
                salaire = o.paiement_salaire
                if salaire:
                    if salaire.periode_mois:
                        periods.append(salaire.periode_mois)
                    if salaire.date_paiement:
                        periods.append(salaire.date_paiement)
                    salaire.delete()
                if o.date_depense:
                    periods.append(o.date_depense)
                if o.periode_mois:
                    periods.append(o.periode_mois)
        elif module == "echeances":
            # Une échéance supprimée retire les encaissements liés (miroir).
            for o in objs:
                if o.date_prevue:
                    periods.append(o.date_prevue)
                for p in o.paiements.all():
                    if p.date_paiement:
                        periods.append(p.date_paiement)
            PaiementClient.objects.filter(echeance__in=objs).delete()
        elif module == "paiements":
            # Un paiement supprimé → statut de l'échéance recalculé après coup.
            for o in objs:
                if o.date_paiement:
                    periods.append(o.date_paiement)
                if o.echeance_id:
                    echeances_a_resynchroniser.append(o.echeance_id)
        conf["queryset"](societe).filter(pk=pk).delete()
        for eid in echeances_a_resynchroniser:
            echeance = EcheancePaiement.objects.filter(
                pk=eid, projet__societe=societe
            ).first()
            if echeance:
                services.recalculer_echeance(societe, echeance)
        for p in periods:
            services.recalculer_finances(societe, p)
        if objs:
            try:
                libelle = str(objs[0])
            except Exception:
                libelle = ""
            services.journaliser(
                societe, "SUPPRESSION", module, libelle, "", request.user
            )
    return redirect(reverse("gestion:crud", args=[module]) + "?deleted=1")


@login_required
def societe_profil(request):
    """Ma société : informations, logo, documents et configuration."""
    societe, ctx, resp = _societe_context(request, "societe")
    if resp:
        return resp

    config_form = SocieteConfigForm(
        request.POST or None,
        request.FILES or None,
        instance=societe,
    )
    if request.method == "POST" and config_form.is_valid():
        societe = config_form.save(commit=False)
        if "logo" in request.FILES:
            societe.logo = _store_upload(
                request.FILES["logo"], "societes/logos", societe.nom
            )
        societe.save()
        config_form.save_m2m()  # modes de paiement cochés
        services.journaliser(
            societe,
            "CONFIGURATION",
            "societe",
            societe.nom,
            "Mise à jour de la configuration",
            request.user,
        )
        return redirect(reverse("gestion:societe_profil") + "?ok=1")

    ctx["config_form"] = config_form
    ctx["open_config"] = (
        request.GET.get("config") == "1"
        or (request.method == "POST" and not config_form.is_valid())
    )
    ctx["documents"] = societe.documents.all()
    ctx["modes_disponibles"] = societe.modes_paiement.filter(actif=True).all()
    ctx["etat_abo"] = abonnements_service.etat(societe)
    ctx["demande_abo"] = societe.abonnements.filter(statut="EN_ATTENTE").select_related("forfait").first()
    ctx["counts"] = {
        "employes": societe.employes.count(),
        "employes_actifs": societe.employes.filter(statut="ACTIF").count(),
        "clients": societe.clients.count(),
        "projets": societe.projets.count(),
        "projets_en_cours": societe.projets.filter(statut="EN_COURS").count(),
    }
    ctx["aujourdhui"] = timezone.localdate()
    ctx["societe_cartes"] = stats.cartes_societe(societe)
    ctx["couleurs"] = [
        (valeur, libelle, COULEUR_HEX.get(valeur, "#0284c7"))
        for valeur, libelle in config_form.fields["couleur"].choices
        if valeur
    ]
    ctx["couleur_actuelle"] = str(config_form["couleur"].value() or societe.couleur)
    ctx["modes_coches"] = [str(v) for v in (config_form["modes_paiement"].value() or [])]
    return render(request, "gestion/societe_profil.html", ctx)


@login_required
def profil(request):
    """Mon profil : détails du compte et photo de profil.

    Accessible même sans société (compte Google par exemple) : l'utilisateur
    peut toujours consulter et modifier son profil.
    """
    if getattr(request.user, "statut", "ACTIF") != "ACTIF":
        return _bounce_inactive(request)
    if request.user.is_superuser and request.user.societes_creees.first() is None:
        return redirect("admin_tableau")
    # Société du compte : la sienne s'il est propriétaire (y compris
    # superuser), sinon celle de sa fiche employé — comme _societe_context.
    societe = (
        request.user.societes_creees.first()
        if request.user.is_superuser
        else services.societe_pour_utilisateur(request.user)
    )
    if societe is not None and not services.peut_acceder(
        request.user, societe, "profil"
    ):
        return redirect("gestion:dashboard")

    ctx = {
        "societe": societe,
        "accent": (
            COULEUR_HEX.get(societe.couleur, "#0284c7") if societe else "#0284c7"
        ),
        "active": "profil",
        "nav_counts": _nav_counts(societe) if societe else {},
        "modules_autorises": (
            services.modules_autorises(request.user, societe) if societe else ["profil"]
        ),
        "est_employe": (
            services.est_employe(request.user, societe) if societe else False
        ),
        "est_compte_employe": services.est_compte_employe(request.user),
        # Sans société : pas de dossiers d'espace (évite une erreur du gabarit)
        "espace_dossiers": [],
    }
    if societe:
        ctx.update(_espace_finances(ctx["modules_autorises"], ctx["nav_counts"], "profil"))
    try:
        ctx["profil_cartes"] = stats.cartes_profil(request.user, societe)
    except Exception:
        ctx["profil_cartes"] = []

    form = UserProfilForm(request.POST or None, request.FILES or None, instance=request.user)

    if request.method == "POST":
        if request.POST.get("supprimer_photo"):
            request.user.photo_profil = ""
            request.user.save(update_fields=["photo_profil"])
            services.journaliser(
                societe,
                "CONFIGURATION",
                "compte",
                "Photo de profil",
                "Photo supprimée",
                request.user,
            )
            return redirect(reverse("gestion:profil") + "?ok=1")
        if form.is_valid():
            user = form.save(commit=False)
            if "photo_profil" in request.FILES:
                user.photo_profil = _store_upload(
                    request.FILES["photo_profil"],
                    "profils/photos",
                    f"{user.prenom or 'utilisateur'}-{user.nom or ''}",
                )
            user.save()
            services.journaliser(
                societe,
                "MODIFICATION",
                "compte",
                "Mon profil",
                "Informations mises à jour",
                request.user,
            )
            return redirect(reverse("gestion:profil") + "?ok=1")

    ctx["form"] = form
    return render(request, "gestion/profil.html", ctx)


@login_required
def ai_page(request):
    """Page plein écran de discussion avec l'assistant IA de la société.

    Réutilise les endpoints ``ai_chat`` / ``ia_conversations`` /
    ``ia_conversation_messages``. Accessible à tout compte rattaché à une
    société (comme le tableau de bord ou le profil).
    """
    societe, ctx, resp = _societe_context(request, "ai")
    if resp:
        return resp
    ctx["ia_mode_local"] = not getattr(settings, "GROQ_API_KEY", "")
    return render(request, "gestion/ia.html", ctx)


@login_required
def ai_chat(request):
    """Endpoint JSON du chat IA (Groq), borné aux modules autorisés.

    Les échanges sont persistés dans ``IaConversation``/``IaMessage`` :
    ``conversation_id`` (optionnel) permet de reprendre une discussion.
    En cas d’échec de Groq, aucun message n’est enregistré.
    """
    societe, _, resp = _societe_context(request, "dashboard")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)

    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"error": "Requête JSON invalide."}, status=400)

    message = (payload.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "Message vide."}, status=400)

    conversation_id = payload.get("conversation_id")
    conversation = None
    if conversation_id:
        conversation = ai.conversations_ia(
            request.user, societe
        ).filter(pk=conversation_id).first()
        if conversation is None:
            return JsonResponse({"error": "Conversation introuvable."}, status=404)

    modules = ai.user_module_keys(request.user, societe)
    historique = []
    if conversation is not None:
        for m in conversation.messages.order_by("-id")[:10][::-1]:
            historique.append({"role": m.role, "content": m.contenu[:4000]})

    try:
        action = ai.exec_commande_ajout_client(societe, request.user, message)
    except Exception:
        action = None
    if action is None and conversation is not None:
        try:
            action = ai.completer_ajout_client(
                societe, request.user, message, conversation
            )
        except Exception:
            action = None
    blocs, etapes = [], []
    if action is not None:
        reply = action
        offline = True
        etapes = [{"icone": "check", "texte": "Action exécutée"}]
    else:
        try:
            resultat = ia_agent.repondre(
                societe, request.user, modules, historique, message
            )
        except Exception:
            resultat = {
                "reply": ai.repondre_hors_ligne(societe, modules, message),
                "blocs": [],
                "etapes": [],
                "offline": True,
            }
        reply = resultat["reply"]
        blocs = resultat["blocs"]
        etapes = resultat["etapes"]
        offline = resultat["offline"]

    if conversation is None:
        conversation = IaConversation.objects.create(
            societe=societe,
            employe=ai.employe_pour_utilisateur(request.user, societe),
            titre=ai.titre_conversation(message),
            statut="ACTIVE",
        )
    IaMessage.objects.create(conversation=conversation, role="user", contenu=message)
    IaMessage.objects.create(
        conversation=conversation,
        role="assistant",
        contenu=reply,
        donnees={"blocs": blocs, "etapes": etapes},
    )
    conversation.save(update_fields=["updated_at"])
    return JsonResponse(
        {
            "reply": reply,
            "blocs": blocs,
            "etapes": etapes,
            "conversation_id": conversation.pk,
            "offline": offline,
        }
    )


@login_required
def ia_conversations(request):
    """Liste JSON des conversations IA du compte (triées par activité)."""
    societe, _, resp = _societe_context(request, "dashboard")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    if request.method != "GET":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    qs = ai.conversations_ia(request.user, societe).prefetch_related("messages")
    items = []
    for conv in qs[:30]:
        msgs = list(conv.messages.all())
        dernier = msgs[-1] if msgs else None
        items.append(
            {
                "id": conv.pk,
                "titre": conv.titre,
                "statut": conv.statut,
                "updated_at": conv.updated_at.isoformat(),
                "n_messages": len(msgs),
                "dernier_message": (
                    dernier.contenu[:120] if dernier and dernier.contenu else ""
                ),
            }
        )
    return JsonResponse({"conversations": items})


@login_required
def ia_conversation_messages(request, pk):
    """Messages d'une conversation IA accessible au compte (JSON)."""
    societe, _, resp = _societe_context(request, "dashboard")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    if request.method != "GET":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    conv = ai.conversations_ia(request.user, societe).filter(pk=pk).first()
    if conv is None:
        return JsonResponse({"error": "Conversation introuvable."}, status=404)
    return JsonResponse(
        {
            "id": conv.pk,
            "titre": conv.titre,
            "statut": conv.statut,
            "messages": [
                {
                    "role": m.role,
                    "contenu": m.contenu,
                    "blocs": (m.donnees or {}).get("blocs", []),
                    "etapes": (m.donnees or {}).get("etapes", []),
                    "created_at": m.created_at.isoformat(),
                }
                for m in conv.messages.all()
            ],
        }
    )


@login_required
def ia_conversation_supprimer(request, pk):
    """Supprime une conversation IA du compte."""
    societe, _, resp = _societe_context(request, "dashboard")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    conv = ai.conversations_ia(request.user, societe).filter(pk=pk).first()
    if conv is None:
        return JsonResponse({"error": "Conversation introuvable."}, status=404)
    conv.delete()
    return JsonResponse({"ok": True})


@login_required
def ai_document_pdf(request):
    """PDF « rapport » soigné (couverture, sections, graphiques) de l'assistant.

    Corps JSON accepté :
    - {"document": {...}}                      : un document de l'assistant ;
    - {"conversation_id": 12}                  : toute la conversation ;
    - {"question": "...", "message": "...", "blocs": [...]} : une réponse.
    Le titre (et le nom du fichier) est proposé par l'IA.
    """
    societe, _, resp = _societe_context(request, "dashboard")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"error": "Requête JSON invalide."}, status=400)
    try:
        from . import rapport_pdf
    except ImportError:
        return JsonResponse(
            {"error": "Installez ReportLab : python -m pip install reportlab"}, status=500
        )

    modules = ai.user_module_keys(request.user, societe)
    blocs_ok = lambda v: [b for b in (v or []) if isinstance(b, dict)][:20]
    if isinstance(payload.get("document"), dict):
        document = ia_agent.construire_document(payload["document"], societe, request.user)
    elif payload.get("conversation_id"):
        conv = ai.conversations_ia(request.user, societe).filter(
            pk=payload.get("conversation_id")
        ).first()
        if conv is None:
            return JsonResponse({"error": "Conversation introuvable."}, status=404)
        echanges, question = [], ""
        for m in conv.messages.order_by("created_at", "id"):
            if m.role == "user":
                question = m.contenu
            else:
                echanges.append((question, m.contenu, (m.donnees or {}).get("blocs", [])))
                question = ""
        if not echanges:
            return JsonResponse({"error": "Conversation vide."}, status=400)
        document = ia_agent.document_depuis_echanges(
            societe, request.user, echanges, conv.titre or "Synthèse de la conversation", modules
        )
    else:
        message = str(payload.get("message") or "")[:20000]
        if not message.strip() and not payload.get("blocs"):
            return JsonResponse({"error": "Rien à exporter."}, status=400)
        document = ia_agent.document_depuis_echanges(
            societe,
            request.user,
            [(str(payload.get("question") or "")[:2000], message, blocs_ok(payload.get("blocs")))],
            "Synthèse de l'assistant IA",
            modules,
        )

    accent = COULEUR_HEX.get(societe.couleur, "#0284c7")
    data = rapport_pdf.document_pdf(document, accent, logo=logo_societe.logo_reader(societe))
    nom = rapport_pdf.nom_fichier(document["titre"])
    reponse = HttpResponse(data, content_type="application/pdf")
    reponse["Content-Disposition"] = f"attachment; filename=\"{nom}\"; filename*=UTF-8''{quote(nom)}"
    reponse["X-Titre-Document"] = quote(document["titre"])
    return reponse


@login_required
def ai_report_pdf(request):
    """Rapport PDF rapide à partir des modules autorisés (option : texte IA)."""
    societe, _, resp = _societe_context(request, "dashboard")
    if resp:
        return HttpResponse(status=302)
    modules = user_module_keys(request.user, societe)
    stats = get_module_stats(societe, modules)
    sections = [
        (blk["label"], blk["lines"])
        for key in modules
        for blk in [stats.get(key)]
        if blk
    ]
    text = ""
    if request.method == "POST":
        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, TypeError):
            payload = {}
        text = (payload.get("text") or "").strip()
    sections_doc = [
        {"titre": titre, "contenu": "\n".join(f"- {l}" for l in lignes)}
        for titre, lignes in sections
    ]
    if text:
        sections_doc.append({"titre": "Synthèse de l'assistant IA", "contenu": text})
    document = {
        "titre": "Rapport rapide",
        "sous_titre": f"Synthèse des modules — {societe.nom} ({societe.pays})",
        "societe": societe.nom,
        "auteur": f"{request.user.prenom} {request.user.nom}".strip(),
        "date": timezone.localdate().strftime("%d/%m/%Y"),
        "indicateurs": [],
        "sections": sections_doc,
    }
    data = rapport_pdf.document_pdf(
        document, COULEUR_HEX.get(societe.couleur, "#0284c7"), type_document="Rapport rapide",
        redacteur="Gestionnaire de société", generateur="Rapport généré automatiquement",
        logo=logo_societe.logo_reader(societe),
    )
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = (
        f'attachment; filename="rapport-{societe.nom}.pdf"'
    )
    return resp


@login_required
def chat_fichier(request, pk):
    """Téléchargement protégé d'une pièce jointe de messagerie.

    Seul le compte d'une société peut lire les fichiers des messages de cette
    même société ; les fichiers vivent hors de MEDIA_ROOT et ne sont donc
    jamais exposés via MEDIA_URL.
    """
    societe, _, resp = _societe_context(request, "employes")
    if resp:
        return resp
    msg = societe.equipe_messages.filter(pk=pk).first()
    if msg is None or not msg.fichier:
        raise Http404("Fichier introuvable.")
    if msg.groupe_id:
        autorise = services.est_membre_groupe(request.user, societe, msg.groupe)
    elif msg.conversation_id:
        autorise = services.est_participant_conversation(
            request.user, msg.conversation
        )
    elif msg.employe_id:
        autorise = services.est_createur(request.user, societe)
    else:
        autorise = services.est_createur(request.user, societe)
    if not autorise:
        raise Http404("Fichier introuvable.")
    full = os.path.join(str(settings.CHAT_MEDIA_ROOT), msg.fichier)
    if not os.path.isfile(full):
        raise Http404("Fichier introuvable.")
    ftype = msg.fichier_type or "application/octet-stream"
    fh = open(full, "rb")
    resp = FileResponse(fh, content_type=ftype)
    # Images et notes vocales sont lues dans la page (inline) ; le reste en pièce jointe.
    inline = ftype.startswith("image/") or ftype.startswith("audio/")
    nom = msg.fichier_nom or os.path.basename(msg.fichier)
    resp["Content-Disposition"] = (
        ("inline" if inline else "attachment")
        + f"; filename*=UTF-8''{quote(nom)}"
    )
    return resp


@login_required
def chat_message_delete(request, pk):
    """Suppression d'un message de messagerie (auteur uniquement)."""
    societe, _, resp = _societe_context(request, "employes", ecriture=False)  # messagerie : pas une modification du module
    if resp:
        return resp
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    msg = societe.equipe_messages.filter(pk=pk).first()
    if msg is None:
        return JsonResponse({"error": "Message introuvable."}, status=404)
    if msg.auteur_id != request.user.pk:
        return JsonResponse({"error": "Suppression non autorisée."}, status=403)
    if msg.fichier:
        full = os.path.join(str(settings.CHAT_MEDIA_ROOT), msg.fichier)
        try:
            if os.path.isfile(full):
                os.remove(full)
        except OSError:
            pass
    cible = (
        f"Groupe — {msg.groupe.titre}"
        if msg.groupe_id
        else f"{msg.employe.prenom} {msg.employe.nom}"
    )
    msg.delete()
    services.journaliser(
        societe, "SUPPRESSION", "equipe", cible, "Message supprimé", request.user
    )
    return JsonResponse({"ok": True, "pk": pk})


IMAGE_CHAT_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


@login_required
def chat_groupe_logo(request, pk):
    """Sert le logo d'un groupe de discussion (réservé à la société)."""
    societe, _, resp = _societe_context(request, "groupes")
    if resp:
        return resp
    groupe = societe.equipe_groupes.filter(pk=pk).first()
    if groupe is None or not groupe.logo:
        raise Http404("Logo introuvable.")
    if not services.est_membre_groupe(request.user, societe, groupe):
        raise Http404("Logo introuvable.")
    full = os.path.join(str(settings.CHAT_MEDIA_ROOT), groupe.logo)
    if not os.path.isfile(full):
        raise Http404("Logo introuvable.")
    ext = os.path.splitext(groupe.logo)[1].lower()
    ftype = IMAGE_CHAT_EXT.get(ext, "image/png")
    fh = open(full, "rb")
    resp = FileResponse(fh, content_type=ftype)
    resp["Cache-Control"] = "no-cache"
    return resp


@login_required
def chat_groupe_config(request, pk):
    """Modifie les paramètres d'un groupe : titre, logo, membres (multipart)."""
    societe, _, resp = _societe_context(request, "groupes")
    if resp:
        return resp
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    groupe = societe.equipe_groupes.filter(pk=pk).first()
    if groupe is None:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)
    if not services.peut_administrer_groupe(request.user, societe, groupe):
        return JsonResponse(
            {"error": "Seuls les administrateurs du groupe peuvent le modifier."}, status=403
        )
    if "description" in request.POST:
        groupe.description = request.POST.get("description", "").strip()[:255]

    titre = (request.POST.get("titre") or "").strip()
    if titre:
        if len(titre) > 120:
            return JsonResponse({"error": "Titre trop long (120 caractères maximum)."}, status=400)
        groupe.titre = titre

    membres = request.POST.getlist("membres")
    ids_valides = set(
        societe.employes.filter(pk__in=[m for m in membres if str(m).isdigit()])
        .values_list("pk", flat=True)
    )
    if not ids_valides:
        return JsonResponse(
            {"error": "Sélectionnez au moins un employé membre."}, status=400
        )

    logo = request.FILES.get("logo")
    if logo:
        ext = os.path.splitext(os.path.basename(logo.name or "").lower())[1]
        mime = IMAGE_CHAT_EXT.get(ext)
        if not mime:
            return JsonResponse(
                {"error": "Seule une image peut servir de logo de groupe."}, status=400
            )
        logo.seek(0, os.SEEK_END)
        taille = logo.tell()
        logo.seek(0)
        if taille > MAX_CHAT_FILE_MB * 1024 * 1024:
            return JsonResponse(
                {"error": f"Logo trop volumineux (maximum {MAX_CHAT_FILE_MB} Mo)."},
                status=400,
            )
        if groupe.logo:
            ancien = os.path.join(str(settings.CHAT_MEDIA_ROOT), groupe.logo)
            try:
                if os.path.isfile(ancien):
                    os.remove(ancien)
            except OSError:
                pass
        rel = os.path.join("groupes", str(societe.pk), f"{uuid.uuid4().hex}{ext}")
        full = os.path.join(str(settings.CHAT_MEDIA_ROOT), rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as out:
            for chunk in logo.chunks():
                out.write(chunk)
        groupe.logo = rel

    groupe.save(update_fields=["titre", "logo", "description"])

    actuels = set(groupe.membres.values_list("employe_id", flat=True))
    retraits = actuels - ids_valides
    ajouts = ids_valides - actuels
    if retraits:
        groupe.membres.filter(employe_id__in=list(retraits)).delete()
    if ajouts:
        EquipeGroupeMembre.objects.bulk_create(
            [
                EquipeGroupeMembre(groupe=groupe, employe_id=i)
                for i in sorted(ajouts)
            ]
        )
    if "admins_envoyes" in request.POST:
        # Administrateurs du groupe (parmi les membres) ; le créateur du groupe le reste toujours
        admins = {int(a) for a in request.POST.getlist("admins") if str(a).isdigit()} & ids_valides
        createur_emp = services.employe_pour_utilisateur(groupe.cree_par, societe) if groupe.cree_par_id else None
        if createur_emp is not None and createur_emp.pk in ids_valides:
            admins.add(createur_emp.pk)
        groupe.membres.update(est_admin=False)
        groupe.membres.filter(employe_id__in=admins).update(est_admin=True)

    services.journaliser(
        societe,
        "MODIFICATION",
        "equipe",
        f"Groupe — {groupe.titre}",
        "Paramètres du groupe mis à jour",
        request.user,
    )
    return JsonResponse({"groupe": _groupe_dict(groupe, request)})


@login_required
def employe_contrat_pdf(request, pk):
    """Contrat de travail imprimable (PDF) ; généré à la volée si l'employé n'en a pas encore."""
    societe, ctx, resp = _societe_context(request, "employes")
    if resp:
        return resp
    employe = societe.employes.filter(pk=pk).select_related("fonction", "societe").first()
    if employe is None:
        raise Http404("Employé introuvable.")
    mon_employe = services.employe_pour_utilisateur(request.user, societe)
    if not services.est_createur(request.user, societe) and (mon_employe is None or mon_employe.pk != employe.pk):
        return HttpResponseForbidden("Seul le propriétaire (ou l'employé concerné) peut imprimer ce contrat.")
    contrat = employe.contrats.filter(statut="ACTIF").order_by("-date_debut").first() \
        or contrat_pdf.assurer_contrat(employe)
    if contrat is None:
        raise Http404("Aucun type de contrat configuré.")
    contenu = contrat_pdf.contrat_pdf(contrat, ctx["accent"], logo=logo_societe.logo_reader(societe))
    reponse = HttpResponse(contenu, content_type="application/pdf")
    nom = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{employe.prenom}-{employe.nom}").strip("-") or "employe"
    mode = "attachment" if request.GET.get("dl") else "inline"
    reponse["Content-Disposition"] = f'{mode}; filename="contrat-{nom}.pdf"'
    return reponse


@login_required
@require_POST
def chat_groupe_supprimer(request, pk):
    """Supprime un groupe (propriétaire) : messages, pièces jointes et logo compris."""
    societe, _, resp = _societe_context(request, "groupes")
    if resp:
        return JsonResponse({"error": "Accès refusé."}, status=403)
    groupe = societe.equipe_groupes.filter(pk=pk).first()
    if groupe is None:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)
    if not services.peut_administrer_groupe(request.user, societe, groupe):
        return JsonResponse({"error": "Seuls les administrateurs du groupe peuvent le supprimer."}, status=403)
    racine = str(settings.CHAT_MEDIA_ROOT)
    chemins = [f for f in groupe.messages.exclude(fichier="").values_list("fichier", flat=True) if f]
    if groupe.logo:
        chemins.append(groupe.logo)
    titre = groupe.titre
    groupe.delete()
    for rel in chemins:
        try:
            full = os.path.join(racine, rel)
            if os.path.isfile(full):
                os.remove(full)
        except OSError:
            pass
    services.journaliser(societe, "SUPPRESSION", "equipe", f"Groupe — {titre}", "Groupe supprimé", request.user)
    return JsonResponse({"ok": True})


@login_required
def notifications_etat(request):
    """État léger des notifications (sondage pour le son temps réel).

    Le registre des rappels / échéances est resynchronisé avant le compte :
    les non-lus du journal **et** les rappels actifs (jalon renseigné)
    alimentent le badge, dans la limite des permissions de ``activites_visibles``
    / ``rappels_visibles``.
    """
    if request.method != "GET":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    societe = services.societe_pour_notifications(request.user)
    if societe is None:
        return JsonResponse({"count": 0, "latest": 0, "rappels": 0})
    services.assurer_echeances_registre(societe, user=request.user)
    qs = services.activites_visibles(request.user, societe)
    latest = qs.order_by("-id").values_list("id", flat=True).first() or 0
    activites_non_lues = qs.filter(lue=False).count()
    rappels_non_lus = (
        services.rappels_visibles(request.user, societe)
        .exclude(jalon="")
        .filter(lue=False)
        .count()
    )
    return JsonResponse(
        {
            "count": activites_non_lues + rappels_non_lus,
            "latest": latest,
            "rappels": rappels_non_lus,
        }
    )


@login_required
def notifications_donnees(request):
    """Données JSON de la boîte de notifications (catégories + 'aujourd'hui / hier').

    Même payload que ``notifications_payload`` utilisé par le context
    processor : le panneau rafraîchit ainsi en temps réel sans rechargement.
    Les permissions sont celles de ``activites_visibles``.
    """
    if request.method != "GET":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    societe = services.societe_pour_notifications(request.user)
    if societe is None:
        return JsonResponse(
            {"categories": [], "total_unread": 0, "latest": 0, "maintenant": ""}
        )
    structure = services.notifications_payload(request.user, societe)
    structure["son"] = request.user.notif_son_actif
    return JsonResponse(structure)


@login_required
def notifications_lire(request):
    """Marque des notifications comme lues (toutes, une seule via `id`,
    ou toute une catégorie via `categorie`). Renvoie la boîte à jour.

    `id` vaut l'identifiant d'une activité du journal, ou `r<pk>` pour un
    rappel / une échéance suivie (le panneau distingue les deux types).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    societe, _, resp = _societe_context(request, "dashboard")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    services.assurer_echeances_registre(societe, user=request.user)
    qs = services.activites_visibles(request.user, societe).filter(lue=False)
    rqs = services.rappels_visibles(request.user, societe).filter(lue=False)

    pk = (request.POST.get("id") or "").strip()
    categorie = (request.POST.get("categorie") or "").strip()

    maj_activites = 0
    if pk:
        if pk.startswith("r") and pk[1:].isdigit():
            maj_activites = rqs.filter(pk=int(pk[1:])).update(lue=True)
        elif pk.isdigit():
            maj_activites = qs.filter(pk=int(pk)).update(lue=True)
    elif categorie:
        modules = services.modules_categorie(categorie)
        if modules:
            maj_activites = qs.filter(module__in=modules).update(lue=True)
            _ = rqs.filter(module__in=modules).update(lue=True)
        else:
            maj_activites = 0
    else:
        maj_activites = qs.update(lue=True)
        _ = rqs.update(lue=True)

    structure = services.notifications_payload(request.user, societe)
    return JsonResponse(
        {
            "ok": True,
            "maj": maj_activites,
            "categories": structure["categories"],
            "total_unread": structure["total_unread"],
            "count": structure["total_unread"],
            "latest": structure["latest"],
            "maintenant": structure["maintenant"],
            "rappels": structure["rappels"],
            "filtres": structure["filtres"],
            "son": request.user.notif_son_actif,
        }
    )


@login_required
def notification_supprimer(request):
    """Supprime une notification du panneau (une seule, via `id`).

    - Activité du journal (identifiant numérique) : supprimée définitivement
      (c'est un journal d'actions, sans dépendance) ;
    - Rappel / échéance (`id` au format ``r<pk>``) : **masqué** — la ligne est
      conservée en base (``masque=True``, non-lu repassé à lu) mais n'apparaît
      plus nulle part tant que la même échéance est suivie, et n'est pas
      re-notifiée par ``assurer_echeances_registre``.

    Ramène le panneau à jour (même forme JSON que ``notifications_lire``).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    societe, _, resp = _societe_context(request, "dashboard")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    services.assurer_echeances_registre(societe, user=request.user)
    pk = (request.POST.get("id") or "").strip()
    supprimes = 0
    if pk and not services.est_createur(request.user, societe):
        # Journal et rappels sont partagés par toute la société (traçabilité) :
        # seul le propriétaire peut en effacer ; un employé ne peut que les marquer lus.
        return JsonResponse({"error": "Seul le propriétaire peut supprimer une notification. "
                                      "Utilisez « Tout marquer lu »."}, status=403)
    if pk:
        if pk.startswith("r") and pk[1:].isdigit():
            supprimes = services.rappels_visibles(request.user, societe).filter(
                pk=int(pk[1:])
            ).update(masque=True, lue=True)
        elif pk.isdigit():
            supprimes = services.activites_visibles(request.user, societe).filter(
                pk=int(pk)
            ).delete()[0]

    structure = services.notifications_payload(request.user, societe)
    return JsonResponse(
        {
            "ok": True,
            "supprimes": supprimes,
            "categories": structure["categories"],
            "total_unread": structure["total_unread"],
            "count": structure["total_unread"],
            "latest": structure["latest"],
            "maintenant": structure["maintenant"],
            "rappels": structure["rappels"],
            "filtres": structure["filtres"],
            "son": request.user.notif_son_actif,
        }
    )


@login_required
def notifications_son(request):
    """Active / coupe le son des notifications pour ce compte.

    POST ``actif`` = "1"/"0" impose explicitement l'état ; sans paramètre, il
    bascule. La préférence est stockée sur le compte (``notif_son_actif``) et
    appliquée côté client (aucune alerte sonore quand elle est coupée).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    raw = (request.POST.get("actif") or "").strip().lower()
    if raw in ("", "toggle"):
        son = not request.user.notif_son_actif
    elif raw in ("1", "true", "on", "oui"):
        son = True
    elif raw in ("0", "false", "off", "non"):
        son = False
    else:
        return JsonResponse({"error": "Valeur invalide."}, status=400)
    request.user.notif_son_actif = son
    request.user.save(update_fields=["notif_son_actif", "updated_at"])
    return JsonResponse({"ok": True, "son": son})


# ---------------------------------------------------------------------------
# Connecteurs (hub d'intégrations externes)
# ---------------------------------------------------------------------------

_CONNECTEUR_OK = {
    "connecte": "Connecteur activé avec succès.",
    "deconnecte": "Connecteur déconnecté et identifiants effacés.",
    "sync": "Synchronisation terminée.",
    "ajoute": "Connecteur ajouté au hub. Renseignez ses identifiants pour l'activer.",
    "options": "Automatisations Google Workspace enregistrées.",
}
_CONNECTEUR_ERREUR = {
    "droits": "Action réservée au propriétaire de la société.",
    "oauth_config": "Identifiants OAuth de l'application non configurés (à définir dans .env).",
    "oauth_etat": "Session OAuth expirée ou invalide. Réessayez.",
    "oauth_refus": "Autorisation refusée par le fournisseur.",
    "oauth_erreur": "Échec de l'échange de jeton avec le fournisseur.",
    "jeton": "Identifiants refusés. Vérifiez les champs saisis.",
    "test": "Identifiants enregistrés mais le test de connexion a échoué. Vérifiez la configuration.",
    "inconnu": "Connecteur introuvable.",
    "sync": "Synchronisation impossible : le connecteur n'est pas opérationnel.",
    "ajout": "Ajout impossible : le nom du service est manquant.",
}


def _connecteur_retour(**params):
    """Redirection vers le hub avec un message de retour (clé de dictionnaire)."""
    url = reverse("gestion:connecteurs")
    paires = [f"{cle}={quote(str(val))}" for cle, val in params.items() if val]
    return redirect(f"{url}?{'&'.join(paires)}" if paires else url)


def _connecteur_flash(request):
    ok = (request.GET.get("ok") or "").strip()
    erreur = (request.GET.get("erreur") or "").strip()
    return _CONNECTEUR_OK.get(ok, ""), _CONNECTEUR_ERREUR.get(erreur, "")


def _connecteur_pour(societe, pk):
    return societe.connecteurs.filter(pk=pk).first()


def _carte_connecteur(request, cls, inst, est_createur):
    """Construit la carte d'un connecteur (enregistré ou personnalisé)."""
    meta = cls.metadata()
    connecte = bool(inst and inst.est_connecte)
    statut = inst.statut if inst else "NON_CONNECTE"
    carte = dict(meta)
    carte.update(
        {
            "pk": inst.pk if inst else None,
            "connecte": connecte,
            "statut": statut,
            "statut_label": dict(Connecteur.STATUT_CHOICES).get(statut, statut),
            "personnalise": bool(inst and inst.est_personnalise),
            "compte_externe": inst.compte_externe if inst else "",
            "derniere_sync": inst.derniere_sync if inst else None,
            "derniere_erreur": (inst.derniere_erreur if (inst and est_createur) else ""),
            "champs_renseignes": (
                inst.identifiants_masques() if (inst and est_createur) else []
            ),
            "oauth_pret": (
                cls.oauth_configure()
                if meta["auth_type"] == AuthType.OAUTH2
                else True
            ),
            "webhook_url": (
                request.build_absolute_uri(
                    reverse(
                        "gestion:connecteur_webhook",
                        args=[inst.pk, inst.webhook_secret],
                    )
                )
                if inst
                else ""
            ),
        }
    )
    return carte


@login_required
def connecteurs(request):
    """Hub : bibliothèque de connecteurs, recherche et ajout, journal."""
    societe, ctx, resp = _societe_context(request, "connecteurs")
    if resp:
        return resp
    est_createur = services.est_createur(request.user, societe)
    instances = {c.type_connecteur: c for c in societe.connecteurs.all()}

    cartes = []
    for cls in tout_connecteurs():
        inst = instances.pop(cls.key, None)
        # Un employé découvre les mêmes connecteurs que le créateur, en
        # lecture seule : seules les actions restent réservées au propriétaire
        # (connexion, configuration, déconnexion) et les données sensibles
        # sont masquées dans « _carte_connecteur ».
        cartes.append(_carte_connecteur(request, cls, inst, est_createur))
    # Instances restantes = connecteurs personnalisés ajoutés en ligne.
    for inst in instances.values():
        if not inst.est_personnalise:
            continue
        cls = inst.classe
        if cls is not None:
            cartes.append(_carte_connecteur(request, cls, inst, est_createur))

    comptes = {}
    for carte in cartes:
        comptes[carte["categorie"]] = comptes.get(carte["categorie"], 0) + 1
    categories = [
        {
            "key": cle,
            "label": CATEGORIE_LABELS.get(cle, cle.replace("_", " ").title()),
            "count": nombre,
        }
        for cle, nombre in comptes.items()
    ]

    type_filtre = (request.GET.get("type") or "").strip()
    visibles = [c for c in cartes if not type_filtre or c["categorie"] == type_filtre]

    evenements, journaux = [], []
    if est_createur:
        evenements = list(
            ConnecteurEvenement.objects.filter(connecteur__societe=societe)
            .select_related("connecteur")[:12]
        )
        journaux = list(
            ConnecteurSyncLog.objects.filter(connecteur__societe=societe)
            .select_related("connecteur")[:12]
        )

    onglet = (request.GET.get("onglet") or "librairie").strip()
    if onglet not in ("librairie", "ajouter") or not est_createur:
        onglet = "librairie"
    requete, recherche = "", None
    if onglet == "ajouter":
        from .connecteurs import catalogue

        requete = (request.GET.get("q") or "").strip()
        recherche = catalogue.rechercher(requete)
        deja = set(societe.connecteurs.values_list("type_connecteur", flat=True))
        for bloc in ("local", "internet"):
            for entree in recherche[bloc]:
                entree["deja"] = bool(entree["registre"] and entree["key"] in deja)

    flash_ok, flash_erreur = _connecteur_flash(request)
    gw_conn = societe.connecteurs.filter(type_connecteur="google_meet").first()
    gw_opts = google_workspace.options(gw_conn) if gw_conn else dict(google_workspace.OPTIONS_DEFAUT)
    ctx["gw"] = {
        "connecte": bool(gw_conn is not None and gw_conn.est_connecte),
        "compte": (gw_conn.compte_externe if gw_conn else "") or "",
        "pk": gw_conn.pk if gw_conn else None,
        "erreur": (gw_conn.derniere_erreur if gw_conn else "") or "",
        "derniere_sync": gw_conn.derniere_sync if gw_conn else None,
        "options": [
            {"cle": cle, "libelle": libelle, "actif": gw_opts[cle]}
            for cle, libelle in google_workspace.OPTIONS_LIBELLES.items()
        ],
    }
    ctx.update(
        {
            "cartes": visibles,
            "categories": categories,
            "type_filtre": type_filtre,
            "onglet": onglet,
            "requete": requete,
            "recherche": recherche,
            "est_createur": est_createur,
            "nb_connectes": sum(1 for c in cartes if c["connecte"]),
            "nb_types": len(cartes),
            "evenements": evenements,
            "journaux": journaux,
            "flash_ok": flash_ok,
            "flash_erreur": flash_erreur,
        }
    )
    return render(request, "gestion/connecteurs.html", ctx)


@login_required
def connecteur_connecter(request, key):
    """Démarre ou finalise la connexion d'un connecteur."""
    societe, _, resp = _societe_context(request, "connecteurs")
    if resp:
        return resp
    if request.method != "POST":
        return _connecteur_retour()
    if not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée au propriétaire de la société.")
    cls = get_connecteur_class(key)
    if cls is None:
        raise Http404("Connecteur inconnu.")
    meta = cls.metadata()

    inst = societe.connecteurs.filter(type_connecteur=key).first()
    if inst is None:
        inst = Connecteur.objects.create(
            societe=societe,
            type_connecteur=key,
            nom=cls.nom,
            auth_mode=meta["auth_type"],
            scopes=meta["scopes"],
            webhook_secret=secrets.token_hex(32),
            cree_par=request.user,
        )
    elif not inst.webhook_secret:
        inst.webhook_secret = secrets.token_hex(32)
        inst.save(update_fields=["webhook_secret", "modifie_le"])

    if meta["auth_type"] == AuthType.OAUTH2:
        if not cls.oauth_configure():
            return _connecteur_retour(erreur="oauth_config")
        state = secrets.token_urlsafe(24)
        request.session["connecteur_oauth"] = {
            "state": state,
            "pk": inst.pk,
            "key": key,
            "ts": timezone.now().timestamp(),
        }
        redirect_uri = request.build_absolute_uri(
            reverse("gestion:connecteur_callback", args=[key])
        )
        try:
            return redirect(cls.authorize_redirect(redirect_uri, state))
        except Exception:
            return _connecteur_retour(erreur="oauth_erreur")

    if meta["auth_type"] == AuthType.WEBHOOK:
        inst.statut = "CONNECTE"
        inst.derniere_erreur = ""
        inst.save(update_fields=["statut", "derniere_erreur", "modifie_le"])
        services.journaliser(
            societe, "CONNEXION", "connecteurs",
            f"Connecteur activé : {cls.nom}", utilisateur=request.user,
        )
        return _connecteur_retour(ok="connecte")

    return _connecteur_finaliser_jeton(societe, inst, cls, request)


def _connecteur_finaliser_jeton(societe, inst, cls, request):
    """Enregistre des identifiants (jeton/clé), teste et retourne la redirection."""
    try:
        cls.connecter_avec_jeton(inst, request.POST)
    except ValueError:
        return _connecteur_retour(erreur="jeton")
    ok, message = cls.tester(inst)
    if ok:
        inst.statut = "CONNECTE"
        inst.derniere_erreur = ""
        inst.compte_externe = cls.recuperer_compte(inst) or inst.compte_externe
    else:
        inst.statut = "ERREUR"
        inst.derniere_erreur = message
    inst.save()
    services.journaliser(
        societe, "CONNEXION", "connecteurs",
        f"Connecteur connecté : {cls.nom}", detail=message,
        utilisateur=request.user,
    )
    return _connecteur_retour(ok="connecte" if ok else "", erreur="" if ok else "test")


@login_required
def connecteur_ajouter(request):
    """Ajoute un connecteur personnalisé depuis le catalogue (recherche Internet)."""
    societe, _, resp = _societe_context(request, "connecteurs")
    if resp:
        return resp
    if request.method != "POST":
        return _connecteur_retour(onglet="ajouter")
    if not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée au propriétaire de la société.")

    nom = (request.POST.get("nom") or "").strip()[:120]
    if not nom:
        return _connecteur_retour(onglet="ajouter", erreur="ajout")

    base = re.sub(r"[^a-z0-9]+", "-", nom.lower()).strip("-") or "service"
    key, rang = f"perso-{base}"[:60], 2
    while societe.connecteurs.filter(type_connecteur=key).exists():
        key = f"perso-{base}-{rang}"[:60]
        rang += 1

    auth = (request.POST.get("auth") or "token").strip()
    configuration = {
        "personnalise": True,
        "nom": nom,
        "fournisseur": (request.POST.get("fournisseur") or "")[:120],
        "description": (request.POST.get("description") or "")[:500],
        "categorie": (request.POST.get("categorie") or "developpeur")[:40],
        "icone": (request.POST.get("icone") or "🧩")[:8],
        "couleur": (request.POST.get("couleur") or "#64748b")[:20],
        "doc_url": (request.POST.get("doc_url") or "")[:400],
        "base_url": (request.POST.get("base_url") or "")[:400],
        "auth": auth,
        "source": (request.POST.get("source") or "Catalogue")[:40],
        "identifiant": (request.POST.get("identifiant") or "")[:200],
    }
    inst = Connecteur.objects.create(
        societe=societe,
        type_connecteur=key,
        nom=nom,
        auth_mode="webhook" if auth == "webhook" else "token",
        configuration=configuration,
        webhook_secret=secrets.token_hex(32),
        cree_par=request.user,
        statut="CONNECTE" if auth == "webhook" else "NON_CONNECTE",
    )
    services.journaliser(
        societe, "CONNEXION", "connecteurs",
        f"Connecteur ajouté : {nom}",
        detail=configuration.get("source", ""), utilisateur=request.user,
    )
    return _connecteur_retour(ok="ajoute")


@login_required
def connecteur_configurer(request, pk):
    """Configure les identifiants d'un connecteur personnalisé."""
    societe, _, resp = _societe_context(request, "connecteurs")
    if resp:
        return resp
    if request.method != "POST":
        return _connecteur_retour()
    if not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée au propriétaire de la société.")
    inst = _connecteur_pour(societe, pk)
    cls = inst.classe if inst else None
    if inst is None or cls is None:
        return _connecteur_retour(erreur="inconnu")
    if cls.auth_type == AuthType.WEBHOOK:
        inst.statut = "CONNECTE"
        inst.derniere_erreur = ""
        inst.save(update_fields=["statut", "derniere_erreur", "modifie_le"])
        return _connecteur_retour(ok="connecte")
    return _connecteur_finaliser_jeton(societe, inst, cls, request)


@login_required
def connecteur_callback(request, key):
    """Retour OAuth2 : échange le code contre des jetons (chiffrés)."""
    societe, _, resp = _societe_context(request, "connecteurs")
    if resp:
        return resp
    if not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée au propriétaire de la société.")
    cls = get_connecteur_class(key)
    if cls is None:
        raise Http404("Connecteur inconnu.")
    data = request.session.pop("connecteur_oauth", None) or {}
    state = (request.GET.get("state") or "").strip()
    if not state or data.get("state") != state or data.get("key") != key:
        return _connecteur_retour(erreur="oauth_etat")
    inst = _connecteur_pour(societe, data.get("pk"))
    if inst is None:
        return _connecteur_retour(erreur="inconnu")
    if request.GET.get("error"):
        return _connecteur_retour(erreur="oauth_refus")
    code = (request.GET.get("code") or "").strip()
    if not code:
        return _connecteur_retour(erreur="oauth_erreur")
    redirect_uri = request.build_absolute_uri(
        reverse("gestion:connecteur_callback", args=[key])
    )
    try:
        brut = cls.echanger_code(code, redirect_uri)
    except Exception:
        return _connecteur_retour(erreur="oauth_erreur")
    if (
        not isinstance(brut, dict)
        or brut.get("ok") is False
        or not (brut.get("access_token") or brut.get("id_token"))
    ):
        return _connecteur_retour(erreur="oauth_erreur")

    inst.definir_jetons(brut)
    inst.statut = "CONNECTE"
    inst.derniere_erreur = ""
    inst.compte_externe = cls.recuperer_compte(inst)
    inst.save()
    ok, message = cls.tester(inst)
    if not ok:
        inst.statut = "ERREUR"
        inst.derniere_erreur = message
        inst.save(update_fields=["statut", "derniere_erreur", "modifie_le"])
        return _connecteur_retour(erreur="test")
    services.journaliser(
        societe, "CONNEXION", "connecteurs",
        f"Connecteur connecté : {cls.nom}", utilisateur=request.user,
    )
    return _connecteur_retour(ok="connecte")


@login_required
def connecteur_deconnecter(request, pk):
    """Efface les identifiants d'un connecteur (retour à l'état non connecté)."""
    societe, _, resp = _societe_context(request, "connecteurs")
    if resp:
        return resp
    if request.method != "POST":
        return _connecteur_retour()
    if not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée au propriétaire de la société.")
    inst = _connecteur_pour(societe, pk)
    if inst is None:
        return _connecteur_retour(erreur="inconnu")
    libelle = inst.nom or inst.type_connecteur
    inst.definir_jetons({})
    inst.statut = "NON_CONNECTE"
    inst.compte_externe = ""
    inst.derniere_erreur = ""
    inst.configuration = {}
    inst.save()
    from . import globe as globe_service
    globe_service.vider_connecteur(inst)
    services.journaliser(
        societe, "SUPPRESSION", "connecteurs",
        f"Connecteur déconnecté : {libelle}", utilisateur=request.user,
    )
    return _connecteur_retour(ok="deconnecte")


@login_required
def connecteur_sync(request, pk):
    """Lance une synchronisation et journalise le résultat."""
    societe, _, resp = _societe_context(request, "connecteurs")
    if resp:
        return resp
    if request.method != "POST":
        return _connecteur_retour()
    if not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée au propriétaire de la société.")
    inst = _connecteur_pour(societe, pk)
    cls = inst.classe if inst else None
    if inst is None or cls is None:
        return _connecteur_retour(erreur="inconnu")
    if not inst.est_connecte:
        return _connecteur_retour(erreur="sync")

    debut = timezone.now()
    elements, message, statut = 0, "", "OK"
    try:
        elements, message = cls.synchroniser(inst)
        inst.derniere_erreur = ""
    except Exception as exc:
        statut, message = "ERREUR", str(exc)
        inst.derniere_erreur = message
    duree = int((timezone.now() - debut).total_seconds() * 1000)
    ConnecteurSyncLog.objects.create(
        connecteur=inst, statut=statut, message=(message or "")[:2000],
        elements=int(elements or 0), duree_ms=duree,
    )
    inst.derniere_sync = timezone.now()
    inst.statut = "ERREUR" if statut == "ERREUR" else "CONNECTE"
    inst.save(update_fields=["derniere_sync", "derniere_erreur", "statut", "modifie_le"])
    libelle = inst.nom or inst.type_connecteur
    services.journaliser(
        societe, "MODIFICATION", "connecteurs",
        f"Synchronisation : {libelle}", detail=message or "", utilisateur=request.user,
    )
    return _connecteur_retour(ok="sync" if statut == "OK" else "", erreur="" if statut == "OK" else "sync")


@csrf_exempt
def connecteur_webhook(request, pk, jeton):
    """Réception d'événements externes (URL secrète + signature optionnelle).

    Sécurité : l'URL porte ``webhook_secret`` (comparé en temps constant), les
    signatures ``X-Connecteur-Signature``/``X-Hub-Signature-256``/``X-Slack-Signature``
    sont vérifiées si présentes, et aucune donnée sensible n'est journalisée.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    inst = (
        Connecteur.objects.filter(pk=pk).select_related("societe").first()
    )
    if (
        inst is None
        or not inst.webhook_secret
        or not secrets.compare_digest(inst.webhook_secret, jeton or "")
    ):
        return JsonResponse({"error": "Connecteur introuvable."}, status=404)

    corps = request.body or b""
    entetes = {cle: valeur for cle, valeur in request.headers.items()}
    cls = inst.classe

    a_signature = any(
        entetes.get(nom)
        for nom in (
            "X-Connecteur-Signature",
            "X-Hub-Signature-256",
            "X-Signature",
            "X-Slack-Signature",
        )
    )
    signature_ok = True
    if a_signature and cls is not None:
        signature_ok = cls.signature_valide(inst, corps, entetes)
        if not signature_ok:
            return JsonResponse({"error": "Signature invalide."}, status=403)

    payload = charger_json(corps)
    resume = {}
    if cls is not None:
        try:
            resume = cls.traiter_webhook(inst, payload, entetes) or {}
        except Exception as exc:
            resume = {"resume": f"Erreur de traitement : {exc}"}

    entetes_surs = {
        cle: valeur
        for cle, valeur in entetes.items()
        if cle.lower()
        in {
            "content-type",
            "user-agent",
            "x-github-event",
            "stripe-signature",
            "x-connecteur-signature",
            "x-hub-signature-256",
            "x-slack-signature",
        }
    }
    evenement = ConnecteurEvenement.objects.create(
        connecteur=inst,
        evenement=str(resume.get("evenement") or "")[:120],
        payload=payload if isinstance(payload, dict) else {},
        entetes=entetes_surs,
        signature_valide=signature_ok,
        traite=True,
    )
    return JsonResponse(
        {"ok": True, "evenement": evenement.pk, "signature": signature_ok}
    )


@login_required
def globe(request):
    """Page du globe 3D interactif (composant générique par connecteur)."""
    societe, ctx, resp = _societe_context(request, "globe")
    if resp:
        return resp
    from . import globe as globe_service
    globe_service.alimenter_app(societe)
    # Rafraîchit l'activité des réseaux sociaux connectés (best-effort).
    # Réservé au propriétaire, borné à une fois toutes les 6 h pour éviter
    # tout appel réseau systématique ; les erreurs sont silencieuses.
    if services.est_createur(request.user, societe):
        from .connecteurs.providers import ReseauSocial
        seuil = timezone.now() - timedelta(hours=6)
        for con in societe.connecteurs.filter(statut="CONNECTE"):
            cls = con.classe
            if not (isinstance(cls, type) and issubclass(cls, ReseauSocial)):
                continue
            if con.derniere_sync and con.derniere_sync > seuil:
                continue
            try:
                cls.synchroniser(con)
                con.derniere_sync = timezone.now()
                con.save(update_fields=["derniere_sync", "modifie_le"])
            except Exception:
                pass
    ctx["globe_donnees_url"] = reverse("gestion:globe_donnees")
    ctx["globe_cartes"] = stats.cartes_globe(societe)
    return render(request, "gestion/globe.html", ctx)


@login_required
def globe_donnees(request):
    """JSON des agrégats du globe (pays → région → ville) selon permissions.

    Le paramètre ``mode`` (``tous`` | ``plateforme`` | ``sociaux``) permet de
    restreindre les données au cœur de la plateforme ou aux réseaux sociaux.
    """
    societe, ctx, resp = _societe_context(request, "globe")
    if resp:
        return resp
    from . import globe as globe_service
    mode = request.GET.get("mode", "tous")
    if mode not in globe_service.MODES_GLOBE:
        mode = "tous"
    agr, sources = globe_service.payload_pour(request.user, societe, mode=mode)
    payload = dict(agr)
    payload["mode"] = mode
    payload["sources"] = sources
    payload["derniere_maj"] = timezone.now().isoformat()
    mesures = [
        {
            "cle": m["cle"],
            "label": m["label"],
            "couleur": m["couleur"],
            "format_ca": m["cle"] == "ca",
        }
        for m in agr["mesures"]
    ]
    if mode == "sociaux":
        mesures = [m for m in mesures if m["cle"] in globe_service.MESURES_RESEAUX]
    elif mode == "plateforme":
        mesures = [m for m in mesures if m["cle"] not in globe_service.MESURES_RESEAUX]
    payload["mesures"] = mesures
    return JsonResponse(payload)


def _peut_gerer_reunions(user, societe):
    return services.est_createur(user, societe) or "reunions" in services.modules_autorises(
        user, societe
    )


def _reunion_json(r):
    debut = datetime.combine(r.date, r.heure)
    fin = debut + timedelta(minutes=r.duree or 60)
    return {
        "id": r.pk,
        "titre": r.titre,
        "date": r.date.isoformat(),
        "heure": r.heure.strftime("%H:%M"),
        "fin": fin.strftime("%H:%M"),
        "duree": r.duree,
        "description": r.description,
        "lien": r.lien_meet,
        "passee": r.est_passee,
        "participants": [f"{p.prenom} {p.nom}".strip() for p in r.participants.all()],
        "cree_par": (
            f"{r.cree_par.prenom} {r.cree_par.nom}".strip() if r.cree_par_id else ""
        ),
    }


@login_required
def reunions_page(request):
    """Calendrier mensuel des réunions (création, glisser-déposer, détails)."""
    societe, ctx, resp = _societe_context(request, "reunions")
    if resp:
        return resp
    reunions = (
        societe.reunions.prefetch_related("participants").select_related("cree_par")
        .order_by("date", "heure")
    )
    meet = societe.connecteurs.filter(type_connecteur="google_meet").first()
    ctx.update(
        {
            "reunions_json": [_reunion_json(r) for r in reunions],
            "employes_json": [
                {"id": e.pk, "nom": f"{e.prenom} {e.nom}".strip(), "email": e.email or ""}
                for e in societe.employes.order_by("nom", "prenom")
            ],
            "peut_gerer": _peut_gerer_reunions(request.user, societe),
            "meet": {
                "connecte": bool(meet is not None and meet.est_connecte),
                "compte": (meet.compte_externe if meet else "") or "",
                "connecter_url": reverse("gestion:connecteur_connecter", args=["google_meet"]),
            },
            "durees": Reunion.DUREE_CHOICES,
            "gw_calendrier": bool(
                meet is not None and meet.est_connecte
                and google_workspace.options(meet)["calendrier"]
            ),
            "reunion_ok": request.GET.get("reunion", ""),
            "reunion_erreur": request.GET.get("reunion_erreur", ""),
        }
    )
    return render(request, "gestion/reunions.html", ctx)


@login_required
def reunions_deplacer(request, pk):
    """Glisser-déposer : change la date d'une réunion à venir (JSON)."""
    societe, _, resp = _societe_context(request, "reunions")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    if not _peut_gerer_reunions(request.user, societe):
        return JsonResponse({"error": "Action non autorisée."}, status=403)
    reunion = societe.reunions.filter(pk=pk).first()
    if reunion is None:
        return JsonResponse({"error": "Réunion introuvable."}, status=404)
    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        payload = {}
    nouvelle = parse_date(str(payload.get("date") or ""))
    if nouvelle is None:
        return JsonResponse({"error": "Date invalide."}, status=400)
    if reunion.est_passee:
        return JsonResponse({"error": "Une réunion passée ne peut pas être déplacée."}, status=400)
    if (nouvelle, reunion.heure) < (timezone.localdate(), timezone.localtime().time()):
        return JsonResponse({"error": "La nouvelle date doit être dans le futur."}, status=400)
    if reunion.evenement_google_id:
        meet = societe.connecteurs.filter(
            type_connecteur="google_meet", statut="CONNECTE"
        ).first()
        ok, message = google_workspace.deplacer_reunion(meet, reunion, nouvelle)
        if not ok:
            return JsonResponse({"error": "Google Meet : " + message}, status=502)
    ancienne = reunion.date_aff
    reunion.date = nouvelle
    reunion.save(update_fields=["date"])
    services.journaliser(
        societe, "MODIFICATION", "reunions", reunion.titre,
        f"Déplacée du {ancienne} au {reunion.date_aff}", request.user,
    )
    return JsonResponse({"ok": True, "reunion": _reunion_json(reunion)})


@login_required
def reunions_supprimer(request, pk):
    """Supprime une réunion (et son événement Google si possible) — JSON."""
    societe, _, resp = _societe_context(request, "reunions")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    if not _peut_gerer_reunions(request.user, societe):
        return JsonResponse({"error": "Action non autorisée."}, status=403)
    reunion = societe.reunions.filter(pk=pk).first()
    if reunion is None:
        return JsonResponse({"error": "Réunion introuvable."}, status=404)
    avertissement = ""
    if reunion.evenement_google_id and not reunion.est_passee:
        meet = societe.connecteurs.filter(
            type_connecteur="google_meet", statut="CONNECTE"
        ).first()
        ok, message = google_workspace.supprimer_evenement(meet, reunion.evenement_google_id)
        if not ok:
            avertissement = "L'événement Google n'a pas pu être supprimé (" + message + ")."
    titre = reunion.titre
    reunion.delete()
    services.journaliser(societe, "SUPPRESSION", "reunions", titre, "", request.user)
    return JsonResponse({"ok": True, "avertissement": avertissement})


@login_required
def reunions_google(request):
    """Événements Google Agenda à afficher dans le calendrier (JSON)."""
    societe, _, resp = _societe_context(request, "reunions")
    if resp:
        return JsonResponse({"error": "Session invalide."}, status=401)
    conn = google_workspace.connecteur(societe)
    if conn is None or not google_workspace.options(conn)["calendrier"]:
        return JsonResponse({"actif": False, "events": []})
    try:
        events = google_workspace.evenements_agenda(conn)
    except Exception:
        logging.getLogger(__name__).warning("Lecture Google Agenda impossible", exc_info=True)
        return JsonResponse({
            "actif": True, "events": [],
            "erreur": "Google Agenda est momentanément injoignable : seules les réunions de l'application sont affichées.",
        })
    return JsonResponse({"actif": True, "events": events})


@login_required
def google_workspace_options(request):
    """Enregistre les automatisations Google Workspace (+ synchro immédiate)."""
    societe, _, resp = _societe_context(request, "connecteurs")
    if resp:
        return resp
    if request.method != "POST":
        return _connecteur_retour()
    if not services.est_createur(request.user, societe):
        return HttpResponseForbidden("Action réservée au propriétaire de la société.")
    conn = societe.connecteurs.filter(type_connecteur="google_meet").first()
    if conn is None or not conn.est_connecte:
        return _connecteur_retour(erreur="sync")
    google_workspace.enregistrer_options(
        conn, {cle: request.POST.get(cle) == "on" for cle in google_workspace.OPTIONS_DEFAUT}
    )
    services.journaliser(
        societe, "CONFIGURATION", "connecteurs", "Google Workspace",
        "Automatisations mises à jour", request.user,
    )
    if request.POST.get("action") == "synchroniser":
        debut = timezone.now()
        statut = "OK"
        try:
            elements, message = google_workspace.synchroniser_tout(conn)
            conn.derniere_erreur = ""
        except Exception as exc:
            elements, message, statut = 0, str(exc), "ERREUR"
            conn.derniere_erreur = message[:500]
        ConnecteurSyncLog.objects.create(
            connecteur=conn, statut=statut, message=(message or "")[:2000],
            elements=int(elements or 0),
            duree_ms=int((timezone.now() - debut).total_seconds() * 1000),
        )
        conn.derniere_sync = timezone.now()
        conn.save(update_fields=["derniere_sync", "derniere_erreur", "modifie_le"])
        return _connecteur_retour(ok="sync" if statut == "OK" else "", erreur="" if statut == "OK" else "sync")
    return _connecteur_retour(ok="options")
