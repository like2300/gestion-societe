"""Catalogue de connecteurs : recherche locale + recherche en ligne.

L'onglet « Ajouter un connecteur » s'appuie sur ce module pour proposer :

1. les connecteurs **déjà fournis** par la plateforme (registre) ;
2. un **catalogue curé** hors-ligne de services populaires (toujours disponible,
   même sans accès Internet) ;
3. l'**annuaire public d'API** ``apis.guru`` (OpenAPI), interrogé en direct pour
   trouver n'importe quelle API publiée sur Internet.

Le résultat est une liste normalisée de dicts, consommée telle quelle par la
vue et le template. Aucune donnée n'est écrite ici.
"""

import re

import requests
from django.core.cache import cache

from .registry import get_connecteur_class, tout_connecteurs

APIS_GURU_URL = "https://api.apis.guru/v2/list.json"
APIS_GURU_CACHE_KEY = "connecteurs:apis_guru_list"
APIS_GURU_ECHEC_KEY = "connecteurs:apis_guru_echec"
APIS_GURU_TTL = 60 * 60 * 24  # 24 h (succès)
APIS_GURU_ECHEC_TTL = 60 * 10  # 10 min (échec : évite de marteler l'annuaire)


def _texte(valeur, limite=300):
    return re.sub(r"\s+", " ", str(valeur or "")).strip()[:limite]


def _correspond(requete, *morceaux):
    """Vrai si la requête (insensible à la casse) apparaît dans les morceaux."""
    if not requete:
        return True
    return requete in " ".join(str(m) for m in morceaux if m).lower()


