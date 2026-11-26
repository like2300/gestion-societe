"""E-mails envoyés aux employés (identifiants et code de validation)."""

import logging

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def _url_absolue(url):
    """Transforme une URL relative en URL absolue pour un client de messagerie."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return settings.SITE_URL.rstrip("/") + "/" + url.lstrip("/")


def contexte_email(societe=None):
    """Données de personnalisation communes à tous les e-mails."""
    from .site_public import images_site

    images = images_site()
    logo_app = (
        images.get("logo_app")
        or images.get("logo_header")
        or images.get("favicon")
        or ""
    )
    nom = getattr(societe, "nom", "") or "Archi"
    logo_societe = ""
    if societe is not None and getattr(societe, "logo", ""):
        try:
            logo_societe = _url_absolue(default_storage.url(societe.logo))
        except Exception:
            logo_societe = ""
    return {
        "email_nom_societe": nom,
        "email_logo_societe": logo_societe,
        "email_logo_app": _url_absolue(logo_app),
        "SITE_URL": settings.SITE_URL,
    }


def _envoyer(sujet, gabarit, contexte, destinataire):
    """Envoie un gabarit texte et HTML. Retourne True si l'envoi réussit."""
    if not destinataire:
        return False
    contexte = dict(contexte)
    contexte.update(contexte_email(contexte.get("societe")))
    contexte.setdefault("login_url", _url_absolue(reverse("account_login")))
    try:
        texte = render_to_string(f"emails/{gabarit}.txt", contexte)
        html = render_to_string(f"emails/{gabarit}.html", contexte)
        send_mail(
            sujet,
            texte,
            settings.DEFAULT_FROM_EMAIL,
            [destinataire],
            html_message=html,
        )
        return True
    except Exception:
        logger.exception("Envoi de l'e-mail « %s » impossible", sujet)
        return False


def envoyer_compte_employe(employe, user, mot_de_passe, code):
    """Envoie les identifiants et le code de première connexion à l'employé."""
    contexte = {
        "societe": employe.societe,
        "employe": employe,
        "email": user.email,
        "mot_de_passe": mot_de_passe,
        "code": code,
    }
    return _envoyer(
        f"Votre accès à {employe.societe.nom}",
        "compte_employe",
        contexte,
        user.email,
    )


def envoyer_code_validation(user, code):
    """Rend un nouveau code de validation à un employé connecté avec Google."""
    employe = getattr(user, "employe_profil", None)
    societe = employe.societe if employe is not None else None
    contexte = {
        "societe": societe,
        "employe": employe,
        "email": user.email,
        "code": code,
    }
    return _envoyer(
        "Votre code de connexion",
        "code_validation",
        contexte,
        user.email,
    )
