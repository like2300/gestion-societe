"""Mot de passe par défaut par société et code de validation Google."""

import secrets

from django.db import migrations, models
from django.utils import timezone


def initialiser(apps, schema_editor):
    from gestion.crypto import chiffrer

    Societe = apps.get_model("gestion", "Societe")
    UserAdmin = apps.get_model("gestion", "UserAdmin")

    for societe in Societe.objects.all():
        if not societe.mot_de_passe_defaut_chiffre:
            societe.mot_de_passe_defaut_chiffre = chiffrer(
                {"mdp": secrets.token_urlsafe(9)}
            )
            societe.save(update_fields=["mot_de_passe_defaut_chiffre"])

    maintenant = timezone.now()
    for user in UserAdmin.objects.filter(
        doit_changer_mdp=True, validation_google_requise=False
    ):
        user.code_validation = f"{secrets.randbelow(1000000):06d}"
        user.code_validation_envoye_le = maintenant
        user.validation_google_requise = True
        user.save(
            update_fields=[
                "code_validation",
                "code_validation_envoye_le",
                "validation_google_requise",
            ]
        )


def neutraliser(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("gestion", "0053_alter_abonnementsociete_statut"),
    ]

    operations = [
        migrations.AddField(
            model_name="societe",
            name="mot_de_passe_defaut_chiffre",
            field=models.TextField(
                blank=True,
                default="",
                verbose_name="mot de passe par défaut des employés (chiffré)",
            ),
        ),
        migrations.AddField(
            model_name="useradmin",
            name="code_validation",
            field=models.CharField(
                blank=True,
                default="",
                max_length=6,
                verbose_name="code de validation à 6 chiffres",
            ),
        ),
        migrations.AddField(
            model_name="useradmin",
            name="code_validation_envoye_le",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="date d'envoi du code de validation",
            ),
        ),
        migrations.AddField(
            model_name="useradmin",
            name="validation_google_requise",
            field=models.BooleanField(
                default=False,
                verbose_name="validation du code requise à la première connexion Google",
            ),
        ),
        migrations.RunPython(initialiser, neutraliser),
    ]
