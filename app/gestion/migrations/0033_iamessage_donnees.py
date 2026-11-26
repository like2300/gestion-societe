from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion", "0032_useradmin_doit_changer_mdp"),
    ]

    operations = [
        migrations.AddField(
            model_name="iamessage",
            name="donnees",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="données enrichies"
            ),
        ),
    ]
