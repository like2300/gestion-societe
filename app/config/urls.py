from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Racine : le tableau de bord (redirige selon la connexion)
    path("", RedirectView.as_view(pattern_name="gestion:dashboard"), name="home"),
    path("admin/", admin.site.urls),
    # Allauth : /accounts/login/, /accounts/signup/, /accounts/logout/,
    # /accounts/password/reset/...
    path("accounts/", include("allauth.urls")),
    # Gestionnaire de société : /gestion/...
    path("gestion/", include("gestion.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
