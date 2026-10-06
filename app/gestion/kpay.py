# -*- coding: utf-8 -*-
"""Client API KPay (Mobile Money) — paiements (dépôts), retraits et utilitaires.

Une seule URL de base : le préfixe de la clé publique (kpay_test_ / kpay_live_)
sélectionne l'environnement. La clé secrète est toujours sans préfixe.

Docs : https://admin.kpay.site (intégration v1). Toutes les fonctions réseau
sont de simples enveloppes de ``requests`` ; les vues appellent uniquement ce
module (facile à moquer dans les tests).
"""

import hashlib
import hmac
import json
import re

import requests
from django.conf import settings

# URL de base (réglable via KPAY_BASE_URL pour la passerelle ou des tests).
BASE_URL = getattr(settings, "KPAY_BASE_URL", "https://admin.kpay.site").rstrip("/")

# Catalogue des opérateurs (valeur EXACTE du champ provider des endpoints).
# (code, libellé affiché, pays, devise)
PROVIDERS = [
    ("MTN_MOMO_CMR", "MTN Mobile Money — Cameroun (XAF)", "CMR", "XAF"),
    ("ORANGE_CMR", "Orange Money — Cameroun (XAF)", "CMR", "XAF"),
    ("MTN_MOMO_BEN", "MTN Mobile Money — Bénin (XOF)", "BEN", "XOF"),
    ("MOOV_BEN", "Moov Money — Bénin (XOF)", "BEN", "XOF"),
    ("MTN_MOMO_CIV", "MTN Mobile Money — Côte d'Ivoire (XOF)", "CIV", "XOF"),
    ("ORANGE_CIV", "Orange Money — Côte d'Ivoire (XOF)", "CIV", "XOF"),
    ("VODACOM_MPESA_COD", "Vodacom M-Pesa — RD Congo (CDF)", "COD", "CDF"),
    ("AIRTEL_COD", "Airtel Money — RD Congo (CDF)", "COD", "CDF"),
    ("ORANGE_COD", "Orange Money — RD Congo (CDF)", "COD", "CDF"),
    ("AIRTEL_GAB", "Airtel Money — Gabon (XAF)", "GAB", "XAF"),
    ("MPESA_KEN", "M-Pesa — Kenya (KES)", "KEN", "KES"),
    ("AIRTEL_COG", "Airtel Money — Congo (XAF)", "COG", "XAF"),
    ("MTN_MOMO_COG", "MTN Mobile Money — Congo (XAF)", "COG", "XAF"),
    ("AIRTEL_RWA", "Airtel Money — Rwanda (RWF)", "RWA", "RWF"),
    ("MTN_MOMO_RWA", "MTN Mobile Money — Rwanda (RWF)", "RWA", "RWF"),
    ("FREE_SEN", "Free Money — Sénégal (XOF)", "SEN", "XOF"),
    ("ORANGE_SEN", "Orange Money — Sénégal (XOF)", "SEN", "XOF"),
    ("ORANGE_SLE", "Orange Money — Sierra Leone (SLE)", "SLE", "SLE"),
    ("AIRTEL_OAPI_UGA", "Airtel Money — Ouganda (UGX)", "UGA", "UGX"),
    ("MTN_MOMO_UGA", "MTN Mobile Money — Ouganda (UGX)", "UGA", "UGX"),
    ("AIRTEL_OAPI_ZMB", "Airtel Money — Zambie (ZMW)", "ZMB", "ZMW"),
    ("MTN_MOMO_ZMB", "MTN Mobile Money — Zambie (ZMW)", "ZMB", "ZMW"),
    ("ZAMTEL_ZMB", "Zamtel — Zambie (ZMW)", "ZMB", "ZMW"),
]

# Statuts terminaux côté KPay (le webhook reste la source d'autorité).
STATUTS_TERMINAUX = {"COMPLETED", "FAILED", "CANCELLED"}


def configuree():
    """True si les deux clés (publique + secrète) sont présentes."""
    return bool(
        getattr(settings, "KPAY_API_KEY", "")
        and getattr(settings, "KPAY_SECRET_KEY", "")
    )


def est_test():
    return str(getattr(settings, "KPAY_API_KEY", "")).startswith("kpay_test_")


def _headers():
    return {
        "X-API-Key": settings.KPAY_API_KEY,
        "X-Secret-Key": settings.KPAY_SECRET_KEY,
        "Content-Type": "application/json",
    }


def _erreur(res, defaut="Une erreur est survenue avec KPay."):
    """Message lisible depuis l'enveloppe d'erreur KPay."""
    try:
        data = res.json()
    except Exception:
        return defaut
    if isinstance(data, dict):
        return data.get("message") or data.get("error") or defaut
    return defaut


# ---------------------------------------------------------------------------
# Encaissements (dépôts) et retraits (payouts) — USSD push
# ---------------------------------------------------------------------------


