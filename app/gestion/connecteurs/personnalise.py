"""Connecteurs personnalisés ajoutés depuis le catalogue en ligne.

Un service découvert sur Internet (annuaire d'API, catalogue curé) n'a pas de
code dédié. On génère alors dynamiquement une classe :class:`ConnecteurBase`
à partir de la ``configuration`` stockée sur l'instance ``Connecteur``.

Avantages :

- l'architecture reste extensible sans reconstruire le hub ;
- chaque service ajouté obtient sa propre ``key`` (``perso-…``) et sa propre
  carte, avec ses champs de connexion ;
- aucun secret n'est stocké dans la ``configuration`` (seuls des métadonnées
  publiques : fournisseur, URL de doc, URL de base, catégorie).
"""

import re

import requests

from .base import AuthType, ConnecteurBase


def _champs_pour(configuration):
    champs = []
    if configuration.get("base_url") is not None:
        champs.append(
            {
                "name": "base_url",
                "label": "URL de base de l'API",
                "type": "url",
                "required": False,
                "placeholder": configuration.get("base_url")
                or "https://api.exemple.com",
                "help": "Laissez vide pour conserver l'URL détectée.",
            }
        )
    champs.append(
        {
            "name": "token",
            "label": "Jeton d'accès (Bearer)",
            "type": "password",
            "required": False,
            "placeholder": "••••••••",
            "help": "Stocké chiffré ; jamais réaffiché.",
        }
    )
    if configuration.get("auth") == "webhook":
        champs.append(
            {
                "name": "shared_secret",
                "label": "Secret partagé",
                "type": "password",
                "required": False,
                "help": "Pour vérifier la signature HMAC-SHA256 des appels.",
            }
        )
    return tuple(champs)


def classe_personnalisee(instance):
    """Construit la classe de connecteur adaptée à cette instance personnalisée."""
    configuration = instance.configuration or {}
    base_url = configuration.get("base_url") or ""
    url_documentation = configuration.get("doc_url") or ""
    est_webhook = configuration.get("auth") == "webhook"

    class ConnecteurPersonnalise(ConnecteurBase):
        key = instance.type_connecteur
        nom = instance.nom or configuration.get("nom") or "Service"
        description = configuration.get("description") or "Connecteur ajouté depuis le catalogue."
        categorie = configuration.get("categorie") or "developpeur"
        icone = configuration.get("icone") or "🧩"
        couleur = configuration.get("couleur") or "#64748b"
        auth_type = AuthType.WEBHOOK if est_webhook else AuthType.TOKEN
        champs = _champs_pour(configuration)
        doc_url = url_documentation

        @classmethod
        def tester(cls, connecteur):
            jetons = connecteur.jetons()
            cible = (jetons.get("base_url") or base_url or "").rstrip("/")
            jeton = jetons.get("token") or ""
            if not cible:
                return True, "Connecteur enregistré (aucune URL à tester)."
            try:
                reponse = requests.get(
                    cible,
                    headers=({"Authorization": f"Bearer {jeton}"} if jeton else {}),
                    timeout=15,
                )
            except requests.RequestException as exc:
                return False, f"Réseau indisponible : {exc}"
            return True, f"Service joignable (HTTP {reponse.status_code})."

    nom_classe = "Perso_" + re.sub(r"[^A-Za-z0-9]+", "_", instance.type_connecteur)
    ConnecteurPersonnalise.__name__ = nom_classe[:60]
    return ConnecteurPersonnalise
