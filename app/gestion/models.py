"""
Modèles du Gestionnaire de société — 38 tables.

Document de référence : app/instruction/db-explication.md
Diagramme : app/instruction/db.md
"""

from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.validators import MaxValueValidator
import uuid

from django.db import models
from django.utils import timezone

# ---------------------------------------------------------------------------
# Choix partagés (champs VARCHAR statut)
# ---------------------------------------------------------------------------

ROLE_ADMIN_CHOICES = [
    ("CREATEUR", "Créateur"),
    ("ADMIN", "Admin"),
    ("EMPLOYE", "Employé"),
]

STATUT_ACTIF_CHOICES = [
    ("ACTIF", "Actif"),
    ("INACTIF", "Inactif"),
    ("SUSPENDU", "Suspendu"),
]

STATUT_SOCIETE_CHOICES = STATUT_ACTIF_CHOICES

STATUT_EMPLOYE_CHOICES = [
    ("ACTIF", "Actif"),
    ("INACTIF", "Inactif"),
    ("SUSPENDU", "Suspendu"),
    ("CONGE", "En congé"),
]

STATUT_CONTRAT_CHOICES = [
    ("ACTIF", "Actif"),
    ("TERMINE", "Terminé"),
    ("RESILIE", "Résilié"),
]

STATUT_CLIENT_CHOICES = STATUT_ACTIF_CHOICES

STATUT_PROJET_CHOICES = [
    ("EN_COURS", "En cours"),
    ("TERMINE", "Terminé"),
    ("SUSPENDU", "Suspendu"),
    ("ANNULE", "Annulé"),
]

STATUT_OBJECTIF_CHOICES = [
    ("EN_ATTENTE", "En attente"),
    ("EN_COURS", "En cours"),
    ("ATTEINT", "Atteint"),
    ("ANNULE", "Annulé"),
]

STATUT_ECHEANCE_CHOICES = [
    ("A_VENIR", "À venir"),
    ("PARTIELLE", "Partielle"),
    ("PAYEE", "Payée"),
    ("RETARD", "Retard"),
]

STATUT_PAIEMENT_CHOICES = [
    ("CONFIRME", "Confirmé"),
    ("EN_ATTENTE", "En attente"),
    ("ANNULE", "Annulé"),
]

SOURCE_CLIENT_CHOICES = [
    ("RECOMMANDATION", "Recommandation"),
    ("SITE_WEB", "Site web"),
    ("RESEAUX_SOCIAUX", "Réseaux sociaux"),
    ("EVENEMENT", "Événement / salon"),
    ("DEMARCHAGE", "Démarchage"),
    ("PARTENAIRE", "Partenaire"),
    ("AUTRE", "Autre"),
]

PROSPECTION_STATUT_CHOICES = [
    ("NOUVEAU", "Nouveau"),
    ("CONTACTE", "Contacté"),
    ("EN_NEGOCIATION", "En négociation"),
    ("GAGNE", "Gagné"),
    ("PERDU", "Perdu"),
]

STATUT_ABONNEMENT_CHOICES = [
    ("EN_ATTENTE", "En attente"),
    ("ACTIF", "Actif"),
    ("EXPIRE", "Expiré"),
    ("SUSPENDU", "Suspendu"),
    ("ANNULE", "Demande refusée"),
]

STATUT_DEPENSE_CHOICES = STATUT_PAIEMENT_CHOICES

STATUT_SALAIRE_CHOICES = [
    ("PREVU", "Prévu"),
    ("PARTIEL", "Partiel"),
    ("PAYE", "Payé"),
    ("RETARD", "Retard"),
]

STATUT_CONVERSATION_IA_CHOICES = [
    ("ACTIVE", "Active"),
    ("ARCHIVEE", "Archivée"),
]

ROLE_IA_MESSAGE_CHOICES = [
    ("user", "Utilisateur"),
    ("assistant", "Assistant"),
]

COULEUR_SOCIETE_CHOICES = [
    ("SKY", "Bleu ciel"),
    ("BLUE", "Bleu royal"),
    ("INDIGO", "Indigo"),
    ("VIOLET", "Violet"),
    ("EMERALD", "Émeraude"),
    ("ORANGE", "Orange"),
    ("ROSE", "Rose"),
    ("SLATE", "Ardoise"),
]


# ---------------------------------------------------------------------------
# 1. user_admin — utilisateur personnalisé
# ---------------------------------------------------------------------------


class UserAdminManager(BaseUserManager):
    """Manager pour UserAdmin (email comme identifiant)."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("L'email est obligatoire.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role_admin", "ADMIN")
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role_admin", "CREATEUR")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superuser doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superuser doit avoir is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class UserAdmin(AbstractBaseUser, PermissionsMixin):
    """1. Utilisateurs administratifs (table user_admin)."""

    email = models.EmailField("email de connexion", max_length=255, unique=True)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    date_naissance = models.DateField(null=True, blank=True)
    lieu_naissance = models.CharField(max_length=150, blank=True, null=True)
    nationalite = models.CharField(max_length=100, blank=True, null=True)
    photo_profil = models.CharField(max_length=500, blank=True, null=True)
    telephone_1 = models.CharField(max_length=30)
    telephone_2 = models.CharField(max_length=30, blank=True, null=True)
    numero_piece_identite = models.CharField(
        max_length=100, unique=True, blank=True, null=True
    )
    role_admin = models.CharField(
        max_length=50, choices=ROLE_ADMIN_CHOICES, default="ADMIN"
    )
    statut = models.CharField(
        max_length=30, choices=STATUT_ACTIF_CHOICES, default="ACTIF"
    )
    is_staff = models.BooleanField("accès admin Django", default=False)
    is_active = models.BooleanField("actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notif_son_actif = models.BooleanField("son des notifications", default=True)
    doit_changer_mdp = models.BooleanField(
        "doit changer son mot de passe", default=False
    )

    objects = UserAdminManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nom", "prenom", "telephone_1"]

    class Meta:
        db_table = "user_admin"
        verbose_name = "administrateur"
        verbose_name_plural = "administrateurs"
        ordering = ["nom", "prenom"]

    def __str__(self):
        return f"{self.prenom} {self.nom} <{self.email}>"


# ---------------------------------------------------------------------------
# 2-3. langue, user_admin_langue
# ---------------------------------------------------------------------------


class Langue(models.Model):
    """2. Catalogue des langues."""

    code = models.CharField(max_length=20, unique=True)
    nom = models.CharField(max_length=100, unique=True)
    actif = models.BooleanField(default=True)

    class Meta:
        db_table = "langue"
        verbose_name = "langue"
        verbose_name_plural = "langues"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class UserAdminLangue(models.Model):
    """3. Langues des administrateurs."""

    user_admin = models.ForeignKey(
        UserAdmin, on_delete=models.CASCADE, related_name="langues"
    )
    langue = models.ForeignKey(
        Langue, on_delete=models.CASCADE, related_name="user_admins"
    )

    class Meta:
        db_table = "user_admin_langue"
        verbose_name = "langue d'administrateur"
        verbose_name_plural = "langues des administrateurs"
        unique_together = [("user_admin", "langue")]

    def __str__(self):
        return f"{self.user_admin} — {self.langue}"


# ---------------------------------------------------------------------------
# 5-6. type_societe, societe, societe_document
# ---------------------------------------------------------------------------


class TypeSociete(models.Model):
    """5. Types de sociétés (SARL, SAS, ONG...)."""

    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "type_societe"
        verbose_name = "type de société"
        verbose_name_plural = "types de société"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Societe(models.Model):
    """4. Sociétés."""

    nom = models.CharField(max_length=200)
    pays = models.CharField(max_length=100)
    slogan = models.CharField(max_length=255, blank=True, null=True)
    logo = models.CharField(max_length=500, blank=True, null=True)
    createur = models.ForeignKey(
        UserAdmin,
        on_delete=models.PROTECT,
        related_name="societes_creees",
        verbose_name="créateur",
    )
    type_societe = models.ForeignKey(
        TypeSociete,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="societes",
    )
    statut = models.CharField(
        max_length=30, choices=STATUT_SOCIETE_CHOICES, default="ACTIF"
    )
    couleur = models.CharField(
        max_length=30,
        choices=COULEUR_SOCIETE_CHOICES,
        default="SKY",
        verbose_name="couleur du dashboard",
    )
    modes_paiement = models.ManyToManyField(
        "ModePaiement",
        blank=True,
        related_name="societes",
        verbose_name="modes de paiement disponibles",
        help_text=(
            "Modes de paiement que la société peut utiliser pour payer "
            "les salaires. Configurable dans « Ma société » ."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "societe"
        verbose_name = "société"
        verbose_name_plural = "sociétés"
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["createur"],
                name="unique_societe_createur",
                violation_error_message=(
                    "Un utilisateur ne peut posséder qu'une seule société."
                ),
            ),
        ]

    def __str__(self):
        return self.nom


class SocieteDocument(models.Model):
    """6. Documents société (RCCM, NIU...)."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="documents"
    )
    type_document = models.CharField(max_length=100)
    numero_document = models.CharField(max_length=150, blank=True, null=True)
    fichier = models.CharField(max_length=500)
    date_emission = models.DateField(null=True, blank=True)
    date_expiration = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "societe_document"
        verbose_name = "document de société"
        verbose_name_plural = "documents de société"

    def __str__(self):
        return f"{self.societe} — {self.type_document}"


# ---------------------------------------------------------------------------
# 7-10. role, permission, role_permission, permission_societe
# ---------------------------------------------------------------------------


