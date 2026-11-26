"""Application « Planning » : agenda des rendez-vous de chaque employé + événements de l'app.

- Chaque employé voit son propre agenda (événements qu'il organise ou auxquels il participe).
- L'administration voit l'agenda de toute l'équipe ou celui d'un employé précis.
- Couches en lecture seule : échéances des tâches, échéances de paiement, factures, fins de contrat.
"""

import json
import re
from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_POST

from . import services
from .models import (
    ContratEmploye,
    EcheancePaiement,
    EvenementAgenda,
    Facture,
    Tache,
    TYPE_EVENEMENT_CHOICES,
    PRIORITE_TACHE_CHOICES,
)

COULEURS_STATUT = {"A_FAIRE": "#3b82f6", "EN_COURS": "#f59e0b", "TERMINEE": "#10b981"}
LIBELLES_STATUT = {"A_FAIRE": "À faire", "EN_COURS": "En cours", "TERMINEE": "Terminée"}

COULEURS_TYPE = {
    "RDV": "#0ea5e9", "REUNION": "#6366f1", "APPEL": "#10b981", "VISITE": "#f59e0b",
    "FORMATION": "#8b5cf6", "CONGE": "#94a3b8", "AUTRE": "#64748b",
}
COUCHES = {
    "taches": ("Mes tâches", "#3b82f6"),
    "echeances": ("Échéances de paiement", "#f97316"),
    "factures": ("Factures à encaisser", "#e11d48"),
    "contrats": ("Fins de contrat", "#a855f7"),
}


def _ctx(request):
    from .views import _societe_context

    societe, ctx, resp = _societe_context(request, "planning")
    if resp:
        return None, None, resp
    ctx["active"] = "planning"
    return societe, ctx, None


def _moi(request, societe):
    return services.employe_pour_utilisateur(request.user, societe)


def _est_admin(request, societe):
    return not services.est_employe(request.user, societe) or services.est_createur(request.user, societe)


def _mes_groupes(request, societe):
    """Groupes d'équipe visibles dans le planning : tous pour l'administration, sinon ceux dont on est membre."""
    qs = societe.equipe_groupes.prefetch_related("membres").order_by("titre")
    if not _est_admin(request, societe):
        moi = _moi(request, societe)
        if moi is None:
            return societe.equipe_groupes.none()
        qs = qs.filter(membres__employe=moi).distinct()
    return qs


def _groupe_qui(request, societe, qui):
    """« grp:<pk> » → groupe accessible à ce compte, sinon None."""
    if not qui.startswith("grp:") or not qui[4:].isdigit():
        return None
    return _mes_groupes(request, societe).filter(pk=int(qui[4:])).first()


def _membres_groupe(groupe):
    return list(groupe.membres.values_list("employe_id", flat=True))


def _mon_filtre(request, societe):
    """Mes rendez-vous : ceux que j'organise ou auxquels je participe."""
    moi = _moi(request, societe)
    filtre = Q(organisateur=request.user)
    if moi:
        filtre |= Q(participants=moi)
    return filtre


def _est_a_moi(request, societe, ev):
    moi = _moi(request, societe)
    return ev.organisateur_id == request.user.pk or bool(moi and moi in ev.participants.all())


def _visibles(request, societe, qui):
    """Événements visibles : chacun ne voit QUE son propre agenda (propriétaire compris).

    Vue « groupe » : on y ajoute les créneaux des membres du groupe, renvoyés masqués
    (« Occupé ») par ``flux`` quand le rendez-vous ne nous concerne pas.
    """
    qs = societe.evenements_agenda.all()
    groupe = _groupe_qui(request, societe, qui)
    if groupe is not None:
        ids = _membres_groupe(groupe)
        comptes = list(societe.employes.filter(pk__in=ids, compte__isnull=False).values_list("compte_id", flat=True))
        return qs.filter(Q(participants__in=ids) | Q(organisateur_id__in=comptes) | _mon_filtre(request, societe)).distinct()
    return qs.filter(_mon_filtre(request, societe)).distinct()


