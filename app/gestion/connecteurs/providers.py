"""Connecteurs fournis avec la plateforme.

Chaque classe est autonome. Les identifiants OAuth de l'*application* sont
lus dans ``app/.env`` (jamais en base) ; les jetons OAuth de l'*entreprise*
sont chiffrés dans le modèle ``Connecteur``.
"""

import os
import uuid

import requests

from django.conf import settings

from .base import AuthType, ConnecteurBase, OAuth2Connecteur
from .registry import register


# ---------------------------------------------------------------------------
# E-mail
# ---------------------------------------------------------------------------
@register
class Gmail(OAuth2Connecteur):
    key = "gmail"
    nom = "Gmail"
    description = "Envoyez et lisez des e-mails, suivez les échanges clients."
    categorie = "email"
    icone = "✉️"
    couleur = "#ea4335"
    scopes = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email"
    client_id_env = "GOOGLE_CONNECTEUR_CLIENT_ID"
    client_secret_env = "GOOGLE_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    doc_url = "https://developers.google.com/gmail/api"
    en_avant = True

    @classmethod
    def extra_authorize_params(cls):
        return {"access_type": "offline", "prompt": "consent"}


@register
class GoogleMeet(OAuth2Connecteur):
    key = "google_meet"
    nom = "Google Workspace"
    description = (
        "Agenda + Meet : réunions avec lien Meet, invitations e-mail, échéances et "
        "tâches dans Google Agenda, calendrier affiché dans la page Réunions."
    )
    categorie = "communication"
    icone = "📹"
    couleur = "#01875f"
    scopes = (
        "https://www.googleapis.com/auth/calendar.events "
        "https://www.googleapis.com/auth/userinfo.email"
    )
    client_id_env = "GOOGLE_CONNECTEUR_CLIENT_ID"
    client_secret_env = "GOOGLE_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    doc_url = "https://developers.google.com/meet"
    en_avant = True

    # ------------------------------------------------------------------
    # Identifiants OAuth de l'application : clés dédiées, avec repli sur
    # les identifiants Google déjà présents dans l'environnement (allauth).
    # Jamais de secret en code ni en base : tout depuis l'environnement.
    # ------------------------------------------------------------------
    @classmethod
    def oauth_configure(cls):
        return bool(cls._client_id() and cls._client_secret())

    @classmethod
    def _client_id(cls):
        return os.getenv(cls.client_id_env or "", "") or os.getenv(
            "GOOGLE_CLIENT_ID", ""
        )

    @classmethod
    def _client_secret(cls):
        return os.getenv(cls.client_secret_env or "", "") or os.getenv(
            "GOOGLE_CLIENT_SECRET", ""
        )

    @classmethod
    def extra_authorize_params(cls):
        return {"access_type": "offline", "prompt": "consent"}

    # ------------------------------------------------------------------
    # Création d'une réunion : événement Calendrier + conférence Meet.
    # ------------------------------------------------------------------
    @classmethod
    def creer_reunion(cls, connecteur, titre, debut_iso, fin_iso, emails=None,
                      description=""):
        """Crée un événement avec conférence Google Meet.

        ``debut_iso``/``fin_iso`` : ``YYYY-MM-DDTHH:MM:SS`` (fuseau du site
        transmis par ``timeZone``). Les adresses de ``emails`` sont ajoutées
        en invitations, mais sans envoi d'e-mails (le partage se fait dans
        la plateforme). Retourne (ok, lien_meet, evenement_id, message).
        """
        jetons = connecteur.jetons()
        jeton = (jetons or {}).get("access_token", "")
        if not jeton:
            return False, "", "", "Jeton d'accès manquant."
        corps = {
            "summary": (titre or "Réunion")[:160],
            "description": (description or "Réunion interne"),
            "start": {"dateTime": debut_iso, "timeZone": settings.TIME_ZONE},
            "end": {"dateTime": fin_iso, "timeZone": settings.TIME_ZONE},
            "conferenceData": {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        adresses = [e for e in (emails or []) if e]
        if adresses:
            corps["attendees"] = [{"email": a} for a in adresses]
        try:
            resp = requests.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events"
                "?sendUpdates=none",
                headers={"Authorization": f"Bearer {jeton}"},
                json=corps,
                timeout=30,
            )
        except requests.RequestException as exc:
            return False, "", "", f"Réseau indisponible : {exc}"
        if resp.status_code not in (200, 201):
            message = f"Google a répondu {resp.status_code}."
            try:
                corps_erreur = resp.json()
                if isinstance(corps_erreur, dict) and corps_erreur.get("error", {}).get("message"):
                    message += " " + corps_erreur["error"]["message"][:200]
            except ValueError:
                pass
            return False, "", "", message
        data = resp.json() if isinstance(resp.json(), dict) else {}
        lien = (data.get("hangoutLink") or "")
        if not lien:
            for ep in ((data.get("conferenceData") or {}).get("entryPoints") or []):
                if ep.get("entryPointType") == "video" and ep.get("uri"):
                    lien = ep["uri"]
                    break
        return (
            bool(lien),
            lien,
            (data.get("id") or ""),
            "Réunion créée." if lien else "Lien Meet introuvable dans la réponse.",
        )

    @classmethod
    def synchroniser(cls, connecteur):
        """Pousse échéances et tâches à venir dans Google Agenda."""
        from .. import google_workspace

        return google_workspace.synchroniser_tout(connecteur)

    @classmethod
    def deplacer_reunion(cls, connecteur, evenement_id, debut_iso, fin_iso):
        """Déplace l'événement Google (nouvelles dates). Retourne (ok, message)."""
        jeton = ((connecteur.jetons() or {}) if connecteur else {}).get("access_token", "")
        if not jeton or not evenement_id:
            return False, "Connecteur Google Meet indisponible."
        try:
            resp = requests.patch(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events/"
                f"{evenement_id}?sendUpdates=none",
                headers={"Authorization": f"Bearer {jeton}"},
                json={
                    "start": {"dateTime": debut_iso, "timeZone": settings.TIME_ZONE},
                    "end": {"dateTime": fin_iso, "timeZone": settings.TIME_ZONE},
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            return False, f"Réseau indisponible : {exc}"
        if resp.status_code not in (200, 201):
            return False, f"Google a répondu {resp.status_code}."
        return True, "Réunion déplacée."

    @classmethod
    def supprimer_reunion(cls, connecteur, evenement_id):
        """Supprime l'événement Google. Retourne (ok, message)."""
        jeton = ((connecteur.jetons() or {}) if connecteur else {}).get("access_token", "")
        if not jeton or not evenement_id:
            return False, "Connecteur Google Meet indisponible."
        try:
            resp = requests.delete(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events/"
                f"{evenement_id}?sendUpdates=none",
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=30,
            )
        except requests.RequestException as exc:
            return False, f"Réseau indisponible : {exc}"
        if resp.status_code not in (200, 204, 410):
            return False, f"Google a répondu {resp.status_code}."
        return True, "Événement Google supprimé."


@register
class Outlook(OAuth2Connecteur):
    key = "outlook"
    nom = "Outlook / Microsoft 365"
    description = "Synchronisez boîte mail, calendrier et contacts Microsoft."
    categorie = "email"
    icone = "📧"
    couleur = "#0078d4"
    scopes = "offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Read"
    client_id_env = "MICROSOFT_CONNECTEUR_CLIENT_ID"
    client_secret_env = "MICROSOFT_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    userinfo_url = "https://graph.microsoft.com/v1.0/me"
    doc_url = "https://learn.microsoft.com/graph/"
    en_avant = True

    @classmethod
    def extra_authorize_params(cls):
        return {"response_mode": "query"}


# ---------------------------------------------------------------------------
# Documents Office (Microsoft 365 / OneDrive via Graph)
# ---------------------------------------------------------------------------
class MicrosoftGraphDocuments(OAuth2Connecteur):
    """Base des documents Office stockés sur OneDrive / SharePoint.

    Réutilise l'application Microsoft de la plateforme
    (``MICROSOFT_CONNECTEUR_CLIENT_ID`` / ``_SECRET``) et l'API Graph.
    Chaque sous-classe ne change que l'extension surveillée.
    """

    categorie = "documents"
    scopes = (
        "offline_access "
        "https://graph.microsoft.com/User.Read "
        "https://graph.microsoft.com/Files.ReadWrite"
    )
    client_id_env = "MICROSOFT_CONNECTEUR_CLIENT_ID"
    client_secret_env = "MICROSOFT_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    userinfo_url = "https://graph.microsoft.com/v1.0/me"
    fichiers_url = "https://graph.microsoft.com/v1.0/me/drive/recent"
    extensions = ()

    @classmethod
    def extra_authorize_params(cls):
        return {"response_mode": "query"}

    @classmethod
    def _est_du_type(cls, fichier):
        nom = str(fichier.get("name") or "")
        extension = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
        return extension in cls.extensions

    @classmethod
    def synchroniser(cls, connecteur):
        """Liste les fichiers récents du type surveillé via Microsoft Graph."""
        jeton = connecteur.jetons().get("access_token", "")
        if not jeton:
            raise RuntimeError("Jeton d'accès manquant : reconnectez le service.")
        try:
            resp = requests.get(
                cls.fichiers_url,
                headers={"Authorization": f"Bearer {jeton}"},
                params={"$top": "100"},
                timeout=25,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Microsoft Graph indisponible : {exc}")
        if resp.status_code == 401:
            raise RuntimeError("Jeton expiré : reconnectez le service.")
        if resp.status_code >= 400:
            raise RuntimeError(f"Microsoft Graph a répondu {resp.status_code}.")
        try:
            elements = resp.json().get("value", [])
        except ValueError:
            elements = []
        retenus = [f for f in elements if cls._est_du_type(f)]
        return len(retenus), f"{len(retenus)} fichier(s) « {cls.nom} » récent(s)."


@register
class MicrosoftWord(MicrosoftGraphDocuments):
    key = "word"
    nom = "Word"
    description = "Retrouvez et suivez vos documents .docx (Word / OneDrive)."
    icone = "📝"
    couleur = "#2b579a"
    extensions = ("docx", "doc")
    doc_url = "https://learn.microsoft.com/graph/api/driveitem-list-recent"


@register
class MicrosoftExcel(MicrosoftGraphDocuments):
    key = "excel"
    nom = "Excel"
    description = "Suivez vos classeurs .xlsx (Excel / OneDrive) et vos feuilles."
    icone = "📊"
    couleur = "#217346"
    extensions = ("xlsx", "xls", "csv")
    doc_url = "https://learn.microsoft.com/graph/api/driveitem-list-recent"


@register
class MicrosoftPowerPoint(MicrosoftGraphDocuments):
    key = "powerpoint"
    nom = "PowerPoint"
    description = "Suivez vos présentations .pptx (PowerPoint / OneDrive)."
    icone = "📽️"
    couleur = "#d24726"
    extensions = ("pptx", "ppt")
    doc_url = "https://learn.microsoft.com/graph/api/driveitem-list-recent"


# ---------------------------------------------------------------------------
# Communication
# ---------------------------------------------------------------------------
@register
class Slack(OAuth2Connecteur):
    key = "slack"
    nom = "Slack"
    description = "Publiez les alertes de la société et recevez les commandes."
    categorie = "communication"
    icone = "💬"
    couleur = "#4a154b"
    scopes = "channels:read chat:write users:read"
    client_id_env = "SLACK_CONNECTEUR_CLIENT_ID"
    client_secret_env = "SLACK_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://slack.com/oauth/v2/authorize"
    token_url = "https://slack.com/api/oauth.v2.access"
    doc_url = "https://api.slack.com/authentication/oauth-v2"
    en_avant = True

    @classmethod
    def tester(cls, connecteur):
        jeton = connecteur.jetons().get("access_token", "")
        if not jeton:
            return False, "Jeton d'accès manquant."
        try:
            resp = requests.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=20,
            )
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            return False, f"Réseau indisponible : {exc}"
        if data.get("ok"):
            return True, f"Connecté à l'espace {data.get('team', '')}.".strip()
        return False, data.get("error", "Réponse Slack invalide.")

    @classmethod
    def recuperer_compte(cls, connecteur):
        equipe = connecteur.jetons().get("team") or {}
        if isinstance(equipe, dict):
            return str(equipe.get("name") or equipe.get("id") or "")[:200]
        return ""


# ---------------------------------------------------------------------------
# Paiement
# ---------------------------------------------------------------------------
@register
class Stripe(ConnecteurBase):
    key = "stripe"
    nom = "Stripe"
    description = "Suivez les paiements, factures et abonnements encaissés."
    categorie = "paiement"
    icone = "💳"
    couleur = "#635bff"
    auth_type = AuthType.TOKEN
    champs = [
        {
            "name": "secret_key",
            "label": "Clé secrète Stripe",
            "type": "password",
            "required": True,
            "help": "Clé « sk_live_… » ou « sk_test_… ». Restez en clé de test au début.",
            "placeholder": "sk_live_…",
        },
        {
            "name": "webhook_secret",
            "label": "Secret de signature webhook (optionnel)",
            "type": "password",
            "required": False,
            "help": "« whsec_… » pour valider les événements entrants.",
        },
    ]
    doc_url = "https://stripe.com/docs/api"
    en_avant = True

    @classmethod
    def tester(cls, connecteur):
        cle = connecteur.jetons().get("secret_key", "")
        if not cle:
            return False, "Clé secrète manquante."
        try:
            resp = requests.get(
                "https://api.stripe.com/v1/balance",
                headers={"Authorization": f"Bearer {cle}"},
                timeout=20,
            )
        except requests.RequestException as exc:
            return False, f"Réseau indisponible : {exc}"
        if resp.status_code == 200:
            return True, "Clé Stripe valide."
        return False, f"Stripe a répondu {resp.status_code}."


# ---------------------------------------------------------------------------
# IA & génération de médias
# ---------------------------------------------------------------------------
@register
class Higgsfield(ConnecteurBase):
    key = "higgsfield"
    nom = "Higgsfield"
    description = "Générez images et vidéos par IA via l'API Higgsfield (SOUL, Cinema…)."
    categorie = "ia"
    icone = "🎬"
    couleur = "#0f172a"
    auth_type = AuthType.TOKEN
    base_url = "https://api.higgsfield.ai"
    champs = [
        {
            "name": "api_key_id",
            "label": "Identifiant de clé API",
            "type": "text",
            "required": True,
            "placeholder": "HF_API_KEY_ID",
            "help": "Créé dans la console Higgsfield (console.higgsfield.ai).",
        },
        {
            "name": "api_key_secret",
            "label": "Secret de clé API",
            "type": "password",
            "required": True,
            "help": "Stocké chiffré ; jamais réaffiché.",
            "placeholder": "••••••••",
        },
        {
            "name": "base_url",
            "label": "URL de base de l'API",
            "type": "url",
            "required": False,
            "placeholder": "https://api.higgsfield.ai",
            "help": "Laissez vide pour l'URL officielle.",
        },
    ]
    doc_url = "https://docs.higgsfield.ai/"

    @classmethod
    def _base(cls, connecteur):
        return (connecteur.jetons().get("base_url") or cls.base_url).rstrip("/")

    @classmethod
    def _entetes(cls, connecteur):
        jetons = connecteur.jetons()
        return {
            "Authorization": (
                f"Key {jetons.get('api_key_id', '')}:{jetons.get('api_key_secret', '')}"
            )
        }

    @classmethod
    def tester(cls, connecteur):
        jetons = connecteur.jetons()
        if not jetons.get("api_key_id") or not jetons.get("api_key_secret"):
            return False, "Identifiant et secret de clé API requis."
        # Un identifiant inexistant suffit : 401/403 => clé refusée, sinon clé OK.
        url = cls._base(connecteur) + "/requests/00000000-0000-0000-0000-000000000000/status"
        try:
            resp = requests.get(url, headers=cls._entetes(connecteur), timeout=20)
        except requests.RequestException as exc:
            return False, f"Réseau indisponible : {exc}"
        if resp.status_code in (401, 403):
            return False, "Clé API refusée par Higgsfield."
        return True, f"Clé API acceptée (HTTP {resp.status_code})."


# ---------------------------------------------------------------------------
# Site & boutique en ligne (self-service : API maison, WooCommerce…)
# ---------------------------------------------------------------------------
@register
class SiteBoutique(ConnecteurBase):
    key = "site_boutique"
    nom = "Mon site / ma boutique en ligne"
    description = (
        "Branchez votre propre site ou boutique : API maison, WooCommerce, "
        "PrestaShop… et recevez les commandes par webhook."
    )
    categorie = "boutique"
    icone = "🛍️"
    couleur = "#7c3aed"
    auth_type = AuthType.TOKEN
    champs = [
        {
            "name": "base_url",
            "label": "URL de l'API du site / de la boutique",
            "type": "url",
            "required": False,
            "placeholder": "https://maboutique.fr/wp-json/wc/v3",
            "help": "Laissez vide pour un branchement uniquement par webhook entrant.",
        },
        {
            "name": "token",
            "label": "Jeton d'accès (Bearer) ou clé API",
            "type": "password",
            "required": False,
            "help": "Pour une API maison ou une boutique avec jeton unique.",
        },
        {
            "name": "consumer_key",
            "label": "Clé publique (WooCommerce)",
            "type": "text",
            "required": False,
            "placeholder": "ck_…",
            "help": "Avec la clé secrète pour l'authentification WooCommerce.",
        },
        {
            "name": "consumer_secret",
            "label": "Clé secrète (WooCommerce)",
            "type": "password",
            "required": False,
            "placeholder": "cs_…",
        },
        {
            "name": "shared_secret",
            "label": "Secret webhook (optionnel)",
            "type": "password",
            "required": False,
            "help": "Pour vérifier la signature HMAC-SHA256 des commandes entrantes.",
        },
    ]
    doc_url = "https://woocommerce.github.io/woocommerce-rest-api-docs/"

    @classmethod
    def tester(cls, connecteur):
        jetons = connecteur.jetons()
        base = (jetons.get("base_url") or "").rstrip("/")
        if not base:
            return True, "Connecteur enregistré (webhook entrant uniquement)."
        entetes, auth = {}, None
        if jetons.get("consumer_key") and jetons.get("consumer_secret"):
            auth = (jetons["consumer_key"], jetons["consumer_secret"])
        elif jetons.get("token"):
            entetes["Authorization"] = f"Bearer {jetons['token']}"
        try:
            resp = requests.get(base, headers=entetes, auth=auth, timeout=15)
        except requests.RequestException as exc:
            return False, f"Réseau indisponible : {exc}"
        return True, f"Site joignable (HTTP {resp.status_code})."

    @classmethod
    def traiter_webhook(cls, connecteur, payload, entetes):
        """Traite une commande entrante et l'ajoute au globe 3D (source générique).

        Compatible avec plusieurs formats courants de webhooks de commande :
        WooCommerce (``order.*`` + ``billing``), formats génériques
        (``commande`` / ``total`` / ``adresse``), ou un objet ``order`` imbriqué.
        """
        resume = super().traiter_webhook(connecteur, payload, entetes)
        if not isinstance(payload, dict):
            return resume

        brut = payload.get("data", {}) if isinstance(payload.get("data"), dict) else payload
        if isinstance(brut.get("order"), dict):
            brut = brut["order"]
        nom_evenement = str(
            payload.get("type") or payload.get("event") or payload.get("event_type") or ""
        ).lower()

        fichier = {
            "order.created": "ordre",
            "order.updated": "ordre",
            "ordre": "ordre",
            "commande": "commande",
            "order": "commande",
            "woocommerce": "commande",
        }.get(nom_evenement, "")
        if not fichier or (
            fichier == "commande"
            and not (brut.get("billing") or brut.get("adresse") or brut.get("total"))
        ):
            return resume

        adresse = (
            brut.get("billing")
            if isinstance(brut.get("billing"), dict)
            else brut.get("adresse") or brut.get("address") or {}
        )
        pays = adresse.get("country") or adresse.get("pays") or brut.get("pays") or ""
        ville = adresse.get("city") or adresse.get("ville") or brut.get("ville") or ""
        total = brut.get("total") or brut.get("montant") or brut.get("amount")
        montant = None
        if total not in (None, ""):
            try:
                montant = float(str(total).replace(" ", "").replace(",", "."))
            except (TypeError, ValueError):
                montant = None

        try:
            from ..globe import alimenter_connecteur

            points = []
            if ville or pays:
                points.append({
                    "mesure": "commande",
                    "pays": pays,
                    "ville": ville,
                })
                if montant is not None:
                    points.append({
                        "mesure": "ca",
                        "pays": pays,
                        "ville": ville,
                        "valeur": montant,
                    })
            if points:
                alimenter_connecteur(connecteur, points, remplacer=False)
        except Exception:
            pass  # le webhook reste journalisé même si le globe ne peut pas être servi

        detail = ", ".join(part for part in (ville, pays) if part)
        resume["resume"] = (
            "Commande reçue"
            + (f" de {detail}" if detail else "")
            + (f" · {montant:g}" if montant is not None else "")
        )
        return resume


# ---------------------------------------------------------------------------
# Réseaux sociaux (suivi de l'activité publique d'un compte)
# ---------------------------------------------------------------------------
class ReseauSocial(OAuth2Connecteur):
    """Socle des connecteurs réseaux sociaux.

    ``synchroniser`` récupère l'activité récente du compte (publications +
    statistiques) puis pousse des points dans le globe 3D via
    ``globe.alimenter_connecteur`` (source générique ``connecteur:<pk>``,
    mode ``remplacer`` pour un instantané). Les points sont géolocalisés au
    pays/ville du compte — par défaut le pays du siège, modifiable via la
    ``configuration`` du connecteur (``pays``/``ville``).
    """

    categorie = "social"
    activites_url = ""

    @classmethod
    def _jeton(cls, connecteur):
        return connecteur.jetons().get("access_token", "")

    @classmethod
    def extraire_compte(cls, connecteur, donnees):
        """Infos du compte depuis la réponse de l'API. Best-effort.

        Retourne ``{"nom", "abonnes", "pays", "ville"}``. Les champs absents
        retombent sur la configuration du connecteur (pays/ville du siège).
        """
        return {"nom": "", "abonnes": None, "pays": "", "ville": ""}

    @classmethod
    def extraire_publications(cls, connecteur, donnees):
        """Publications récentes depuis la réponse de l'API. Best-effort.

        Retourne une liste de dicts : ``titre``, ``date`` (ISO), ``likes``,
        ``commentaires``, ``partages``, ``lien``.
        """
        return []

    @classmethod
    def recuperer_activite(cls, connecteur, limite=12):
        """Récupère l'activité récente d'un compte. Retourne (compte, pubs)."""
        jeton = cls._jeton(connecteur)
        if not jeton:
            raise RuntimeError("Jeton d'accès manquant : reconnectez le service.")
        if not cls.activites_url:
            return cls.extraire_compte(connecteur, {}), []
        try:
            resp = requests.get(
                cls.activites_url,
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=25,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"{cls.nom} indisponible : {exc}")
        if resp.status_code in (401, 403):
            raise RuntimeError("Accès refusé : reconnectez le compte.")
        if resp.status_code >= 400:
            raise RuntimeError(f"{cls.nom} a répondu {resp.status_code}.")
        try:
            donnees = resp.json()
        except ValueError:
            donnees = {}
        if not isinstance(donnees, dict):
            donnees = {}
        return cls.extraire_compte(connecteur, donnees), cls.extraire_publications(
            connecteur, donnees
        )

    @classmethod
    def _points_sociaux(cls, connecteur, compte, publications):
        """Transforme l'activité d'un compte en points géographiques.

        - un point ``abonne`` : follower(s) du compte (valeur) ;
        - un point ``publication`` par publication ;
        - un point ``engagement`` par publication (somme likes+commentaires+partages).
        """
        config = connecteur.configuration or {}
        pays = compte.get("pays") or config.get("pays") or "Bénin"
        ville = compte.get("ville") or config.get("ville") or "Cotonou"
        points = []
        abonnes = compte.get("abonnes")
        if abonnes is not None:
            points.append({
                "mesure": "abonne",
                "pays": pays, "ville": ville,
                "valeur": abonnes,
                "metadonnees": {
                    "compte": compte.get("nom") or "",
                    "reseau": cls.nom,
                },
            })
        for pub in publications[:120]:
            engagement = (
                (pub.get("likes") or 0)
                + (pub.get("commentaires") or 0)
                + (pub.get("partages") or 0)
            )
            points.append({
                "mesure": "publication",
                "pays": pays, "ville": ville,
                "date_evenement": pub.get("date"),
                "metadonnees": {
                    "titre": pub.get("titre") or "",
                    "lien": pub.get("lien") or "",
                    "reseau": cls.nom,
                },
            })
            points.append({
                "mesure": "engagement",
                "pays": pays, "ville": ville,
                "valeur": engagement,
                "date_evenement": pub.get("date"),
            })
        return points

    @classmethod
    def synchroniser(cls, connecteur):
        """Synchronise l'activité sociale du compte vers le globe 3D."""
        from ..globe import alimenter_connecteur

        compte, publications = cls.recuperer_activite(connecteur)
        points = cls._points_sociaux(connecteur, compte, publications)
        if points:
            nb = alimenter_connecteur(connecteur, points, remplacer=True)
            return (
                nb,
                f"{len(publications)} publication(s) suivie(s) · "
                f"{nb} point(s) ajouté(s) au globe.",
            )
        return 0, "Aucune activité récente à synchroniser."


@register
class Facebook(ReseauSocial):
    key = "facebook"
    nom = "Facebook"
    description = "Suivez l'activité de votre page : publications et réactions."
    icone = "📘"
    couleur = "#1877f2"
    scopes = "pages_show_list pages_read_engagement pages_manage_posts"
    client_id_env = "FACEBOOK_CONNECTEUR_CLIENT_ID"
    client_secret_env = "FACEBOOK_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://www.facebook.com/dialog/oauth"
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    userinfo_url = "https://graph.facebook.com/me?fields=name"
    activites_url = "https://graph.facebook.com/v19.0/me/feed?fields=message,created_time,permalink_url,likes.summary(true),comments.summary(true)"
    doc_url = "https://developers.facebook.com/docs/graph-api"
    en_avant = True

    @classmethod
    def extraire_compte(cls, connecteur, donnees):
        nom = (
            donnees.get("name")
            or donnees.get("nom")
            or donnees.get("username")
            or donnees.get("handle")
            or ""
        )
        abonne = donnees.get("fan_count") or donnees.get("followers_count")
        return {"nom": str(nom)[:120], "abonnes": abonne, "pays": "", "ville": ""}

    @classmethod
    def extraire_publications(cls, connecteur, donnees):
        resultat = []
        for item in donnees.get("data") or []:
            if not isinstance(item, dict):
                continue
            likes = (item.get("likes") or {}).get("summary", {}).get("total_count")
            commentaires = (item.get("comments") or {}).get("summary", {}).get(
                "total_count"
            )
            resultat.append({
                "titre": str(item.get("message") or item.get("story") or "")[:200],
                "date": (item.get("created_time") or "")[:10],
                "lien": item.get("permalink_url") or item.get("link") or "",
                "likes": int(likes or 0),
                "commentaires": int(commentaires or 0),
                "partages": (item.get("shares") or {}).get("count", 0) or 0,
            })
        return resultat


@register
class Instagram(ReseauSocial):
    key = "instagram"
    nom = "Instagram"
    description = "Suivez l'activité de votre compte : publications et abonnés."
    icone = "📸"
    couleur = "#e4405f"
    scopes = "instagram_business_basic instagram_business_content_management pages_show_list"
    client_id_env = "FACEBOOK_CONNECTEUR_CLIENT_ID"
    client_secret_env = "FACEBOOK_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://www.facebook.com/dialog/oauth"
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    userinfo_url = "https://graph.facebook.com/me?fields=name"
    activites_url = "https://graph.facebook.com/v19.0/me/media?fields=caption,timestamp,permalink,like_count,comments_count,media_type"
    doc_url = "https://developers.facebook.com/docs/instagram-platform"
    en_avant = True

    @classmethod
    def extraire_compte(cls, connecteur, donnees):
        nom = donnees.get("name") or donnees.get("username") or ""
        return {"nom": str(nom)[:120], "abonnes": None, "pays": "", "ville": ""}

    @classmethod
    def extraire_publications(cls, connecteur, donnees):
        resultat = []
        for item in donnees.get("data") or []:
            if not isinstance(item, dict):
                continue
            resultat.append({
                "titre": str(item.get("caption") or "")[:200],
                "date": (item.get("timestamp") or "")[:10],
                "lien": item.get("permalink") or "",
                "likes": int(item.get("like_count") or 0),
                "commentaires": int(item.get("comments_count") or 0),
                "partages": 0,
            })
        return resultat


@register
class LinkedIn(ReseauSocial):
    key = "linkedin"
    nom = "LinkedIn"
    description = "Suivez les posts publiés par votre page ou profil."
    icone = "💼"
    couleur = "#0a66c2"
    scopes = "w_member_social r_liteprofile r_emailaddress openid profile"
    client_id_env = "LINKEDIN_CONNECTEUR_CLIENT_ID"
    client_secret_env = "LINKEDIN_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://www.linkedin.com/oauth/v2/authorization"
    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    userinfo_url = "https://api.linkedin.com/v2/userinfo"
    activites_url = "https://api.linkedin.com/rest/posts?q=author"
    doc_url = "https://learn.microsoft.com/linkedin/"
    en_avant = True

    @classmethod
    def extraire_compte(cls, connecteur, donnees):
        nom = donnees.get("name") or donnees.get("preferred_username") or ""
        return {"nom": str(nom)[:120], "abonnes": None, "pays": "", "ville": ""}

    @classmethod
    def extraire_publications(cls, connecteur, donnees):
        resultat = []
        for item in donnees.get("elements") or donnees.get("data") or []:
            if not isinstance(item, dict):
                continue
            contenu = item.get("content") or {}
            media = item.get("media") or contenu.get("media") or {}
            texte = (
                contenu.get("title")
                or contenu.get("commentary")
                or item.get("commentary")
                or ""
            )
            if isinstance(texte, dict):
                texte = texte.get("text") or ""
            compte_activite = item.get("activity") or ""
            ident = item.get("id") or str(compte_activite).rsplit(":", 1)[-1]
            resultat.append({
                "titre": str(texte)[:200],
                "date": (item.get("created_time") or item.get("createdAt") or "")[:10] or None,
                "lien": media.get("originalUrl") or "",
                "likes": 0, "commentaires": 0, "partages": 0,
                "metadonnees": {"identifiant": ident},
            })
        return resultat


@register
class XConnecteur(ReseauSocial):
    key = "x"
    nom = "X (Twitter)"
    description = "Suivez vos tweets et statistiques d'audience."
    icone = "🐦"
    couleur = "#111827"
    scopes = "tweet.read users.read offline.access"
    client_id_env = "X_CONNECTEUR_CLIENT_ID"
    client_secret_env = "X_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://twitter.com/i/oauth2/authorize"
    token_url = "https://api.twitter.com/2/oauth2/token"
    userinfo_url = "https://api.twitter.com/2/users/me?user.fields=name,username,public_metrics"
    activites_url = "https://api.twitter.com/2/users/me/tweets?tweet.fields=public_metrics,created_at"
    doc_url = "https://developer.x.com/en/docs"
    en_avant = True

    @classmethod
    def extraire_compte(cls, connecteur, donnees):
        utilisateur = (donnees.get("data") or {}) if isinstance(
            donnees.get("data"), dict
        ) else {}
        nom = utilisateur.get("name") or utilisateur.get("username") or ""
        metriques = utilisateur.get("public_metrics") or {}
        return {
            "nom": str(nom)[:120],
            "abonnes": metriques.get("followers_count"),
            "pays": "",
            "ville": "",
        }

    @classmethod
    def extraire_publications(cls, connecteur, donnees):
        resultat = []
        for item in donnees.get("data") or []:
            if not isinstance(item, dict):
                continue
            metriques = item.get("public_metrics") or {}
            tweet_id = item.get("id") or ""
            resultat.append({
                "titre": str(item.get("text") or "")[:200],
                "date": (item.get("created_at") or "")[:10],
                "lien": f"https://x.com/i/web/status/{tweet_id}" if tweet_id else "",
                "likes": int(metriques.get("like_count") or 0),
                "commentaires": int(metriques.get("reply_count") or 0),
                "partages": int(metriques.get("retweet_count") or 0)
                + int(metriques.get("quote_count") or 0),
            })
        return resultat


@register
class TikTok(ReseauSocial):
    key = "tiktok"
    nom = "TikTok"
    description = "Suivez vos vidéos publiées et leur audience."
    icone = "🎵"
    couleur = "#111111"
    scopes = "user.info.basic video.list video.publish"
    client_id_env = "TIKTOK_CONNECTEUR_CLIENT_ID"
    client_secret_env = "TIKTOK_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://www.tiktok.com/v2/auth/authorize/"
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    userinfo_url = "https://open.tiktokapis.com/v2/user/info/?fields=display_name,follower_count"
    activites_url = "https://open.tiktokapis.com/v2/video/list/?fields=title,create_time,like_count,comment_count,share_count,share_url"
    doc_url = "https://developers.tiktok.com/"
    en_avant = True

    @classmethod
    def extraire_compte(cls, connecteur, donnees):
        utilisateur = (donnees.get("data") or {}).get("user") or {}
        nom = utilisateur.get("display_name") or utilisateur.get("username") or ""
        return {
            "nom": str(nom)[:120],
            "abonnes": utilisateur.get("follower_count"),
            "pays": "",
            "ville": "",
        }

    @classmethod
    def extraire_publications(cls, connecteur, donnees):
        resultat = []
        for item in (donnees.get("data") or {}).get("videos") or []:
            if not isinstance(item, dict):
                continue
            stats = item.get("stats") or item
            timestamp = item.get("create_time")
            resultat.append({
                "titre": str(item.get("title") or "")[:200],
                "date": str(timestamp)[:10] if timestamp else None,
                "lien": item.get("share_url") or "",
                "likes": int(stats.get("like_count") or 0),
                "commentaires": int(stats.get("comment_count") or 0),
                "partages": int(stats.get("share_count") or 0),
            })
        return resultat


@register
class YouTube(ReseauSocial):
    key = "youtube"
    nom = "YouTube"
    description = "Suivez vos vidéos récentes et votre chaîne."
    icone = "▶️"
    couleur = "#ff0000"
    scopes = "https://www.googleapis.com/auth/youtube.readonly"
    client_id_env = "YOUTUBE_CONNECTEUR_CLIENT_ID"
    client_secret_env = "YOUTUBE_CONNECTEUR_CLIENT_SECRET"
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    userinfo_url = "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true"
    activites_url = "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true"
    doc_url = "https://developers.google.com/youtube/v3"
    en_avant = True

    @classmethod
    def extraire_compte(cls, connecteur, donnees):
        chaine = (donnees.get("items") or [{}])[0] if isinstance(
            donnees.get("items"), list
        ) else {}
        snippet = chaine.get("snippet") or {}
        statistiques = chaine.get("statistics") or {}
        return {
            "nom": str(snippet.get("title") or "")[:120],
            "abonnes": statistiques.get("subscriberCount"),
            "pays": "",
            "ville": "",
        }

    @classmethod
    def extraire_publications(cls, connecteur, donnees):
        resultat = []
        for item in donnees.get("items") or []:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet") or {}
            statistiques = item.get("statistics") or {}
            ident = item.get("id") or ""
            resultat.append({
                "titre": str(snippet.get("title") or "")[:200],
                "date": (snippet.get("publishedAt") or "")[:10],
                "lien": f"https://www.youtube.com/watch?v={ident}" if ident else "",
                "likes": int(statistiques.get("likeCount") or 0),
                "commentaires": int(statistiques.get("commentCount") or 0),
                "partages": 0,
            })
        return resultat


# ---------------------------------------------------------------------------
# Connecteurs génériques (extensibilité sans nouveau code côté hub)
# ---------------------------------------------------------------------------
@register
class WebhookEntrant(ConnecteurBase):
    key = "webhook_entrant"
    nom = "Webhook entrant"
    description = "Recevez des événements d'un service externe via une URL signée."
    categorie = "webhook"
    icone = "🪝"
    couleur = "#0ea5e9"
    auth_type = AuthType.WEBHOOK
    champs = [
        {
            "name": "shared_secret",
            "label": "Secret partagé (optionnel)",
            "type": "password",
            "required": False,
            "help": "Utilisé pour vérifier la signature HMAC-SHA256 des appels.",
        },
    ]
    doc_url = ""


@register
class ApiPersonnalisee(ConnecteurBase):
    key = "api_personnalisee"
    nom = "API personnalisée"
    description = "Connectez n'importe quelle API interne via un jeton Bearer."
    categorie = "developpeur"
    icone = "🧩"
    couleur = "#64748b"
    auth_type = AuthType.TOKEN
    champs = [
        {
            "name": "base_url",
            "label": "URL de base de l'API",
            "type": "url",
            "required": True,
            "help": "Ex. https://api.mon-service.com/v1",
            "placeholder": "https://…",
        },
        {
            "name": "token",
            "label": "Jeton d'accès (Bearer)",
            "type": "password",
            "required": True,
            "help": "Stocké chiffré ; jamais réaffiché après enregistrement.",
            "placeholder": "••••••••",
        },
    ]

    @classmethod
    def tester(cls, connecteur):
        jetons = connecteur.jetons()
        base = (jetons.get("base_url") or "").rstrip("/")
        jeton = jetons.get("token") or ""
        if not base or not jeton:
            return False, "URL et jeton requis."
        try:
            resp = requests.get(
                base,
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=15,
            )
        except requests.RequestException as exc:
            return False, f"Réseau indisponible : {exc}"
        # Toute réponse HTTP (même 401/404) prouve que le serveur a répondu.
        return True, f"API joignable (HTTP {resp.status_code})."
