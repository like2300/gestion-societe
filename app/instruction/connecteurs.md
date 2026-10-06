# Connecteurs — architecture, sécurité et extension

Hub d'intégrations externes (Gmail, Outlook, Slack, Stripe, webhooks, API
personnalisée…). Cette page documente **comment ajouter un connecteur** et
**comment l'IA peut les utiliser sans contourner la sécurité**.

## Vue d'ensemble

```
gestion/
  crypto.py                 chiffrement Fernet des identifiants (au repos)
  connecteurs/
    __init__.py             exporte le socle + charge providers.py
    base.py                 ConnecteurBase / OAuth2Connecteur / AuthType
    registry.py             registre (@register) : sources de vérité
    providers.py            connecteurs fournis (Gmail, Slack, …)
    ia.py                   passerelle IA (listes blanches + permissions)
  models.py                 Connecteur, ConnecteurEvenement, ConnecteurSyncLog
  views.py                  hub, connecter, callback, deconnecter, sync, webhook
templates/gestion/connecteurs.html   interface du hub
```

Le hub ne connaît **aucun** fournisseur en dur : il itère sur le registre et
affiche les métadonnées déclarées par chaque classe.

## Ajouter un connecteur (sans toucher au reste)

1. Ouvrir `gestion/connecteurs/providers.py`.
2. Décrire la classe et la décorer avec `@register`.

### Connecteur à clé d'API / jeton

```python
from .base import AuthType, ConnecteurBase
from .registry import register

@register
class MonOutil(ConnecteurBase):
    key = "mon_outil"                 # identifiant unique (stocké en base)
    nom = "Mon outil"
    description = "À quoi sert ce connecteur."
    categorie = "communication"       # filtre du hub
    icone = "🔧"
    couleur = "#0284c7"
    auth_type = AuthType.TOKEN
    champs = [
        {"name": "token", "label": "Jeton", "type": "password",
         "required": True, "help": "Stocké chiffré."},
    ]

    @classmethod
    def tester(cls, connecteur):
        jeton = connecteur.jetons().get("token", "")
        return (bool(jeton), "Jeton présent.")

    @classmethod
    def synchroniser(cls, connecteur):
        # Appels réseau ici. Ne jamais journaliser un secret.
        return 0, "Rien à synchroniser."
```

### Connecteur OAuth2

```python
from .base import OAuth2Connecteur
from .registry import register

@register
class MonOAuth(OAuth2Connecteur):
    key = "mon_oauth"
    nom = "Mon OAuth"
    categorie = "email"
    scopes = "read write"
    client_id_env = "MON_OAUTH_CLIENT_ID"
    client_secret_env = "MON_OAUTH_CLIENT_SECRET"
    authorize_url = "https://exemple.com/oauth/authorize"
    token_url = "https://exemple.com/oauth/token"
    userinfo_url = "https://exemple.com/api/me"
```

Renseigner `MON_OAUTH_CLIENT_ID` / `MON_OAUTH_CLIENT_SECRET` dans `app/.env`.
Le bouton « Connecter » devient actif et l'échange de code est géré par le
socle (`echanger_code`, `rafraichir`, `recuperer_compte`).

Aucune modification n'est nécessaire dans les vues, les URLs ou le template :
la carte apparaît automatiquement dans le hub et dans les filtres.

## Connecteurs fournis

| Clé | Nom | Catégorie | Auth | Notes |
| --- | --- | --- | --- | --- |
| `gmail` | Gmail | email | OAuth2 | Google (`GOOGLE_CONNECTEUR_*`) |
| `outlook` | Outlook / Microsoft 365 | email | OAuth2 | Microsoft (`MICROSOFT_CONNECTEUR_*`) |
| `word` | Word | documents | OAuth2 | Graph `/me/drive/recent`, `.docx/.doc` |
| `excel` | Excel | documents | OAuth2 | Graph, `.xlsx/.xls/.csv` |
| `powerpoint` | PowerPoint | documents | OAuth2 | Graph, `.pptx/.ppt` |
| `slack` | Slack | communication | OAuth2 | `SLACK_CONNECTEUR_*` |
| `stripe` | Stripe | paiement | Jeton | Clé `sk_…` |
| `higgsfield` | Higgsfield | ia | Jeton | Clé API (ID + secret), `Authorization: Key id:secret` |
| `site_boutique` | Mon site / ma boutique en ligne | boutique | Jeton | URL API + jeton **ou** clés WooCommerce + webhook |
| `webhook_entrant` | Webhook entrant | webhook | Webhook | URL signée |
| `api_personnalisee` | API personnalisée | developpeur | Jeton | URL + Bearer |

- **Documents Office** : les trois connecteurs partagent l'application
  Microsoft de la plateforme et l'API Graph ; `synchroniser()` liste les
  fichiers récents de l'extension surveillée. Il faut donc configurer
  `MICROSOFT_CONNECTEUR_CLIENT_ID` / `_SECRET` (un seul enregistrement suffit).
- **Higgsfield** : deux identifiants (`api_key_id` + `api_key_secret`), créés
  dans la console Higgsfield ; `tester()` vérifie la clé sans consommer de
  génération. Base par défaut : `https://api.higgsfield.ai`.
