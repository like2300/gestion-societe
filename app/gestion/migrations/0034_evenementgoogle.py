import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion", "0033_iamessage_donnees"),
    ]

    operations = [
        migrations.CreateModel(
            name="EvenementGoogle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("objet_type", models.CharField(max_length=20)),
                ("objet_id", models.PositiveIntegerField()),
                ("evenement_id", models.CharField(max_length=200)),
                ("maj_le", models.DateTimeField(auto_now=True)),
                ("societe", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evenements_google", to="gestion.societe")),
            ],
            options={
                "verbose_name": "événement Google Agenda",
                "verbose_name_plural": "événements Google Agenda",
                "db_table": "evenement_google",
                "constraints": [models.UniqueConstraint(fields=("societe", "objet_type", "objet_id"), name="unique_evenement_google")],
            },
        ),
    ]
