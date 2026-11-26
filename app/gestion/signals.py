"""Signaux : journalisation des connexions et traçage de la présence."""

from allauth.account.signals import user_logged_in as allauth_user_logged_in
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone


@receiver(user_logged_in)
def journaliser_connexion(sender, request, user, **kwargs):
    """Ajoute une entrée « Connexion » au journal de la société de l'utilisateur."""
    from . import services

    if getattr(user, "is_superuser", False):
        return
    # Rattachement automatique des fiches employé portant le même email.
    services.lier_comptes_utilisateur(user)
    societe = services.societe_pour_utilisateur(user)
    if societe is None:
        return
    services.journaliser(
        societe,
        "CONNEXION",
        "compte",
        f"{user.prenom} {user.nom}",
        "Connexion à la plateforme",
        user,
    )
    _ouvrir_presence(user, societe, request)


@receiver(allauth_user_logged_in)
def marquer_connexion_google(sender, request, user, **kwargs):
    """Repère une connexion Google pour la validation par code à 6 chiffres."""
    session = getattr(request, "session", None)
    if session is None:
        return
    sociallogin = kwargs.get("sociallogin")
    provider = getattr(getattr(sociallogin, "account", None), "provider", "")
    if provider == "google":
        session["connexion_par_google"] = True
    else:
        session.pop("connexion_par_google", None)


@receiver(user_logged_out)
def fermer_presence(sender, request, user, **kwargs):
    """À la déconnexion, clôt la session d'activité de l'employé (durée).

    Le signal est émis avant le vidage de la session : la clé de session
    correspond encore à la présence ouverte, ce qui permet de clôturer
    exactement la session de l'onglet/du navigateur déconnecté.
    """
    from .models import EmployePresence

    if user is None or getattr(user, "is_superuser", False):
        return
    employe = getattr(user, "employe_profil", None)
    if employe is None:
        return
    session = getattr(request, "session", None)
    session_key = session.session_key if session and session.session_key else ""
    ouvertes = list(
        EmployePresence.objects.filter(
            employe=employe, date_deconnexion__isnull=True
        ).order_by("-date_connexion")
    )
    if not ouvertes:
        return
    cible = None
    if session_key:
        for p in ouvertes:
            if p.session_key == session_key:
                cible = p
                break
    if cible is None:
        # Repli : session unique, on clôt la plus récente.
        cible = ouvertes[0]
    cible.finaliser(timezone.now())


def _ouvrir_presence(user, societe, request):
    """Démarre (ou relance) le compteur de présence de l'employé."""
    from .models import EmployePresence

    employe = getattr(user, "employe_profil", None)
    if employe is None or societe is None:
        return
    session_key = getattr(request, "session", None)
    session_key = session_key.session_key if session_key else ""
    maintenant = timezone.now()
    # Finalise une éventuelle session abandonnée (même compte, nouvelle connexion).
    for ouverte in EmployePresence.objects.filter(
        employe=employe, date_deconnexion__isnull=True
    ):
        if ouverte.session_key and ouverte.session_key != session_key:
            ouverte.finaliser()
    presence = EmployePresence.objects.create(
        employe=employe,
        societe=societe,
        session_key=session_key,
        date_connexion=maintenant,
        derniere_activite=maintenant,
        ip=_adresse_ip(request),
        user_agent=_user_agent(request),
    )
    if session_key:
        request.session["_presence_id"] = presence.pk


def _adresse_ip(request):
    try:
        if request is None:
            return ""
        x = getattr(request, "META", {}) or {}
        return (x.get("HTTP_X_FORWARDED_FOR") or x.get("REMOTE_ADDR") or "")[:64]
    except Exception:
        return ""


def _user_agent(request):
    try:
        if request is None:
            return ""
        return (getattr(request, "META", {}) or {}).get("HTTP_USER_AGENT", "")[:300]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Google Workspace : échéances et tâches poussées dans Google Agenda
# ---------------------------------------------------------------------------
def _agenda(objet_type, instance, suppression=False):
    try:
        from . import google_workspace

        google_workspace.planifier(objet_type, instance, suppression=suppression)
    except Exception:
        pass  # jamais bloquant


@receiver(post_save, sender="gestion.EcheancePaiement")
def echeance_vers_agenda(sender, instance, **kwargs):
    _agenda("echeance", instance)


@receiver(post_delete, sender="gestion.EcheancePaiement")
def echeance_retiree_agenda(sender, instance, **kwargs):
    _agenda("echeance", instance, suppression=True)


@receiver(post_save, sender="gestion.Tache")
def tache_vers_agenda(sender, instance, **kwargs):
    _agenda("tache", instance)


@receiver(post_delete, sender="gestion.Tache")
def tache_retiree_agenda(sender, instance, **kwargs):
    _agenda("tache", instance, suppression=True)