class Role(models.Model):
    """7. Rôles internes."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="roles"
    )
    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    statut = models.CharField(
        max_length=30, choices=STATUT_ACTIF_CHOICES, default="ACTIF"
    )

    class Meta:
        db_table = "role"
        verbose_name = "rôle"
        verbose_name_plural = "rôles"
        ordering = ["societe", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.societe})"


class Permission(models.Model):
    """8. Catalogue global des permissions."""

    code = models.CharField(max_length=100, unique=True)
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    module = models.CharField(max_length=100, blank=True, null=True)
    actif = models.BooleanField(default=True)

    class Meta:
        db_table = "permission"
        verbose_name = "permission"
        verbose_name_plural = "permissions"
        ordering = ["module", "code"]

    def __str__(self):
        return f"{self.code} — {self.nom}"


class RolePermission(models.Model):
    """9. Permissions des rôles."""

    role = models.ForeignKey(
        Role, on_delete=models.CASCADE, related_name="permissions"
    )
    permission = models.ForeignKey(
        Permission, on_delete=models.CASCADE, related_name="roles"
    )

    class Meta:
        db_table = "role_permission"
        verbose_name = "permission de rôle"
        verbose_name_plural = "permissions des rôles"
        unique_together = [("role", "permission")]

    def __str__(self):
        return f"{self.role} — {self.permission}"


class PermissionSociete(models.Model):
    """10. Fonctionnalités activées pour une société."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="permissions_activees"
    )
    permission = models.ForeignKey(
        Permission, on_delete=models.CASCADE, related_name="societes"
    )
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=30, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "permission_societe"
        verbose_name = "permission de société"
        verbose_name_plural = "permissions des sociétés"
        unique_together = [("societe", "permission")]

    def __str__(self):
        return f"{self.societe} — {self.permission} ({'activée' if self.active else 'désactivée'})"


# ---------------------------------------------------------------------------
# 11. fonction
# ---------------------------------------------------------------------------


class Fonction(models.Model):
    """11. Postes/fonctions."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="fonctions"
    )
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    actif = models.BooleanField(default=True)

    class Meta:
        db_table = "fonction"
        verbose_name = "fonction"
        verbose_name_plural = "fonctions"
        ordering = ["societe", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.societe})"


# ---------------------------------------------------------------------------
# 2bis. employe, employe_langue
# ---------------------------------------------------------------------------


class Employe(models.Model):
    """12. Employés."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="employes"
    )
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    date_naissance = models.DateField(null=True, blank=True)
    lieu_naissance = models.CharField(max_length=150, blank=True, default="")
    nationalite = models.CharField(max_length=100, blank=True, null=True)
    numero_piece_identite = models.CharField(
        max_length=60, blank=True, default="", verbose_name="n° de pièce d'identité"
    )
    adresse = models.CharField(max_length=255, blank=True, default="")
    photo_profil = models.CharField(max_length=500, blank=True, null=True)
    telephone_1 = models.CharField(max_length=30)
    telephone_2 = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    password_hash = models.CharField(max_length=255, blank=True, null=True)
    salaire = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employes",
    )
    fonction = models.ForeignKey(
        Fonction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employes",
    )
    statut = models.CharField(
        max_length=30, choices=STATUT_EMPLOYE_CHOICES, default="ACTIF"
    )
    date_recrutement = models.DateField(null=True, blank=True)
    jour_paiement = models.PositiveSmallIntegerField(null=True, blank=True)
    permissions = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="Modules accessibles (barre latérale).",
    )
    # Parmi les modules accessibles : ceux ouverts en LECTURE SEULE (consultation sans
    # création, modification ni suppression). Absent de la liste = accès en modification.
    permissions_lecture = models.JSONField(
        default=list,
        blank=True,
        help_text="Modules accessibles en lecture seule.",
    )
    compte = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employe_profil",
        verbose_name="compte utilisateur",
        help_text=(
            "Compte de connexion relié à cet employé. Renseigné quand "
            "l'employé accepte l'invitation à rejoindre l'équipe."
        ),
    )

    class Meta:
        db_table = "employe"
        verbose_name = "employé"
        verbose_name_plural = "employés"
        ordering = ["societe", "nom", "prenom"]

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.societe})"


class EmployeDocument(models.Model):
    """13. Documents d'un employé (pièce d'identité, contrat, diplôme…)."""

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="documents"
    )
    type_document = models.CharField(max_length=100)
    fichier = models.CharField(max_length=500)
    date_document = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "employe_document"
        verbose_name = "document d'employé"
        verbose_name_plural = "documents d'employé"

    def __str__(self):
        return f"{self.employe} — {self.type_document}"


class EmployeLangue(models.Model):
    """13. Langues des employés."""

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="langues"
    )
    langue = models.ForeignKey(
        Langue, on_delete=models.CASCADE, related_name="employes"
    )

    class Meta:
        db_table = "employe_langue"
        verbose_name = "langue d'employé"
        verbose_name_plural = "langues des employés"
        unique_together = [("employe", "langue")]

    def __str__(self):
        return f"{self.employe} — {self.langue}"


# ---------------------------------------------------------------------------
# 2ter. demande_adhesion — invitation à rejoindre une équipe
# ---------------------------------------------------------------------------


STATUT_DEMANDE_ADHESION_CHOICES = [
    ("EN_ATTENTE", "En attente"),
    ("ACCEPTEE", "Acceptée"),
    ("REFUSEE", "Refusée"),
]

ORIGINE_DEMANDE_CHOICES = [
    ("INVITATION", "Invitation"),
    ("DEMANDE", "Demande"),
]


class DemandeAdhesion(models.Model):
    """Lien entre un compte et une société pour rejoindre une équipe.

    Deux sens possibles (champ ``origine``) :

    - ``INVITATION`` : créée à l'inscription quand l'email correspond à une
      fiche ``Employe`` existante. Le compte accepte ou refuse l'invitation.
    - ``DEMANDE`` : créée par le compte lui-même depuis la page « rejoindre
      une société ». Le créateur de la société l'accepte ou la refuse, ce qui
      crée la fiche ``Employe`` correspondante.
    """

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="demandes_adhesion"
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="demandes_adhesion",
        verbose_name="employé visé",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="demandes_adhesion",
        verbose_name="compte invité",
    )
    statut = models.CharField(
        max_length=20,
        choices=STATUT_DEMANDE_ADHESION_CHOICES,
        default="EN_ATTENTE",
    )
    origine = models.CharField(
        max_length=20,
        choices=ORIGINE_DEMANDE_CHOICES,
        default="INVITATION",
        help_text="Invitation reçue ou demande envoyée par le compte.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "demande_adhesion"
        verbose_name = "demande d'adhésion"
        verbose_name_plural = "demandes d'adhésion"
        ordering = ["-created_at"]
        unique_together = [("user", "societe")]

    def __str__(self):
        return f"{self.user} → {self.societe} ({self.get_statut_display()})"


# ---------------------------------------------------------------------------
# 14-15. type_contrat, contrat_employe
# ---------------------------------------------------------------------------


class TypeContrat(models.Model):
    """14. Types de contrat (CDI, CDD, STAGE...)."""

    code = models.CharField(max_length=30, unique=True)
    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "type_contrat"
        verbose_name = "type de contrat"
        verbose_name_plural = "types de contrat"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.nom}"


class ContratEmploye(models.Model):
    """15. Contrats de travail."""

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="contrats"
    )
    type_contrat = models.ForeignKey(
        TypeContrat, on_delete=models.PROTECT, related_name="contrats"
    )
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)
    salaire_contractuel = models.DecimalField(max_digits=15, decimal_places=2)
    fichier_contrat = models.CharField(max_length=500, blank=True, null=True)
    statut = models.CharField(
        max_length=30, choices=STATUT_CONTRAT_CHOICES, default="ACTIF"
    )
    # Clauses du contrat imprimé (généré automatiquement à la création de l'employé)
    poste = models.CharField(max_length=150, blank=True, default="")
    lieu_travail = models.CharField(max_length=255, blank=True, default="")
    heures_hebdo = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="heures par semaine")
    periode_essai_jours = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="période d'essai (jours)")
    missions = models.TextField(blank=True, default="")

    class Meta:
        db_table = "contrat_employe"
        verbose_name = "contrat d'employé"
        verbose_name_plural = "contrats d'employés"
        ordering = ["-date_debut"]

    def __str__(self):
        return f"{self.employe} — {self.type_contrat.code} du {self.date_debut}"


# ---------------------------------------------------------------------------
# 16-19. type_client, client, client_document, projet_client
# ---------------------------------------------------------------------------


