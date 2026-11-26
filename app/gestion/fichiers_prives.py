"""Documents confidentiels : stockage privé + téléchargement contrôlé.

Les documents de la société (statuts, RCCM…), des clients et des employés (pièces
d'identité…) ne sont JAMAIS servis par ``MEDIA_URL`` (public, sans connexion) :
ils sont rangés dans ``PRIVATE_MEDIA_ROOT`` et téléchargés uniquement via
``gestion:document_fichier``, qui vérifie la société ET la permission :

- document de la société → module « Documents » (ou « Ma société ») ;
- document client       → module « Clients » ;
- document employé      → propriétaire, ou l'employé concerné lui-même.

Les anciens fichiers restés dans MEDIA_ROOT sont déplacés à la première lecture
(et par la commande ``manage.py securiser_documents``).
"""

import mimetypes
import os
import re
import shutil
import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.storage import FileSystemStorage
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.urls import reverse

from . import services

TYPES = ("societe", "client", "employe")


def stockage():
    return FileSystemStorage(location=str(settings.PRIVATE_MEDIA_ROOT))


def stocker(upload, dossier, base):
    """Enregistre un téléversement dans le stockage privé ; retourne le chemin relatif."""
    ext = os.path.splitext(upload.name or "")[1].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", (base or "").lower()).strip("-") or "document"
    return stockage().save(f"{dossier}/{slug}-{uuid.uuid4().hex}{ext}", upload)


def chemin(rel):
    """Chemin absolu du fichier privé ; déplace au passage un ancien fichier public."""
    if not rel or ".." in rel.replace("\\", "/").split("/"):
        return None
    prive = os.path.join(str(settings.PRIVATE_MEDIA_ROOT), rel)
    if os.path.isfile(prive):
        return prive
    public = os.path.join(str(settings.MEDIA_ROOT), rel)
    if os.path.isfile(public):
        os.makedirs(os.path.dirname(prive), exist_ok=True)
        shutil.move(public, prive)
        return prive
    return None


def url(type_, pk):
    return reverse("gestion:document_fichier", args=[type_, pk])


def _document(request, type_, pk):
    """(document, société) si l'utilisateur a le droit de le lire, sinon lève Http404 / renvoie None."""
    from .models import ClientDocument, EmployeDocument, SocieteDocument
    from .views import _societe_context

    module = {"societe": "documents", "client": "clients", "employe": "employes"}[type_]
    societe, ctx, resp = _societe_context(request, "dashboard")
    if resp:
        return None, resp
    autorises = ctx["modules_autorises"]
    if type_ == "societe":
        doc = SocieteDocument.objects.filter(pk=pk, societe=societe).first()
        ok = bool({"documents", "societe"} & set(autorises))
    elif type_ == "client":
        doc = ClientDocument.objects.filter(pk=pk, client__societe=societe).first()
        ok = module in autorises
    else:
        doc = EmployeDocument.objects.filter(pk=pk, employe__societe=societe).first()
        moi = services.employe_pour_utilisateur(request.user, societe)
        ok = services.est_createur(request.user, societe) or bool(doc and moi and doc.employe_id == moi.pk)
    if doc is None:
        raise Http404("Document introuvable.")
    if not ok:
        return None, HttpResponseForbidden("Vous n'avez pas accès à ce document.")
    return doc, None


@login_required
def telecharger(request, type_, pk):
    if type_ not in TYPES:
        raise Http404
    doc, refus = _document(request, type_, pk)
    if refus is not None:
        return refus
    complet = chemin(doc.fichier)
    if complet is None:
        raise Http404("Fichier introuvable sur le serveur.")
    nom = os.path.basename(complet)
    type_mime = mimetypes.guess_type(nom)[0] or "application/octet-stream"
    reponse = FileResponse(open(complet, "rb"), content_type=type_mime,
                           as_attachment=bool(request.GET.get("dl")), filename=nom)
    reponse["Cache-Control"] = "private, no-store"
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse
