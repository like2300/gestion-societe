"""Modules de la barre latérale, utilisés pour les permissions IA et employés."""

EMPLOYE_PERM_MODULES = [
    {"key": "dashboard", "nom": "Tableau de bord", "cat": "Général"},
    {"key": "employes", "nom": "Employés", "cat": "Équipe & clients"},
    {"key": "groupes", "nom": "Créer des groupes de discussion", "cat": "Général"},
    {"key": "taches", "nom": "Tâches", "cat": "Équipe & clients"},
    {"key": "clients", "nom": "Clients", "cat": "Équipe & clients"},
    {"key": "prospection", "nom": "Prospection", "cat": "Équipe & clients"},
    {"key": "projets", "nom": "Projets", "cat": "Équipe & clients"},
    {"key": "finances", "nom": "Finances", "cat": "Finances"},
    {"key": "depenses", "nom": "Dépenses", "cat": "Finances"},
    {"key": "salaires", "nom": "Salaires", "cat": "Finances"},
    {"key": "contrats", "nom": "Contrats", "cat": "Finances"},
    {"key": "echeances", "nom": "Échéances", "cat": "Finances"},
    {"key": "paiements", "nom": "Paiements", "cat": "Finances"},
    {"key": "factures", "nom": "Factures", "cat": "Finances"},
    {"key": "roles", "nom": "Rôles & Permissions", "cat": "Organisation"},
    {"key": "fonctions", "nom": "Fonctions", "cat": "Organisation"},
    {"key": "reunions", "nom": "Réunions", "cat": "Organisation"},
    {"key": "documents", "nom": "Documents", "cat": "Organisation"},
    {"key": "bureau", "nom": "Applications (Tableur, Documents, Présentations)", "cat": "Applications"},
    {"key": "connecteurs", "nom": "Connecteurs", "cat": "Organisation"},
    {"key": "globe", "nom": "Globe 3D", "cat": "Organisation"},
    {"key": "societe", "nom": "Ma société", "cat": "Organisation"},
]
DEFAULT_EMPLOYE_PERMS = ["dashboard", "employes"]

ALL_MODULE_KEYS = [m["key"] for m in EMPLOYE_PERM_MODULES]