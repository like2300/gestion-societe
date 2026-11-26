from django.db import migrations

CODES = (
    ("hero_fond", "Fond du bandeau d'accueil"),
    ("macbook", "Cadre MacBook des captures"),
    ("dashboard", "Capture — tableau de bord"),
    ("collaboration", "Capture — collaboration"),
    ("finances", "Capture — finances"),
    ("planning", "Capture — planning"),
    ("bureau", "Capture — bureautique"),
    ("assistant_ia", "Capture — assistant IA"),
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
        ("gestion", "0045_avis_imagesite"),
    ]

    operations = [
        migrations.RunPython(creer_emplacements, supprimer_emplacements),
    ]
