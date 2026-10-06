"""
Django settings for the "Gestionnaire de société" project.

Generated scaffold adapted to the app/ folder layout.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Chargement des variables d'environnement depuis app/.env
load_dotenv(BASE_DIR / ".env")


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-dev-only-key-change-me-before-any-deployment")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]


# Application definition

INSTALLED_APPS = [
    # Unfold (admin moderne) — doit précéder django.contrib.admin
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Allauth (authentification : login, signup, reset password...)
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    # Local apps
    "gestion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Allauth (requis depuis 0.56+)
    "allauth.account.middleware.AccountMiddleware",
    # Traçage de la présence des employés (temps passé sur la plateforme).
    "gestion.middleware.PresenceActiviteMiddleware",
]

# Custom user model (user_admin table).
AUTH_USER_MODEL = "gestion.UserAdmin"

# --- Authentification : backends Django + allauth -------------------------

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Connexion par email uniquement (UserAdmin n'a pas de champ username)
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_LOGOUT_ON_GET = True

# Formulaire d'inscription personnalisé : choix « Administrateur / Employé ».
ACCOUNT_FORMS = {"signup": "gestion.forms.SignupFormPro"}

# --- Connexion sociale : Google --------------------------------------------
# Identifiants lus dans .env (pas besoin de créer une SocialApp en base).
# URI de redirection à déclarer dans la console Google :
#   http://127.0.0.1:8000/accounts/google/login/callback/

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APPS": [
            {
                "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
                "secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "settings": {
                    "scope": ["profile", "email"],
                    "auth_params": {
                        "access_type": "online",
                        # Force l'affichage direct du sélecteur de comptes Google
                        "prompt": "select_account",
                    },
                },
            }
        ],
        "OAUTH_PKCE_ENABLED": True,
    }
}
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_EMAIL_VERIFICATION = False

# En GET, passe directement la main à Google (sélecteur de comptes)
# au lieu d'afficher la page intermédiaire /accounts/google/login/.
SOCIALACCOUNT_LOGIN_ON_GET = True

LOGIN_REDIRECT_URL = "gestion:post_login_redirect"
LOGOUT_REDIRECT_URL = "/accounts/login/"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.media",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "gestion.context_processors.media_prefix",
                "gestion.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/ref/settings/#i18n

LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Porto-Novo"
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/ref/settings/#static-url

STATIC_URL = "/static/"

# --- Unfold (panneau admin moderne) ---------------------------------------

UNFOLD = {
    "SITE_TITLE": "Gestionnaire de société",
    "SITE_HEADER": "Gestionnaire de société",
    "SITE_SYMBOL": "domain",
    "SHOW_LANGUAGES": False,
}
STATIC_ROOT = BASE_DIR / "static"

# User-uploaded files (photos, logos, documents, justificatifs...)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Pièces jointes de la messagerie : stockées hors de MEDIA_ROOT pour n'être
# jamais servies via MEDIA_URL ; téléchargées uniquement via la vue protégée
# `gestion:chat_fichier` (réservée à la société propriétaire du message).
CHAT_MEDIA_ROOT = os.getenv("CHAT_MEDIA_ROOT", BASE_DIR / "chat_media")

# Fichiers « livrables » des tâches : même principe que la messagerie — stockage
# privé hors de MEDIA_ROOT, jamais servis via MEDIA_URL ; téléchargés uniquement
# via la vue protégée `gestion:tache_livrable_fichier` (déposant, attributaire
# ou propriétaire de la société).
TACHE_MEDIA_ROOT = os.getenv("TACHE_MEDIA_ROOT", BASE_DIR / "tache_media")

# --- Connecteurs : chiffrement des identifiants au repos -------------------
# Clé Fernet optionnelle. Si absente, une clé stable est dérivée de
# DJANGO_SECRET_KEY. Définir une valeur dédiée en production.
CONNECTEURS_ENCRYPTION_KEY = os.getenv("CONNECTEURS_ENCRYPTION_KEY", "")

# --- Email / SMTP (confirmations allauth, réinitialisation...) ------------

if os.getenv("EMAIL_CONSOLE", "True").lower() in ("true", "1", "yes"):
    # Dev : les emails s'affichent dans la console, aucun serveur SMTP requis
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "Gestionnaire de société <no-reply@example.com>"
)

# --- IA (Groq) ---
# Clé lue dans app/.env ; ne jamais la versionner dans le code.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# --- KPay (Mobile Money) ---
# Clés lues dans app/.env. Le préfixe de KPAY_API_KEY (kpay_test_ / kpay_live_)
# sélectionne l'environnement ; la clé secrète n'a pas de préfixe (64 hex).
KPAY_API_KEY = os.getenv("KPAY_API_KEY", "")
KPAY_SECRET_KEY = os.getenv("KPAY_SECRET_KEY", "")
KPAY_GATEWAY_SECRET = os.getenv("KPAY_GATEWAY_SECRET", "")
KPAY_WEBHOOK_SECRET = os.getenv("KPAY_WEBHOOK_SECRET", "")
KPAY_BASE_URL = os.getenv("KPAY_BASE_URL", "https://admin.kpay.site")

# Default primary key field type
# https://docs.djangoproject.com/en/6.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