class TypeClient(models.Model):
    """16. Types de client."""

    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "type_client"
        verbose_name = "type de client"
        verbose_name_plural = "types de client"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Client(models.Model):
    """17. Clients."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="clients"
    )
    nom = models.CharField(max_length=200)
    logo = models.CharField(
        max_length=500, blank=True, null=True, verbose_name="logo"
    )
    type_client = models.ForeignKey(
        TypeClient, on_delete=models.PROTECT, related_name="clients"
    )
    email = models.EmailField(blank=True, null=True)
    telephone_1 = models.CharField(max_length=30)
    telephone_2 = models.CharField(max_length=30, blank=True, null=True)
    adresse = models.CharField(max_length=255, blank=True, null=True)
    ville = models.CharField(max_length=100, blank=True, null=True)
    pays = models.CharField(max_length=100, blank=True, null=True)
    statut = models.CharField(
        max_length=30, choices=STATUT_CLIENT_CHOICES, default="ACTIF"
    )
    source = models.CharField(
        max_length=30,
        choices=SOURCE_CLIENT_CHOICES,
        default="",
        blank=True,
        verbose_name="source du client",
        help_text="D'où vient ce client (prospection, recommandation…).",
    )
    cree_par = models.ForeignKey(
        "UserAdmin",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clients_creees",
        verbose_name="fiche créée par",
    )
    responsable = models.ForeignKey(
        "Employe",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clients_suivis",
        verbose_name="responsable du client",
        help_text="Employé en charge du suivi de ce client.",
    )
    created_at = models.DateTimeField(
        default=timezone.now, verbose_name="date de création de la fiche"
    )

    class Meta:
        db_table = "client"
        verbose_name = "client"
        verbose_name_plural = "clients"
        ordering = ["societe", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.societe})"


class ProspectionClient(models.Model):
    """17 bis. Prospection commerciale (pipeline avant client).

    Une ligne = un prospect suivi par un responsable commercial. La conversion
    (``convertir_prospection``) crée le ``Client`` lié, bascule le statut sur
    « Gagné » et garde la trace du créateur / responsable / source sur la fiche
    client (traçabilité opérationnelle de l'espace Clients).
    """

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="prospections"
    )
    nom = models.CharField(max_length=200, verbose_name="entreprise")
    contact = models.CharField(
        max_length=120, blank=True, default="", verbose_name="contact"
    )
    email = models.EmailField(blank=True, default="")
    telephone = models.CharField(max_length=30, blank=True, default="")
    ville = models.CharField(max_length=100, blank=True, default="")
    pays = models.CharField(max_length=100, blank=True, default="")
    description = models.TextField(blank=True, default="")
    source = models.CharField(
        max_length=30, choices=SOURCE_CLIENT_CHOICES, default="AUTRE"
    )
    budget_estime = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    statut = models.CharField(
        max_length=30, choices=PROSPECTION_STATUT_CHOICES, default="NOUVEAU"
    )
    date_prospection = models.DateField(
        null=True, blank=True, verbose_name="date de prospection"
    )
    type_client = models.ForeignKey(
        TypeClient,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="prospections",
        verbose_name="type de client (conversion)",
    )
    responsable = models.ForeignKey(
        Employe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospects",
        verbose_name="responsable",
        help_text="Commercial en charge de ce prospect.",
    )
    client = models.OneToOneField(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospection",
        verbose_name="client converti",
    )
    cree_par = models.ForeignKey(
        UserAdmin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospections_creees",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prospection_client"
        verbose_name = "prospect"
        verbose_name_plural = "prospects"
        ordering = ["societe", "-created_at"]
        indexes = [
            models.Index(fields=["societe", "statut"]),
        ]

    def __str__(self):
        return f"{self.nom} ({self.get_statut_display()})"


class Reunion(models.Model):
    """Réunion interne : programmation, participants et lien Google Meet."""

    DUREE_CHOICES = [
        (15, "15 min"),
        (30, "30 min"),
        (45, "45 min"),
        (60, "60 min"),
        (90, "1 h 30"),
        (120, "2 h"),
    ]

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="reunions"
    )
    titre = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    date = models.DateField(verbose_name="date")
    heure = models.TimeField(verbose_name="heure")
    duree = models.PositiveSmallIntegerField(
        choices=DUREE_CHOICES, default=60, verbose_name="durée (minutes)"
    )
    participants = models.ManyToManyField(
        Employe, blank=True, related_name="reunions"
    )
    lien_meet = models.CharField(
        max_length=400, blank=True, default="", verbose_name="lien Google Meet"
    )
    evenement_google_id = models.CharField(
        max_length=200, blank=True, default="", verbose_name="événement Google"
    )
    compte_externe = models.CharField(
        max_length=200, blank=True, default="", verbose_name="compte Meet utilisé"
    )
    cree_par = models.ForeignKey(
        UserAdmin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reunions_crees",
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reunion"
        verbose_name = "réunion"
        verbose_name_plural = "réunions"
        ordering = ["-date", "-heure"]
        indexes = [models.Index(fields=["societe", "date"])]

    def __str__(self):
        return f"{self.titre} ({self.date} {self.heure})"

    @property
    def est_passee(self):
        maintenant = timezone.localtime()
        return (self.date, self.heure) < (maintenant.date(), maintenant.time())

    @property
    def date_aff(self):
        return self.date.strftime("%d/%m/%Y") if self.date else ""

    @property
    def heure_aff(self):
        return self.heure.strftime("%H:%M") if self.heure else ""


class ClientDocument(models.Model):
    """18. Documents client."""

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="documents"
    )
    type_document = models.CharField(max_length=100)
    fichier = models.CharField(max_length=500)
    date_document = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "client_document"
        verbose_name = "document client"
        verbose_name_plural = "documents client"

    def __str__(self):
        return f"{self.client} — {self.type_document}"


class ProjetClient(models.Model):
    """19. Projets clients."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="projets"
    )
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="projets"
    )
    nom = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)
    budget = models.DecimalField(max_digits=15, decimal_places=2)
    statut = models.CharField(
        max_length=30, choices=STATUT_PROJET_CHOICES, default="EN_COURS"
    )

    class Meta:
        db_table = "projet_client"
        verbose_name = "projet client"
        verbose_name_plural = "projets clients"
        ordering = ["-date_debut"]

    def __str__(self):
        return f"{self.nom} ({self.client})"


# ---------------------------------------------------------------------------
# 20-25. projet_chef, projet_objectif, groupe_projet, membres, conversations
# ---------------------------------------------------------------------------


class ProjetChef(models.Model):
    """20. Chefs de projet multiples."""

    projet = models.ForeignKey(
        ProjetClient, on_delete=models.CASCADE, related_name="chefs"
    )
    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="projets_diriges"
    )
    date_affectation = models.DateField()
    principal = models.BooleanField(default=False)

    class Meta:
        db_table = "projet_chef"
        verbose_name = "chef de projet"
        verbose_name_plural = "chefs de projet"
        unique_together = [("projet", "employe")]

    def __str__(self):
        return f"{self.employe} → {self.projet}"


class ProjetObjectif(models.Model):
    """21. Objectifs multiples."""

    projet = models.ForeignKey(
        ProjetClient, on_delete=models.CASCADE, related_name="objectifs"
    )
    titre = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    date_echeance = models.DateField(null=True, blank=True)
    statut = models.CharField(
        max_length=30, choices=STATUT_OBJECTIF_CHOICES, default="EN_ATTENTE"
    )

    class Meta:
        db_table = "projet_objectif"
        verbose_name = "objectif de projet"
        verbose_name_plural = "objectifs de projet"
        ordering = ["date_echeance"]

    def __str__(self):
        return self.titre


class GroupeProjet(models.Model):
    """22. Groupes de travail."""

    projet = models.ForeignKey(
        ProjetClient, on_delete=models.CASCADE, related_name="groupes"
    )
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    cree_par = models.ForeignKey(
        Employe,
        on_delete=models.PROTECT,
        related_name="groupes_crees",
        verbose_name="créé par",
    )

    class Meta:
        db_table = "groupe_projet"
        verbose_name = "groupe de projet"
        verbose_name_plural = "groupes de projet"
        ordering = ["projet", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.projet})"


class GroupeProjetMembre(models.Model):
    """23. Membres des groupes."""

    groupe = models.ForeignKey(
        GroupeProjet, on_delete=models.CASCADE, related_name="membres"
    )
    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="groupes"
    )
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "groupe_projet_membre"
        verbose_name = "membre de groupe"
        verbose_name_plural = "membres des groupes"
        unique_together = [("groupe", "employe")]

    def __str__(self):
        return f"{self.employe} — {self.groupe}"


class ConversationGroupe(models.Model):
    """24. Conversations groupe."""

    groupe = models.ForeignKey(
        GroupeProjet, on_delete=models.CASCADE, related_name="conversations"
    )
    titre = models.CharField(max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conversation_groupe"
        verbose_name = "conversation de groupe"
        verbose_name_plural = "conversations de groupe"

    def __str__(self):
        return self.titre or f"Conversation #{self.pk}"


class MessageGroupe(models.Model):
    """25. Messages groupe."""

    conversation = models.ForeignKey(
        ConversationGroupe, on_delete=models.CASCADE, related_name="messages"
    )
    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="messages_groupe"
    )
    contenu = models.TextField()
    fichier = models.CharField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message_groupe"
        verbose_name = "message de groupe"
        verbose_name_plural = "messages de groupe"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.employe} @ {self.conversation} : {self.contenu[:30]}"


# ---------------------------------------------------------------------------
# 26-28. echeance_paiement, mode_paiement, paiement_client
# ---------------------------------------------------------------------------


class ModePaiement(models.Model):
    """28. Modes de paiement."""

    code = models.CharField(max_length=50, unique=True)
    nom = models.CharField(max_length=100)
    actif = models.BooleanField(default=True)

    class Meta:
        db_table = "mode_paiement"
        verbose_name = "mode de paiement"
        verbose_name_plural = "modes de paiement"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class EcheancePaiement(models.Model):
    """26. Échéances projet."""

    projet = models.ForeignKey(
        ProjetClient, on_delete=models.CASCADE, related_name="echeances"
    )
    numero_echeance = models.PositiveIntegerField()
    montant_prevu = models.DecimalField(max_digits=15, decimal_places=2)
    date_prevue = models.DateField()
    statut = models.CharField(
        max_length=30, choices=STATUT_ECHEANCE_CHOICES, default="A_VENIR"
    )

    class Meta:
        db_table = "echeance_paiement"
        verbose_name = "échéance de paiement"
        verbose_name_plural = "échéances de paiement"
        ordering = ["projet", "numero_echeance"]
        unique_together = [("projet", "numero_echeance")]

    def __str__(self):
        return f"{self.projet} — échéance #{self.numero_echeance}"


class PaiementClient(models.Model):
    """27. Paiements clients."""

    projet = models.ForeignKey(
        ProjetClient, on_delete=models.CASCADE, related_name="paiements"
    )
    echeance = models.ForeignKey(
        EcheancePaiement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paiements",
    )
    montant = models.DecimalField(max_digits=15, decimal_places=2)
    date_paiement = models.DateField()
    mode_paiement = models.ForeignKey(
        ModePaiement, on_delete=models.PROTECT, related_name="paiements_clients"
    )
    reference = models.CharField(max_length=150, blank=True, null=True)
    statut = models.CharField(
        max_length=30, choices=STATUT_PAIEMENT_CHOICES, default="EN_ATTENTE"
    )

    class Meta:
        db_table = "paiement_client"
        verbose_name = "paiement client"
        verbose_name_plural = "paiements clients"
        ordering = ["-date_paiement"]

    def __str__(self):
        return f"{self.projet} — {self.montant} le {self.date_paiement}"


# ---------------------------------------------------------------------------
# 29-32. forfait, forfait_permission, abonnement_societe, paiement_abonnement
# ---------------------------------------------------------------------------


