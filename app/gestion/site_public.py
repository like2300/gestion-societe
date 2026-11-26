"""Site vitrine public + page de paiement de l'abonnement (lien reçu par e-mail).

- ``accueil``          : présentation du logiciel, fonctionnalités, tarifs (forfaits actifs), FAQ.
- ``choisir_forfait``  : mémorise le forfait choisi puis envoie vers l'inscription
                         (ou directement vers la création de la société si déjà connecté).
- ``payer``            : page publique protégée par le jeton de l'abonnement :
                         Mobile Money (KPay) avec vérification, ou paiement déclaré
                         (virement…) validé ensuite dans le back-office.
"""

import time

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import abonnements, kpay, services
from .models import AbonnementSociete, Avis, Forfait, ImageSite, IMAGES_VITRINE_DEFAUT

SESSION_FORFAIT = "forfait_choisi"

FONCTIONNALITES = [
    ("users", "Équipe & RH", "Fiches employés, contrats générés automatiquement, permissions fines en lecture ou modification."),
    ("briefcase", "Clients & projets", "Portefeuille clients, prospection, projets et échéances de paiement suivis au même endroit."),
    ("wallet", "Finances & factures", "Paiements, dépenses, salaires, factures PDF et encaissement Mobile Money."),
    ("calendar", "Planning", "Agenda personnel, rendez-vous de groupe, rappels et tâches à ne pas oublier."),
    ("grid", "Applications intégrées", "Tableur, documents et présentations avec images, exports Excel, Word, PowerPoint et PDF."),
    ("spark", "Assistant IA", "Posez une question : il analyse vos chiffres, rédige vos rapports et planifie pour vous."),
    ("chat", "Messagerie & groupes", "Discussions privées et groupes d'équipe avec fichiers et notes vocales."),
    ("shield", "Sécurité", "Données isolées par société, documents confidentiels protégés, journal d'activité."),
]

INCLUS = [
    "Tous les modules (équipe, clients, finances, planning)",
    "Tableur, Documents et Présentations",
    "Assistant IA",
    "Messagerie et groupes d'équipe",
    "Permissions par employé (lecture / modification)",
    "Exports PDF, Excel, Word et PowerPoint",
]

FAQ = [
    ("Puis-je essayer gratuitement ?", "Oui : le forfait gratuit donne accès à la plateforme pendant sa durée, sans moyen de paiement."),
    ("Comment payer mon abonnement ?", "Après la création de votre société, vous recevez un e-mail avec un lien de paiement : Mobile Money ou virement."),
    ("Mes données sont-elles protégées ?", "Chaque société est isolée ; les documents confidentiels ne sont accessibles qu'aux personnes autorisées."),
    ("Mes employés ont-ils un accès ?", "Oui : chaque employé reçoit son compte et ne voit que les modules que vous lui ouvrez."),
]

def images_site():
    """URL des images de la vitrine : fichier chargé dans l'admin ou image d'origine."""
    objets = {i.code: i for i in ImageSite.objects.all()}
    return {
        code: (objets[code].image.url if code in objets and objets[code].image
               else static(defaut) if defaut else "")
        for code, defaut in IMAGES_VITRINE_DEFAUT.items()
    }


def accueil(request):
    forfaits = list(abonnements.forfaits_publics())
    populaire = max(forfaits, key=lambda f: f.prix).pk if len(forfaits) > 1 else None
    connecte = request.user.is_authenticated
    return render(request, "vitrine/accueil.html", {
        "forfaits": forfaits, "populaire": populaire, "fonctionnalites": FONCTIONNALITES,
        "inclus": INCLUS, "faq": FAQ, "connecte": connecte,
        "images": images_site(),
        "avis": Avis.objects.filter(actif=True)[:12],
        "espace_url": reverse("gestion:post_login_redirect") if connecte else "",
    })


def choisir_forfait(request, pk):
    forfait = get_object_or_404(Forfait, pk=pk, actif=True)
    request.session[SESSION_FORFAIT] = forfait.pk
    if not request.user.is_authenticated:
        return redirect(reverse("account_signup") + f"?forfait={forfait.pk}")
    # Un superadmin propriétaire d'une société passe par societes_creees (comme le reste de l'app)
    societe = services.societe_pour_utilisateur(request.user) or request.user.societes_creees.first()
    if societe is None:
        return redirect("gestion:societe_create")
    request.session.pop(SESSION_FORFAIT, None)
    if not services.est_createur(request.user, societe):
        messages.error(request, "Seul le propriétaire de la société peut changer d'offre.")
        return redirect("gestion:dashboard")
    # Société existante : demande de changement d'offre (en attente d'activation ou de paiement)
    en_cours = societe.abonnements.filter(statut="EN_ATTENTE").first()
    if en_cours and en_cours.forfait_id == forfait.pk:
        return redirect("abonnement_payer", jeton=en_cours.jeton) if forfait.prix else redirect("gestion:mon_abonnement")
    actif = societe.abonnements.filter(statut="ACTIF").select_related("forfait").first()
    if actif and actif.forfait_id == forfait.pk:
        messages.info(request, f"Vous êtes déjà sur le forfait {forfait.nom}.")
        return redirect("gestion:mon_abonnement")
    # Une seule demande à la fois : la précédente est remplacée
    for ancienne in societe.abonnements.filter(statut="EN_ATTENTE"):
        abonnements.refuser(ancienne)
    dernier = actif or societe.abonnements.select_related("forfait").order_by("-created_at", "-pk").first()
    abo = abonnements.demarrer(societe, forfait, request, ancien=dernier.forfait if dernier else None)
    messages.success(request, f"Demande envoyée : passage au forfait {forfait.nom}.")
    return redirect("abonnement_payer", jeton=abo.jeton) if forfait.prix else redirect("gestion:mon_abonnement")


