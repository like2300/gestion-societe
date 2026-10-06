from django.db import migrations


def marquer_employes(apps, schema_editor):
    """Marque en rôle « Employé » les comptes déjà reliés à un employé.

    Un compte est considéré employé s'il possède une fiche ``Employe`` liée
    ou une demande d'adhésion, et qu'il n'a pas créé de société. Les
    super-utilisateurs et les créateurs de société sont laissés intacts.
    """
    UserAdmin = apps.get_model("gestion", "UserAdmin")
    Employe = apps.get_model("gestion", "Employe")
    DemandeAdhesion = apps.get_model("gestion", "DemandeAdhesion")
    Societe = apps.get_model("gestion", "Societe")

    comptes_employes = set(
        Employe.objects.exclude(compte__isnull=True).values_list(
            "compte_id", flat=True
        )
    )
    comptes_employes |= set(
        DemandeAdhesion.objects.values_list("user_id", flat=True)
    )

    createurs = set(Societe.objects.values_list("createur_id", flat=True))
    cibles = comptes_employes - createurs
    if cibles:
        UserAdmin.objects.filter(pk__in=cibles).exclude(
            role_admin="EMPLOYE"
        ).exclude(is_superuser=True).update(role_admin="EMPLOYE")


class Migration(migrations.Migration):

    dependencies = [
        ("gestion", "0014_demandeadhesion_origine_alter_useradmin_role_admin"),
    ]

    operations = [
        migrations.RunPython(marquer_employes, migrations.RunPython.noop),
    ]