def format_prix(montant, devise):
    """Montant lisible : « 49 $ », « 49,50 $ », « 25 000 XOF », « Gratuit » pour 0."""
    if not montant:
        return "Gratuit"
    entier = float(montant) == int(montant)
    texte = f"{float(montant):,.0f}" if entier else f"{float(montant):,.2f}"
    texte = texte.replace(",", " ").replace(".", ",")
    return f"{texte} $" if devise == "USD" else f"{texte} {devise}"


class Forfait(models.Model):
    """29. Forfaits."""

    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    prix = models.DecimalField(max_digits=15, decimal_places=2)
    devise = models.CharField(max_length=10, default="XOF")
    duree_jours = models.PositiveIntegerField()
    actif = models.BooleanField(default=True)

    @property
    def prix_affiche(self):
        """« 49 $ », « 25 000 XOF », « Gratuit »."""
        return format_prix(self.prix, self.devise)

    class Meta:
        db_table = "forfait"
        verbose_name = "forfait"
        verbose_name_plural = "forfaits"
        ordering = ["prix"]

    def __str__(self):
        return f"{self.nom} ({self.prix} {self.devise} / {self.duree_jours} j)"


class ForfaitPermission(models.Model):
    """30. Permissions du forfait."""

    forfait = models.ForeignKey(
        Forfait, on_delete=models.CASCADE, related_name="permissions"
    )
    permission = models.ForeignKey(
        Permission, on_delete=models.CASCADE, related_name="forfaits"
    )

    class Meta:
        db_table = "forfait_permission"
        verbose_name = "permission de forfait"
        verbose_name_plural = "permissions des forfaits"
        unique_together = [("forfait", "permission")]

    def __str__(self):
        return f"{self.forfait} — {self.permission}"


class AbonnementSociete(models.Model):
    """31. Abonnements sociétés."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="abonnements"
    )
    forfait = models.ForeignKey(
        Forfait, on_delete=models.PROTECT, related_name="abonnements"
    )
    date_debut = models.DateField()
    date_fin = models.DateField()
    prix_paye = models.DecimalField(max_digits=15, decimal_places=2)
    statut = models.CharField(
        max_length=30, choices=STATUT_ABONNEMENT_CHOICES, default="EN_ATTENTE"
    )
    renouvellement_auto = models.BooleanField(default=False)
    # Lien de paiement envoyé par e-mail (page publique protégée par ce jeton)
    jeton = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Demande de changement d'offre : forfait que la société avait avant cette demande
    ancien_forfait = models.ForeignKey(
        Forfait, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="forfait précédent (changement d'offre)",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = "abonnement_societe"
        verbose_name = "abonnement de société"
        verbose_name_plural = "abonnements de sociétés"
        ordering = ["-date_debut"]

    def __str__(self):
        return f"{self.societe} — {self.forfait} ({self.statut})"


class PaiementAbonnement(models.Model):
    """32. Paiements abonnements."""

    abonnement = models.ForeignKey(
        AbonnementSociete, on_delete=models.CASCADE, related_name="paiements"
    )
    montant = models.DecimalField(max_digits=15, decimal_places=2)
    date_paiement = models.DateField()
    mode_paiement = models.ForeignKey(
        ModePaiement, on_delete=models.PROTECT, related_name="paiements_abonnements"
    )
    reference = models.CharField(max_length=150, blank=True, null=True)
    statut = models.CharField(
        max_length=30, choices=STATUT_PAIEMENT_CHOICES, default="EN_ATTENTE"
    )
    telephone = models.CharField(max_length=30, blank=True, default="")
    kpay_id = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = "paiement_abonnement"
        verbose_name = "paiement d'abonnement"
        verbose_name_plural = "paiements d'abonnements"
        ordering = ["-date_paiement"]

    def __str__(self):
        return f"{self.abonnement} — {self.montant} le {self.date_paiement}"


# ---------------------------------------------------------------------------
# 33-35. type_depense, depense_societe, paiement_salaire
# ---------------------------------------------------------------------------


class TypeDepense(models.Model):
    """33. Types de dépenses."""

    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "type_depense"
        verbose_name = "type de dépense"
        verbose_name_plural = "types de dépense"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class DepenseSociete(models.Model):
    """34. Dépenses société."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="depenses"
    )
    type_depense = models.ForeignKey(
        TypeDepense, on_delete=models.PROTECT, related_name="depenses"
    )
    nom = models.CharField(max_length=200)
    montant = models.DecimalField(max_digits=15, decimal_places=2)
    date_depense = models.DateField()
    description = models.TextField(blank=True, null=True)
    fichier_justificatif = models.CharField(max_length=500, blank=True, null=True)
    statut = models.CharField(
        max_length=30, choices=STATUT_DEPENSE_CHOICES, default="CONFIRME"
    )
    paiement_salaire = models.OneToOneField(
        "PaiementSalaire",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="depense",
        verbose_name="salaire lié",
        help_text="Dépense générée automatiquement quand un salaire est validé comme payé.",
    )
    employe = models.ForeignKey(
        "Employe",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="depenses",
        verbose_name="employé lié (type Salaires)",
        help_text="Renseigné pour les dépenses de type « Salaires » afin de créer / lier le paiement de salaire.",
    )
    periode_mois = models.DateField(
        "période (mois) liée",
        null=True,
        blank=True,
        help_text="Mois de paie concerné pour les dépenses de type « Salaires ».",
    )

    class Meta:
        db_table = "depense_societe"
        verbose_name = "dépense de société"
        verbose_name_plural = "dépenses de sociétés"
        ordering = ["-date_depense"]

    def __str__(self):
        return f"{self.nom} — {self.montant} ({self.societe})"


class PaiementSalaire(models.Model):
    """35. Paiements salaires."""

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="paiements_salaire"
    )
    contrat = models.ForeignKey(
        ContratEmploye,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paiements_salaire",
    )
    periode_mois = models.DateField("période (mois)")
    montant_du = models.DecimalField(max_digits=15, decimal_places=2)
    montant_paye = models.DecimalField(max_digits=15, decimal_places=2)
    date_prevue = models.DateField()
    date_paiement = models.DateField(null=True, blank=True)
    mode_paiement = models.ForeignKey(
        ModePaiement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paiements_salaires",
    )
    statut = models.CharField(
        max_length=30, choices=STATUT_SALAIRE_CHOICES, default="PREVU"
    )

    class Meta:
        db_table = "paiement_salaire"
        verbose_name = "paiement de salaire"
        verbose_name_plural = "paiements de salaires"
        ordering = ["-periode_mois"]

    def __str__(self):
        return f"{self.employe} — {self.periode_mois:%m/%Y} ({self.statut})"


# ---------------------------------------------------------------------------
# 36. finance — synthèse financière (matérialisée)
# ---------------------------------------------------------------------------


