"""Modules de la barre latérale, utilisés pour les permissions IA et employés."""

EMPLOYE_PERM_MODULES = [
    {"key": "dashboard", "nom": "Tableau de bord"},
    {"key": "employes", "nom": "Employés"},
    {"key": "taches", "nom": "Tâches"},
    {"key": "clients", "nom": "Clients"},
    {"key": "prospection", "nom": "Prospection"},
    {"key": "projets", "nom": "Projets"},
    {"key": "finances", "nom": "Finances"},
    {"key": "depenses", "nom": "Dépenses"},
    {"key": "salaires", "nom": "Salaires"},
    {"key": "contrats", "nom": "Contrats"},
    {"key": "echeances", "nom": "Échéances"},
    {"key": "paiements", "nom": "Paiements"},
    {"key": "roles", "nom": "Rôles & Permissions"},
    {"key": "fonctions", "nom": "Fonctions"},
    {"key": "reunions", "nom": "Réunions"},
    {"key": "documents", "nom": "Documents"},
    {"key": "connecteurs", "nom": "Connecteurs"},
    {"key": "globe", "nom": "Globe 3D"},
    {"key": "societe", "nom": "Ma société"},
]
DEFAULT_EMPLOYE_PERMS = ["dashboard", "employes"]

ALL_MODULE_KEYS = [m["key"] for m in EMPLOYE_PERM_MODULES]