- **Site / boutique** : connecteur universel pour un site ou une boutique en
  ligne. Renseignez l'URL de l'API + un jeton Bearer, **ou** les clés
  WooCommerce (`consumer_key` / `consumer_secret`), **ou** uniquement un
  `shared_secret` pour recevoir les commandes par webhook. Le catalogue propose
  aussi WooCommerce, PrestaShop, Magento, Wix, Squarespace et BigCommerce en
  connecteurs personnalisés.

## Onglet « Ajouter un connecteur » (recherche Internet)

Depuis le hub, l'onglet **Ajouter un connecteur** (propriétaire uniquement)
permet de chercher un service et de l'ajouter en un clic. Trois sources sont
interrogées puis fusionnées et dédupliquées :

1. **Connecteurs fournis** par la plateforme (registre) → bouton « Connecter »
   (flux normal, OAuth ou jeton).
2. **Catalogue curé** (`catalogue.SERVICES_CURES`) : une trentaine de services
   populaires, disponible **hors-ligne**.
3. **Annuaire public d'API** `apis.guru` (OpenAPI), interrogé en direct et mis
   en cache 24 h. En cas d'indisponibilité réseau, seul le message d'alerte est
   affiché et le reste continue de fonctionner.

Ajouter un service non fourni crée un **connecteur personnalisé** :

- clé unique `perso-<slug>` (doublons suffixés `-2`, `-3`…) ;
- métadonnées publiques stockées dans `Connecteur.configuration`
  (fournisseur, description, URL de doc, catégorie…), **aucun secret** ;
- classe de connecteur générée à la volée par
  `connecteurs/personnalise.py` (champs « URL de base » + « Jeton »),
  exposée par `Connecteur.classe` ;
- le propriétaire renseigne ensuite ses identifiants via « Configurer »
  (chiffrés par `crypto.py`).

Pour ajouter un service fréquent au catalogue hors-ligne, compléter
`SERVICES_CURES` dans `catalogue.py` (ou écrire un vrai provider quand une
intégration dédiée est nécessaire).

## Sécurité

- **Chiffrement au repos.** Les jetons sont chiffrés par
  `gestion.crypto.chiffrer` (Fernet) avant d'être écrits dans
  `Connecteur.identifiants_chiffres`. Définir `CONNECTEURS_ENCRYPTION_KEY`
  dans `.env` en production (sinon la clé est dérivée de `SECRET_KEY`).
- **Jamais réaffichés.** L'interface n'expose que `identifiants_masques()`
  (les *noms* des champs renseignés, pas les valeurs).
- **Isolation multi-tenant.** Toute lecture/écriture passe par
  `societe.connecteurs` ; une société ne voit jamais les connecteurs d'une
  autre.
- **Droits.** Gérer un connecteur (connecter, déconnecter, synchroniser) est
  réservé au **créateur** de la société. Un employé ne peut accéder au hub que
  si le module `connecteurs` lui est autorisé, et il ne voit alors que les
  connecteurs déjà actifs, en lecture seule.
- **Webhooks entrants.** L'URL contient un secret (`webhook_secret`) comparé
  en temps constant. Si une signature est présente, elle est vérifiée en
  HMAC-SHA256 (`X-Connecteur-Signature`, `X-Hub-Signature-256`, `X-Signature`)
  ou via le schéma Slack (`X-Slack-Signature: v0=…`). Seuls des en-têtes
  techniques sont conservés dans le journal.

## Utilisation par l'IA

L'IA n'accède **jamais** aux secrets. Elle passe exclusivement par
`gestion/connecteurs/ia.py`, qui applique les mêmes règles que l'interface :

| Fonction | Rôle |
| --- | --- |
| `resume_connecteurs(user, societe)` | Liste non sensible (nom, catégorie, statut, compte, dernière synchro), filtrée par permissions et par société. |
| `actions_disponibles(user, societe)` | Liste blanche des actions autorisées (vide pour un employé). |
| `synchroniser_connecteur(user, societe, type)` | Exécute une synchro **au nom de l'utilisateur**, après revérification `peut_acceder` + `est_createur` + appartenance du connecteur à `societe`. |

Ces garanties sont volontairement redondantes avec les vues HTTP : même si le
modèle invoquait une action, elle serait rejetée si l'utilisateur n'a pas les
droits. Le prompt système (`gestion/ai.py`) précise en outre à l'assistant de
ne jamais demander ni afficher de mot de passe, clé d'API ou jeton.

### Ajouter une action IA

1. Implémenter la logique dans le provider (ex. `synchroniser`).
2. L'ajouter à `actions_disponibles()` dans `ia.py`.
3. Ne transmettre que des paramètres non sensibles et revérifier les droits à
   l'entrée de la fonction.

### Alimentation du globe

Les connecteurs alimentent automatiquement le **globe 3D** : un événement de
commande (webhook ou `synchroniser`) pousse un point `commande` + un point `ca`
(avec pays/ville du client) via `globe.alimenter_connecteur` — voir
`SiteBoutique.traiter_webhook` et le guide complet dans `../instruction/globe3d.md`.

Ne jamais exposer `Connecteur.jetons()`, `identifiants_chiffres` ou
`webhook_secret` à l'IA ni à une réponse HTTP.
