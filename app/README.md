# Gestionnaire de société — Application Django

Application Django basée sur le schéma de 38 tables décrit dans
`instruction/db-explication.md` (dictionnaire de données) et
`instruction/db.md` (diagramme ER).

## Environnement

Les environnements virtuels **Windows** se trouvent dans `env/` et `env312/`
(non versionnés, voir `.gitignore`). Depuis PowerShell :

```powershell
cd app
python -m venv env            # si absent
.\env\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py runserver
```

> Note : l'ancien venv Linux (créé sous WSL) a été remplacé par un venv
> Windows, utilisable directement depuis PowerShell.

## Base de données

- SGBD : SQLite (`db.sqlite3`) — remplacer par PostgreSQL/MySQL dans
  `config/settings.py` pour la production.
- Modèles : `gestion/models.py` (38 tables, `db_table` respecte les noms du
  dictionnaire de données, ex. `user_admin`, `societe`, `projet_client`...).
- Le modèle utilisateur personnalisé est `gestion.UserAdmin`
  (`AUTH_USER_MODEL`), identifié par email.

## Variables d'environnement

Le fichier `app/.env` (non versionné, voir `.env.example`) contient :

- `DJANGO_SECRET_KEY` : clé secrète Django
- `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`
- `EMAIL_CONSOLE=True` : les emails (confirmations, réinitialisation)
  s'affichent dans la console — pratique en dev
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` : SMTP réel dès que
  `EMAIL_CONSOLE=False`
- `ACCOUNT_DEFAULT_HTTP_PROTOCOL` : `http` en local, `https` en production

## Admin moderne (Unfold) et authentification (allauth)

- L'admin utilise **django-unfold** (interface Tailwind moderne) :
  http://127.0.0.1:8000/admin/
- **django-allauth** fournit l'authentification complète sur
  http://127.0.0.1:8000/accounts/login/ (connexion par email),
  `/accounts/signup/`, `/accounts/password/reset/`
- Templates allauth sur mesure dans `app/templates/account/`, habillés avec
  le layout Unfold `unauthenticated`
- L'utilisateur est `gestion.UserAdmin` (connexion par **email**, pas de
  username) — `ACCOUNT_LOGIN_METHODS = {"email"}`

## Commandes utiles

```powershell
python manage.py makemigrations gestion   # générer les migrations
python manage.py migrate                  # créer/mettre à jour la base
python manage.py seed_demo                # référentiels + superuser + société démo
python manage.py createsuperuser          # autre administrateur
python manage.py runserver                # serveur de développement
```

Puis ouvrir http://127.0.0.1:8000/admin/

Connexion de démonstration créée par `seed_demo` :
- email : `admin@example.com`
- mot de passe : `admin` (à changer impérativement)

## Organisation

```
app/
├── manage.py
├── requirements.txt        # Django
├── db.sqlite3              # base de données (créée par migrate)
├── .env / .env.example     # variables d'environnement (secret, SMTP)
├── config/                 # projet Django (settings, urls, wsgi, asgi)
├── gestion/                # application métier
├── templates/account/      # templates allauth habillés Unfold
│   ├── models.py           # 38 modèles (choices, managers, Finance.recalculer())
│   ├── admin.py            # tout est enregistré dans l'admin Django
│   └── management/commands/seed_demo.py
├── instruction/            # documentation du schéma (db.md, db-explication.md)
└── env/, env312/            # environnements virtuels Windows (non versionnés)
```

## Notes métier

- `statut` : listes de choix Django correspondant aux règles du dictionnaire
  (ex. échéance `À venir/Partielle/Payée/Retard`).
- `Finance.recalculer()` recalcule recettes, dépenses (dépenses + salaires) et
  solde d'un mois pour une société.
- Les fichiers (photos, logos, justificatifs) sont des chemins `VARCHAR(500)`
  comme dans le schéma ; `MEDIA_ROOT`/`MEDIA_URL` sont prêts si vous passez à
  des `FileField`.
