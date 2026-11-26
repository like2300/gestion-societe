import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0030_iaconversation_societe_alter_iaconversation_employe'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type_document', models.CharField(max_length=100)),
                ('fichier', models.CharField(max_length=500)),
                ('date_document', models.DateField(blank=True, null=True)),
                ('employe', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='gestion.employe')),
            ],
            options={
                'verbose_name': "document d'employé",
                'verbose_name_plural': "documents d'employé",
                'db_table': 'employe_document',
            },
        ),
    ]
