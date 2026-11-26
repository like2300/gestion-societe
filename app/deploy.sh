#!/bin/bash
# =====================================================================
# Script de deploiement — Gestionnaire de societe (Django)
# Serveur : AlwaysData — https://appsfortesting.alwaysdata.net/
# =====================================================================
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "== [1/6] Environnement Python =="
if [ -d "venv" ]; then
    source venv/bin/activate
fi
python3 -m pip install -q -r requirements.txt

echo "== [2/6] Variables d'environnement (production) =="
export DJANGO_DEBUG="${DJANGO_DEBUG:-False}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost,appsfortesting.alwaysdata.net}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-django-insecure-dev-only-key-change-me-before-any-deployment}"
export EMAIL_CONSOLE="${EMAIL_CONSOLE:-False}"

echo "== [3/6] Migrations =="
python3 manage.py migrate --noinput

echo "== [4/6] Fichiers statiques =="
python3 manage.py collectstatic --noinput

echo "== [5/6] Redirections URL =="
python3 manage.py check --deploy

echo "== [6/6] Lancement =="
if command -v gunicorn >/dev/null 2>&1; then
    exec gunicorn --chdir "$APP_DIR" --bind 0.0.0.0:8080 config.wsgi:application
fi
exec python3 manage.py runserver 0.0.0.0:8080