# ---------------------------------------------------------------------------
# Catalogue curé (fonctionne hors-ligne)
# ---------------------------------------------------------------------------
SERVICES_CURES = [
    {"nom": "Gmail", "fournisseur": "Google", "categorie": "email", "icone": "✉️",
     "couleur": "#ea4335", "auth": "oauth2", "registry_key": "gmail",
     "description": "Boîte mail Google Workspace.",
     "doc_url": "https://developers.google.com/gmail/api"},
    {"nom": "Google Calendar", "fournisseur": "Google", "categorie": "productivite",
     "icone": "📅", "couleur": "#4285f4", "auth": "oauth2",
     "description": "Agenda et événements Google.",
     "doc_url": "https://developers.google.com/calendar"},
    {"nom": "Google Drive", "fournisseur": "Google", "categorie": "productivite",
     "icone": "🗂️", "couleur": "#34a853", "auth": "oauth2",
     "description": "Fichiers et dossiers partagés.",
     "doc_url": "https://developers.google.com/drive"},
    {"nom": "Outlook / Microsoft 365", "fournisseur": "Microsoft", "categorie": "email",
     "icone": "📧", "couleur": "#0078d4", "auth": "oauth2", "registry_key": "outlook",
     "description": "Mail, calendrier et contacts Microsoft Graph.",
     "doc_url": "https://learn.microsoft.com/graph/"},
    {"nom": "Slack", "fournisseur": "Salesforce", "categorie": "communication",
     "icone": "💬", "couleur": "#4a154b", "auth": "oauth2", "registry_key": "slack",
     "description": "Messagerie d'équipe et alertes.",
     "doc_url": "https://api.slack.com/"},
    {"nom": "Discord", "fournisseur": "Discord", "categorie": "communication",
     "icone": "🎮", "couleur": "#5865f2", "auth": "webhook",
     "description": "Notifications sur un salon Discord via webhook.",
     "doc_url": "https://discord.com/developers/docs/resources/webhook"},
    {"nom": "Telegram", "fournisseur": "Telegram", "categorie": "communication",
     "icone": "📨", "couleur": "#229ed9", "auth": "token",
     "description": "Bots et canaux Telegram.",
     "doc_url": "https://core.telegram.org/bots/api"},
    {"nom": "Zoom", "fournisseur": "Zoom", "categorie": "communication",
     "icone": "🎥", "couleur": "#2d8cff", "auth": "oauth2",
     "description": "Réunions et webinaires.",
     "doc_url": "https://developers.zoom.us/docs/api/"},
    {"nom": "Stripe", "fournisseur": "Stripe", "categorie": "paiement",
     "icone": "💳", "couleur": "#635bff", "auth": "token", "registry_key": "stripe",
     "description": "Paiements, factures et abonnements.",
     "doc_url": "https://stripe.com/docs/api"},
    {"nom": "PayPal", "fournisseur": "PayPal", "categorie": "paiement",
     "icone": "💰", "couleur": "#003087", "auth": "oauth2",
     "description": "Paiements et remboursements.",
     "doc_url": "https://developer.paypal.com/api/rest/"},
    {"nom": "HubSpot", "fournisseur": "HubSpot", "categorie": "crm",
     "icone": "🧲", "couleur": "#ff7a59", "auth": "oauth2",
     "description": "CRM, contacts et pipeline commercial.",
     "doc_url": "https://developers.hubspot.com/docs/api/overview"},
    {"nom": "Salesforce", "fournisseur": "Salesforce", "categorie": "crm",
     "icone": "☁️", "couleur": "#00a1e0", "auth": "oauth2",
     "description": "CRM et gestion de la relation client.",
     "doc_url": "https://developer.salesforce.com/docs"},
    {"nom": "Pipedrive", "fournisseur": "Pipedrive", "categorie": "crm",
     "icone": "📈", "couleur": "#017737", "auth": "token",
     "description": "Pipeline de ventes.",
     "doc_url": "https://developers.pipedrive.com/docs/api/v1"},
    {"nom": "Notion", "fournisseur": "Notion", "categorie": "productivite",
     "icone": "📓", "couleur": "#111111", "auth": "token",
     "description": "Pages, bases de données et notes.",
     "doc_url": "https://developers.notion.com/"},
    {"nom": "Airtable", "fournisseur": "Airtable", "categorie": "productivite",
     "icone": "🗃️", "couleur": "#ffbf00", "auth": "token",
     "description": "Bases de données collaboratives.",
     "doc_url": "https://airtable.com/developers/web/api/introduction"},
    {"nom": "Trello", "fournisseur": "Atlassian", "categorie": "productivite",
     "icone": "📋", "couleur": "#0079bf", "auth": "token",
     "description": "Tableaux et cartes de suivi.",
     "doc_url": "https://developer.atlassian.com/cloud/trello/rest/"},
    {"nom": "Asana", "fournisseur": "Asana", "categorie": "productivite",
     "icone": "✅", "couleur": "#f06a6a", "auth": "oauth2",
     "description": "Gestion de tâches et projets.",
     "doc_url": "https://developers.asana.com/docs"},
    {"nom": "Jira", "fournisseur": "Atlassian", "categorie": "productivite",
     "icone": "🧭", "couleur": "#0052cc", "auth": "oauth2",
     "description": "Suivi de tickets et projets agiles.",
     "doc_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/"},
    {"nom": "Monday.com", "fournisseur": "monday.com", "categorie": "productivite",
     "icone": "🟣", "couleur": "#ff3d57", "auth": "token",
     "description": "Gestion de travail et tableaux.",
     "doc_url": "https://developer.monday.com/api-reference/"},
    {"nom": "Dropbox", "fournisseur": "Dropbox", "categorie": "productivite",
     "icone": "📦", "couleur": "#0061ff", "auth": "oauth2",
     "description": "Stockage et partage de fichiers.",
     "doc_url": "https://www.dropbox.com/developers/documentation"},
    {"nom": "GitHub", "fournisseur": "GitHub", "categorie": "developpeur",
     "icone": "🐙", "couleur": "#24292f", "auth": "token",
     "description": "Dépôts, issues et déploiements.",
     "doc_url": "https://docs.github.com/rest"},
    {"nom": "Shopify", "fournisseur": "Shopify", "categorie": "paiement",
     "icone": "🛒", "couleur": "#96bf48", "auth": "token",
     "description": "Boutique, commandes et produits.",
     "doc_url": "https://shopify.dev/docs/api"},
    {"nom": "Mailchimp", "fournisseur": "Intuit", "categorie": "marketing",
     "icone": "🐵", "couleur": "#ffe01b", "auth": "token",
     "description": "Campagnes e-mail et audiences.",
     "doc_url": "https://mailchimp.com/developer/"},
    {"nom": "SendGrid", "fournisseur": "Twilio", "categorie": "email",
     "icone": "📤", "couleur": "#1a82e2", "auth": "token",
     "description": "Envoi d'e-mails transactionnels.",
     "doc_url": "https://www.twilio.com/docs/sendgrid/api-reference"},
    {"nom": "Twilio", "fournisseur": "Twilio", "categorie": "communication",
     "icone": "📞", "couleur": "#f22f46", "auth": "token",
     "description": "SMS, voix et WhatsApp.",
     "doc_url": "https://www.twilio.com/docs/usage/api"},
    {"nom": "Zendesk", "fournisseur": "Zendesk", "categorie": "crm",
     "icone": "🎧", "couleur": "#03363d", "auth": "token",
     "description": "Support client et tickets.",
     "doc_url": "https://developer.zendesk.com/api-reference/"},
    {"nom": "Intercom", "fournisseur": "Intercom", "categorie": "crm",
     "icone": "💡", "couleur": "#1f8ded", "auth": "token",
     "description": "Messagerie client et support.",
     "doc_url": "https://developers.intercom.com/"},
    {"nom": "Wise", "fournisseur": "Wise", "categorie": "paiement",
     "icone": "💱", "couleur": "#9fe870", "auth": "token",
     "description": "Transferts internationaux.",
     "doc_url": "https://docs.wise.com/api-docs"},
    {"nom": "QuickBooks", "fournisseur": "Intuit", "categorie": "paiement",
     "icone": "📚", "couleur": "#2ca01c", "auth": "oauth2",
     "description": "Comptabilité et facturation.",
     "doc_url": "https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/account"},
    {"nom": "Google Sheets", "fournisseur": "Google", "categorie": "productivite",
     "icone": "📊", "couleur": "#0f9d58", "auth": "oauth2",
     "description": "Tableurs collaboratifs.",
     "doc_url": "https://developers.google.com/sheets/api"},
    {"nom": "WooCommerce", "fournisseur": "WordPress", "categorie": "boutique",
     "icone": "🛒", "couleur": "#7f54b3", "auth": "token",
     "description": "Boutique WordPress : produits, commandes et clients.",
     "doc_url": "https://woocommerce.github.io/woocommerce-rest-api-docs/"},
    {"nom": "PrestaShop", "fournisseur": "PrestaShop", "categorie": "boutique",
     "icone": "🏬", "couleur": "#df0067", "auth": "token",
     "description": "Boutique en ligne PrestaShop (Webservice).",
     "doc_url": "https://devdocs.prestashop-project.org/"},
    {"nom": "Magento / Adobe Commerce", "fournisseur": "Adobe", "categorie": "boutique",
     "icone": "🧱", "couleur": "#ee672f", "auth": "token",
     "description": "E-commerce Magento / Adobe Commerce.",
     "doc_url": "https://developer.adobe.com/commerce/webapi/"},
    {"nom": "Wix", "fournisseur": "Wix", "categorie": "boutique",
     "icone": "🌐", "couleur": "#0c6efc", "auth": "token",
     "description": "Site et boutique Wix.",
     "doc_url": "https://dev.wix.com/docs/rest"},
    {"nom": "Squarespace", "fournisseur": "Squarespace", "categorie": "boutique",
     "icone": "⬛", "couleur": "#111111", "auth": "token",
     "description": "Site et commerce Squarespace.",
     "doc_url": "https://developers.squarespace.com/"},
    {"nom": "BigCommerce", "fournisseur": "BigCommerce", "categorie": "boutique",
     "icone": "🏪", "couleur": "#121118", "auth": "token",
     "description": "E-commerce BigCommerce (catalogues, commandes).",
     "doc_url": "https://developer.bigcommerce.com/docs/rest-management"},
    {"nom": "Webhook personnalisé", "fournisseur": "—", "categorie": "webhook",
     "icone": "🪝", "couleur": "#0ea5e9", "auth": "webhook",
     "registry_key": "webhook_entrant",
     "description": "Recevoir des événements depuis n'importe quel service.",
     "doc_url": ""},
    {"nom": "API personnalisée", "fournisseur": "—", "categorie": "developpeur",
     "icone": "🧩", "couleur": "#64748b", "auth": "token",
     "registry_key": "api_personnalisee",
     "description": "Brancher une API interne via un jeton Bearer.",
     "doc_url": ""},
]


