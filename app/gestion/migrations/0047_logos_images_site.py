from django.db import migrations

CODES = (
    ("logo_header", "Logo dans l'en-tête"),
    ("logo_footer", "Logo dans le pied de page"),
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
        ("gestion", "0046_seed_images_site"),
    ]

    operations = [
        migrations.RunPython(creer_emplacements, supprimer_emplacements),
    ]
