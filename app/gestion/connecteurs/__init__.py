"""Hub de connecteurs : bibliothèque extensible d'intégrations externes."""

from .base import (
    CATEGORIE_LABELS,
    AuthType,
    ConnecteurBase,
    OAuth2Connecteur,
    charger_json,
)
from .registry import (
    categories_disponibles,
    get_connecteur_class,
    metadata_librairie,
    register,
    tout_connecteurs,
)

# Import des connecteurs fournis : enregistre les classes via @register.
from . import providers  # noqa: E402,F401

__all__ = [
    "CATEGORIE_LABELS",
    "AuthType",
    "ConnecteurBase",
    "OAuth2Connecteur",
    "charger_json",
    "categories_disponibles",
    "get_connecteur_class",
    "metadata_librairie",
    "register",
    "tout_connecteurs",
]