def init_depot(montant, provider, telephone, external_id, description="", metadata=None):
    """Initie un paiement Mobile Money (mode USSD : le client valide sur son téléphone).

    Retourne ``(ok: bool, data: dict)``. Si ``ok``, ``data`` est la réponse 201
    (champ ``id`` à conserver) ; sinon ``data`` est un dictionnaire d'erreur
    avec ``message`` et ``statusCode``.
    """
    if not configuree():
        return False, {
            "statusCode": 503,
            "message": (
                "KPay n'est pas configuré : renseignez KPAY_API_KEY / KPAY_SECRET_KEY."
            ),
        }
    try:
        res = requests.post(
            f"{BASE_URL}/api/v1/payments/init",
            headers=_headers(),
            json={
                "amount": int(montant),
                "provider": provider,
                "phoneNumber": telephone,
                "externalId": external_id,
                "description": description,
                "metadata": metadata or {},
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, {"statusCode": 0, "message": f"Réseau KPay indisponible : {exc}"}
    if res.status_code in (200, 201):
        return True, res.json()
    return False, {
        "statusCode": res.status_code,
        "message": _erreur(res),
    }


def init_retrait(montant, provider, telephone, external_id, description="", metadata=None):
    """Initie un retrait Mobile Money (virement vers le numéro du bénéficiaire)."""
    if not configuree():
        return False, {
            "statusCode": 503,
            "message": (
                "KPay n'est pas configuré : renseignez KPAY_API_KEY / KPAY_SECRET_KEY."
            ),
        }
    try:
        res = requests.post(
            f"{BASE_URL}/api/v1/payments/withdraw",
            headers=_headers(),
            json={
                "amount": int(montant),
                "provider": provider,
                "phoneNumber": telephone,
                "externalId": external_id,
                "description": description,
                "metadata": metadata or {},
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, {"statusCode": 0, "message": f"Réseau KPay indisponible : {exc}"}
    if res.status_code in (200, 201):
        return True, res.json()
    return False, {
        "statusCode": res.status_code,
        "message": _erreur(res),
    }


def statut_depot(kpay_id):
    """Polling du statut d'un paiement (GET /api/v1/payments/:id)."""
    if not configuree():
        return False, {"message": "KPay n'est pas configuré."}
    try:
        res = requests.get(
            f"{BASE_URL}/api/v1/payments/{kpay_id}",
            headers=_headers(),
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, {"message": f"Réseau KPay indisponible : {exc}"}
    if res.status_code == 200:
        return True, res.json()
    return False, {"statusCode": res.status_code, "message": _erreur(res)}


def statut_retrait(kpay_id):
    """Polling du statut d'un retrait (GET /api/v1/payments/withdraw/:id)."""
    if not configuree():
        return False, {"message": "KPay n'est pas configuré."}
    try:
        res = requests.get(
            f"{BASE_URL}/api/v1/payments/withdraw/{kpay_id}",
            headers=_headers(),
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, {"message": f"Réseau KPay indisponible : {exc}"}
    if res.status_code == 200:
        return True, res.json()
    return False, {"statusCode": res.status_code, "message": _erreur(res)}


def solde_wallets():
    """Soldes des wallets de l'application (GET /api/v1/payments/balance).

    Retourne ``(ok, data)`` ; ``data`` est la liste des wallets ou un message
    d'erreur.
    """
    if not configuree():
        return False, {"message": "KPay n'est pas configuré."}
    try:
        res = requests.get(
            f"{BASE_URL}/api/v1/payments/balance",
            headers=_headers(),
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, {"message": f"Réseau KPay indisponible : {exc}"}
    if res.status_code == 200:
        return True, res.json()
    return False, {"statusCode": res.status_code, "message": _erreur(res)}


def predire_provider(telephone):
    """Suggère le provider d'un numéro (POST /api/v1/payments/predict-provider)."""
    if not configuree():
        return False, {"message": "KPay n'est pas configuré."}
    try:
        res = requests.post(
            f"{BASE_URL}/api/v1/payments/predict-provider",
            headers=_headers(),
            json={"phoneNumber": telephone},
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, {"message": f"Réseau KPay indisponible : {exc}"}
    if res.status_code in (200, 201):
        return True, res.json()
    return False, {"statusCode": res.status_code, "message": _erreur(res)}


# ---------------------------------------------------------------------------
# Vérification de signature (webhooks + retour passerelle)
# ---------------------------------------------------------------------------


def verifier_signature(corps_brut, signature, secret=None):
    """Vérifie la signature HMAC-SHA256 (hex) d'un corps brut.

    ``corps_brut`` doit être le corps JSON BRUT reçu (jamais re-sérialisé).
    Le secret par défaut est KPAY_WEBHOOK_SECRET. Comparaison en temps constant.
    """
    secret = secret if secret is not None else getattr(
        settings, "KPAY_WEBHOOK_SECRET", ""
    )
    if not secret or not signature:
        return False
    if isinstance(corps_brut, str):
        corps_brut = corps_brut.encode("utf-8")
    attendu = hmac.new(secret.encode("utf-8"), corps_brut, hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, signature.strip().lower())


def verifier_retour_passerelle(status, reference, external_id, ts, sig):
    """Vérifie la signature d'un retour passerelle.

    Chaîne signée : ``status|reference|externalId|ts`` (HMAC-SHA256 hex avec
    KPAY_GATEWAY_SECRET). Utilisée si le mode passerelle hébergée est activé.
    """
    secret = getattr(settings, "KPAY_GATEWAY_SECRET", "")
    if not secret:
        return False
    a_tester = f"{status}|{reference}|{external_id}|{ts}"
    attendu = hmac.new(secret.encode("utf-8"), a_tester.encode("utf-8"),
                       hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, (sig or "").strip().lower())


def normaliser_telephone(telephone):
    """Normalise un numéro pour KPay : chiffres seulement, sans + ni 0 initial.

    KPay attend un format international (ex. 237670000001). Si le numéro ne
    comporte pas déjà l'indicatif du pays (2-3 chiffres), on le retourne tel
    quel après nettoyage des caractères non numériques.
    """
    chiffres = re.sub(r"\D", "", str(telephone or ""))
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    return chiffres


def charger_webhook(corps_brut):
    """Charge le corps JSON d'un webhook (dictionnaire vide si invalide)."""
    try:
        return json.loads(corps_brut.decode("utf-8") if isinstance(corps_brut, bytes) else corps_brut)
    except Exception:
        return {}