from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestion", "0005_depensesociete_paiement_salaire"),
    ]

    operations = [
        migrations.AddField(
            model_name="societe",
            name="modes_paiement",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Modes de paiement que la société peut utiliser pour payer "
                    "les salaires. Configurable dans « Ma société » ."
                ),
                related_name="societes",
                to="gestion.modepaiement",
                verbose_name="modes de paiement disponibles",
            ),
        ),
    ]
