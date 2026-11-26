"""Page « Groupes » : espace dédié aux groupes de discussion de l'équipe.

- Chacun voit les groupes dont il fait partie (le propriétaire les voit tous).
- Le propriétaire et les employés ayant la permission « Créer des groupes »
  peuvent en créer ; le créateur devient administrateur du groupe.
- Les administrateurs d'un groupe le modifient (titre, description, logo,
  membres, autres administrateurs) et peuvent le supprimer.
- Un membre peut quitter un groupe (sauf son créateur).

La création et la modification réutilisent les points d'accès JSON existants
(``gestion:groupes`` et ``gestion:chat_groupe_config``) ; la discussion s'ouvre
dans l'espace Employés (``?groupe=<pk>``).
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services


def _ctx(request):
    from .views import _societe_context

    societe, ctx, resp = _societe_context(request, "groupes")
    if resp:
        return None, None, resp
    ctx["active"] = "groupes"
    return societe, ctx, None


@login_required
def page(request):
    societe, ctx, resp = _ctx(request)
    if resp:
        return resp
    moi = services.employe_pour_utilisateur(request.user, societe)
    groupes = (services.groupes_visibles(request.user, societe)
               .select_related("cree_par").prefetch_related("membres__employe__fonction"))
    peut_discuter = "employes" in ctx["modules_autorises"]
    cartes = []
    for g in groupes:
        membres = [m for m in g.membres.all()]
        mon_lien = next((m for m in membres if moi and m.employe_id == moi.pk), None)
        admin = services.peut_administrer_groupe(request.user, societe, g)
        createur = g.cree_par
        cartes.append({
            "pk": g.pk, "titre": g.titre, "description": g.description,
            "logo_url": reverse("gestion:chat_groupe_logo", args=[g.pk]) if g.logo else "",
            "membres": [{"pk": m.employe_id, "nom": f"{m.employe.prenom} {m.employe.nom}",
                         "fonction": m.employe.fonction.nom if m.employe.fonction_id else "",
                         "admin": m.est_admin} for m in membres],
            "nb_messages": g.messages.count(),
            "createur": (f"{getattr(createur, 'prenom', '')} {getattr(createur, 'nom', '')}".strip()
                         or getattr(createur, "email", "")) if createur else "",
            "cree_le": g.created_at,
            "role": "Administrateur" if admin else ("Membre" if mon_lien else "Supervision"),
            "peut_admin": admin,
            "peut_quitter": bool(mon_lien) and g.cree_par_id != request.user.pk,
            "discussion": f"{reverse('gestion:employes')}?groupe={g.pk}" if peut_discuter else "",
        })
    employes = societe.employes.select_related("fonction").order_by("prenom", "nom")
    ctx.update({
        "cartes": cartes,
        "mes_groupes": [c for c in cartes if c["role"] != "Supervision"],
        "autres_groupes": [c for c in cartes if c["role"] == "Supervision"],
        "peut_creer": services.peut_creer_groupe(request.user, societe),
        "est_proprietaire": services.est_createur(request.user, societe),
        "moi_pk": moi.pk if moi else None,
        "employes_js": [{"pk": e.pk, "nom": f"{e.prenom} {e.nom}", "fonction": e.fonction.nom if e.fonction_id else ""}
                        for e in employes],
        "url_creer": reverse("gestion:groupes"),
        "url_config": reverse("gestion:chat_groupe_config", args=[0]),
        "url_supprimer": reverse("gestion:chat_groupe_supprimer", args=[0]),
        "url_quitter": reverse("gestion:groupe_quitter", args=[0]),
    })
    return render(request, "gestion/groupes.html", ctx)


@login_required
@require_POST
def quitter(request, pk):
    societe, ctx, resp = _ctx(request)
    if resp:
        return JsonResponse({"error": "Accès refusé."}, status=403)
    groupe = services.groupes_visibles(request.user, societe).filter(pk=pk).first()
    moi = services.employe_pour_utilisateur(request.user, societe)
    if groupe is None or moi is None:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)
    if groupe.cree_par_id == request.user.pk:
        return JsonResponse({"error": "Le créateur ne peut pas quitter son groupe : supprimez-le ou confiez-le."}, status=400)
    groupe.membres.filter(employe=moi).delete()
    services.journaliser(societe, "MODIFICATION", "equipe", f"Groupe — {groupe.titre}",
                         f"{moi.prenom} {moi.nom} a quitté le groupe", request.user)
    return JsonResponse({"ok": True})
