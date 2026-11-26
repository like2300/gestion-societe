from django.db import migrations

CODES = (("og_image", "Image de partage (WhatsApp, réseaux sociaux)"),)


def creer_emplacement(apps, schema_editor):
    ImageSite = apps.get_model("gestion", "ImageSite")
    for code, titre in CODES:
        ImageSite.objects.get_or_create(code=code, defaults={"titre": titre})


def supprimer_emplacement(apps, schema_editor):
    ImageSite = apps.get_model("gestion", "ImageSite")
    ImageSite.objects.filter(code__in=[code for code, _ in CODES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("gestion", "0051_alter_imagesite_code"),
    ]

    operations = [
        migrations.RunPython(creer_emplacement, supprimer_emplacement),
    ]