def _peut_modifier(request, societe, ev):
    """Seul l'organisateur modifie, déplace ou supprime un rendez-vous."""
    return ev.organisateur_id == request.user.pk


@login_required
def page(request):
    from .bureau import dossiers_apps  # import local : bureau importe déjà services/views

    societe, ctx, resp = _ctx(request)
    if resp:
        return resp
    admin = _est_admin(request, societe)
    moi = _moi(request, societe)
    ctx.update({
        "est_admin": admin,
        "types": TYPE_EVENEMENT_CHOICES,
        "couleurs_type": COULEURS_TYPE,
        "couches": [{"cle": k, "nom": v[0], "couleur": v[1]} for k, v in COUCHES.items()],
        "employes_js": [
            {"pk": e.pk, "nom": f"{e.prenom} {e.nom}", "fonction": e.fonction.nom if e.fonction_id else ""}
            for e in societe.employes.select_related("fonction").order_by("prenom", "nom")
        ],
        "clients_js": [{"pk": c.pk, "nom": c.nom} for c in societe.clients.order_by("nom")],
        "priorites": PRIORITE_TACHE_CHOICES,
        "statuts_tache": [(k, LIBELLES_STATUT[k], v) for k, v in COULEURS_STATUT.items()],
        "moi_pk": moi.pk if moi else None,
        "groupes_js": [
            {"pk": g.pk, "titre": g.titre, "membres": [m.employe_id for m in g.membres.all()],
             "moi_membre": bool(moi and any(m.employe_id == moi.pk for m in g.membres.all()))}
            for g in _mes_groupes(request, societe)
        ],
        "dossiers_apps": dossiers_apps(request, societe, "planning"),
        "flux_url": reverse("gestion:planning_flux"),
        "sauver_url": reverse("gestion:planning_sauver"),
        "rappels_url": reverse("gestion:planning_rappels"),
    })
    return render(request, "gestion/planning.html", ctx)


def _iso(d):
    return d.isoformat() if d else None


def _jour(d):
    return d.isoformat() if d else None