def _depuis_classe(cls):
    meta = cls.metadata()
    return {
        "registre": True,
        "key": cls.key,
        "nom": meta["nom"],
        "fournisseur": "",
        "description": meta["description"],
        "categorie": meta["categorie"],
        "icone": meta["icone"],
        "couleur": meta["couleur"],
        "auth": meta["auth_type"],
        "doc_url": meta["doc_url"],
        "base_url": "",
        "source": "Plateforme",
        "identifiant": cls.key,
    }


def rechercher_local(requete):
    """Connecteurs fournis par la plateforme correspondant à la requête."""
    requete = requete.lower()
    resultats = []
    for cls in tout_connecteurs():
        if _correspond(requete, cls.nom, cls.description, cls.categorie):
            resultats.append(_depuis_classe(cls))
    return resultats


def rechercher_cures(requete):
    """Catalogue curé, en marquant les services déjà fournis par la plateforme."""
    requete = requete.lower()
    resultats = []
    for service in SERVICES_CURES:
        if not _correspond(
            requete,
            service["nom"],
            service.get("fournisseur"),
            service.get("description"),
            service.get("categorie"),
        ):
            continue
        entree = dict(service)
        entree.update(
            {
                "registre": False,
                "key": "",
                "base_url": "",
                "source": "Catalogue",
                "identifiant": service["nom"],
            }
        )
        cle_registre = entree.pop("registry_key", "")
        if cle_registre and get_connecteur_class(cle_registre):
            entree["registre"] = True
            entree["key"] = cle_registre
        resultats.append(entree)
    return resultats


