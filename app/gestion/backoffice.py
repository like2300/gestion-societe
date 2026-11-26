"""Back-office SaaS : espace épuré de l'équipe de la plateforme (comptes staff / superadmin).

- Vue d'ensemble : indicateurs, graphiques (inscriptions, revenus, forfaits), paiements à valider.
- Abonnements    : filtrer, activer, prolonger, suspendre, renvoyer le lien de paiement.
- Paiements      : valider (→ abonnement activé + e-mail) ou rejeter les paiements déclarés.
- Sociétés       : toutes les sociétés clientes et leur abonnement.
"""

from decimal import Decimal, InvalidOperation
from functools import wraps

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import abonnements
from .models import AbonnementSociete, Forfait, PaiementAbonnement, Societe

SEL_LIEN_ACTIVATION = "activation-societe"
DUREE_LIEN_ACTIVATION = 3600  # secondes


def equipe_saas(vue):
    """Administration de la plateforme : réservée aux superadmins."""
    @wraps(vue)
    def enveloppe(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_superuser:
            return HttpResponseForbidden("Espace réservé à l'équipe de la plateforme.")
        return vue(request, *args, **kwargs)
    return enveloppe


def _graphiques(st):
    """Géométrie SVG des graphiques (barres, courbe, anneau) calculée côté serveur."""
    n = len(st["labels"])
    larg, haut = 600, 180
    pas = larg / max(n, 1)
    maxi = max(st["inscriptions"] + [1])
    barres = [{"x": round(i * pas + pas * .2, 1), "w": round(pas * .6, 1),
               "h": round(v / maxi * (haut - 20), 1), "y": round(haut - v / maxi * (haut - 20), 1),
               "v": v, "label": st["labels"][i], "ty": round(haut - v / maxi * (haut - 20) - 5, 1)}
              for i, v in enumerate(st["inscriptions"])]
    maxr = max(st["revenus"] + [1])
    pts = [(round(i * pas + pas / 2, 1), round(haut - r / maxr * (haut - 24) - 4, 1)) for i, r in enumerate(st["revenus"])]
    courbe = " ".join(f"{x},{y}" for x, y in pts)
    aire = f"{pts[0][0]},{haut} " + courbe + f" {pts[-1][0]},{haut}" if pts else ""
    couleurs = ["#7cc23f", "#1f4a17", "#f26a2a", "#b9ec7c", "#a6aba6", "#e24a3b"]
    total = sum(v for _, v in st["repartition"]) or 1
    circ, cumul, anneau = 2 * 3.14159 * 54, 0, []
    for i, (nom, v) in enumerate(st["repartition"]):
        long = v / total * circ
        anneau.append({"nom": nom, "v": v, "pct": round(v / total * 100), "couleur": couleurs[i % len(couleurs)],
                       "dash": f"{long:.1f} {circ - long:.1f}", "offset": f"{-cumul:.1f}"})
        cumul += long
    # Coordonnées en texte (point décimal) : la localisation française afficherait « 12,5 » dans le SVG
    f = lambda v: f"{float(v):.1f}"  # noqa: E731
    for b in barres:
        b.update({k: f(b[k]) for k in ("x", "w", "h", "y", "ty")})
    pts = [(f(x), f(y)) for x, y in pts]
    return {"barres": barres, "courbe": courbe, "aire": aire,
            "points": [{"x": x, "y": y, "v": st["revenus"][i], "label": st["labels"][i]} for i, (x, y) in enumerate(pts)],
            "anneau": anneau, "larg": larg, "haut": haut, "max_revenus": maxr}


@equipe_saas
def index(request):
    st = abonnements.statistiques()
    periode = request.GET.get("periode") if request.GET.get("periode") in ("jour", "mois", "annee") else "mois"
    jour = parse_date(request.GET.get("date") or "") or timezone.localdate()
    ventes = abonnements.ventes(periode, jour)
    devise = request.GET.get("devise") if request.GET.get("devise") in ("USD", "XAF", "XOF") else "USD"
    taux = 1 if devise == "USD" else float(settings.TAUX_USD.get(devise, 1))
    return render(request, "backoffice/index.html", {
        "section": "index", "st": st, "g": _graphiques(st), "v": ventes, "vg": _barres_ventes(ventes, taux),
        "devise": devise, "taux": taux, "periode": periode, "jour": jour,
        "nav_precedent": _decaler(periode, jour, -1), "nav_suivant": _decaler(periode, jour, 1),
        "demandes": abonnements.demandes_en_attente()[:6],
        "a_valider": PaiementAbonnement.objects.filter(statut="EN_ATTENTE")
                     .select_related("abonnement__societe", "abonnement__forfait", "mode_paiement").order_by("-pk")[:8],
        "recentes": Societe.objects.select_related("createur").order_by("-created_at")[:6],
    })


def _decaler(periode, jour, sens):
    """Date de la période précédente / suivante (navigation ‹ ›)."""
    if periode == "jour":
        return jour + timedelta(days=sens)
    if periode == "annee":
        return jour.replace(year=jour.year + sens, month=1, day=1)
    d = jour.replace(day=1)
    return (d + timedelta(days=32)).replace(day=1) if sens > 0 else (d - timedelta(days=1)).replace(day=1)


def _barres_ventes(v, taux):
    """Barres SVG des ventes de la période (coordonnées en texte, montants convertis)."""
    vals = [x * taux for x in v["valeurs"]]
    n, larg, haut = max(len(vals), 1), 640, 170
    pas, maxi = larg / n, max(vals + [1])
    return [{"x": f"{i * pas + pas * .18:.1f}", "w": f"{pas * .64:.1f}", "h": f"{max(x / maxi * (haut - 10), 3 if x else 2):.1f}",
             "y": f"{haut - max(x / maxi * (haut - 10), 3 if x else 2):.1f}", "v": x, "label": v["labels"][i],
             "plein": bool(x), "lx": f"{i * pas + pas / 2:.1f}", "montre": n <= 12 or i % 5 == 0 or i == n - 1}
            for i, x in enumerate(vals)]


@equipe_saas
def liste_demandes(request):
    """Demandes à traiter : nouvelles offres payantes et changements d'offre."""
    return render(request, "backoffice/demandes.html", {
        "section": "demandes", "demandes": abonnements.demandes_en_attente(),
        "traitees": (AbonnementSociete.objects.filter(ancien_forfait__isnull=False).exclude(statut="EN_ATTENTE")
                     .select_related("societe", "forfait", "ancien_forfait").order_by("-created_at")[:15]),
    })


@equipe_saas
def liste_abonnements(request):
    abonnements.expirer_les_echus()
    statut = request.GET.get("statut") or ""
    q = (request.GET.get("q") or "").strip()
    qs = AbonnementSociete.objects.select_related("societe", "forfait", "societe__createur").order_by("-created_at", "-pk")
    if statut:
        qs = qs.filter(statut=statut)
    if q:
        qs = qs.filter(Q(societe__nom__icontains=q) | Q(societe__createur__email__icontains=q))
    return render(request, "backoffice/abonnements.html", {
        "section": "abonnements", "abonnements": qs[:200], "statut": statut, "q": q,
        "statuts": AbonnementSociete._meta.get_field("statut").choices,
    })


@equipe_saas
@require_POST
def action_abonnement(request, pk, action):
    abo = get_object_or_404(AbonnementSociete.objects.select_related("societe", "forfait"), pk=pk)
    if action in ("activer", "prolonger", "encaisser", "offrir"):
        # encaisser : paiement reçu hors ligne (compté dans les ventes) ; offrir / activer : sans encaissement
        abonnements.activer(abo, request=request, encaisse=(action == "encaisser"))
        messages.success(request, f"{abo.societe.nom} : {abo.forfait.nom} actif jusqu'au {abo.date_fin:%d/%m/%Y}"
                                  + (" — paiement encaissé." if action == "encaisser" else "."))
    elif action == "refuser":
        abonnements.refuser(abo)
        messages.success(request, f"Demande de {abo.societe.nom} refusée.")
    elif action == "suspendre":
        abonnements.suspendre(abo)
        messages.success(request, f"{abo.societe.nom} : abonnement suspendu.")
    elif action == "relancer":
        ok = abonnements._envoyer(
            f"Votre abonnement {abo.forfait.nom} — {abo.societe.nom}", "societe_creee",
            {"societe": abo.societe, "abonnement": abo, "forfait": abo.forfait, "gratuit": not abo.forfait.prix,
             "lien": abonnements.lien_paiement(abo, request), "prenom": getattr(abo.societe.createur, "prenom", "")},
            getattr(abo.societe.createur, "email", ""))
        (messages.success if ok else messages.error)(request, "Lien de paiement renvoyé." if ok else "Envoi de l'e-mail impossible.")
    return redirect(request.META.get("HTTP_REFERER") or "backoffice:abonnements")


@equipe_saas
def liste_paiements(request):
    statut = request.GET.get("statut", "EN_ATTENTE")
    qs = PaiementAbonnement.objects.select_related("abonnement__societe", "abonnement__forfait", "mode_paiement").order_by("-pk")
    if statut:
        qs = qs.filter(statut=statut)
    return render(request, "backoffice/paiements.html", {"section": "paiements", "paiements": qs[:200], "statut": statut})


@equipe_saas
@require_POST
def action_paiement(request, pk, action):
    p = get_object_or_404(PaiementAbonnement.objects.select_related("abonnement__societe", "abonnement__forfait"), pk=pk)
    if p.statut == "EN_ATTENTE":
        if action == "valider":
            abonnements.activer(p.abonnement, p, request)
            messages.success(request, f"Paiement validé : {p.abonnement.societe.nom} est actif.")
        elif action == "rejeter":
            p.statut = "ANNULE"
            p.save(update_fields=["statut"])
            messages.success(request, "Paiement rejeté.")
    return redirect(request.META.get("HTTP_REFERER") or "backoffice:paiements")


@equipe_saas
def liste_societes(request):
    q = (request.GET.get("q") or "").strip()
    qs = Societe.objects.select_related("createur").order_by("-created_at")
    if q:
        qs = qs.filter(Q(nom__icontains=q) | Q(createur__email__icontains=q))
    lignes = []
    for s in qs[:300]:
        abo = abonnements.courant(s)
        lignes.append({"s": s, "abo": abo, "employes": s.employes.count()})
    return render(request, "backoffice/societes.html", {
        "section": "societes",
        "lignes": lignes,
        "q": q,
        "en_attente": abonnements.demandes_en_attente(),
    })


@equipe_saas
@require_POST
def lien_activation_societe(request, pk):
    """Crée un lien signé valable 1 h, lié au compte de l'administrateur connecté."""
    abo = get_object_or_404(abonnements.demandes_en_attente(), pk=pk)
    jeton = signing.dumps({"abo": abo.pk, "admin": request.user.pk}, salt=SEL_LIEN_ACTIVATION)
    chemin = reverse("backoffice:activer_societe", args=[jeton])
    return JsonResponse({
        "lien": request.build_absolute_uri(chemin),
        "societe": abo.societe.nom,
        "expire": (timezone.now() + timedelta(seconds=DUREE_LIEN_ACTIVATION)).strftime("%H:%M"),
    })


@require_GET
def activer_societe(request, jeton):
    """Active une société après connexion du compte qui a généré le lien."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    try:
        donnees = signing.loads(jeton, salt=SEL_LIEN_ACTIVATION, max_age=DUREE_LIEN_ACTIVATION)
    except signing.BadSignature:
        messages.error(request, "Lien d'activation invalide ou expiré.")
        return redirect("backoffice:societes")
    if not request.user.is_superuser or donnees.get("admin") != request.user.pk:
        return HttpResponseForbidden("Ce lien est réservé au compte qui l'a généré.")
    abo = get_object_or_404(AbonnementSociete, pk=donnees.get("abo"))
    if abo.statut != "EN_ATTENTE":
        messages.info(request, f"{abo.societe.nom} : la demande n'est plus en attente.")
    else:
        abonnements.activer(abo, request=request)
        messages.success(request, f"{abo.societe.nom} activée. Abonnement {abo.forfait.nom} actif.")
    return redirect("backoffice:societes")


DEVISES_FORFAIT = ("USD", "XOF", "XAF", "EUR")


def _valider_forfait(post, exclude_pk=None):
    """Valide les champs d'un forfait soumis depuis le back-office."""
    nom = (post.get("nom") or "").strip()
    if not nom:
        return None, "Le nom du forfait est obligatoire."
    if len(nom) > 100:
        return None, "Le nom du forfait ne peut pas dépasser 100 caractères."
    qs = Forfait.objects.filter(nom__iexact=nom)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        return None, f"Un forfait nommé « {nom} » existe déjà."

    prix_brut = (post.get("prix") or "0").strip().replace(",", ".").replace(" ", "")
    try:
        prix = Decimal(prix_brut).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None, "Le prix saisi est invalide."
    if prix < 0:
        return None, "Le prix ne peut pas être négatif."

    devise = (post.get("devise") or "USD").strip().upper()[:10]
    if devise not in DEVISES_FORFAIT:
        return None, "Devise non supportée."

    try:
        duree = int((post.get("duree_jours") or "").strip())
    except ValueError:
        return None, "La durée en jours doit être un entier."
    if duree < 1:
        return None, "La durée doit être d'au moins 1 jour."

    return {
        "nom": nom,
        "prix": prix,
        "devise": devise,
        "duree_jours": duree,
        "description": (post.get("description") or "").strip(),
        "actif": post.get("actif") == "on",
    }, None


@equipe_saas
def liste_forfaits(request):
    """Liste et édition directe des forfaits et tarifs du programme."""
    forfaits = (
        Forfait.objects.annotate(
            nb_actifs=Count("abonnements", filter=Q(abonnements__statut="ACTIF"))
        )
        .order_by("prix", "nom")
    )
    return render(request, "backoffice/forfaits.html", {
        "section": "forfaits",
        "forfaits": forfaits,
        "devises": DEVISES_FORFAIT,
    })


@equipe_saas
@require_POST
def creer_forfait(request):
    data, erreur = _valider_forfait(request.POST)
    if erreur:
        messages.error(request, erreur)
        return redirect("backoffice:forfaits")
    forfait = Forfait.objects.create(**data)
    messages.success(request, f"Forfait « {forfait.nom} » créé ({forfait.prix_affiche}).")
    return redirect("backoffice:forfaits")


@equipe_saas
@require_POST
def modifier_forfait(request, pk):
    forfait = get_object_or_404(Forfait, pk=pk)
    data, erreur = _valider_forfait(request.POST, exclude_pk=forfait.pk)
    if erreur:
        messages.error(request, erreur)
        return redirect("backoffice:forfaits")
    for champ, valeur in data.items():
        setattr(forfait, champ, valeur)
    forfait.save()
    messages.success(request, f"Tarif « {forfait.nom} » mis à jour : {forfait.prix_affiche} / {forfait.duree_jours} jours.")
    return redirect("backoffice:forfaits")


@equipe_saas
@require_POST
def toggle_forfait(request, pk):
    forfait = get_object_or_404(Forfait, pk=pk)
    forfait.actif = not forfait.actif
    forfait.save(update_fields=["actif"])
    etat = "activé" if forfait.actif else "masqué du site public"
    messages.success(request, f"Forfait « {forfait.nom} » {etat}.")
    return redirect("backoffice:forfaits")