@login_required
def flux(request):
    """Flux JSON pour FullCalendar : ?start=&end=&qui=moi|tous|emp:<pk>&couches=taches,echeances…"""
    societe, ctx, resp = _ctx(request)
    if resp:
        return JsonResponse([], safe=False, status=403)
    debut = parse_datetime(request.GET.get("start") or "") or timezone.now() - timedelta(days=40)
    fin = parse_datetime(request.GET.get("end") or "") or timezone.now() + timedelta(days=40)
    if timezone.is_naive(debut):
        debut = timezone.make_aware(debut)
    if timezone.is_naive(fin):
        fin = timezone.make_aware(fin)
    qui = request.GET.get("qui") or "moi"
    admin = _est_admin(request, societe)
    moi = _moi(request, societe)
    sortie = []
    qs = (_visibles(request, societe, qui).filter(debut__lt=fin, fin__gt=debut)
          .select_related("organisateur", "client").prefetch_related("participants"))
    groupe = _groupe_qui(request, societe, qui)
    for ev in qs:
        couleur = ev.couleur or COULEURS_TYPE.get(ev.type_evenement, "#0ea5e9")
        if groupe is not None and not _est_a_moi(request, societe, ev):
            # Rendez-vous d'un collègue du groupe : seul le créneau est partagé (confidentialité)
            noms = [f"{p.prenom} {p.nom}" for p in ev.participants.all()]
            sortie.append({
                "id": f"ev-{ev.pk}", "title": "Occupé",
                "start": _iso(timezone.localtime(ev.debut)) if not ev.journee_entiere else _jour(timezone.localtime(ev.debut).date()),
                "end": _iso(timezone.localtime(ev.fin)) if not ev.journee_entiere else _jour(timezone.localtime(ev.fin).date() + timedelta(days=1)),
                "allDay": ev.journee_entiere, "backgroundColor": "#94a3b8", "borderColor": "#94a3b8",
                "editable": False, "classNames": ["pl-occupe"],
                "extendedProps": {"source": "agenda", "masque": True, "pk": ev.pk, "participants_noms": noms,
                                  "modifiable": False},
            })
            continue
        sortie.append({
            "id": f"ev-{ev.pk}",
            "title": ev.titre,
            "start": _iso(timezone.localtime(ev.debut)) if not ev.journee_entiere else _jour(timezone.localtime(ev.debut).date()),
            "end": _iso(timezone.localtime(ev.fin)) if not ev.journee_entiere else _jour(timezone.localtime(ev.fin).date() + timedelta(days=1)),
            "allDay": ev.journee_entiere,
            "backgroundColor": couleur, "borderColor": couleur,
            "editable": _peut_modifier(request, societe, ev),
            "extendedProps": {
                "source": "agenda", "pk": ev.pk, "type": ev.type_evenement,
                "type_label": ev.get_type_evenement_display(), "description": ev.description,
                "lieu": ev.lieu, "client_id": ev.client_id or "", "client": ev.client.nom if ev.client else "",
                "participants": [p.pk for p in ev.participants.all()],
                "participants_noms": [f"{p.prenom} {p.nom}" for p in ev.participants.all()],
                "organisateur": (f"{getattr(ev.organisateur, 'prenom', '')} {getattr(ev.organisateur, 'nom', '')}".strip()
                                 or getattr(ev.organisateur, "email", "")) if ev.organisateur else "",
                "couleur": ev.couleur, "rappel": ev.rappel_minutes or "",
                "image": ev.image.url if ev.image else "",
                "modifiable": _peut_modifier(request, societe, ev),
            },
        })
    couches = set((request.GET.get("couches") or "").split(","))
    d0, d1 = debut.date(), fin.date()

    def lecture_seule(cle, pk, titre, jour, lien, detail=""):
        nom, couleur = COUCHES[cle]
        sortie.append({
            "id": f"{cle}-{pk}", "title": titre, "start": _jour(jour), "allDay": True,
            "backgroundColor": couleur, "borderColor": couleur, "editable": False,
            "classNames": ["pl-couche"],
            "extendedProps": {"source": cle, "couche": nom, "lien": lien, "description": detail},
        })

    def ajouter_taches(qs, mine):
        for x in qs.select_related("assignee", "projet"):
            j1 = x.echeance or x.date_debut
            j0 = min(x.date_debut or j1, j1)
            nom = f"{x.assignee.prenom} {x.assignee.nom}" if x.assignee_id else ""
            c = COULEURS_STATUT.get(x.statut, "#3b82f6")
            sortie.append({
                "id": f"tache-{x.pk}", "title": x.titre, "start": _jour(j0), "end": _jour(j1 + timedelta(days=1)),
                "allDay": True, "backgroundColor": c, "borderColor": c, "editable": False,
                "classNames": ["pl-tache", "st-" + x.statut.lower()] + ([] if mine else ["autre"]),
                "extendedProps": {
                    "source": "tache", "pk": x.pk, "statut": x.statut, "statut_label": LIBELLES_STATUT.get(x.statut, ""),
                    "priorite": x.priorite, "priorite_label": x.get_priorite_display(), "progres": x.progres,
                    "assignee": nom, "assignee_id": x.assignee_id, "projet": x.projet.nom if x.projet_id else "",
                    "description": x.description, "echeance": _jour(x.echeance), "mine": mine,
                    "modifiable": mine or admin, "lien": reverse("gestion:taches"),
                },
            })

    taches = (Tache.objects.filter(societe=societe).exclude(statut="ANNULEE")
              .filter(Q(echeance__gte=d0) | Q(echeance__isnull=True, date_debut__gte=d0))
              .filter(Q(date_debut__lt=d1) | Q(date_debut__isnull=True, echeance__lt=d1))
              .exclude(echeance__isnull=True, date_debut__isnull=True))
    if "taches" in couches:
        # Mes tâches : celles qui me sont attribuées (+ celles que j'ai attribuées si j'administre)
        filtre_t = Q(assignee=moi) if moi else Q(pk__in=[])
        if admin:
            filtre_t |= Q(cree_par=request.user)
        ajouter_taches(taches.filter(filtre_t).distinct(), True)
    if admin and "echeances" in couches:
        for e in (EcheancePaiement.objects.filter(projet__societe=societe, date_prevue__gte=d0, date_prevue__lt=d1)
                  .exclude(statut="PAYEE").select_related("projet")):
            lecture_seule("echeances", e.pk, f"Échéance : {e.projet.nom} #{e.numero_echeance}", e.date_prevue,
                          reverse("gestion:crud", args=["echeances"]), f"{int(e.montant_prevu):,} FCFA".replace(",", " "))
    if admin and "factures" in couches:
        for f in Facture.objects.filter(societe=societe, statut="EMISE", date_echeance__gte=d0, date_echeance__lt=d1):
            lecture_seule("factures", f.pk, f"Facture {f.numero} — {f.client_nom}", f.date_echeance,
                          reverse("gestion:factures"), f"{int(f.total_ttc):,} FCFA à encaisser".replace(",", " "))
    if admin and "contrats" in couches:
        for c in ContratEmploye.objects.filter(employe__societe=societe, statut="ACTIF", date_fin__gte=d0, date_fin__lt=d1).select_related("employe"):
            lecture_seule("contrats", c.pk, f"Fin de contrat : {c.employe.prenom} {c.employe.nom}", c.date_fin,
                          reverse("gestion:employes"))
    return JsonResponse(sortie, safe=False)


