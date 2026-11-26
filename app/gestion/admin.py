"""Interface d'administration Django pour le Gestionnaire de société."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import (
    AbonnementSociete,
    Client,
    ClientDocument,
    ContratEmploye,
    ConversationGroupe,
    DepenseSociete,
    EcheancePaiement,
    Employe,
    EmployeLangue,
    Finance,
    Fonction,
    Forfait,
    ForfaitPermission,
    GroupeProjet,
    GroupeProjetMembre,
    IaConversation,
    IaMessage,
    KpayOperation,
    Langue,
    MessageGroupe,
    ModePaiement,
    PaiementAbonnement,
    PaiementClient,
    PaiementSalaire,
    Permission,
    PermissionSociete,
    ProjetChef,
    ProjetClient,
    ProjetObjectif,
    Role,
    RolePermission,
    Societe,
    SocieteDocument,
    TypeClient,
    TypeContrat,
    TypeDepense,
    TypeSociete,
    UserAdmin,
    UserAdminLangue,
)


@admin.register(UserAdmin)
class UserAdminAdmin(BaseUserAdmin, ModelAdmin):
    """Admin dédié au modèle utilisateur personnalisé (email), thème Unfold."""

    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    ordering = ("email",)
    list_display = (
        "email",
        "nom",
        "prenom",
        "role_admin",
        "statut",
        "is_staff",
        "is_active",
    )
    list_filter = ("role_admin", "statut", "is_staff", "is_active")
    search_fields = ("email", "nom", "prenom", "telephone_1")
    fieldsets = (
        ("Identité", {"fields": ("email", "password")}),
        (
            "Informations personnelles",
            {
                "fields": (
                    "nom",
                    "prenom",
                    "date_naissance",
                    "lieu_naissance",
                    "nationalite",
                    "photo_profil",
                    "telephone_1",
                    "telephone_2",
                    "numero_piece_identite",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "role_admin",
                    "statut",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "nom", "prenom", "telephone_1", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("last_login", "created_at", "updated_at")


@admin.register(Langue)
class LangueAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "actif")
    search_fields = ("code", "nom")


class UserAdminLangueInline(admin.TabularInline):
    model = UserAdminLangue
    extra = 0


class EmployeLangueInline(admin.TabularInline):
    model = EmployeLangue
    extra = 0


@admin.register(TypeSociete)
class TypeSocieteAdmin(admin.ModelAdmin):
    list_display = ("nom", "description")
    search_fields = ("nom",)


class SocieteDocumentInline(admin.TabularInline):
    model = SocieteDocument
    extra = 0


class RoleInline(admin.TabularInline):
    model = Role
    extra = 0


class FonctionInline(admin.TabularInline):
    model = Fonction
    extra = 0


class AbonnementSocieteInline(admin.TabularInline):
    model = AbonnementSociete
    extra = 0


@admin.register(Societe)
class SocieteAdmin(admin.ModelAdmin):
    list_display = ("nom", "pays", "type_societe", "createur", "statut", "created_at")
    list_filter = ("statut", "type_societe", "pays")
    search_fields = ("nom", "slogan", "pays")
    readonly_fields = ("created_at", "updated_at")
    inlines = [SocieteDocumentInline, RoleInline, FonctionInline, AbonnementSocieteInline]


@admin.register(SocieteDocument)
class SocieteDocumentAdmin(admin.ModelAdmin):
    list_display = ("societe", "type_document", "numero_document", "date_emission", "date_expiration")
    list_filter = ("type_document",)
    search_fields = ("type_document", "numero_document")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("nom", "societe", "statut")
    list_filter = ("societe", "statut")
    search_fields = ("nom",)


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "module", "actif")
    list_filter = ("module", "actif")
    search_fields = ("code", "nom")


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ("role", "permission")
    search_fields = ("role__nom", "permission__code")


@admin.register(PermissionSociete)
class PermissionSocieteAdmin(admin.ModelAdmin):
    list_display = ("societe", "permission", "active", "source", "updated_at")
    list_filter = ("active", "source", "societe")
    search_fields = ("societe__nom", "permission__code")


@admin.register(Fonction)
class FonctionAdmin(admin.ModelAdmin):
    list_display = ("nom", "societe", "actif")
    list_filter = ("societe", "actif")
    search_fields = ("nom",)


@admin.register(Employe)
class EmployeAdmin(admin.ModelAdmin):
    list_display = (
        "nom",
        "prenom",
        "societe",
        "fonction",
        "role",
        "salaire",
        "statut",
        "date_recrutement",
    )
    list_filter = ("statut", "societe", "fonction")
    search_fields = ("nom", "prenom", "email", "telephone_1")
    inlines = [EmployeLangueInline]


@admin.register(ContratEmploye)
class ContratEmployeAdmin(admin.ModelAdmin):
    list_display = ("employe", "type_contrat", "date_debut", "date_fin", "salaire_contractuel", "statut")
    list_filter = ("statut", "type_contrat")
    search_fields = ("employe__nom", "employe__prenom")


@admin.register(TypeContrat)
class TypeContratAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "description")
    search_fields = ("code", "nom")


@admin.register(TypeClient)
class TypeClientAdmin(admin.ModelAdmin):
    list_display = ("nom", "description")
    search_fields = ("nom",)


class ClientDocumentInline(admin.TabularInline):
    model = ClientDocument
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("nom", "societe", "type_client", "telephone_1", "ville", "pays", "statut")
    list_filter = ("statut", "societe", "type_client", "pays")
    search_fields = ("nom", "email", "telephone_1")
    inlines = [ClientDocumentInline]


@admin.register(ProjetClient)
class ProjetClientAdmin(admin.ModelAdmin):
    list_display = ("nom", "client", "societe", "date_debut", "date_fin", "budget", "statut")
    list_filter = ("statut", "societe")
    search_fields = ("nom", "description")


@admin.register(ProjetChef)
class ProjetChefAdmin(admin.ModelAdmin):
    list_display = ("projet", "employe", "date_affectation", "principal")
    list_filter = ("principal",)


@admin.register(ProjetObjectif)
class ProjetObjectifAdmin(admin.ModelAdmin):
    list_display = ("titre", "projet", "date_echeance", "statut")
    list_filter = ("statut",)
    search_fields = ("titre",)


@admin.register(GroupeProjet)
class GroupeProjetAdmin(admin.ModelAdmin):
    list_display = ("nom", "projet", "cree_par")
    search_fields = ("nom",)


@admin.register(GroupeProjetMembre)
class GroupeProjetMembreAdmin(admin.ModelAdmin):
    list_display = ("groupe", "employe", "date_ajout")


@admin.register(ConversationGroupe)
class ConversationGroupeAdmin(admin.ModelAdmin):
    list_display = ("titre", "groupe", "created_at")


@admin.register(MessageGroupe)
class MessageGroupeAdmin(admin.ModelAdmin):
    list_display = ("conversation", "employe", "created_at", "contenu")
    search_fields = ("contenu",)


@admin.register(ModePaiement)
class ModePaiementAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "actif")
    list_filter = ("actif",)
    search_fields = ("code", "nom")


@admin.register(EcheancePaiement)
class EcheancePaiementAdmin(admin.ModelAdmin):
    list_display = ("projet", "numero_echeance", "montant_prevu", "date_prevue", "statut")
    list_filter = ("statut",)


@admin.register(PaiementClient)
class PaiementClientAdmin(admin.ModelAdmin):
    list_display = ("projet", "echeance", "montant", "date_paiement", "mode_paiement", "reference", "statut")
    list_filter = ("statut", "mode_paiement")
    search_fields = ("reference",)


@admin.register(Forfait)
class ForfaitAdmin(admin.ModelAdmin):
    list_display = ("nom", "prix", "devise", "duree_jours", "actif")
    list_editable = ("prix", "devise", "duree_jours", "actif")
    list_filter = ("actif", "devise")
    search_fields = ("nom",)


@admin.register(ForfaitPermission)
class ForfaitPermissionAdmin(admin.ModelAdmin):
    list_display = ("forfait", "permission")


@admin.register(AbonnementSociete)
class AbonnementSocieteAdmin(admin.ModelAdmin):
    list_display = ("societe", "forfait", "date_debut", "date_fin", "prix_paye", "statut", "renouvellement_auto")
    list_filter = ("statut", "forfait")


@admin.register(PaiementAbonnement)
class PaiementAbonnementAdmin(admin.ModelAdmin):
    list_display = ("abonnement", "montant", "date_paiement", "mode_paiement", "reference", "statut")
    list_filter = ("statut", "mode_paiement")


@admin.register(TypeDepense)
class TypeDepenseAdmin(admin.ModelAdmin):
    list_display = ("nom", "description")
    search_fields = ("nom",)


@admin.register(DepenseSociete)
class DepenseSocieteAdmin(admin.ModelAdmin):
    list_display = ("nom", "societe", "type_depense", "montant", "date_depense", "statut")
    list_filter = ("statut", "societe", "type_depense")
    search_fields = ("nom",)


@admin.register(PaiementSalaire)
class PaiementSalaireAdmin(admin.ModelAdmin):
    list_display = (
        "employe",
        "contrat",
        "periode_mois",
        "montant_du",
        "montant_paye",
        "date_prevue",
        "date_paiement",
        "statut",
    )
    list_filter = ("statut",)
    search_fields = ("employe__nom", "employe__prenom")


@admin.register(Finance)
class FinanceAdmin(admin.ModelAdmin):
    list_display = ("societe", "periode", "total_recettes", "total_depenses", "solde")
    list_filter = ("societe",)


@admin.register(KpayOperation)
class KpayOperationAdmin(admin.ModelAdmin):
    list_display = (
        "societe",
        "type_operation",
        "reference",
        "montant",
        "devise",
        "statut",
        "telephone",
        "is_test",
        "created_at",
    )
    list_filter = ("type_operation", "statut", "is_test", "societe")
    search_fields = ("kpay_id", "reference", "external_id", "telephone")
    readonly_fields = (
        "societe", "type_operation", "kpay_id", "reference", "provider_reference",
        "external_id", "montant", "montant_net", "frais", "devise", "provider",
        "pays", "telephone", "mode", "is_test", "message", "motif_echec",
        "created_at", "updated_at",
    )


@admin.register(IaConversation)
class IaConversationAdmin(admin.ModelAdmin):
    list_display = ("titre", "societe", "employe", "statut", "created_at", "updated_at")
    list_filter = ("statut", "societe")
    search_fields = ("titre",)


@admin.register(IaMessage)
class IaMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "created_at", "contenu")
    list_filter = ("role",)
    search_fields = ("contenu",)


# Tables de liaison simples, enregistrement direct
admin.site.register(UserAdminLangue)


from .models import Facture, LigneFacture  # noqa: E402


class LigneFactureInline(admin.TabularInline):
    model = LigneFacture
    extra = 0


@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    list_display = ("numero", "societe", "client_nom", "date_emission", "statut", "total_ttc")
    list_filter = ("statut", "societe")
    search_fields = ("numero", "client_nom", "objet")
    inlines = [LigneFactureInline]


from .models import FichierBureau  # noqa: E402


@admin.register(FichierBureau)
class FichierBureauAdmin(admin.ModelAdmin):
    list_display = ("titre", "type_fichier", "societe", "updated_at")
    list_filter = ("type_fichier", "societe")
    search_fields = ("titre",)


from .models import EvenementAgenda  # noqa: E402


@admin.register(EvenementAgenda)
class EvenementAgendaAdmin(admin.ModelAdmin):
    list_display = ("titre", "type_evenement", "debut", "fin", "societe", "organisateur")
    list_filter = ("type_evenement", "societe")
    search_fields = ("titre", "lieu", "description")
    filter_horizontal = ("participants",)
    date_hierarchy = "debut"


# ---------------------------------------------------------------------------
# Données utiles au support (les messages privés, documents confidentiels et
# identifiants des connecteurs restent volontairement hors de l'admin).
# ---------------------------------------------------------------------------
from .models import (  # noqa: E402
    ActivitePlateforme,
    DemandeAdhesion,
    EquipeGroupe,
    EquipeGroupeMembre,
    ModeleContrat,
    ProspectionClient,
    Tache,
)


@admin.register(Tache)
class TacheAdmin(admin.ModelAdmin):
    list_display = ("titre", "societe", "assignee", "priorite", "statut", "progres", "echeance")
    list_filter = ("statut", "priorite", "societe")
    search_fields = ("titre", "description")
    date_hierarchy = "echeance"
    raw_id_fields = ("assignee", "cree_par", "projet")


@admin.register(ProspectionClient)
class ProspectionClientAdmin(admin.ModelAdmin):
    list_display = ("nom", "societe", "contact", "statut", "budget_estime", "date_prospection")
    list_filter = ("statut", "societe")
    search_fields = ("nom", "contact", "email")


@admin.register(DemandeAdhesion)
class DemandeAdhesionAdmin(admin.ModelAdmin):
    list_display = ("user", "societe", "employe", "origine", "statut", "created_at")
    list_filter = ("statut", "origine", "societe")
    search_fields = ("user__email",)
    raw_id_fields = ("user", "employe")


@admin.register(ModeleContrat)
class ModeleContratAdmin(admin.ModelAdmin):
    list_display = ("nom", "societe", "type_contrat", "actif", "updated_at")
    list_filter = ("actif", "type_contrat", "societe")
    search_fields = ("nom",)


class EquipeGroupeMembreInline(admin.TabularInline):
    model = EquipeGroupeMembre
    extra = 0
    raw_id_fields = ("employe",)


@admin.register(EquipeGroupe)
class EquipeGroupeAdmin(admin.ModelAdmin):
    list_display = ("titre", "societe", "cree_par", "created_at")
    list_filter = ("societe",)
    search_fields = ("titre",)
    inlines = [EquipeGroupeMembreInline]
    exclude = ("logo",)


@admin.register(ActivitePlateforme)
class ActivitePlateformeAdmin(admin.ModelAdmin):
    """Journal d'activité : consultation seule (traçabilité)."""

    list_display = ("created_at", "societe", "utilisateur", "action", "module", "libelle")
    list_filter = ("action", "module", "societe")
    search_fields = ("libelle", "detail")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# L'administration de la plateforme (tableau de bord /admin/ et données détaillées)
# est réservée aux superadmins : un compte « staff » simple n'y a pas accès.
admin.site.has_permission = lambda request: bool(request.user.is_active and request.user.is_superuser)
