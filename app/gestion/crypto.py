"""Chiffrement au repos des identifiants de connecteurs (OAuth, tokens, clés).

Les jetons ne sont jamais stockés en clair. On utilise Fernet
(AES-128-CBC + HMAC-SHA256) avec une clé, par ordre de priorité :

1. ``CONNECTEURS_ENCRYPTION_KEY`` dans ``app/.env`` (recommandé en prod) ;
2. une clé dérivée de façon stable de ``DJANGO_SECRET_KEY`` (dev).

Conséquence : changer ``SECRET_KEY`` ou la clé fait perdre les jetons
existants (il faut alors reconnecter les services depuis le hub).
"""

import base64
import hashlib
import json

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    """Fernet prêt à l'emploi (clé .env native ou dérivée du SECRET_KEY)."""
    raw = (getattr(settings, "CONNECTEURS_ENCRYPTION_KEY", "") or "").strip()
    if raw:
        try:
            return Fernet(raw.encode())
        except (ValueError, TypeError):
            # Toute chaîne fournie est acceptée : on la dérive en clé valide.
            digest = hashlib.sha256(raw.encode()).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
    secret = (getattr(settings, "SECRET_KEY", "") or "insecure-dev").encode()
    digest = hashlib.sha256(b"connecteurs:" + secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def chiffrer(donnees):
    """Chiffre un dict Python et retourne une chaîne opaque (stockée en base)."""
    if donnees is None:
        return ""
    blob = json.dumps(donnees, separators=(",", ":"), ensure_ascii=False).encode()
    return _fernet().encrypt(blob).decode()


def dechiffrer(texte):
    """Déchiffre une chaîne produite par :func:`chiffrer` (dict vide si invalide)."""
    if not texte:
        return {}
    try:
        raw = _fernet().decrypt(texte.encode())
    except Exception:
        return {}
    try:
        donnees = json.loads(raw.decode())
    except (ValueError, TypeError):
        return {}
    return donnees if isinstance(donnees, dict) else {}