def forfait_en_session(request):
    """Forfait choisi sur le site (session), consommé à la création de la société."""
    pk = request.session.pop(SESSION_FORFAIT, None)
    return Forfait.objects.filter(pk=pk, actif=True).first() if pk else None


@require_http_methods(["GET", "POST"])
def payer(request, jeton):
    abo = get_object_or_404(AbonnementSociete.objects.select_related("societe", "forfait"), jeton=jeton)
    abonnements.courant(abo.societe)  # applique l'expiration éventuelle
    abo.refresh_from_db()
    paiement_kpay = abo.paiements.filter(statut="EN_ATTENTE").exclude(kpay_id="").order_by("-pk").first()
    declare = abo.paiements.filter(statut="EN_ATTENTE", kpay_id="").order_by("-pk").first()
    if request.method == "POST" and abo.forfait.prix and abo.statut != "SUSPENDU":
        action = request.POST.get("action")
        if action == "mobile":
            tel = kpay.normaliser_telephone(request.POST.get("telephone") or "")
            provider = request.POST.get("provider") or ""
            if not tel or provider not in {p[0] for p in kpay.PROVIDERS}:
                messages.error(request, "Indiquez votre numéro et votre opérateur Mobile Money.")
                return redirect("abonnement_payer", jeton=abo.jeton)
            monnaie = {p[0]: p[3] for p in kpay.PROVIDERS}[provider]
            montant = abonnements.montant_local(abo.forfait.prix, abo.forfait.devise, monnaie)
            if not montant:
                messages.error(request, f"Paiement en {monnaie} indisponible pour le moment : déclarez votre paiement ci-dessous.")
                return redirect("abonnement_payer", jeton=abo.jeton)
            ok, data = kpay.init_depot(montant, provider, tel, f"abo-{abo.pk}-{int(time.time())}",
                                       f"Abonnement {abo.forfait.nom} ({abo.forfait.prix_affiche}) — {abo.societe.nom}",
                                       metadata={"prix": str(abo.forfait.prix), "devise": abo.forfait.devise,
                                                 "montant_local": montant, "monnaie": monnaie})
            if ok:
                abonnements.declarer_paiement(abo, "Mobile Money", reference=str(data.get("id", "")),
                                              telephone=tel, kpay_id=str(data.get("id", "")))
                messages.success(request, "Demande envoyée : validez le paiement sur votre téléphone, puis cliquez sur « J'ai validé ».")
            else:
                messages.error(request, data.get("message") or "Paiement Mobile Money impossible.")
        elif action == "verifier" and paiement_kpay:
            ok, data = kpay.statut_depot(paiement_kpay.kpay_id)
            statut = str((data or {}).get("status") or "").upper()
            if ok and statut == "COMPLETED":
                abonnements.activer(abo, paiement_kpay, request)
                messages.success(request, "Paiement reçu : votre abonnement est actif. Merci !")
            elif ok and statut in ("FAILED", "CANCELLED", "EXPIRED"):
                paiement_kpay.statut = "ANNULE"
                paiement_kpay.save(update_fields=["statut"])
                messages.error(request, "Le paiement n'a pas abouti. Vous pouvez réessayer.")
            else:
                messages.info(request, "Paiement pas encore confirmé : validez-le sur votre téléphone puis réessayez.")
        elif action == "declarer":
            reference = (request.POST.get("reference") or "").strip()
            if not reference:
                messages.error(request, "Indiquez la référence de votre virement ou transaction.")
            else:
                abonnements.declarer_paiement(abo, request.POST.get("mode") or "Virement bancaire", reference=reference)
                messages.success(request, "Merci ! Votre paiement est en cours de vérification ; vous recevrez un e-mail dès l'activation.")
        return redirect("abonnement_payer", jeton=abo.jeton)
    return render(request, "vitrine/payer.html", {
        "images": images_site(),
        "abo": abo, "societe": abo.societe, "forfait": abo.forfait,
        "kpay_ok": kpay.configuree(), "providers": kpay.PROVIDERS,
        "equivalents": abonnements.equivalents_locaux(abo.forfait),
        "paiement_kpay": paiement_kpay, "declare": declare,
        "modes": ["Virement bancaire", "Mobile Money", "Espèces", "Chèque"],
    })
