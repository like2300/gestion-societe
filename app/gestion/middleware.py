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

class MotDePasseInitialMiddleware:
    """Bloque un compte qui utilise encore le mot de passe par défaut.

    Tant que ``user.doit_changer_mdp`` est vrai (employé à sa première
    connexion), seules la fenêtre de changement de mot de passe et la
    déconnexion sont accessibles :
    - toute page du tableau de bord renvoie vers l'accueil, où la fenêtre
      obligatoire s'affiche (impossible de la fermer) ;
    - toute action (POST, API JSON…) est refusée (403).
    """

    AUTORISES = ("/static/", "/media/", "/accounts/logout/", "/favicon")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "doit_changer_mdp", False):
            reponse = self._bloquer(request)
            if reponse is not None:
                return reponse
        return self.get_response(request)

    def _bloquer(self, request):
        from django.http import JsonResponse
        from django.shortcuts import redirect
        from django.urls import reverse

        chemin = request.path
        url_mdp = reverse("gestion:mdp_premiere_connexion")
        url_accueil = reverse("gestion:dashboard")
        if chemin == url_mdp or chemin.startswith(self.AUTORISES):
            return None
        if request.method in ("GET", "HEAD") and chemin == url_accueil:
            return None  # l'accueil affiche la fenêtre obligatoire
        ajax = (
            request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "")
            or request.method not in ("GET", "HEAD")
        )
        if ajax:
            return JsonResponse(
                {"ok": False, "erreur": "Définissez d'abord votre mot de passe personnel."},
                status=403,
            )
        return redirect(url_accueil)


class AbonnementRestreintMiddleware:
    """Bloque l'application quand l'abonnement manque, est en attente, expiré ou suspendu.

    Les pages de création de société, de choix d'offre et de redirection après
    connexion restent ouvertes pour permettre de choisir un forfait.
    """

    AUTORISES = (
        "/static/", "/media/", "/accounts/", "/favicon",
        "/gestion/post-login/", "/gestion/societe/creer/",
        "/gestion/societe/abonnement/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated and request.path.startswith("/gestion/")
                and not request.path.startswith(self.AUTORISES)):
            reponse = self._bloquer(request, user)
            if reponse is not None:
                return reponse
        return self.get_response(request)

    def _bloquer(self, request, user):
        from django.http import JsonResponse
        from django.shortcuts import render

        from . import abonnements, services

        if getattr(user, "is_superuser", False):
            societe = user.societes_creees.first()
        else:
            societe = services.societe_pour_utilisateur(user)
        if societe is None:
            return None
        e = abonnements.etat(societe)
        if not e or not e["restreinte"]:
            return None
        # Le créateur garde l'accès à sa page d'abonnement pour suivre sa demande.
        if request.path.startswith("/gestion/societe/abonnement/"):
            return None
        ajax = (request.headers.get("x-requested-with") == "XMLHttpRequest"
                or "application/json" in request.headers.get("accept", "")
                or request.method not in ("GET", "HEAD"))
        if ajax:
            return JsonResponse({"ok": False, "erreur": "L'accès de votre société est momentanément restreint."}, status=403)
        return render(request, "gestion/acces_restreint.html", {"societe": societe, "etat": e}, status=403)
