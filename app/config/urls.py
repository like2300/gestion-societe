from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles import views as staticfiles_views
from django.urls import include, path, re_path
from django.views.static import serve as fichier_statique

from gestion import backoffice
from gestion.urls_public import backoffice_urls, vitrine

urlpatterns = [
    # Racine : site vitrine public (présentation, tarifs, inscription) + paiement par lien
    *vitrine,
    # Back-office de l'équipe SaaS (abonnements, paiements, sociétés)
    path("backoffice/", include(backoffice_urls)),
    # /admin/ : tableau de bord de l'équipe (ventes, demandes d'offre, activations) ;
    # les données brutes restent accessibles dans l'admin Django (/admin/gestion/…)
    path("admin/", backoffice.index, name="admin_tableau"),
    path("admin/", admin.site.urls),
    # Allauth : /accounts/login/, /accounts/signup/, /accounts/logout/,
    # /accounts/password/reset/...
    path("accounts/", include("allauth.urls")),
    # Gestionnaire de société : /gestion/...
    path("gestion/", include("gestion.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# AlwaysData : le service Python ne sert pas /static/ seul.
# Django cherche les fichiers dans STATIC_ROOT et dans les dossiers static/ des apps.
# Les images de la vitrine chargées dans l'admin sont servies uniquement sous
# /media/vitrine/ ; les autres médias restent privés.
urlpatterns += [
    re_path(r"^static/(?P<path>.*)$", staticfiles_views.serve, {"insecure": True}),
    re_path(r"^media/vitrine/(?P<path>.*)$", fichier_statique,
            {"document_root": settings.MEDIA_ROOT / "vitrine"}),
]
