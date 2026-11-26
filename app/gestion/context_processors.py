import os

from django.conf import settings
from django.utils.functional import SimpleLazyObject

_UI_DIR = os.path.join(os.path.dirname(__file__), "static", "gestion")

SEO_DESCRIPTION = (
    "Archi : pilotez votre entreprise au même endroit : collaboration d'équipe, "
    "RH, clients, projets, finances, planning, suite bureautique et assistant IA."
)


def images_publiques(request):
    """Images de la vitrine et logo de l'application, sur toutes les pages."""
    from .site_public import images_site

    return {"images": SimpleLazyObject(images_site)}


def seo(request):
    """Réglages SEO communs à toutes les pages publiques."""
    return {"SITE_URL": settings.SITE_URL, "SEO_DESCRIPTION": SEO_DESCRIPTION}


def _ui_version():
    """Version des fichiers ui.* (date de modification) : force le navigateur
    à recharger le CSS/JS après chaque mise à jour, sans Ctrl+F5."""
    try:
        return str(int(max(
            os.path.getmtime(os.path.join(_UI_DIR, nom))
            for nom in ("ui.css", "gfield.css", "ui.js", "ui-table.js", "ui-forms.js", "logout-confirm.js", "wa-picker.js", "taches.css", "taches-board.js", "apayer.js", "bureau.css", "bureau-commun.js", "bureau-sheets.js", "bureau-slides.js", "planning.css", "planning.js", "rappels.js")
        )))
    except OSError:
        return "1"


def media_prefix(request):
    """Fournit MEDIA_PREFIX (préfixe médias) et UI_VERSION à toutes les pages."""
    from django.utils.functional import SimpleLazyObject

    def _partages():
        # Applications où l'utilisateur est invité comme partenaire (Tableur / Documents / Présentations)
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return set()
        from .models import FichierBureau

        codes = FichierBureau.objects.filter(partenaires__compte=user).values_list("type_fichier", flat=True).distinct()
        return {{"SHEET": "sheets", "DOC": "docs", "SLIDES": "slides"}.get(c) for c in codes}

    return {"MEDIA_PREFIX": settings.MEDIA_URL, "UI_VERSION": _ui_version(), "BUREAU_PARTAGES": SimpleLazyObject(_partages)}


def notifications(request):
    """Alimente la boîte de notifications (journal des actions) du dashboard.

    Les catégories (rappels, clients, tâches, …) et les compteurs de non-lu
    sont construits par ``services.notifications_payload`` : le panneau est
    rendu en serveur puis rafraîchi en temps réel via l'endpoint JSON
    ``gestion:notifications_donnees`` (même payload, mêmes permissions).
    """
    from . import services

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    societe = services.societe_pour_notifications(user)
    if societe is None:
        return {}

    structure = services.notifications_payload(user, societe)
    return {
        "notif_categories": structure["categories"],
        "notif_total_unread": structure["total_unread"],
        "nav_notif_count": structure["total_unread"],
        "nav_notif_last": structure["latest"],
        "notif_maintenant": structure["maintenant"],
        "notif_filtres": structure.get("filtres", {}),
        "notif_son": getattr(user, "notif_son_actif", True),
        # Journal partagé : seul le propriétaire peut en supprimer des entrées
        "notif_peut_supprimer": services.est_createur(user, societe),
    }


def mdp_initial(request):
    """Indique si l'utilisateur doit définir son mot de passe (première connexion)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    doit = bool(getattr(user, "doit_changer_mdp", False))
    contexte = {"doit_changer_mdp": doit}
    if doit:
        from . import services

        societe = services.societe_pour_utilisateur(user)
        contexte["mdp_defaut"] = services.mot_de_passe_defaut(societe)
    return contexte


def abonnement_alerte(request):
    """Pop-up de réabonnement : uniquement pour le CRÉATEUR de la société, quand
    l'abonnement se termine dans 7 jours ou moins, ou a expiré / été suspendu.
    Ajoute au passage la notification correspondante dans la cloche (sans doublon)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not request.path.startswith("/gestion/"):
        return {}
    from . import abonnements, services

    societe = services.societe_pour_notifications(user)
    if societe is None or not services.est_createur(user, societe):
        return {}
    e = abonnements.etat(societe)
    if not e or e["niveau"] not in ("bientot", "expire", "suspendu"):
        return {}
    abonnements.notifier_fin(societe, e)
    return {"abo_alerte": e}