class Finance(models.Model):
    """36. Synthèse financière (table matérialisée, valeurs recalculables)."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="finances"
    )
    periode = models.DateField()
    total_recettes = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_depenses = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    solde = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        db_table = "finance"
        verbose_name = "synthèse financière"
        verbose_name_plural = "synthèses financières"
        ordering = ["-periode"]
        unique_together = [("societe", "periode")]

    def recalculer(self):
        """Recalcule recettes / dépenses / solde pour la période du mois."""
        debut = self.periode.replace(day=1)
        if self.periode.month == 12:
            fin = self.periode.replace(year=self.periode.year + 1, month=1, day=1)
        else:
            fin = self.periode.replace(month=self.periode.month + 1, day=1)

        recettes = (
            PaiementClient.objects.filter(
                projet__societe=self.societe,
                date_paiement__gte=debut,
                date_paiement__lt=fin,
                statut="CONFIRME",
            ).aggregate(total=models.Sum("montant"))["total"]
            or 0
        )
        depenses_societe = (
            DepenseSociete.objects.filter(
                societe=self.societe,
                date_depense__gte=debut,
                date_depense__lt=fin,
                statut="CONFIRME",
                # Les dépenses générées par un salaire payé sont déjà comptées
                # via « salaires » (montant_paye) : exclues pour éviter un doublon.
                paiement_salaire__isnull=True,
            ).aggregate(total=models.Sum("montant"))["total"]
            or 0
        )
        salaires = (
            PaiementSalaire.objects.filter(
                employe__societe=self.societe,
                date_paiement__gte=debut,
                date_paiement__lt=fin,
            ).aggregate(total=models.Sum("montant_paye"))["total"]
            or 0
        )
        self.total_recettes = recettes
        self.total_depenses = depenses_societe + salaires
        self.solde = self.total_recettes - self.total_depenses
        self.save()

    def __str__(self):
        return f"{self.societe} — {self.periode:%m/%Y} : {self.solde}"


KPAY_TYPE_CHOICES = [
    ("DEPOSIT", "Encaissement"),
    ("PAYOUT", "Retrait"),
]

KPAY_STATUT_CHOICES = [
    ("PENDING", "En attente"),
    ("PROCESSING", "En cours"),
    ("COMPLETED", "Complété"),
    ("FAILED", "Échoué"),
    ("CANCELLED", "Annulé"),
]


class KpayOperation(models.Model):
    """Opération Mobile Money (KPay) : encaissement client ou retrait de salaire.

    Une ligne = une transaction KPay (init_response 201), tracée de l'initiation
    jusqu'au statut terminal. Le statut final est confirmé par le webhook KPay
    (source d'autorité) ou par le polling (bouton « Rafraîchir »).
    """

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="kpay_operations"
    )
    type_operation = models.CharField(max_length=20, choices=KPAY_TYPE_CHOICES)

    # Lien métier (au moins un des trois renseigné selon le type).
    paiement = models.ForeignKey(
        PaiementClient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kpay_operations",
    )
    echeance = models.ForeignKey(
        EcheancePaiement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kpay_operations",
    )
    salaire = models.ForeignKey(
        PaiementSalaire,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kpay_operations",
    )

    # Champs renvoyés par KPay.
    kpay_id = models.CharField(max_length=100, db_index=True)
    reference = models.CharField(max_length=150, blank=True, default="")
    provider_reference = models.CharField(max_length=150, blank=True, default="")
    external_id = models.CharField(max_length=150, db_index=True)
    statut = models.CharField(
        max_length=20, choices=KPAY_STATUT_CHOICES, default="PENDING"
    )
    montant = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    montant_net = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    frais = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    devise = models.CharField(max_length=10, default="XAF")
    provider = models.CharField(max_length=50, blank=True, default="")
    pays = models.CharField(max_length=10, blank=True, default="")
    telephone = models.CharField(max_length=30, blank=True, default="")
    mode = models.CharField(max_length=20, default="USSD")
    is_test = models.BooleanField(default=True)
    message = models.TextField(blank=True, default="")
    motif_echec = models.TextField(blank=True, default="")

    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kpay_operations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "kpay_operation"
        verbose_name = "opération KPay"
        verbose_name_plural = "opérations KPay"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_type_operation_display()} {self.reference or self.kpay_id}"

    @property
    def terminal(self):
        return self.statut in ("COMPLETED", "FAILED", "CANCELLED")


# ---------------------------------------------------------------------------
# 37-38. ia_conversation, ia_message
# ---------------------------------------------------------------------------


class IaConversation(models.Model):
    """37. Conversations IA (persistées, une par utilisateur/société)."""

    societe = models.ForeignKey(
        Societe,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations_ia",
        help_text="Société de la conversation (toujours renseigné par le code).",
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations_ia",
        help_text=(
            "Fiche employé reliée au compte qui a créé la conversation. Vide "
            "pour un créateur/propriétaire sans fiche employé."
        ),
    )
    titre = models.CharField(max_length=200)
    statut = models.CharField(
        max_length=30, choices=STATUT_CONVERSATION_IA_CHOICES, default="ACTIVE"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ia_conversation"
        verbose_name = "conversation IA"
        verbose_name_plural = "conversations IA"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.titre} ({self.employe})"


class IaMessage(models.Model):
    """38. Messages IA."""

    conversation = models.ForeignKey(
        IaConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20, choices=ROLE_IA_MESSAGE_CHOICES)
    contenu = models.TextField()
    # Blocs riches de l'assistant (graphiques, indicateurs, documents) et
    # étapes suivies par l'agent : {"blocs": [...], "etapes": [...]}.
    donnees = models.JSONField("données enrichies", default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ia_message"
        verbose_name = "message IA"
        verbose_name_plural = "messages IA"
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.role}] {self.contenu[:40]}"


# ---------------------------------------------------------------------------
# 39. equipe_message — messagerie interne de la page Employés
# ---------------------------------------------------------------------------


class EquipeGroupe(models.Model):
    """39bis. Groupe de discussion d'équipe : titre + membres (employés).

    Le groupe appartient à la société (isolation) et son créateur est le
    compte administrateur connecté.
    """

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="equipe_groupes"
    )
    titre = models.CharField(max_length=120, verbose_name="titre du groupe")
    description = models.CharField(max_length=255, blank=True, default="")
    logo = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="logo du groupe (chemin privé)",
        help_text="Chemin relatif vers CHAT_MEDIA_ROOT ; servi par la vue protégée.",
    )
    cree_par = models.ForeignKey(
        UserAdmin,
        on_delete=models.CASCADE,
        related_name="equipe_groupes_crees",
        verbose_name="créé par",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "equipe_groupe"
        verbose_name = "groupe d'équipe"
        verbose_name_plural = "groupes d'équipe"
        ordering = ["-created_at"]

    def __str__(self):
        return self.titre


class EquipeGroupeMembre(models.Model):
    """39ter. Appartenance d'un employé à un groupe de discussion."""

    groupe = models.ForeignKey(
        EquipeGroupe, on_delete=models.CASCADE, related_name="membres"
    )
    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="equipe_groupes"
    )
    # Administrateur du groupe : peut le modifier, gérer ses membres et le supprimer
    est_admin = models.BooleanField(default=False)

    class Meta:
        db_table = "equipe_groupe_membre"
        verbose_name = "membre d'un groupe d'équipe"
        verbose_name_plural = "membres d'un groupe d'équipe"
        unique_together = [("groupe", "employe")]

    def __str__(self):
        return f"{self.employe} → {self.groupe}"


class EquipeConversation(models.Model):
    """39quater. Conversation privée entre deux comptes (participants).

    Une conversation privée n'est lisible que par ses participants : elle
    remplace l'ancien « fil par employé » qui laissait le propriétaire lire
    tous les échanges de la société.
    """

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="equipe_conversations"
    )
    participants = models.ManyToManyField(
        UserAdmin,
        related_name="equipe_conversations",
        verbose_name="participants",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "equipe_conversation"
        verbose_name = "conversation privée"
        verbose_name_plural = "conversations privées"
        ordering = ["-created_at"]

    def __str__(self):
        noms = [
            (f"{u.prenom} {u.nom}".strip() or u.email)
            for u in self.participants.all()
        ]
        return " ↔ ".join(noms) if noms else f"Conversation #{self.pk}"


class EquipeMessage(models.Model):
    """39. Messagerie d'équipe : échange de messages.

    Chaque message appartient à la société (isolation) et est relié soit à une
    conversation privée (``conversation``, exactement deux participants), soit
    à un groupe de discussion (``groupe``), et à son auteur.
    """

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="equipe_messages"
    )
    conversation = models.ForeignKey(
        EquipeConversation,
        on_delete=models.CASCADE,
        related_name="messages",
        null=True,
        blank=True,
        verbose_name="conversation privée",
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        related_name="equipe_messages",
        null=True,
        blank=True,
        verbose_name="employé (fil individuel)",
    )
    groupe = models.ForeignKey(
        EquipeGroupe,
        on_delete=models.CASCADE,
        related_name="messages",
        null=True,
        blank=True,
        verbose_name="groupe (fil de groupe)",
    )
    auteur = models.ForeignKey(
        UserAdmin,
        on_delete=models.CASCADE,
        related_name="equipe_messages",
        verbose_name="auteur",
    )
    contenu = models.TextField(verbose_name="message", blank=True)
    fichier = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="fichier (chemin privé)",
        help_text="Chemin relatif vers CHAT_MEDIA_ROOT ; jamais servi via MEDIA_URL.",
    )
    fichier_nom = models.CharField(
        max_length=150, blank=True, default="", verbose_name="nom original du fichier"
    )
    fichier_type = models.CharField(
        max_length=100, blank=True, default="", verbose_name="type MIME du fichier"
    )
    lu = models.BooleanField(
        default=False,
        verbose_name="lu par le destinataire",
        help_text="Repasse à vrai quand le destinataire consulte le fil.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "equipe_message"
        verbose_name = "message d'équipe"
        verbose_name_plural = "messages d'équipe"
        ordering = ["created_at"]

    def __str__(self):
        cible = self.groupe.titre if self.groupe_id else str(self.employe)
        return f"{self.auteur} → {cible} : {self.contenu[:40]}"


# ---------------------------------------------------------------------------
# 39. activite_plateforme (journal des actions)
# ---------------------------------------------------------------------------


class ActivitePlateforme(models.Model):
    """39. Journal des actions effectuées sur la plateforme.

    Une ligne par action notable (création, modification, suppression,
    paiement, message, connexion…), rattachée à la société et à l'auteur.
    Alimente la boîte de notifications du tableau de bord.
    """

    ACTION_CHOICES = [
        ("CREATION", "Création"),
        ("MODIFICATION", "Modification"),
        ("SUPPRESSION", "Suppression"),
        ("PAIEMENT", "Paiement"),
        ("VALIDATION", "Validation"),
        ("MESSAGE", "Message"),
        ("CONNEXION", "Connexion"),
        ("CONFIGURATION", "Configuration"),
    ]

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="activites"
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activites",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    module = models.CharField(max_length=40)
    libelle = models.CharField(max_length=200, blank=True, default="")
    detail = models.TextField(blank=True, default="")
    lue = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "activite_plateforme"
        verbose_name = "activité de plateforme"
        verbose_name_plural = "activités de plateforme"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["societe", "-created_at"])]

    def __str__(self):
        return f"{self.get_action_display()} · {self.module} — {self.libelle}"


class Rappel(models.Model):
    """Rappel / échéance suivi pour le centre d'échéances et la cloche.

    Une ligne par « échéance » : paiement projet, tâche avec date limite,
    paie prévue, contrat, projet, objectif, document… Le registre est
    resynchronisé depuis les données réelles (``assurer_echeances_registre``),
    ce qui garantit l'unicité (une ligne par élément) et l'actualité (date,
    statut et jalon recalculés). ``jalon`` décrit la proximité (J30, J7, J3,
    J1, J0, RETARD) et pilote la priorité affichée.
    """

    JALON_CHOICES = [
        ("", "Hors rappel"),
        ("J30", "30 jours"),
        ("J7", "7 jours"),
        ("J3", "3 jours"),
        ("J1", "Veille"),
        ("J0", "Jour J"),
        ("RETARD", "En retard"),
    ]
    PRIORITE_CHOICES = [
        ("", "—"),
        ("basse", "Basse"),
        ("moyenne", "Moyenne"),
        ("haute", "Haute"),
        ("urgente", "Urgente"),
        ("critique", "Critique"),
    ]

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="rappels"
    )
    module = models.CharField(max_length=40)
    cible = models.CharField(max_length=60)
    libelle = models.CharField(max_length=200, blank=True, default="")
    element = models.CharField(max_length=200, blank=True, default="")
    montant = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    date_prevue = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=30, blank=True, default="")
    jalon = models.CharField(
        max_length=20, choices=JALON_CHOICES, blank=True, default=""
    )
    priorite = models.CharField(
        max_length=20, choices=PRIORITE_CHOICES, blank=True, default=""
    )
    lue = models.BooleanField(default=False)
    masque = models.BooleanField(
        "masqué (supprimé par l'utilisateur)", default=False
    )
    lien = models.CharField(max_length=200, blank=True, default="")
    genre_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rappel"
        verbose_name = "rappel / échéance suivie"
        verbose_name_plural = "rappels / échéances suivies"
        ordering = ["date_prevue"]
        unique_together = [("societe", "module", "cible")]
        indexes = [models.Index(fields=["societe", "module", "lue"])]

    def __str__(self):
        return f"{self.libelle} — {self.date_prevue or 'sans date'} ({self.jalon or '—'})"