@login_required
def rappels(request):
    """« À ne pas oublier » du compte connecté (sondé par toutes les pages) :
    - rendez-vous des prochaines 24 h où il est organisateur ou participant (heure du rappel incluse) ;
    - ses tâches ouvertes en retard, du jour ou du lendemain."""
    from .views import _societe_context

    societe, ctx, resp = _societe_context(request, "dashboard")
    if resp or not services.peut_acceder(request.user, societe, "planning"):
        return JsonResponse({"rendez_vous": [], "taches": []})
    moi = _moi(request, societe)
    maintenant = timezone.now()
    filtre = Q(organisateur=request.user)
    if moi:
        filtre |= Q(participants=moi)
    evs = (societe.evenements_agenda.filter(filtre, fin__gt=maintenant, debut__lt=maintenant + timedelta(hours=24))
           .distinct().order_by("debut")[:20])
    rendez_vous = []
    for ev in evs:
        debut = timezone.localtime(ev.debut)
        rendez_vous.append({
            "id": ev.pk, "titre": ev.titre, "lieu": ev.lieu, "journee": ev.journee_entiere,
            "debut": debut.isoformat(), "heure": "" if ev.journee_entiere else f"{debut:%H:%M}",
            "rappel": (debut - timedelta(minutes=ev.rappel_minutes)).isoformat() if ev.rappel_minutes else None,
            "en_cours": ev.debut <= maintenant,
        })
    taches = []
    if moi:
        aujourd_hui = timezone.localdate()
        for t in (Tache.objects.filter(societe=societe, assignee=moi, echeance__isnull=False,
                                       echeance__lte=aujourd_hui + timedelta(days=1))
                  .exclude(statut__in=("TERMINEE", "ANNULEE")).order_by("echeance")[:15]):
            ecart = (t.echeance - aujourd_hui).days
            taches.append({
                "id": t.pk, "titre": t.titre, "echeance": t.echeance.isoformat(),
                "etat": "retard" if ecart < 0 else ("jour" if ecart == 0 else "demain"),
                "priorite": t.priorite,
            })
    return JsonResponse({"rendez_vous": rendez_vous, "taches": taches, "planning": reverse("gestion:planning"),
                         "taches_url": reverse("gestion:taches"),
                         "maintenant": timezone.localtime(maintenant).isoformat()})


IMAGE_MAX = 4_000_000  # octets après décodage


def _image_depuis_data_url(valeur):
    """« data:image/png|jpeg;base64,… » (compressée dans le navigateur) → ContentFile vérifié, sinon None."""
    import base64
    import io
    import uuid

    from django.core.files.base import ContentFile
    from PIL import Image

    m = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/]+=*)", str(valeur or ""))
    if not m:
        return None
    try:
        octets = base64.b64decode(m.group(2))
        if len(octets) > IMAGE_MAX:
            return None
        with Image.open(io.BytesIO(octets)) as im:
            im.verify()
    except Exception:
        return None
    ext = "png" if m.group(1) == "png" else "jpg"
    return ContentFile(octets, name=f"{uuid.uuid4().hex[:16]}.{ext}")


