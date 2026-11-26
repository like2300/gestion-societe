from django.db import migrations

CODES = (
    ("logo_app", "Logo de l'application (connexion, favicon)"),
    ("favicon", "Favicon du site"),
)


def creer_emplacements(apps, schema_editor):
    ImageSite = apps.get_model("gestion", "ImageSite")
    for code, titre in CODES:
        ImageSite.objects.get_or_create(code=code, defaults={"titre": titre})


def supprimer_emplacements(apps, schema_editor):
    ImageSite = apps.get_model("gestion", "ImageSite")
    ImageSite.objects.filter(code__in=[code for code, _ in CODES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("gestion", "0049_alter_imagesite_code"),
    ]

    operations = [
        migrations.RunPython(creer_emplacements, supprimer_emplacements),
    ]
