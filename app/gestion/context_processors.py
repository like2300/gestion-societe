from django.conf import settings


def media_prefix(request):
    """Fournit MEDIA_PREFIX pour toutes les pages (préfixe médias absolu)."""
    return {"MEDIA_PREFIX": settings.MEDIA_URL}


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
    }
