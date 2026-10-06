"""Passerelle IA ↔ connecteurs : accès strictement filtré par les permissions.

Règles de sécurité (à ne jamais contourner) :

1. **Aucun secret ne sort d'ici.** Les fonctions ne renvoient que des
   métadonnées (nom, catégorie, statut, compte, date de synchro). Les jetons
   restent chiffrés en base et ne sont lus que par le provider au moment de
   l'appel réseau.
2. **Double vérification.** Chaque action revérifie côté serveur
   ``peut_acceder`` (module ``connecteurs``) *et* ``est_createur`` — exactement
   comme les vues HTTP. L'IA agit « au nom » de l'utilisateur, jamais avec des
   droits élargis.
3. **Isolation multi-tenant.** Le connecteur est toujours recherché via
   ``societe.connecteurs`` : impossible de toucher une autre société.
4. **Liste blanche d'actions.** Seules les actions exposées par
   :func:`actions_disponibles` peuvent être exécutées ; il n'existe aucun
   moyen générique d'appeler un connecteur.
"""

from .. import services
from .registry import get_connecteur_class

MODULE = "connecteurs"


def resume_connecteurs(user, societe):
    """Liste non sensible des connecteurs visibles par cet utilisateur."""
    if societe is None or not services.peut_acceder(user, societe, MODULE):
        return []
    est_createur = services.est_createur(user, societe)
    resume = []
    for inst in societe.connecteurs.all():
        if not est_createur and not inst.est_connecte:
            continue
        cls = inst.classe
        resume.append(
            {
                "type": inst.type_connecteur,
                "nom": inst.nom or inst.type_connecteur,
                "categorie": cls.categorie if cls else "autre",
                "connecte": inst.est_connecte,
                "compte": inst.compte_externe,
                "derniere_sync": (
                    inst.derniere_sync.isoformat() if inst.derniere_sync else None
                ),
            }
        )
    return resume


def actions_disponibles(user, societe):
    """Actions connecteurs que l'IA est autorisée à exécuter pour cet utilisateur."""
    if societe is None or not services.peut_acceder(user, societe, MODULE):
        return {}
    if not services.est_createur(user, societe):
        # Un employé peut consulter, jamais agir sur les connecteurs.
        return {}
    return {
        "synchroniser_connecteur": {
            "description": "Lance la synchronisation d'un connecteur connecté.",
            "parametres": {"type_connecteur": "clé du connecteur, ex. « gmail »"},
        }
    }


def synchroniser_connecteur(user, societe, type_connecteur):
    """Synchronise un connecteur au nom de l'utilisateur (droits revérifiés)."""
    if societe is None or not services.est_createur(user, societe):
        raise PermissionError("Action réservée au propriétaire de la société.")
    if not services.peut_acceder(user, societe, MODULE):
        raise PermissionError("Module Connecteurs non autorisé pour ce compte.")
    inst = societe.connecteurs.filter(type_connecteur=type_connecteur).first()
    if inst is None or not inst.est_connecte:
        raise ValueError("Connecteur inconnu ou non connecté.")
    cls = inst.classe or get_connecteur_class(type_connecteur)
    if cls is None:
        raise ValueError("Connecteur inconnu.")
    return cls.synchroniser(inst)