# ---------------------------------------------------------------------------
# 40. connecteurs externes (hub d'intégrations, multi-tenant)
# ---------------------------------------------------------------------------


class Connecteur(models.Model):
    """40. Connexion d'une société à un service externe (Gmail, Slack…).

    Isolation multi-tenant : un connecteur appartient à *une* société et n'est
    jamais visible ni utilisable par une autre. Les identifiants (jetons OAuth,
    clés d'API) sont stockés chiffrés dans ``identifiants_chiffres`` via
    ``gestion.crypto`` et ne sont jamais exposés dans les templates ou l'API.
    """

    STATUT_CHOICES = [
        ("NON_CONNECTE", "Non connecté"),
        ("CONNECTE", "Connecté"),
        ("ERREUR", "Erreur"),
    ]

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="connecteurs"
    )
    type_connecteur = models.CharField(max_length=60, verbose_name="type de connecteur")
    nom = models.CharField(max_length=120, blank=True, default="")
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default="NON_CONNECTE"
    )
    auth_mode = models.CharField(max_length=20, blank=True, default="token")
    identifiants_chiffres = models.TextField(
        blank=True,
        default="",
        verbose_name="identifiants chiffrés",
        help_text="Blob chiffré (Fernet) des jetons/clés ; jamais en clair.",
    )
    configuration = models.JSONField(
        default=dict, blank=True, verbose_name="configuration non secrète"
    )
    scopes = models.CharField(max_length=300, blank=True, default="")
    compte_externe = models.CharField(max_length=200, blank=True, default="")
    webhook_secret = models.CharField(max_length=64, blank=True, default="")
    sync_actif = models.BooleanField(default=True)
    derniere_sync = models.DateTimeField(null=True, blank=True)
    derniere_erreur = models.TextField(blank=True, default="")
    cree_par = models.ForeignKey(
        UserAdmin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="connecteurs_crees",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "connecteur"
        verbose_name = "connecteur"
        verbose_name_plural = "connecteurs"
        ordering = ["type_connecteur", "-cree_le"]
        indexes = [models.Index(fields=["societe", "type_connecteur"])]

    def __str__(self):
        return self.nom or self.type_connecteur

    # -- Identifiants (jamais exposés en clair) ----------------------------
    def jetons(self):
        """Déchiffre les identifiants pour un usage serveur uniquement."""
        from .crypto import dechiffrer

        return dechiffrer(self.identifiants_chiffres)

    def definir_jetons(self, donnees):
        from .crypto import chiffrer

        self.identifiants_chiffres = chiffrer(donnees or {})

    def identifiants_masques(self):
        """Noms des champs renseignés, sans aucune valeur (pour l'UI)."""
        return sorted(self.jetons().keys())

    @property
    def classe(self):
        """Classe de connecteur enregistrée, ou classe dynamique si personnalisé."""
        from .connecteurs import get_connecteur_class

        enregistree = get_connecteur_class(self.type_connecteur)
        if enregistree is not None:
            return enregistree
        if (self.configuration or {}).get("personnalise"):
            from .connecteurs.personnalise import classe_personnalisee

            return classe_personnalisee(self)
        return None

    @property
    def est_personnalise(self):
        return bool((self.configuration or {}).get("personnalise"))

    @property
    def est_connecte(self):
        return self.statut == "CONNECTE"


class ConnecteurEvenement(models.Model):
    """41. Événement de webhook reçu pour un connecteur (journal d'entrée)."""

    connecteur = models.ForeignKey(
        Connecteur, on_delete=models.CASCADE, related_name="evenements"
    )
    evenement = models.CharField(max_length=120, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    entetes = models.JSONField(default=dict, blank=True)
    signature_valide = models.BooleanField(default=False)
    traite = models.BooleanField(default=False)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "connecteur_evenement"
        verbose_name = "événement de connecteur"
        verbose_name_plural = "événements de connecteur"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.connecteur} · {self.evenement or 'événement'}"


class ConnecteurSyncLog(models.Model):
    """42. Trace d'une synchronisation (succès ou erreur) d'un connecteur."""

    STATUT_CHOICES = [("OK", "Succès"), ("ERREUR", "Erreur")]

    connecteur = models.ForeignKey(
        Connecteur, on_delete=models.CASCADE, related_name="sync_logs"
    )
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES)
    message = models.TextField(blank=True, default="")
    elements = models.IntegerField(default=0)
    duree_ms = models.IntegerField(default=0)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "connecteur_sync_log"
        verbose_name = "journal de synchronisation"
        verbose_name_plural = "journaux de synchronisation"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.connecteur} · {self.statut}"


STATUT_TACHE_CHOICES = [
    ("A_FAIRE", "À faire"),
    ("EN_COURS", "En cours"),
    ("TERMINEE", "Terminée"),
    ("ANNULEE", "Annulée"),
]

PRIORITE_TACHE_CHOICES = [
    ("FAIBLE", "Faible"),
    ("MOYENNE", "Moyenne"),
    ("HAUTE", "Haute"),
]


class Tache(models.Model):
    """43. Tâche attribuée à un employé par l'administrateur.

    L'« onglet Tâches » permet au propriétaire d'assigner du travail et de
    suivre son évolution (statut + progression) ; un employé ne voit que ses
    propres tâches et peut en faire avancer le statut et la progression.
    """

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="taches"
    )
    titre = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    assignee = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        related_name="taches",
        verbose_name="employé attributaire",
    )
    cree_par = models.ForeignKey(
        UserAdmin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="taches_crees",
        verbose_name="créée par",
    )
    projet = models.ForeignKey(
        ProjetClient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="taches",
        verbose_name="projet lié",
        help_text="Projet du client auquel cette tâche contribue (suivi client).",
    )
    priorite = models.CharField(
        max_length=20,
        choices=PRIORITE_TACHE_CHOICES,
        default="MOYENNE",
        verbose_name="priorité",
    )
    statut = models.CharField(
        max_length=20,
        choices=STATUT_TACHE_CHOICES,
        default="A_FAIRE",
    )
    progres = models.PositiveSmallIntegerField(
        "avancement (%)", default=0, validators=[MaxValueValidator(100)]
    )
    echeance = models.DateField(null=True, blank=True, verbose_name="échéance")
    date_debut = models.DateField(
        null=True, blank=True, verbose_name="début effectif du travail"
    )
    date_terminee = models.DateTimeField(
        null=True, blank=True, verbose_name="terminée le"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tache"
        verbose_name = "tâche"
        verbose_name_plural = "tâches"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.titre} → {self.assignee.prenom} {self.assignee.nom}"

    def changer_statut(self, nouveau_statut, auteur=None):
        """Passe la tâche à un nouveau statut en journalisant l'évolution."""
        ancien = self.statut
        if ancien == nouveau_statut:
            return False
        self.statut = nouveau_statut
        if nouveau_statut == "EN_COURS" and self.date_debut is None:
            self.date_debut = timezone.localdate()
        if nouveau_statut == "TERMINEE":
            self.date_terminee = timezone.now()
        if nouveau_statut == "A_FAIRE" and self.date_terminee:
            self.date_terminee = None
        progres_avant = self.progres
        # Tâche rouverte : l'avancement ne peut pas rester à 100 % (incohérent avec le statut)
        if ancien == "TERMINEE" and nouveau_statut in ("A_FAIRE", "EN_COURS"):
            self.progres = 0 if nouveau_statut == "A_FAIRE" else min(self.progres, 90)
            self.date_terminee = None
        self.save(update_fields=["statut", "date_debut", "date_terminee", "progres"])
        TacheEvolution.objects.create(
            tache=self,
            auteur=auteur,
            statut_avant=ancien,
            statut_apres=nouveau_statut,
            progres_avant=progres_avant,
            progres_apres=self.progres,
        )
        return True

    def changer_progres(self, valeur, auteur=None):
        """Met à jour l'avancement (%) et déduit le statut si nécessaire."""
        valeur = max(0, min(100, int(valeur or 0)))
        avant = self.progres
        if valeur == avant:
            return False
        self.progres = valeur
        if valeur >= 100 and self.statut != "TERMINEE":
            self.statut = "TERMINEE"
            self.date_terminee = timezone.now()
            self.save(
                update_fields=[
                    "progres",
                    "statut",
                    "date_terminee",
                ]
            )
            TacheEvolution.objects.create(
                tache=self,
                auteur=auteur,
                statut_avant=avant and "EN_COURS" or self.statut,
                statut_apres="TERMINEE",
                progres_avant=avant,
                progres_apres=valeur,
            )
            return True
        self.save(update_fields=["progres"])
        TacheEvolution.objects.create(
            tache=self,
            auteur=auteur,
            progres_avant=avant,
            progres_apres=valeur,
        )
        return True

    def recalculer_progres(self, auteur=None):
        """Avancement automatique à partir des objectifs de la tâche.

        Chaque objectif défini par l'administrateur a le même poids
        (ex. 2 objectifs → 50 % + 50 %). L'avancement suit donc la règle
        « des priorités à atteindre » : cocher un objectif fait évoluer
        la tâche sans aucune saisie manuelle du pourcentage.
        """
        objectifs = list(self.objectifs.all())
        total = len(objectifs)
        nouveau = 0
        if total:
            nb_atteints = sum(1 for o in objectifs if o.termine)
            nouveau = round(100 * nb_atteints / total)
        avant = self.progres
        ancien_statut = self.statut

        if nouveau != avant or (
            nouveau >= 100 and self.statut != "TERMINEE"
        ) or (self.statut == "TERMINEE" and nouveau < 100):
            self.progres = nouveau
            if nouveau >= 100 and self.statut != "TERMINEE":
                self.statut = "TERMINEE"
                self.date_terminee = timezone.now()
            elif self.statut == "TERMINEE" and nouveau < 100:
                self.statut = "EN_COURS"
                self.date_terminee = None
            elif nouveau > 0 and self.statut == "A_FAIRE":
                self.statut = "EN_COURS"
                if self.date_debut is None:
                    self.date_debut = timezone.localdate()
            self.save(
                update_fields=["progres", "statut", "date_debut", "date_terminee"]
            )
            if self.statut != ancien_statut:
                TacheEvolution.objects.create(
                    tache=self,
                    auteur=auteur,
                    statut_avant=ancien_statut,
                    statut_apres=self.statut,
                    progres_avant=avant,
                    progres_apres=nouveau,
                )
            else:
                TacheEvolution.objects.create(
                    tache=self,
                    auteur=auteur,
                    progres_avant=avant,
                    progres_apres=nouveau,
                )
            return True
        return False


