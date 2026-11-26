"""Routes publiques (site vitrine, paiement par lien) et back-office SaaS."""

from django.urls import path

from . import backoffice, site_public

vitrine = [
    path("", site_public.accueil, name="vitrine"),
    path("tarifs/<int:pk>/", site_public.choisir_forfait, name="choisir_forfait"),
    path("abonnement/<uuid:jeton>/", site_public.payer, name="abonnement_payer"),
]

backoffice_urls = ([
    path("", backoffice.index, name="index"),
    path("demandes/", backoffice.liste_demandes, name="demandes"),
    path("abonnements/", backoffice.liste_abonnements, name="abonnements"),
    path("abonnements/<int:pk>/<str:action>/", backoffice.action_abonnement, name="abonnement_action"),
    path("paiements/", backoffice.liste_paiements, name="paiements"),
    path("paiements/<int:pk>/<str:action>/", backoffice.action_paiement, name="paiement_action"),
    path("societes/", backoffice.liste_societes, name="societes"),
    path("societes/<int:pk>/lien-activation/", backoffice.lien_activation_societe, name="lien_activation"),
    path("activer/<str:jeton>/", backoffice.activer_societe, name="activer_societe"),
    path("forfaits/", backoffice.liste_forfaits, name="forfaits"),
    path("forfaits/creer/", backoffice.creer_forfait, name="forfait_creer"),
    path("forfaits/<int:pk>/modifier/", backoffice.modifier_forfait, name="forfait_modifier"),
    path("forfaits/<int:pk>/toggle/", backoffice.toggle_forfait, name="forfait_toggle"),
], "backoffice")
