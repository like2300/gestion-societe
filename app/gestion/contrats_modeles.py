"""Ma société › Modèles de contrat : la société rédige ses propres contrats de travail.

Le texte contient des variables dynamiques ``{{ variable }}`` (voir
``contrat_pdf.VARIABLES``) remplies à l'impression avec la fiche de l'employé et
son contrat. Un modèle peut viser un type de contrat (CDI, CDD…) ou servir de
modèle général. Sans modèle, le contrat standard de l'application est utilisé.
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import contrat_pdf, logo_societe, services
from .models import ContratEmploye, Employe, ModeleContrat, TypeContrat


def _ctx(request, ecriture=None):
    from .views import _espace_finances, _societe_context

    societe, ctx, resp = _societe_context(request, "societe", ecriture=ecriture)
    if resp:
        return None, None, resp
    ctx["active"] = "modeles_contrat"
    ctx.update(_espace_finances(ctx["modules_autorises"], ctx["nav_counts"], "modeles_contrat"))
    return societe, ctx, None


@login_required
def page(request):
    """Liste + éditeur (?modele=<pk> ou ?nouveau=1)."""
    societe, ctx, resp = _ctx(request)
    if resp:
        return resp
    modeles = list(societe.modeles_contrat.select_related("type_contrat"))
    courant = None
    if request.GET.get("modele"):
        courant = next((m for m in modeles if str(m.pk) == request.GET["modele"]), None)
    elif not request.GET.get("nouveau") and modeles:
        courant = modeles[0]
    ctx.update({
        "modeles": modeles,
        "courant": courant,
        "contenu": courant.contenu if courant else contrat_pdf.MODELE_DEFAUT,
        "types": TypeContrat.objects.order_by("nom"),
        "variables": contrat_pdf.VARIABLES,
        "contenu_standard": contrat_pdf.MODELE_DEFAUT,
        "employes": societe.employes.order_by("prenom", "nom"),
    })
    return render(request, "gestion/modeles_contrat.html", ctx)


@login_required
@require_POST
def enregistrer(request):
    societe, ctx, resp = _ctx(request)
    if resp:
        return resp
    pk = request.POST.get("pk")
    modele = societe.modeles_contrat.filter(pk=pk).first() if pk else ModeleContrat(societe=societe)
    if modele is None:
        raise Http404
    modele.nom = (request.POST.get("nom") or "").strip()[:150] or "Modèle de contrat"
    modele.type_contrat = TypeContrat.objects.filter(pk=request.POST.get("type_contrat") or 0).first()
    modele.contenu = (request.POST.get("contenu") or "").strip()[:60000] or contrat_pdf.MODELE_DEFAUT
    modele.actif = request.POST.get("actif") == "on"
    nouveau = modele.pk is None
    modele.save()
    services.journaliser(societe, "CREATION" if nouveau else "MODIFICATION", "societe",
                         f"Modèle de contrat — {modele.nom}", "", request.user)
    messages.success(request, f"Modèle « {modele.nom} » enregistré.")
    return redirect(f"{reverse('gestion:modeles_contrat')}?modele={modele.pk}")


@login_required
@require_POST
def supprimer(request, pk):
    societe, ctx, resp = _ctx(request)
    if resp:
        return resp
    modele = societe.modeles_contrat.filter(pk=pk).first()
    if modele:
        nom = modele.nom
        modele.delete()
        services.journaliser(societe, "SUPPRESSION", "societe", f"Modèle de contrat — {nom}", "", request.user)
        messages.success(request, f"Modèle « {nom} » supprimé.")
    return redirect("gestion:modeles_contrat")


@login_required
@require_POST
def apercu(request):
    """Aperçu PDF du texte en cours d'édition (non enregistré), avec un employé réel ou fictif."""
    societe, ctx, resp = _ctx(request, ecriture=False)
    if resp:
        return resp
    type_contrat = TypeContrat.objects.filter(pk=request.POST.get("type_contrat") or 0).first() \
        or TypeContrat.objects.filter(code="CDI").first() or TypeContrat.objects.first()
    employe = societe.employes.filter(pk=request.POST.get("employe") or 0).select_related("fonction").first()
    if employe is not None:
        reel = employe.contrats.filter(statut="ACTIF").order_by("-date_debut").first()
        contrat = ContratEmploye(
            employe=employe, type_contrat=type_contrat,
            date_debut=reel.date_debut if reel else (employe.date_recrutement or date.today()),
            date_fin=reel.date_fin if reel else None,
            salaire_contractuel=reel.salaire_contractuel if reel else (employe.salaire or 0),
            poste=employe.fonction.nom if employe.fonction_id else "", lieu_travail=reel.lieu_travail if reel else "",
            heures_hebdo=reel.heures_hebdo if reel else 40, periode_essai_jours=reel.periode_essai_jours if reel else 90,
            missions=reel.missions if reel else "",
        )
    else:
        fictif = Employe(societe=societe, nom="EXEMPLE", prenom="Jean", nationalite="congolaise",
                         lieu_naissance="Brazzaville", numero_piece_identite="CNI-000000", adresse="12 avenue de la Paix",
                         telephone_1="06 000 00 00", email="jean.exemple@mail.com", jour_paiement=28,
                         date_naissance=date(1995, 4, 12))
        contrat = ContratEmploye(
            employe=fictif, type_contrat=type_contrat, date_debut=date.today(), salaire_contractuel=250000,
            poste="Assistant(e) administratif(ve)", lieu_travail=f"{societe.nom}, {societe.pays or ''}".strip(", "),
            heures_hebdo=40, periode_essai_jours=90, missions="Accueil des clients\nSuivi administratif",
        )
    contrat._modele_texte = request.POST.get("contenu") or contrat_pdf.MODELE_DEFAUT
    pdf = contrat_pdf.contrat_pdf(contrat, ctx["accent"], logo=logo_societe.logo_reader(societe))
    reponse = HttpResponse(pdf, content_type="application/pdf")
    reponse["Content-Disposition"] = 'inline; filename="apercu-contrat.pdf"'
    return reponse
