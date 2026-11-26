"""Déplace les documents confidentiels de MEDIA_ROOT (public) vers PRIVATE_MEDIA_ROOT.

Usage : python manage.py securiser_documents
Les chemins enregistrés en base restent identiques (relatifs) ; seul l'emplacement
physique change. Sans danger à relancer.
"""

from django.core.management.base import BaseCommand

from gestion.fichiers_prives import chemin
from gestion.models import ClientDocument, EmployeDocument, SocieteDocument


class Command(BaseCommand):
    help = "Met à l'abri (stockage privé) les documents de la société, des clients et des employés."

    def handle(self, *args, **options):
        deplaces = manquants = 0
        for modele in (SocieteDocument, ClientDocument, EmployeDocument):
            for doc in modele.objects.exclude(fichier=""):
                if chemin(doc.fichier):
                    deplaces += 1
                else:
                    manquants += 1
                    self.stdout.write(f"Fichier introuvable : {modele.__name__} #{doc.pk} ({doc.fichier})")
        self.stdout.write(self.style.SUCCESS(f"{deplaces} document(s) en stockage privé, {manquants} introuvable(s)."))
