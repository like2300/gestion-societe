"""Registre des connecteurs : point d'extension unique.

Pour ajouter une intégration :

    from .registry import register
    from .base import ConnecteurBase

    @register
    class MonService(ConnecteurBase):
        key = "mon_service"
        nom = "Mon service"
        ...

Le hub, les filtres et le stockage découvrent le connecteur automatiquement.
"""

_REGISTRY = {}
_ORDER = []


def register(cls):
    """Décorateur d'enregistrement d'une classe de connecteur."""
    if not getattr(cls, "key", ""):
        raise ValueError("Un connecteur doit définir une clé `key`.")
    _REGISTRY[cls.key] = cls
    if cls.key not in _ORDER:
        _ORDER.append(cls.key)
    return cls


def get_connecteur_class(key):
    return _REGISTRY.get(key)


def tout_connecteurs():
    """Tous les connecteurs enregistrés, dans l'ordre de déclaration."""
    return [_REGISTRY[k] for k in _ORDER]


def categories_disponibles():
    """Catégories distinctes (ordre d'apparition) pour les filtres du hub."""
    vus = []
    for cls in tout_connecteurs():
        if cls.categorie not in vus:
            vus.append(cls.categorie)
    return vus


def metadata_librairie():
    return [cls.metadata() for cls in tout_connecteurs()]