class TacheObjectif(models.Model):
    """43ter. Objectif (priorité) à atteindre dans une tâche.

    Les objectifs sont définis par l'administrateur à l'attribution de la
    tâche. L'avancement de la tâche est calculé automatiquement : chaque
    objectif a le même poids (ex. 2 objectifs → 50 % + 50 %). Cocher un
    objectif comme atteint fait évoluer l'avancement, sans % manuel.
    """

    tache = models.ForeignKey(
        Tache, on_delete=models.CASCADE, related_name="objectifs"
    )
    libelle = models.CharField(max_length=255, verbose_name="objectif")
    ordre = models.PositiveSmallIntegerField(default=0, verbose_name="ordre")
    termine = models.BooleanField(
        default=False, verbose_name="atteint"
    )
    date_termine = models.DateTimeField(
        null=True, blank=True, verbose_name="atteint le"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tache_objectif"
        verbose_name = "objectif de tâche"
        verbose_name_plural = "objectifs de tâches"
        ordering = ["ordre", "pk"]

    def __str__(self):
        return self.libelle

    @property
    def poids(self):
        total = self.tache.objectifs.count()
        return round(100 / total) if total else 0


class TacheEvolution(models.Model):
    """43bis. Évolution d'une tâche (ligne de temps de suivi du travail)."""

    tache = models.ForeignKey(
        Tache, on_delete=models.CASCADE, related_name="evolutions"
    )
    auteur = models.ForeignKey(
        UserAdmin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tache_evolutions",
        verbose_name="par",
    )
    statut_avant = models.CharField(
        max_length=20, choices=STATUT_TACHE_CHOICES, blank=True, default=""
    )
    statut_apres = models.CharField(
        max_length=20, choices=STATUT_TACHE_CHOICES, blank=True, default=""
    )
    progres_avant = models.PositiveSmallIntegerField(null=True, blank=True)
    progres_apres = models.PositiveSmallIntegerField(null=True, blank=True)
    commentaire = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tache_evolution"
        verbose_name = "évolution de tâche"
        verbose_name_plural = "évolutions de tâche"
        ordering = ["-created_at"]

    def __str__(self):
        if self.statut_apres:
            return f"{self.tache} — {self.get_statut_avant_display()} → {self.get_statut_apres_display()}"
        return f"{self.tache} — {self.progres_avant}% → {self.progres_apres}%"


STATUT_LIVRABLE_CHOICES = [
    ("SOUMIS", "Soumis"),
    ("VALIDE", "Validé"),
    ("CORRIGER", "Correction demandée"),
]


class TacheLivrable(models.Model):
    """43ter. Fichier livrable déposé par l'employé sur une tâche.

    L'employé attributaire dépose un fichier (PDF, Excel...) et le soumet pour
    validation ; le propriétaire de la société valide ou demande une correction.
    Chaque dépôt crée une nouvelle ligne (l'historique est conservé) et une
    ``TacheEvolution`` documente chaque étape. Les fichiers vivent hors de
    MEDIA_ROOT (``TACHE_MEDIA_ROOT``) et ne sont téléchargés que via la vue
    protégée ``gestion:tache_livrable_fichier``.
    """

    tache = models.ForeignKey(
        Tache, on_delete=models.CASCADE, related_name="livrables"
    )
    employe = models.ForeignKey(
        Employe,
        on_delete=models.CASCADE,
        related_name="livrables",
        verbose_name="déposé par",
    )
    fichier = models.CharField(max_length=500)
    nom_fichier = models.CharField(max_length=150)
    type_fichier = models.CharField(max_length=100, blank=True, default="")
    statut = models.CharField(
        max_length=20, choices=STATUT_LIVRABLE_CHOICES, default="SOUMIS"
    )
    message = models.TextField(blank=True, default="")
    commentaire_admin = models.TextField(blank=True, default="")
    repondu_par = models.ForeignKey(
        UserAdmin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="livrables_traites",
    )
    date_depot = models.DateTimeField(auto_now_add=True)
    date_reponse = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tache_livrable"
        verbose_name = "livrable de tâche"
        verbose_name_plural = "livrables de tâche"
        ordering = ["-date_depot"]

    def __str__(self):
        return f"{self.tache} — {self.nom_fichier} ({self.get_statut_display()})"


class EmployePresence(models.Model):
    """44. Session d'activité d'un employé sur la plateforme.

    Traçage de présence : heure de connexion, heure de déconnexion et durée
    passée dans la plateforme (extrait des heures de connexion / déconnexion),
    alimentés par les signaux de connexion et de déconnexion et « pingés » par
    l'application pour couvrir les sessions abandonnées.
    """

    employe = models.ForeignKey(
        Employe, on_delete=models.CASCADE, related_name="presences"
    )
    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="presences"
    )
    session_key = models.CharField(max_length=64, blank=True, default="")
    date_connexion = models.DateTimeField()
    date_deconnexion = models.DateTimeField(null=True, blank=True)
    derniere_activite = models.DateTimeField(null=True, blank=True)
    duree_secondes = models.IntegerField(default=0)
    ip = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "employe_presence"
        verbose_name = "présence employé"
        verbose_name_plural = "présences employés"
        ordering = ["-date_connexion"]
        indexes = [
            models.Index(fields=["societe", "employe", "-date_connexion"]),
        ]

    def __str__(self):
        return f"{self.employe} — {self.date_connexion:%d/%m %H:%M}"

    def finaliser(self, deconnexion=None):
        """Clôt la session et calcule la durée passée dans la plateforme."""
        if self.date_deconnexion is not None:
            return
        fin = deconnexion or self.derniere_activite or self.date_connexion
        self.date_deconnexion = fin
        self.duree_secondes = max(
            0, int((fin - self.date_connexion).total_seconds())
        )
        self.save(update_fields=["date_deconnexion", "duree_secondes"])

    @property
    def en_cours(self):
        return self.date_deconnexion is None


class PointGeo(models.Model):
    """42. Point géographique alimentant le globe 3D.

    Source générique : n'importe quel connecteur (Shopify, WooCommerce, CRM…)
    ou module interne (clients, paiements…) pousse des points via
    ``gestion/globe.py``. Le globe 3D n'affiche que des agrégats (pays → région
    → ville) ; aucun libellé privé n'y transite.
    """

    MESURE_CHOICES = [
        ("client", "Client"),
        ("commande", "Commande / commande"),
        ("ca", "Chiffre d'affaires"),
        ("prospect", "Prospect"),
        ("publication", "Publication"),
        ("engagement", "Engagement"),
        ("abonne", "Abonné"),
    ]

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="points_geo"
    )
    source = models.CharField(max_length=120, default="app:autre")
    connecteur = models.ForeignKey(
        Connecteur,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="points_geo",
    )
    mesure = models.CharField(max_length=20, choices=MESURE_CHOICES, default="client")
    pays = models.CharField(max_length=120, blank=True, default="")
    region = models.CharField(max_length=120, blank=True, default="")
    ville = models.CharField(max_length=120, blank=True, default="")
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    valeur = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    date_evenement = models.DateField(null=True, blank=True)
    metadonnees = models.JSONField(default=dict, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "point_geo"
        verbose_name = "point géographique"
        verbose_name_plural = "points géographiques"
        indexes = [
            models.Index(fields=["societe", "source"]),
            models.Index(fields=["societe", "pays"]),
            models.Index(fields=["societe", "mesure"]),
        ]

    def __str__(self):
        return f"{self.mesure} · {self.pays} · {self.ville} ({self.societe})"


class EvenementGoogle(models.Model):
    """Lien entre un objet (échéance, tâche) et son événement Google Agenda."""

    societe = models.ForeignKey(
        Societe, on_delete=models.CASCADE, related_name="evenements_google"
    )
    objet_type = models.CharField(max_length=20)
    objet_id = models.PositiveIntegerField()
    evenement_id = models.CharField(max_length=200)
    maj_le = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "evenement_google"
        verbose_name = "événement Google Agenda"
        verbose_name_plural = "événements Google Agenda"
        constraints = [
            models.UniqueConstraint(
                fields=["societe", "objet_type", "objet_id"], name="unique_evenement_google"
            )
        ]

    def __str__(self):
        return f"{self.objet_type} #{self.objet_id} → {self.evenement_id}"


# ---------------------------------------------------------------------------
# Facturation clients (espace Finances)
# ---------------------------------------------------------------------------

STATUT_FACTURE_CHOICES = [
    ("BROUILLON", "Brouillon"),
    ("EMISE", "Émise"),
    ("PAYEE", "Payée"),
    ("ANNULEE", "Annulée"),
]


class Facture(models.Model):
    """Facture client : en-tête + lignes (``LigneFacture``), totaux recalculés.

    Numérotation par société et par année : FAC-2026-0001. Une facture payée
    liée à un projet est enregistrée dans Paiements (recette) ; liée à une
    échéance, elle solde aussi l'échéance.
    """

    societe = models.ForeignKey(Societe, on_delete=models.CASCADE, related_name="factures")
    numero = models.CharField("numéro", max_length=30)
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures"
    )
    client_nom = models.CharField("client (copie)", max_length=200, blank=True, default="")
    projet = models.ForeignKey(
        ProjetClient, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures"
    )
    echeance = models.ForeignKey(
        EcheancePaiement, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures"
    )
    objet = models.CharField(max_length=255, blank=True, default="")
    date_emission = models.DateField("date d'émission", default=timezone.localdate)
    date_echeance = models.DateField("date d'échéance", null=True, blank=True)
    statut = models.CharField(max_length=20, choices=STATUT_FACTURE_CHOICES, default="BROUILLON")
    taux_tva = models.DecimalField("TVA (%)", max_digits=5, decimal_places=2, default=0)
    remise = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_ht = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_tva = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_ttc = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    notes = models.TextField(blank=True, default="")
    conditions = models.TextField("conditions de paiement", blank=True, default="")
    date_paiement = models.DateField(null=True, blank=True)
    paiement = models.ForeignKey(
        "PaiementClient", on_delete=models.SET_NULL, null=True, blank=True, related_name="factures"
    )
    cree_par = models.ForeignKey(
        UserAdmin, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures_creees"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_emission", "-id"]
        unique_together = [("societe", "numero")]
        verbose_name = "facture"

    def __str__(self):
        return f"{self.numero} — {self.client_nom or self.client}"

    def recalculer(self, enregistrer=True):
        from decimal import Decimal, ROUND_HALF_UP

        ht = sum((l.montant for l in self.lignes.all()), Decimal("0"))
        ht = max(ht - (self.remise or Decimal("0")), Decimal("0"))
        tva = (ht * (self.taux_tva or Decimal("0")) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        self.total_ht, self.total_tva, self.total_ttc = ht, tva, ht + tva
        if enregistrer:
            self.save(update_fields=["total_ht", "total_tva", "total_ttc", "updated_at"])

    @property
    def en_retard(self):
        return (
            self.statut == "EMISE" and self.date_echeance is not None
            and self.date_echeance < timezone.localdate()
        )


class LigneFacture(models.Model):
    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name="lignes")
    designation = models.CharField("désignation", max_length=255)
    quantite = models.DecimalField("quantité", max_digits=12, decimal_places=2, default=1)
    prix_unitaire = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["ordre", "id"]

    @property
    def montant(self):
        return (self.quantite or 0) * (self.prix_unitaire or 0)


