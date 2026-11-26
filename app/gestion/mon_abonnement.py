"""Ma société › Mon abonnement : offre actuelle, demande en cours, changement d'offre, historique."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import abonnements


@login_required
def page(request):
    from django.shortcuts import redirect

    from . import services
    from .views import _espace_finances, _societe_context

    societe, ctx, resp = _societe_context(request, "societe")
    if resp:
        return resp
    if not services.est_createur(request.user, societe):
        return redirect("gestion:dashboard")
    ctx["active"] = "abonnement"
    ctx.update(_espace_finances(ctx["modules_autorises"], ctx["nav_counts"], "abonnement"))
    dernier = abonnements.courant(societe)
    ctx.update({
        "actif": societe.abonnements.filter(statut="ACTIF").select_related("forfait").first(),
        "dernier": dernier,
        "demande": societe.abonnements.filter(statut="EN_ATTENTE").select_related("forfait", "ancien_forfait").first(),
        "forfaits": abonnements.forfaits_publics(),
        "historique": societe.abonnements.select_related("forfait", "ancien_forfait").order_by("-created_at", "-pk")[:12],
        "paiements": (abonnements.PaiementAbonnement.objects.filter(abonnement__societe=societe)
                      .select_related("abonnement__forfait", "mode_paiement").order_by("-pk")[:12]),
        "peut_changer": True,
    })
    return render(request, "gestion/mon_abonnement.html", ctx)
