"""Socle d'extension des connecteurs.

Ajouter une intégration = écrire une sous-classe de :class:`ConnecteurBase`
(ou :class:`OAuth2Connecteur`) dans ``providers.py`` et la décorer avec
``@register``. Aucune autre partie de l'architecture n'a besoin d'être
modifiée : le hub, les filtres, les cartes et le stockage des identifiants
sont pilotés par les métadonnées déclarées ici.
"""

import hashlib
import hmac
import json
import os
from urllib.parse import urlencode

import requests


#: Libellés français des catégories (filtres du hub).
CATEGORIE_LABELS = {
    "email": "E-mail",
    "communication": "Communication",
    "paiement": "Paiement",
    "webhook": "Webhooks",
    "developpeur": "Développeur",
    "productivite": "Productivité",
    "documents": "Documents",
    "crm": "CRM",
    "marketing": "Marketing",
    "ia": "IA & génération",
    "boutique": "Site & boutique",
    "api": "API",
    "social": "Réseaux sociaux",
    "autre": "Autre",
}



class AuthType:
    """Modes d'authentification gérés par le socle."""

    OAUTH2 = "oauth2"    # redirection vers le fournisseur, jetons rafraîchis
    TOKEN = "token"      # clé d'API / jeton collé par le PDG (jamais re-affiché)
    WEBHOOK = "webhook"  # connecteur entrant : reçoit des événements signés
    NONE = "none"        # aucun identifiant (ex. endpoint public)


