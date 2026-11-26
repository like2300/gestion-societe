from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion", "0031_employedocument"),
    ]

    operations = [
        migrations.AddField(
            model_name="useradmin",
            name="doit_changer_mdp",
            field=models.BooleanField(
                default=False, verbose_name="doit changer son mot de passe"
            ),
        ),
    ]
