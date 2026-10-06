"""Middleware : fait vivre la présence des employés pendant leur navigation.

À chaque requête d'un employé connecté, la présence ouverte (session courante)
voit son « dernier instant d'activité » rafraîchi, au plus une fois par minute,
afin de quantifier le temps passé dans la plateforme même sans déconnexion
explicite (session abandonnée, onglet fermé…).
"""

import time

from django.utils import timezone


class PresenceActiviteMiddleware:
    """Pilote l'horodatage d'activité d'une session de présence employé."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._pinger(request)
        return self.get_response(request)

    def _pinger(self, request):
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return
        employe = getattr(request.user, "employe_profil", None)
        if employe is None or getattr(employe, "societe_id", None) is None:
            return
        session = getattr(request, "session", None)
        if session is None:
            return
        presence_id = session.get("_presence_id")
        if not presence_id:
            return
        # Limitation : rafraîchir l'activité à chaque page suffit ; le
        # heartbeat JavaScript fournit les pings intermédiaires. Le throttle
        # est volontairement court (15 s) pour rester bien sous EN_LIGNE_DELAI.
        cle = "_presence_ping"
        maintenant = time.time()
        dernier = session.get(cle) or 0
        if maintenant - dernier < 15:
            return
        session[cle] = maintenant
        now = timezone.now()
        try:
            from .models import EmployePresence

            EmployePresence.objects.filter(
                pk=presence_id,
                employe=employe,
                date_deconnexion__isnull=True,
            ).update(derniere_activite=now)
        except Exception:
            return