# ---------------------------------------------------------------------------
# Applications bureautiques intégrées : Tableur, Documents, Présentations
# ---------------------------------------------------------------------------

TYPE_FICHIER_BUREAU_CHOICES = [
    ("SHEET", "Tableur"),
    ("DOC", "Document"),
    ("SLIDES", "Présentation"),
]


class FichierBureau(models.Model):
    """Fichier créé dans les applications intégrées (contenu JSON propre à chaque type).

    - SHEET  : {"cells": {"A1": {"v": "=SUM(B1:B3)", "b": 1, "al": "c", "fmt": "money"}}, "nrows", "ncols", "cols"}
    - DOC    : {"html": "<h1>…</h1><p>…</p>"}  (HTML nettoyé côté serveur)
    - SLIDES : {"theme": "accent", "slides": [{"layout": "titre", "titre": "…", "texte": "…"}]}
    """

    societe = models.ForeignKey(Societe, on_delete=models.CASCADE, related_name="fichiers_bureau")
    type_fichier = models.CharField(max_length=10, choices=TYPE_FICHIER_BUREAU_CHOICES)
    titre = models.CharField(max_length=200, default="Sans titre")
    contenu = models.JSONField(default=dict, blank=True)
    apercu = models.CharField(max_length=300, blank=True, default="")
    favori = models.BooleanField(default=False)
    prive = models.BooleanField(
        "privé", default=False,
        help_text="Privé : visible seulement par son créateur, les partenaires et l'administration.",
    )
    partenaires = models.ManyToManyField(
        "Employe", blank=True, related_name="fichiers_partages",
        help_text="Employés invités à modifier ce fichier.",
    )
    version = models.PositiveIntegerField(default=1)
    cree_par = models.ForeignKey(
        UserAdmin, on_delete=models.SET_NULL, null=True, blank=True, related_name="fichiers_bureau"
    )
    modifie_par = models.ForeignKey(
        UserAdmin, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "fichier bureautique"
        verbose_name_plural = "fichiers bureautiques"

    def __str__(self):
        return f"{self.get_type_fichier_display()} — {self.titre}"


# ---------------------------------------------------------------------------
# Planning : agenda des rendez-vous (chaque employé a le sien)
# ---------------------------------------------------------------------------

TYPE_EVENEMENT_CHOICES = [
    ("RDV", "Rendez-vous"),
    ("REUNION", "Réunion"),
    ("APPEL", "Appel"),
    ("VISITE", "Visite client"),
    ("FORMATION", "Formation"),
    ("CONGE", "Absence / congé"),
    ("AUTRE", "Autre"),
]


class EvenementAgenda(models.Model):
    """Événement du planning : visible par son organisateur et ses participants (et l'administration)."""

    societe = models.ForeignKey(Societe, on_delete=models.CASCADE, related_name="evenements_agenda")
    titre = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    lieu = models.CharField(max_length=255, blank=True, default="")
    type_evenement = models.CharField(max_length=20, choices=TYPE_EVENEMENT_CHOICES, default="RDV")
    couleur = models.CharField(max_length=9, blank=True, default="")
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    journee_entiere = models.BooleanField(default=False)
    organisateur = models.ForeignKey(
        UserAdmin, on_delete=models.SET_NULL, null=True, blank=True, related_name="evenements_organises"
    )
    participants = models.ManyToManyField("Employe", blank=True, related_name="evenements_agenda")
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="evenements_agenda"
    )
    rappel_minutes = models.PositiveIntegerField(null=True, blank=True)
    image = models.ImageField(upload_to="planning/", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["debut"]
        verbose_name = "événement du planning"
        verbose_name_plural = "événements du planning"

    def __str__(self):
        return f"{self.titre} ({self.debut:%d/%m/%Y %H:%M})"


class ModeleContrat(models.Model):
    """Modèle de contrat de travail propre à la société, avec variables dynamiques.

    Le texte contient des variables ``{{ nom_variable }}`` remplacées à l'impression
    (voir ``contrat_pdf.VARIABLES``). Une ligne commençant par « # » devient un titre
    d'article. Un modèle peut viser un type de contrat (CDI, CDD…) ; sinon il sert
    de modèle par défaut.
    """

    societe = models.ForeignKey(Societe, on_delete=models.CASCADE, related_name="modeles_contrat")
    nom = models.CharField(max_length=150)
    type_contrat = models.ForeignKey(
        TypeContrat, on_delete=models.SET_NULL, null=True, blank=True, related_name="modeles",
        help_text="Vide : modèle utilisé pour tous les types sans modèle dédié.",
    )
    contenu = models.TextField()
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "modèle de contrat"
        verbose_name_plural = "modèles de contrat"

    def __str__(self):
        return self.nom


# ---------------------------------------------------------------------------
# Vitrine : images modifiables et avis clients
# ---------------------------------------------------------------------------

IMAGES_VITRINE = (
    ("hero_fond", "Fond du bandeau d'accueil"),
    ("macbook", "Cadre MacBook des captures"),
    ("dashboard", "Capture — tableau de bord"),
    ("collaboration", "Capture — collaboration"),
    ("finances", "Capture — finances"),
    ("planning", "Capture — planning"),
    ("bureau", "Capture — bureautique"),
    ("assistant_ia", "Capture — assistant IA"),
    ("logo_header", "Logo dans l'en-tête"),
    ("logo_footer", "Logo dans le pied de page"),
    ("logo_app", "Logo de l'application (connexion, favicon)"),
    ("favicon", "Favicon du site"),
    ("og_image", "Image de partage (WhatsApp, réseaux sociaux)"),
)

IMAGES_VITRINE_DEFAUT = {
    "hero_fond": "vitrine/hero-login-bg.jpg",
    "macbook": "vitrine/macbook-air-m5-transparent.png",
    "dashboard": "vitrine/captures/dashboard.png",
    "collaboration": "vitrine/captures/collaboration.png",
    "finances": "vitrine/captures/finances.png",
    "planning": "vitrine/captures/planning.png",
    "bureau": "vitrine/captures/bureau.png",
    "assistant_ia": "vitrine/captures/assistant_ia.png",
    "logo_header": "",
    "logo_footer": "",
    "logo_app": "",
    "favicon": "vitrine/favicon.svg",
    "og_image": "vitrine/og/og-image.png",
}


class ImageSite(models.Model):
    """Image de la vitrine remplaçable depuis l'administration."""

    code = models.CharField(max_length=40, choices=IMAGES_VITRINE, unique=True)
    titre = models.CharField(max_length=120, blank=True)
    image = models.ImageField(upload_to="vitrine/", blank=True)
    alt = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "image_site"
        verbose_name = "image du site"
        verbose_name_plural = "images du site"
        ordering = ["code"]

    def __str__(self):
        return self.get_code_display() or self.code


class Avis(models.Model):
    """Témoignage client affiché sur la page d'accueil publique."""

    NOTE_CHOICES = [(i, f"{i} étoile{'s' if i > 1 else ''}") for i in range(1, 6)]

    nom = models.CharField(max_length=120)
    fonction = models.CharField(max_length=120, blank=True)
    societe = models.CharField(max_length=120, blank=True)
    message = models.TextField()
    note = models.PositiveSmallIntegerField(choices=NOTE_CHOICES, default=5)
    photo = models.ImageField(upload_to="vitrine/avis/", blank=True)
    actif = models.BooleanField(default=True)
    ordre = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "avis"
        verbose_name = "avis client"
        verbose_name_plural = "avis clients"
        ordering = ["ordre", "-created_at", "pk"]

    def __str__(self):
        return f"{self.nom} — {self.note}/5"