def _date_heure(valeur, defaut=None):
    if not valeur:
        return defaut
    d = parse_datetime(valeur)
    if d is None:
        j = parse_date(valeur)
        if j is None:
            return defaut
        d = datetime.combine(j, time.min)
    if timezone.is_naive(d):
        d = timezone.make_aware(d)
    return d


@login_required
@require_POST
def sauver(request):
    """Création / modification / déplacement / suppression d'un événement (JSON)."""
    societe, ctx, resp = _ctx(request)
    if resp:
        return JsonResponse({"ok": False, "erreur": "Accès refusé."}, status=403)
    try:
        d = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "erreur": "Données invalides."}, status=400)
    action = d.get("action") or "enregistrer"
    if action in ("tache", "tache_statut"):
        return _sauver_tache(request, societe, d, action)
    ev = None
    if d.get("pk"):
        ev = societe.evenements_agenda.filter(pk=d["pk"]).first()
        if ev is None:
            raise Http404
        if not _peut_modifier(request, societe, ev):
            return JsonResponse({"ok": False, "erreur": "Seul l'organisateur peut modifier cet événement."}, status=403)
    if action == "supprimer":
        if ev:
            titre = ev.titre
            if ev.image:
                ev.image.delete(save=False)
            ev.delete()
            services.journaliser(societe, "SUPPRESSION", "planning", titre, "Événement supprimé", request.user)
        return JsonResponse({"ok": True})
    if action == "deplacer":
        if not ev:
            raise Http404
        journee = bool(d.get("journee"))
        debut = _date_heure(d.get("debut"), ev.debut)
        fin = _date_heure(d.get("fin"), None)
        if journee:
            j0 = timezone.localtime(debut).date()
            j1 = (timezone.localtime(fin).date() - timedelta(days=1)) if fin else j0  # fin exclusive côté calendrier
            ev.debut = timezone.make_aware(datetime.combine(j0, time.min))
            ev.fin = timezone.make_aware(datetime.combine(max(j1, j0), time(23, 59)))
        else:
            ev.debut = debut
            ev.fin = fin if fin and fin > debut else debut + timedelta(hours=1)
        ev.journee_entiere = journee
        ev.save(update_fields=["debut", "fin", "journee_entiere", "updated_at"])
        return JsonResponse({"ok": True})

    titre = str(d.get("titre") or "").strip()[:200]
    if not titre:
        return JsonResponse({"ok": False, "erreur": "Le titre est obligatoire."}, status=400)
    journee = bool(d.get("journee"))
    debut = _date_heure(d.get("debut"))
    fin = _date_heure(d.get("fin"))
    if debut is None:
        return JsonResponse({"ok": False, "erreur": "La date de début est obligatoire."}, status=400)
    if journee:
        debut = timezone.make_aware(datetime.combine(timezone.localtime(debut).date(), time.min))
        fin = timezone.make_aware(datetime.combine(timezone.localtime(fin or debut).date(), time(23, 59)))
    elif fin is None or fin <= debut:
        fin = debut + timedelta(hours=1)
    nouveau = ev is None
    if nouveau:
        ev = EvenementAgenda(societe=societe, organisateur=request.user)
    ev.titre = titre
    ev.description = str(d.get("description") or "")[:5000]
    ev.lieu = str(d.get("lieu") or "")[:255]
    ev.type_evenement = d.get("type") if d.get("type") in COULEURS_TYPE else "RDV"
    couleur = str(d.get("couleur") or "")
    ev.couleur = couleur if len(couleur) in (4, 7) and couleur.startswith("#") else ""
    ev.debut, ev.fin, ev.journee_entiere = debut, fin, journee
    ev.client = societe.clients.filter(pk=d.get("client") or 0).first()
    try:
        ev.rappel_minutes = int(d["rappel"]) if d.get("rappel") not in (None, "") else None
    except (TypeError, ValueError):
        ev.rappel_minutes = None
    if d.get("image"):
        fichier = _image_depuis_data_url(d["image"])
        if fichier is None:
            return JsonResponse({"ok": False, "erreur": "Image invalide (PNG ou JPG, 4 Mo maximum)."}, status=400)
        if ev.image:
            ev.image.delete(save=False)
        ev.image.save(fichier.name, fichier, save=False)
    elif d.get("image_supprimer") and ev.image:
        ev.image.delete(save=False)
    ev.save()
    ids = [int(x) for x in (d.get("participants") or []) if str(x).isdigit()]
    participants = list(societe.employes.filter(pk__in=ids))
    moi = _moi(request, societe)
    if nouveau and moi and moi not in participants and not _est_admin(request, societe):
        participants.append(moi)  # un employé est toujours dans son propre rendez-vous
    ev.participants.set(participants)
    services.journaliser(
        societe, "CREATION" if nouveau else "MODIFICATION", "planning", ev.titre,
        f"{timezone.localtime(ev.debut):%d/%m/%Y %H:%M}", request.user,
    )
    return JsonResponse({"ok": True, "pk": ev.pk})