class ConnecteurBase:
    """Description + comportement d'un type de connecteur.

    Toutes les méthodes reçoivent l'instance ``Connecteur`` (qui porte les
    identifiants *chiffrés* et la configuration propre à l'entreprise) pour
    garantir l'isolation multi-tenant.
    """

    key = ""
    nom = ""
    description = ""
    categorie = "autre"
    icone = "🔌"
    couleur = "#0284c7"
    auth_type = AuthType.TOKEN
    scopes = ""
    champs = ()          # [{"name","label","type","required","help","placeholder"}]
    doc_url = ""
    en_avant = False

    # ------------------------------------------------------------------
    # Métadonnées exposées au hub (jamais de secret ici)
    # ------------------------------------------------------------------
    @classmethod
    def metadata(cls):
        return {
            "key": cls.key,
            "nom": cls.nom,
            "description": cls.description,
            "categorie": cls.categorie,
            "categorie_label": CATEGORIE_LABELS.get(
                cls.categorie, cls.categorie.replace("_", " ").title()
            ),
            "icone": cls.icone,
            "couleur": cls.couleur,
            "auth_type": cls.auth_type,
            "scopes": cls.scopes,
            "champs": list(cls.champs),
            "doc_url": cls.doc_url,
            "en_avant": cls.en_avant,
        }

    # ------------------------------------------------------------------
    # Connecteurs OAuth2
    # ------------------------------------------------------------------
    client_id_env = ""
    client_secret_env = ""
    authorize_url = ""
    token_url = ""

    @classmethod
    def oauth_configure(cls):
        """Vrai si les identifiants OAuth de l'application sont présents (.env)."""
        return bool(
            os.getenv(cls.client_id_env or "", "")
            and os.getenv(cls.client_secret_env or "", "")
        )

    @classmethod
    def _client_id(cls):
        return os.getenv(cls.client_id_env or "", "")

    @classmethod
    def _client_secret(cls):
        return os.getenv(cls.client_secret_env or "", "")

    @classmethod
    def authorize_redirect(cls, redirect_uri, state):
        """URL de consentement du fournisseur (OAuth2 « authorization code »)."""
        params = {
            "client_id": cls._client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": cls.scopes,
            "state": state,
        }
        params.update(cls.extra_authorize_params())
        return f"{cls.authorize_url}?{urlencode(params)}"

    @classmethod
    def extra_authorize_params(cls):
        return {}

    @classmethod
    def echanger_code(cls, code, redirect_uri):
        """Échange le code d'autorisation contre des jetons. Retourne un dict."""
        resp = requests.post(
            cls.token_url,
            data={
                "code": code,
                "client_id": cls._client_id(),
                "client_secret": cls._client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    def rafraichir(cls, connecteur):
        """Rafraîchit le jeton d'accès à partir du refresh token (si dispo)."""
        from ..models import Connecteur  # import tardif (évite les cycles)

        jetons = connecteur.jetons()
        refresh = jetons.get("refresh_token")
        if not refresh:
            return jetons
        resp = requests.post(
            cls.token_url,
            data={
                "client_id": cls._client_id(),
                "client_secret": cls._client_secret(),
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        nouveaux = resp.json()
        fusion = dict(jetons)
        fusion.update(nouveaux)
        connecteur.definir_jetons(fusion)
        connecteur.save(update_fields=["identifiants_chiffres", "modifie_le"])
        return fusion

    # ------------------------------------------------------------------
    # Cycle de vie (à surcharger selon le connecteur)
    # ------------------------------------------------------------------
    @classmethod
    def connecter_avec_jeton(cls, connecteur, donnees):
        """Valide et enregistre une clé d'API / un jeton saisi manuellement."""
        jetons = {}
        champs = {c["name"] for c in cls.champs}
        for nom in champs:
            valeur = (donnees.get(nom) or "").strip()
            if valeur:
                jetons[nom] = valeur
        manquants = [
            c["label"]
            for c in cls.champs
            if c.get("required") and not jetons.get(c["name"])
        ]
        if manquants:
            raise ValueError("Champs requis : " + ", ".join(manquants))
        connecteur.definir_jetons(jetons)
        connecteur.statut = "CONNECTE"
        connecteur.derniere_erreur = ""
        connecteur.save(
            update_fields=["identifiants_chiffres", "statut", "derniere_erreur", "modifie_le"]
        )
        return jetons

    @classmethod
    def tester(cls, connecteur):
        """Vérifie que les identifiants fonctionnent. Retourne (ok, message)."""
        return True, "Identifiants enregistrés."

    @classmethod
    def recuperer_compte(cls, connecteur):
        """Libellé du compte relié (par défaut : aucun). Surchargé si possible."""
        return ""

    @classmethod
    def synchroniser(cls, connecteur):
        """Synchronise les données. Retourne (elements, message) ou lève une erreur.

        L'implémentation par défaut ne fait rien : chaque connecteur précis
        peut la remplacer (import de factures Stripe, e-mails, messages Slack…).
        """
        return 0, "Synchronisation non implémentée pour ce connecteur."

    # ------------------------------------------------------------------
    # Webhooks entrants
    # ------------------------------------------------------------------
    @classmethod
    def _secret_webhook(cls, connecteur):
        """Secret de signature : champ dédié, sinon secret généré du connecteur."""
        jetons = connecteur.jetons()
        return (
            jetons.get("webhook_secret")
            or jetons.get("shared_secret")
            or connecteur.webhook_secret
            or ""
        )

    @classmethod
    def signature_valide(cls, connecteur, corps_brut, entetes):
        """Vérifie une signature HMAC-SHA256 sur le corps brut.

        Gère deux conventions, comparées en temps constant :
        - en-tête hexadécimal ``X-Connecteur-Signature`` (et compatibilité
          ``X-Hub-Signature-256``/``X-Signature`` avec préfixe ``sha256=``) ;
        - schéma Slack ``X-Slack-Signature: v0=…`` (HMAC sur ``v0:ts:corps``).
        """
        secret_str = cls._secret_webhook(connecteur)
        if not secret_str:
            return False
        secret = secret_str.encode()
        candidats = []
        for nom in ("X-Connecteur-Signature", "X-Hub-Signature-256", "X-Signature"):
            valeur = entetes.get(nom, "")
            if valeur.startswith("sha256="):
                valeur = valeur[7:]
            if valeur:
                candidats.append(valeur)
        attendu = hmac.new(secret, corps_brut, hashlib.sha256).hexdigest()
        if any(hmac.compare_digest(attendu, c) for c in candidats):
            return True
        sig = entetes.get("X-Slack-Signature", "")
        ts = entetes.get("X-Slack-Request-Timestamp", "")
        if sig.startswith("v0=") and ts:
            base = f"v0:{ts}:".encode() + corps_brut
            attendu_v0 = "v0=" + hmac.new(secret, base, hashlib.sha256).hexdigest()
            if hmac.compare_digest(attendu_v0, sig):
                return True
        return False

    @classmethod
    def traiter_webhook(cls, connecteur, payload, entetes):
        """Traite un événement entrant. Retourne un dict de résumé.

        Par défaut, on enregistre simplement l'événement. Les connecteurs
        précis peuvent réagir (créer un paiement, un client, etc.) en appelant
        uniquement des services internes vérifiés.
        """
        evenement = ""
        if isinstance(payload, dict):
            evenement = (
                payload.get("type") or payload.get("event") or payload.get("event_type") or ""
            )
        return {"evenement": str(evenement)[:120], "resume": "Événement enregistré."}


class OAuth2Connecteur(ConnecteurBase):
    """Base des connecteurs OAuth2 avec test de connexion standard."""

    auth_type = AuthType.OAUTH2
    #: endpoint « userinfo » optionnel pour valider le jeton
    userinfo_url = ""

    @classmethod
    def tester(cls, connecteur):
        if not cls.userinfo_url:
            return True, "Connexion OAuth enregistrée."
        jeton = connecteur.jetons().get("access_token", "")
        if not jeton:
            return False, "Jeton d'accès manquant."
        try:
            resp = requests.get(
                cls.userinfo_url,
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=20,
            )
        except requests.RequestException as exc:
            return False, f"Réseau indisponible : {exc}"
        if resp.status_code == 200:
            return True, "Connexion vérifiée."
        return False, f"Le fournisseur a répondu {resp.status_code}."

    @classmethod
    def extra_authorize_params(cls):
        # access_type=offline + prompt=consent => refresh_token garanti (Google).
        return {}

    @classmethod
    def recuperer_compte(cls, connecteur):
        """Libellé du compte relié (e-mail…) via l'endpoint userinfo. Best-effort."""
        if not cls.userinfo_url:
            return ""
        jeton = connecteur.jetons().get("access_token", "")
        if not jeton:
            return ""
        try:
            data = requests.get(
                cls.userinfo_url,
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=15,
            ).json()
        except (requests.RequestException, ValueError):
            return ""
        if not isinstance(data, dict):
            return ""
        for cle in ("email", "mail", "userPrincipalName", "preferred_username", "name"):
            if data.get(cle):
                return str(data[cle])[:200]
        return ""


def charger_json(corps_brut):
    """Parse un corps JSON de webhook (dict vide si invalide)."""
    try:
        data = json.loads(corps_brut.decode("utf-8", "replace"))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