def _charger_apis_guru():
    """Liste OpenAPI d'apis.guru. Retourne ``(donnees, ok)``.

    Un succès est mis en cache 24 h ; un échec est mémorisé 10 min seulement,
    pour ne pas marteler l'annuaire tout en récupérant vite une fois le réseau
    revenu. ``ok`` vaut False quand la liste n'a pas pu être chargée.
    """
    donnees = cache.get(APIS_GURU_CACHE_KEY)
    if isinstance(donnees, dict) and donnees:
        return donnees, True
    if cache.get(APIS_GURU_ECHEC_KEY):
        return {}, False
    try:
        reponse = requests.get(APIS_GURU_URL, timeout=15)
        reponse.raise_for_status()
        donnees = reponse.json()
        if not isinstance(donnees, dict) or not donnees:
            raise ValueError("annuaire vide")
    except Exception:
        cache.set(APIS_GURU_ECHEC_KEY, True, APIS_GURU_ECHEC_TTL)
        return {}, False
    cache.set(APIS_GURU_CACHE_KEY, donnees, APIS_GURU_TTL)
    return donnees, True


def rechercher_en_ligne(requete, limite=30):
    """Recherche dans l'annuaire public d'API (apis.guru).

    Retourne ``(resultats, ok)`` ; ``ok`` est False si l'annuaire n'a pas pu
    être interrogé (hors-ligne).
    """
    requete = (requete or "").strip().lower()
    if not requete:
        return [], True
    donnees, ok = _charger_apis_guru()
    if not donnees:
        return [], ok
    resultats = []
    for identifiant, entree in donnees.items():
        if not isinstance(entree, dict):
            continue
        version = (entree.get("versions") or {}).get(entree.get("preferred"), {})
        info = version.get("info") or {}
        titre = info.get("title") or identifiant
        description = info.get("description") or ""
        contact = info.get("contact") or {}
        fournisseur = contact.get("name") or identifiant.split(".")[0]
        # On cherche sur le nom/identifiant/fournisseur (précis) ; la description
        # n'est pas indexée pour éviter le bruit des liens « github » partagés.
        if not _correspond(requete, titre, identifiant, fournisseur):
            continue
        resultats.append(
            {
                "registre": False,
                "key": "",
                "nom": _texte(titre, 120),
                "fournisseur": _texte(fournisseur, 120),
                "description": _texte(description, 280),
                "categorie": "api",
                "icone": "🌐",
                "couleur": "#0284c7",
                "auth": "token",
                "doc_url": version.get("swaggerUrl")
                or version.get("swaggerYamlUrl")
                or f"https://apis.guru/{identifiant}",
                "base_url": "",
                "source": "apis.guru",
                "identifiant": identifiant,
            }
        )
        if len(resultats) >= limite:
            break
    return resultats, ok


def rechercher(requete, limite=30):
    """Recherche consolidée consommée par la vue du hub."""
    requete = (requete or "").strip()
    local = rechercher_local(requete)
    cures = rechercher_cures(requete)
    try:
        online, online_ok = rechercher_en_ligne(requete, limite=limite)
    except Exception:
        online, online_ok = [], False

    # Déduplication par nom (casse/espaces) en gardant la 1re occurrence.
    vus, fusion = set(), []
    for bloc in (local, cures, online):
        for entree in bloc:
            cle = entree["nom"].strip().lower()
            if cle in vus:
                continue
            vus.add(cle)
            fusion.append(entree)
    return {
        "local": [e for e in fusion if e["registre"]],
        "internet": [e for e in fusion if not e["registre"]],
        "online_ok": online_ok,
        "total": len(fusion),
    }