def _sauver_tache(request, societe, d, action):
    """Tâches depuis le planning : un employé crée ses propres tâches, l'administration les attribue."""
    admin = _est_admin(request, societe)
    if services.en_lecture_seule(request.user, societe, "taches"):
        return JsonResponse({"ok": False, "erreur": "Accès en lecture seule aux tâches."}, status=403)
    moi = _moi(request, societe)
    t = None
    if d.get("pk"):
        t = Tache.objects.filter(societe=societe, pk=d["pk"]).first()
        if t is None:
            raise Http404
        if not admin and (moi is None or t.assignee_id != moi.pk):
            return JsonResponse({"ok": False, "erreur": "Vous ne pouvez modifier que vos propres tâches."}, status=403)
    if action == "tache_statut":
        statut = d.get("statut")
        if t is None or statut not in COULEURS_STATUT:
            return JsonResponse({"ok": False, "erreur": "Statut invalide."}, status=400)
        t.changer_statut(statut, request.user)
        if statut == "TERMINEE" and t.progres < 100:
            t.changer_progres(100, request.user)
        return JsonResponse({"ok": True})

    titre = str(d.get("titre") or "").strip()[:200]
    if not titre:
        return JsonResponse({"ok": False, "erreur": "Le titre de la tâche est obligatoire."}, status=400)
    echeance = parse_date(str(d.get("echeance") or ""))
    if echeance is None:
        return JsonResponse({"ok": False, "erreur": "Choisissez le jour de la tâche."}, status=400)
    debut = parse_date(str(d.get("debut") or "")) or echeance
    if debut > echeance:
        debut, echeance = echeance, debut
    if admin:
        assignee = societe.employes.filter(pk=d.get("assignee") or 0).first()
        if assignee is None:
            return JsonResponse({"ok": False, "erreur": "Choisissez l'employé à qui attribuer la tâche."}, status=400)
    else:
        if moi is None:
            return JsonResponse({"ok": False, "erreur": "Votre compte n'est lié à aucune fiche employé."}, status=403)
        assignee = moi  # un employé ne crée des tâches que pour lui-même
    nouveau = t is None
    if nouveau:
        t = Tache(societe=societe, cree_par=request.user)
    t.titre = titre
    t.description = str(d.get("description") or "")[:5000]
    t.assignee = assignee
    t.priorite = d.get("priorite") if d.get("priorite") in dict(PRIORITE_TACHE_CHOICES) else "MOYENNE"
    t.echeance = echeance
    t.date_debut = debut
    t.save()
    services.journaliser(societe, "CREATION" if nouveau else "MODIFICATION", "taches", t.titre,
                         f"{assignee.prenom} {assignee.nom} · {echeance:%d/%m/%Y}", request.user)
    return JsonResponse({"ok": True, "pk": t.pk})
