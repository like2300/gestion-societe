"""
Commande de peuplement : `python manage.py seed_demo`

Crée les données de référence (langues, types, permissions, forfaits,
modes de paiement), un superuser et une société de démonstration.
Idempotent : réexécutable sans créer de doublons.
"""

from django.core.management.base import BaseCommand

from gestion.models import (
    Client,
    ContratEmploye,
    EcheancePaiement,
    Employe,
    Fonction,
    Forfait,
    Langue,
    ModePaiement,
    PaiementClient,
    Permission,
    ProjetClient,
    Role,
    Societe,
    TypeClient,
    TypeContrat,
    TypeDepense,
    TypeSociete,
    UserAdmin,
)

PERMISSIONS = [
    ("EMPLOYE_LISTER", "Lister les employés", "Employés"),
    ("EMPLOYE_CREER", "Créer un employé", "Employés"),
    ("CLIENT_GERER", "Gérer les clients", "Clients"),
    ("PROJET_GERER", "Gérer les projets", "Projets"),
    ("FINANCE_CONSULTER", "Consulter la synthèse financière", "Finances"),
    ("DEPENSE_GERER", "Gérer les dépenses", "Finances"),
    ("PARAMETRAGE_SOCIETE", "Paramétrer la société", "Paramétrage"),
]


class Command(BaseCommand):
    help = "Peuple la base : référentiels, superuser et société de démonstration."

    def handle(self, *args, **options):
        # --- Référentiels ---------------------------------------------------
        langues = {}
        for code, nom in [
            ("fr", "Français"),
            ("en", "Anglais"),
            ("fon", "Fon"),
            ("yor", "Yoruba"),
            ("es", "Espagnol"),
        ]:
            langues[code] = Langue.objects.get_or_create(code=code, defaults={"nom": nom})[0]

        types_societe = {}
        for nom in ["SARL", "SAS", "SA", "ONG", "Entreprise individuelle"]:
            types_societe[nom] = TypeSociete.objects.get_or_create(nom=nom)[0]

        types_contrat = {}
        for code, nom in [
            ("CDI", "Contrat à durée indéterminée"),
            ("CDD", "Contrat à durée déterminée"),
            ("STAGE", "Stage"),
            ("FREELANCE", "Prestation freelance"),
        ]:
            types_contrat[code] = TypeContrat.objects.get_or_create(code=code, defaults={"nom": nom})[0]

        types_client = {}
        for nom in ["Particulier", "Entreprise", "Administration", "ONG"]:
            types_client[nom] = TypeClient.objects.get_or_create(nom=nom)[0]

        modes = {}
        for code, nom in [
            ("ESPECES", "Espèces"),
            ("VIREMENT", "Virement bancaire"),
            ("MOBILE_MONEY", "Mobile Money"),
            ("CHEQUE", "Chèque"),
            ("CARTE", "Carte bancaire"),
        ]:
            modes[code] = ModePaiement.objects.get_or_create(code=code, defaults={"nom": nom})[0]

        for nom in ["Salaire", "Loyer", "Matériel", "Transport", "Marketing", "Impôts"]:
            TypeDepense.objects.get_or_create(nom=nom)

        permissions = {}
        for code, nom, module in PERMISSIONS:
            permissions[code] = Permission.objects.get_or_create(
                code=code, defaults={"nom": nom, "module": module}
            )[0]

        forfait_gratuit = Forfait.objects.get_or_create(
            nom="Gratuit",
            defaults={
                "description": "Découverte de la plateforme",
                "prix": 0,
                "devise": "XOF",
                "duree_jours": 30,
            },
        )[0]
        forfait_premium = Forfait.objects.get_or_create(
            nom="Premium",
            defaults={
                "description": "Toutes les fonctionnalités",
                "prix": 25000,
                "devise": "XOF",
                "duree_jours": 30,
            },
        )[0]
        for code in ["EMPLOYE_LISTER", "CLIENT_GERER", "PROJET_GERER", "FINANCE_CONSULTER"]:
            forfait_gratuit.permissions.get_or_create(permission=permissions[code])
        for permission in permissions.values():
            forfait_premium.permissions.get_or_create(permission=permission)

        # --- Superuser ------------------------------------------------------
        if not UserAdmin.objects.filter(email="admin@example.com").exists():
            UserAdmin.objects.create_superuser(
                email="admin@example.com",
                password="admin",
                nom="Admin",
                prenom="Système",
                telephone_1="0100000000",
            )
            self.stdout.write(self.style.WARNING("Superuser créé : admin@example.com / admin (à changer !)"))
        admin = UserAdmin.objects.get(email="admin@example.com")
        admin.langues.get_or_create(langue=langues["fr"])

        # --- Société de démonstration ---------------------------------------
        societe, created = Societe.objects.get_or_create(
            nom="Démo SARL",
            defaults={
                "pays": "Bénin",
                "slogan": "La gestion simplifiée",
                "createur": admin,
                "type_societe": types_societe["SARL"],
            },
        )
        if not created:
            self.stdout.write(self.style.SUCCESS("Données de démonstration déjà présentes."))
            return

        for code in ["EMPLOYE_LISTER", "EMPLOYE_CREER", "CLIENT_GERER", "PROJET_GERER", "FINANCE_CONSULTER"]:
            societe.permissions_activees.get_or_create(
                permission=permissions[code], defaults={"active": True, "source": "Forfait"}
            )

        role_manager = Role.objects.create(societe=societe, nom="Manager")
        fonction_dev = Fonction.objects.create(societe=societe, nom="Développeur")

        employe = Employe.objects.create(
            societe=societe,
            nom="Ahouansou",
            prenom="Kossi",
            telephone_1="0297000001",
            email="kossi@demo.bj",
            salaire=250000,
            role=role_manager,
            fonction=fonction_dev,
            date_recrutement="2024-01-15",
            jour_paiement=30,
        )
        employe.langues.get_or_create(langue=langues["fr"])
        employe.langues.get_or_create(langue=langues["fon"])
        ContratEmploye.objects.create(
            employe=employe,
            type_contrat=types_contrat["CDI"],
            date_debut="2024-01-15",
            salaire_contractuel=250000,
        )

        client = Client.objects.create(
            societe=societe,
            nom="Entreprise X",
            type_client=types_client["Entreprise"],
            telephone_1="0297000002",
            ville="Cotonou",
            pays="Bénin",
        )

        projet = ProjetClient.objects.create(
            societe=societe,
            client=client,
            nom="Site web vitrine",
            description="Développement du site vitrine de l'entreprise X.",
            date_debut="2025-09-01",
            budget=1500000,
        )
        echeance = EcheancePaiement.objects.create(
            projet=projet,
            numero_echeance=1,
            montant_prevu=750000,
            date_prevue="2025-09-30",
        )
        PaiementClient.objects.create(
            projet=projet,
            echeance=echeance,
            montant=750000,
            date_paiement="2025-09-28",
            mode_paiement=modes["VIREMENT"],
            reference="VIR-2025-001",
            statut="CONFIRME",
        )

        self.stdout.write(self.style.SUCCESS("Seed terminé : référentiels, superuser, société 'Démo SARL'."))
