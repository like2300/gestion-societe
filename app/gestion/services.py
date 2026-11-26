"""Helpers métier : paie, dépenses de salaires, échéances/paiements, synthèse financière."""

from datetime import date, timedelta

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .models import (
    ActivitePlateforme,
    Client,
    ContratEmploye,
    DepenseSociete,
    EcheancePaiement,
    Employe,
    EquipeConversation,
    EquipeMessage,
    ModePaiement,
    PaiementClient,
    PaiementSalaire,
    ProjetClient,
    ProjetObjectif,
    Rappel,
    SOURCE_CLIENT_CHOICES,
    SocieteDocument,
    Tache,
    TacheEvolution,
    TacheLivrable,
    TypeClient,
    TypeDepense,
    UserAdmin,
)
from .perm import ALL_MODULE_KEYS, DEFAULT_EMPLOYE_PERMS


# ---------------------------------------------------------------------------
# Présence : employés « en ligne »
# ---------------------------------------------------------------------------

EN_LIGNE_DELAI = 120  # secondes sans activité -> hors ligne


def etats_connexion_en_ligne(societe):
    """Employés « en ligne » : présence ouverte dont la session existe encore
    **et** dont la dernière activité est récente (< EN_LIGNE_DELAI).

    L'activité est rafraîchie par le navigateur (heartbeat) tant que la
    personne navigue dans la plateforme : dès qu'elle ferme/masque l'onglet,
    l'activité vieillit et le badge bascule « hors ligne ».
    """
    from django.contrib.sessions.models import Session

    maintenant = timezone.now()
    ouvertes = list(
        societe.presences.filter(date_deconnexion__isnull=True)
        .order_by("employe_id", "-date_connexion")
    )
    cles = [p.session_key for p in ouvertes if p.session_key]
    actives = set(
        Session.objects.filter(
            session_key__in=cles, expire_date__gt=maintenant
        ).values_list("session_key", flat=True)
    )
    etats = {}
    for p in ouvertes:
        if p.employe_id in etats:
            continue
        recente = bool(
            p.derniere_activite
            and (maintenant - p.derniere_activite).total_seconds() < EN_LIGNE_DELAI
        )
        etats[p.employe_id] = bool(
            p.session_key and p.session_key in actives and recente
        )
    return etats


# ---------------------------------------------------------------------------
# Accès : société de l'utilisateur, rôle employé et modules autorisés
# ---------------------------------------------------------------------------

# Pages accessibles à tout compte relié à une société, indépendamment des
# permissions employé (tableau de bord, assistant IA et profil personnel).
PAGES_TOUJOURS_ACCESSIBLES = {"dashboard", "ai", "profil", "compte", "planning", "groupes"}


def societe_pour_utilisateur(user):
    """Société d'un compte : celle qu'il a créée, sinon celle de son employé.

    Retourne None pour un visiteur anonyme, un super-utilisateur ou un compte
    pas encore relié à une société (invitation en attente, par exemple).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return None
    societe = user.societes_creees.first()
    if societe is not None:
        return societe
    employe = getattr(user, "employe_profil", None)
    if employe is not None:
        return employe.societe
    return None


def societe_pour_notifications(user):
    """Société dont le compte consulte le journal d'activité (cloche).

    ``societe_pour_utilisateur`` exclut volontairement le super-utilisateur de
    l'usage général ; or un super-utilisateur peut être propriétaire d'une
    société (créateur) et se connecte alors à l'application. Ses notifications
    doivent s'afficher comme celles de n'importe quel créateur. Retourne donc
    sa propre société (``societes_creees.first()``), sinon ``None``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return user.societes_creees.first()
    return societe_pour_utilisateur(user)


def est_compte_employe(user):
    """Vrai si le compte a été créé en tant qu'employé.

    Un compte « employé » rejoint une société existante : il ne peut pas créer
    sa propre société.
    """
    return getattr(user, "role_admin", None) == "EMPLOYE"


def est_employe(user, societe):
    """Vrai si `user` est un employé (non créateur) relié à `societe`."""
    if user is None or getattr(user, "is_superuser", False):
        return False
    if getattr(societe, "createur_id", None) == getattr(user, "pk", None):
        return False
    employe = getattr(user, "employe_profil", None)
    return employe is not None and employe.societe_id == getattr(societe, "pk", None)


def est_createur(user, societe):
    """Vrai si `user` est le créateur (propriétaire) de `societe`.

    Un super-utilisateur qui a fondé la société est son propriétaire à part
    entière (il profite de l'application comme un créateur).
    """
    if user is None or not getattr(user, "pk", None):
        return False
    return getattr(societe, "createur_id", None) == getattr(user, "pk", None)


def employe_pour_utilisateur(user, societe):
    """Fiche Employe reliée au compte `user` dans `societe` (sinon None)."""
    employe = getattr(user, "employe_profil", None)
    if employe is not None and employe.societe_id == getattr(societe, "pk", None):
        return employe
    return None


def peut_creer_groupe(user, societe):
    """Propriétaire, ou employé ayant reçu la permission « Créer des groupes »."""
    if est_createur(user, societe):
        return True
    employe = employe_pour_utilisateur(user, societe)
    return employe is not None and "groupes" in (employe.permissions or [])


def peut_administrer_groupe(user, societe, groupe):
    """Propriétaire, créateur du groupe ou membre désigné administrateur du groupe."""
    if groupe is None:
        return False
    if est_createur(user, societe) or groupe.cree_par_id == getattr(user, "pk", None):
        return True
    employe = employe_pour_utilisateur(user, societe)
    return employe is not None and groupe.membres.filter(employe_id=employe.pk, est_admin=True).exists()


def groupes_visibles(user, societe):
    """Groupes visibles : tous pour le propriétaire, sinon ceux dont on est membre ou créateur."""
    qs = societe.equipe_groupes.all()
    if est_createur(user, societe):
        return qs
    filtre = Q(cree_par_id=getattr(user, "pk", None))
    employe = employe_pour_utilisateur(user, societe)
    if employe is not None:
        filtre |= Q(membres__employe_id=employe.pk)
    return qs.filter(filtre).distinct()


def est_membre_groupe(user, societe, groupe):
    """Vrai si `user` peut voir un groupe : propriétaire, créateur du groupe ou employé membre."""
    if est_createur(user, societe):
        return True
    if groupe is None:
        return False
    if groupe.cree_par_id == getattr(user, "pk", None):
        return True
    employe = employe_pour_utilisateur(user, societe)
    if employe is None:
        return False
    return groupe.membres.filter(employe_id=employe.pk).exists()


def _relier_compte(employe, user):
    """Relie `user` à la fiche `employe` (compte, rôle, messages existants)."""
    if employe.compte_id == user.pk:
        return user
    employe.compte = user
    champs = ["compte"]
    if not employe.permissions:
        employe.permissions = list(DEFAULT_EMPLOYE_PERMS)
        champs.append("permissions")
    employe.save(update_fields=champs)
    if getattr(user, "role_admin", None) != "EMPLOYE":
        user.role_admin = "EMPLOYE"
        user.save(update_fields=["role_admin"])
    rattacher_conversations_employe(employe, user)
    return user


def lier_comptes_utilisateur(user):
    """Relie automatiquement `user` aux fiches employé non liées de son email.

    Rend le chat automatique : dès qu'un compte possède l'email d'une fiche
    employé, il y est relié sans aucune action manuelle.
    """
    if user is None or not getattr(user, "pk", None):
        return
    if getattr(user, "is_superuser", False):
        return
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return
    if getattr(user, "employe_profil", None) is not None:
        return
    if user.societes_creees.exists():
        return
    fiches = Employe.objects.filter(
        email__iexact=email, compte__isnull=True
    ).select_related("societe")
    for employe in fiches:
        if employe.societe is None or employe.societe.createur_id == user.pk:
            continue
        _relier_compte(employe, user)


def assurer_compte_employe(employe):
    """Garantit qu'une fiche employé dispose d'un compte de connexion relié.

    - si un compte existe déjà avec cet email : on le relie ;
    - sinon on crée un compte « Employé » avec le mot de passe par défaut
      (``settings.EMPLOYE_MOT_DE_PASSE_DEFAUT``) ; à sa première connexion,
      l'employé est invité à définir son propre mot de passe.

    Retourne le compte relié, ou None si la création/le lien est impossible.
    """
    if employe is None:
        return None
    if employe.compte_id:
        return employe.compte
    email = (employe.email or "").strip()
    societe = employe.societe
    if not email or societe is None:
        return None
    createur = societe.createur
    if createur is not None and (createur.email or "").strip().lower() == email.lower():
        return None
    user = UserAdmin.objects.filter(email__iexact=email).first()
    if user is None:
        user = UserAdmin(
            email=email,
            nom=employe.nom or "",
            prenom=employe.prenom or "",
            telephone_1=employe.telephone_1 or "",
            telephone_2=employe.telephone_2 or "",
            role_admin="EMPLOYE",
        )
        mdp = getattr(settings, "EMPLOYE_MOT_DE_PASSE_DEFAUT", "") or ""
        if mdp:
            user.set_password(mdp)
            user.doit_changer_mdp = True
        else:
            user.set_unusable_password()
        user.save()
    else:
        if user.is_superuser or societe.createur_id == user.pk:
            return None
        existant = getattr(user, "employe_profil", None)
        if existant is not None and existant.pk != employe.pk:
            return None
        if user.societes_creees.exists():
            return None
    return _relier_compte(employe, user)


def rattacher_conversations_employe(employe, user):
    """Ajoute `user` aux conversations existantes de la fiche `employe`.

    Appelé quand un compte est relié à une fiche employé : le compte doit
    pouvoir lire les messages qui lui étaient destinés (anciens fils migrés).
    """
    if employe is None or user is None or not getattr(user, "pk", None):
        return
    conv_ids = list(
        EquipeMessage.objects.filter(employe=employe, conversation__isnull=False)
        .values_list("conversation_id", flat=True)
        .distinct()
    )
    for conversation in EquipeConversation.objects.filter(pk__in=conv_ids):
        conversation.participants.add(user)


def est_participant_conversation(user, conversation):
    """Vrai si `user` fait partie des participants d'une conversation privée."""
    if conversation is None or user is None or not getattr(user, "pk", None):
        return False
    return conversation.participants.filter(pk=user.pk).exists()


def conversation_entre(societe, user_a, user_b):
    """Conversation privée entre `user_a` et `user_b` (créée si besoin).

    `user_b` peut être None (employé sans compte) : la conversation ne
    contient alors que `user_a`.
    """
    if societe is None or user_a is None or not getattr(user_a, "pk", None):
        return None
    if user_b is not None and user_b.pk == user_a.pk:
        user_b = None
    qs = EquipeConversation.objects.filter(societe=societe, participants=user_a)
    if user_b is not None:
        candidats = qs.filter(participants=user_b)
        attendu = 2
    else:
        candidats = qs
        attendu = 1
    for conversation in candidats:
        if conversation.participants.count() == attendu:
            return conversation
    conversation = EquipeConversation.objects.create(societe=societe)
    conversation.participants.add(user_a)
    if user_b is not None:
        conversation.participants.add(user_b)
    return conversation


def conversation_pour_fiche(societe, user, employe, creer=True):
    """Conversation privée entre `user` et la fiche `employe`.

    - fiche reliée à un compte : conversation entre les deux comptes ;
    - fiche sans compte : fil « en attente », propre à `user` et rattaché à
      cette fiche. Il devient une vraie conversation à deux dès que la fiche
      reçoit un compte (`rattacher_conversations_employe`).

    `creer=False` permet de lire sans créer de fil vide.
    """
    if societe is None or user is None or employe is None:
        return None
    if employe.compte_id is not None:
        return conversation_entre(societe, user, employe.compte)
    conversation = (
        EquipeConversation.objects.filter(
            societe=societe, participants=user, messages__employe=employe
        )
        .distinct()
        .first()
    )
    if conversation is None and creer:
        conversation = EquipeConversation.objects.create(societe=societe)
        conversation.participants.add(user)
    return conversation


def partager_reunion(societe, reunion, utilisateur):
    """Partage le lien Meet de la réunion dans la messagerie interne.

    Un message privé avec le lien est posté dans le fil de chaque participant
    disposant d'un compte (via ``conversation_pour_fiche``). Le partage dans
    les notifications est assuré par l'appelant (``journaliser`` module
    ``reunions``). Retourne le nombre de messages envoyés.
    """
    if societe is None or reunion is None or not reunion.lien_meet:
        return 0
    contenu = (
        f"🔗 Réunion : {reunion.titre} — {reunion.date_aff} à {reunion.heure_aff} "
        f"(durée : {reunion.duree} min). Participez : {reunion.lien_meet}"
    )
    envoyes = 0
    for employe in reunion.participants.select_related("compte"):
        if employe.compte_id is None or employe.compte_id == getattr(
            utilisateur, "pk", None
        ):
            continue
        conversation = conversation_pour_fiche(
            societe, utilisateur, employe, creer=True
        )
        if conversation is None:
            continue
        EquipeMessage.objects.create(
            societe=societe,
            conversation=conversation,
            employe=employe,
            auteur=utilisateur,
            contenu=contenu[:4000],
        )
        envoyes += 1
    return envoyes


def module_actif(cle):
    """False si le module est désactivé pour toute l'application (settings)."""
    return cle not in getattr(settings, "MODULES_DESACTIVES", ())


def modules_autorises(user, societe):
    """Clés des modules de la barre latérale autorisés pour ce compte."""
    if user is None:
        return []
    if getattr(user, "is_superuser", False) or getattr(societe, "createur_id", None) == getattr(user, "pk", None):
        return [cle for cle in ALL_MODULE_KEYS if module_actif(cle)]
    employe = getattr(user, "employe_profil", None)
    if employe is not None and employe.societe_id == getattr(societe, "pk", None):
        permissions = employe.permissions or list(DEFAULT_EMPLOYE_PERMS)
        return [cle for cle in permissions if cle in ALL_MODULE_KEYS and module_actif(cle)]
    return ["dashboard"]


def en_lecture_seule(user, societe, module):
    """Vrai si ce compte (employé) n'a qu'un accès en lecture au module."""
    if not est_employe(user, societe):
        return False
    employe = getattr(user, "employe_profil", None)
    return employe is not None and module in (employe.permissions_lecture or [])


def peut_acceder(user, societe, active):
    """Autorise (ou non) l'accès à la page `active` pour ce compte."""
    if not module_actif(active):
        return False
    if not est_employe(user, societe):
        return True
    if active in PAGES_TOUJOURS_ACCESSIBLES:
        return True
    return active in modules_autorises(user, societe)


# ---------------------------------------------------------------------------
# Journal des actions (boîte de notifications)
# ---------------------------------------------------------------------------

JOURNAL_MODULES = {
    "employes": "Employés",
    "taches": "Tâches",
    "clients": "Clients",
    "prospection": "Prospection",
    "projets": "Projets",
    "depenses": "Dépenses",
    "salaires": "Salaires",
    "contrats": "Contrats",
    "echeances": "Échéances",
    "paiements": "Paiements",
    "factures": "Factures",
    "bureau": "Applications",
    "roles": "Rôles",
    "fonctions": "Fonctions",
    "reunions": "Réunions",
    "documents": "Documents",
    "connecteurs": "Connecteurs",
    "societe": "Ma société",
    "equipe": "Messagerie",
    "compte": "Compte",
    "abonnement": "Abonnement",
}

JOURNAL_MODULE_URLS = {
    "employes": "gestion:employes",
    "taches": "gestion:taches",
    "clients": "gestion:clients",
    "projets": "gestion:projets",
    "societe": "gestion:societe_profil",
    "compte": "gestion:profil",
    "finances": "gestion:finances",
    "factures": "gestion:factures",
    "equipe": "gestion:employes",
    "connecteurs": "gestion:connecteurs",
    "reunions": "gestion:reunions",
    "abonnement": "gestion:mon_abonnement",
}


def journaliser(societe, action, module, libelle="", detail="", utilisateur=None):
    """Enregistre une action dans le journal de la société (best-effort)."""
    if societe is None:
        return None
    try:
        return ActivitePlateforme.objects.create(
            societe=societe,
            utilisateur=utilisateur,
            action=action,
            module=module,
            libelle=(libelle or "")[:200],
            detail=detail or "",
        )
    except Exception:
        return None


def activites_visibles(user, societe):
    """Activités du journal visibles par ce compte.

    - le propriétaire voit tout ;
    - les actions de messagerie ne sont montrées qu'au propriétaire : elles
      peuvent révéler le contenu d'échanges privés ou l'existence de groupes
      auxquels l'utilisateur n'appartient pas ;
    - un employé ne voit que les modules auxquels il a la permission, plus ses
      propres actions de compte (profil personnel).
    """
    qs = societe.activites.all()
    if est_createur(user, societe):
        return qs
    qs = qs.exclude(module="equipe")
    if employe_pour_utilisateur(user, societe) is None:
        return qs.none()
    autorises = set(modules_autorises(user, societe))
    return qs.filter(Q(module__in=autorises) | Q(module="compte", utilisateur=user))


def journal_module_label(module):
    """Libellé lisible d'un module du journal."""
    return JOURNAL_MODULES.get(module, (module or "").replace("_", " ").title())


def journal_module_url(module):
    """URL de la page correspondant à un module du journal."""
    name = JOURNAL_MODULE_URLS.get(module) if module_actif(module) else None
    if name:
        try:
            return reverse(name)
        except NoReverseMatch:
            pass
    try:
        from .crud import CRUD_CONFIG

        if module in CRUD_CONFIG:
            return reverse("gestion:crud", args=[module])
    except NoReverseMatch:
        pass
    try:
        return reverse("gestion:dashboard")
    except NoReverseMatch:
        return "/"


# ---------------------------------------------------------------------------
# Boîte de notifications moderne : catégories + vue aujourd'hui / hier
# ---------------------------------------------------------------------------

# Catégories de la cloche : regroupement thématique des modules du journal.
# Les permissions restent appliquées en amont (``activites_visibles``) : une
# catégorie n'apparaît que si le compte voit au moins une de ses activités.
NOTIF_CATEGORIES = (
    {"key": "rappels", "label": "Rappels", "sigle": "R", "couleur": "amber",
     "modules": ("echeances", "paiements", "abonnement")},
    {"key": "clients", "label": "Clients", "sigle": "C", "couleur": "indigo",
     "modules": ("clients", "prospection", "projets")},
    {"key": "taches", "label": "Tâches", "sigle": "T", "couleur": "emerald",
     "modules": ("taches",)},
    {"key": "employes", "label": "Employés", "sigle": "E", "couleur": "sky",
     "modules": ("employes", "roles", "fonctions", "contrats")},
    {"key": "reunions", "label": "Réunions", "sigle": "R", "couleur": "indigo",
     "modules": ("reunions",)},
    {"key": "finances", "label": "Finances", "sigle": "F", "couleur": "rose",
     "modules": ("finances", "salaires", "depenses")},
    {"key": "documents", "label": "Documents", "sigle": "D", "couleur": "violet",
     "modules": ("documents", "societe")},
    {"key": "messages", "label": "Messagerie", "sigle": "M", "couleur": "fuchsia",
     "modules": ("equipe",)},
    {"key": "configuration", "label": "Configuration", "sigle": "G", "couleur": "teal",
     "modules": ("connecteurs",)},
    {"key": "compte", "label": "Compte", "sigle": "P", "couleur": "slate",
     "modules": ("compte",)},
    {"key": "autre", "label": "Autres", "sigle": "A", "couleur": "gray", "modules": ()},
)

GROUPE_JOURS = ["Aujourd'hui", "Hier", "Plus tôt"]


def categorie_notification(module):
    """Clé de catégorie correspondant à un module du journal."""
    for cat in NOTIF_CATEGORIES:
        if cat["modules"] and module in cat["modules"]:
            return cat["key"]
    return "autre"


def modules_categorie(cle):
    """Modules du journal rattachés à une catégorie (() pour inconnue)."""
    for cat in NOTIF_CATEGORIES:
        if cat["key"] == cle:
            if cat["modules"]:
                return cat["modules"]
            couverts = {
                m for c in NOTIF_CATEGORIES if c["modules"] for m in c["modules"]
            }
            return tuple(
                sorted(set(JOURNAL_MODULES) - couverts)
            )
    return ()


def module_categorie_label(module):
    """Libellé de la catégorie associée à un module."""
    cle = categorie_notification(module)
    for cat in NOTIF_CATEGORIES:
        if cat["key"] == cle:
            return cat["label"]
    return "Autres"


def notifications_payload(user, societe, limite=40, maintenant=None):
    """Structure de la boîte de notifications : catégories + compteurs.

    Repart de ``activites_visibles`` (les permissions déterminent ce que le
    compte voit), regroupe par thématique et sépare chaque catégorie en
    tranches « Aujourd'hui / Hier / Plus tôt ». ``limite`` borne le nombre
    d'activités échantillonnées par catégorie (le compteur non-lu, lui, porte
    sur l'ensemble de la catégorie).

    Le registre des rappels / échéances est resynchronisé en amont
    (``assurer_echeances_registre``, sans doublons) puis les rappels actifs
    (jalon renseigné, c.-à-d. à moins de 30 jours ou en retard) rejoignent le
    fil de leur catégorie. Le payload expose aussi ``rappels`` et ``filtres``
    pour les pastilles de filtrage du panneau.
    """
    maintenant = maintenant or timezone.now()
    jour = timezone.localdate()
    hier = jour - timedelta(days=1)
    assurer_echeances_registre(societe, user=user)
    qs = activites_visibles(user, societe).select_related("utilisateur")
    rappels = list(
        rappels_visibles(user, societe).exclude(jalon="").order_by("date_prevue")
    )

    def groupe_du(dt):
        d = timezone.localtime(dt).date()
        if d == jour:
            return GROUPE_JOURS[0]
        if d == hier:
            return GROUPE_JOURS[1]
        return GROUPE_JOURS[2]

    total_unread = 0
    unread_par_cat = {}
    for ligne in (
        qs.filter(lue=False).values("module").annotate(non_lues=Count("id"))
    ):
        cle = categorie_notification(ligne["module"])
        unread_par_cat[cle] = unread_par_cat.get(cle, 0) + ligne["non_lues"]
        total_unread += ligne["non_lues"]
    for r in rappels:
        if not r.lue:
            cle = categorie_notification(r.module)
            unread_par_cat[cle] = unread_par_cat.get(cle, 0) + 1
            total_unread += 1

    portees = {c["key"]: [] for c in NOTIF_CATEGORIES}
    for a in qs[: max(limite * 3, 60)]:
        cle = categorie_notification(a.module)
        if len(portees[cle]) < limite:
            portees[cle].append(_item_activite(a, groupe_du))
    for r in rappels:
        cle = categorie_notification(r.module)
        if len(portees[cle]) < limite:
            portees[cle].append(_item_rappel(r, groupe_du, jour))

    categories = []
    for cat in NOTIF_CATEGORIES:
        items = portees[cat["key"]]
        if not items:
            continue
        par_groupe = {g: [] for g in GROUPE_JOURS}
        for item in items:
            par_groupe[item["groupe"]].append(item)
        categories.append(
            {
                "key": cat["key"],
                "label": cat["label"],
                "sigle": cat["sigle"],
                "couleur": cat["couleur"],
                "unread": unread_par_cat.get(cat["key"], 0),
                "total": len(items),
                "groupes": [
                    {"groupe": g, "items": par_groupe[g]}
                    for g in GROUPE_JOURS
                    if par_groupe[g]
                ],
            }
        )
    # Les catégories avec du non-lu d'abord, puis par ordre alphabétique.
    categories.sort(key=lambda c: (c["unread"] == 0, c["label"]))
    return {
        "categories": categories,
        "total_unread": total_unread,
        "latest": (
            qs.order_by("-id").values_list("id", flat=True).first() or 0
        ),
        "maintenant": maintenant.strftime("%H:%M"),
        "rappels": len(rappels),
        "filtres": {
            "activites": qs.count(),
            "rappels": len(rappels),
            "echeances": len(rappels),
        },
    }


def _item_activite(a, groupe_du):
    """Entrée « activité » (journal) du panneau de notifications."""
    return {
        "id": a.pk,
        "action": a.action,
        "action_label": a.get_action_display(),
        "module": a.module,
        "module_label": journal_module_label(a.module),
        "url": journal_module_url(a.module),
        "libelle": a.libelle,
        "detail": a.detail,
        "lue": a.lue,
        "auteur": (
            f"{a.utilisateur.prenom} {a.utilisateur.nom}"
            if a.utilisateur
            else "Système"
        ),
        "groupe": groupe_du(a.created_at),
        "heure": a.created_at.strftime("%H:%M"),
        "type": "activite",
        "rappel": False,
        "jalon": "",
        "priorite": "",
        "date_prevue": "",
        "statut": "",
        "temps": "",
    }


def _item_rappel(r, groupe_du, jour=None):
    """Entrée « rappel / échéance » du panneau de notifications."""
    return {
        "id": f"r{r.pk}",
        "action": "RAPPEL",
        "action_label": "Rappel",
        "module": r.module,
        "module_label": journal_module_label(r.module),
        "url": r.lien or journal_module_url(r.module),
        "libelle": r.libelle,
        "detail": _detail_rappel(r),
        "lue": r.lue,
        "auteur": "Automatique",
        "groupe": groupe_du(r.genre_le),
        "heure": r.genre_le.strftime("%H:%M"),
        "type": "rappel",
        "rappel": True,
        "jalon": r.jalon,
        "priorite": r.priorite,
        "date_prevue": r.date_prevue.isoformat() if r.date_prevue else "",
        "date_aff": r.date_prevue.strftime("%d/%m/%Y") if r.date_prevue else "",
        "statut": r.statut,
        "temps": temps_restant(r.date_prevue, aujourdhui=jour),
    }


def _detail_rappel(r):
    """Détail lisible d'une ligne de rappel / échéance."""
    parts = []
    if r.date_prevue:
        parts.append(f"Échéance le {r.date_prevue:%d/%m/%Y}")
    if r.statut:
        parts.append(statut_label(r.statut))
    if r.element:
        parts.append(r.element)
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Registre des échéances & rappels (centre d'échéances + cloche)
# ---------------------------------------------------------------------------

# Tranches d'affichage du centre d'échéances (ordre d'affichage).
GROUPES_CENTRE = [
    "En retard",
    "Aujourd'hui",
    "Demain",
    "Cette semaine",
    "Ce mois",
    "À venir",
]

STATUT_LABELS = {
    "A_VENIR": "À venir",
    "PARTIELLE": "Partielle",
    "PAYEE": "Payée",
    "RETARD": "Retard",
    "A_FAIRE": "À faire",
    "EN_COURS": "En cours",
    "TERMINEE": "Terminée",
    "PREVU": "Prévu",
    "PARTIEL": "Partiel",
    "PAYE": "Payé",
    "ACTIF": "Actif",
    "TERMINE": "Terminé",
    "RESILIE": "Résilié",
    "SUSPENDU": "Suspendu",
    "ANNULE": "Annulé",
    "EN_ATTENTE": "En attente",
    "ATTEINT": "Atteint",
}


def statut_label(statut):
    """Libellé lisible d'un code de statut (— si inconnu)."""
    return STATUT_LABELS.get(statut or "", statut or "—")


def montant_display(v):
    """Montant lisible (espaces de milliers), — si absent/invalide."""
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


JALON_LABELS = {
    "J30": "Rappel (30 j)",
    "J7": "Rappel (7 j)",
    "J3": "Rappel (3 j)",
    "J1": "Veille",
    "J0": "Jour J",
    "RETARD": "En retard",
}


def jalon_label(jalon):
    """Libellé lisible d'un jalon de rappel ("" si aucun)."""
    return JALON_LABELS.get(jalon or "", "")


def jalon_echeance(date_prevue, aujourdhui=None):
    """(jalon, jours_restants, priorite) selon la proximité d'une date.

    J30 → basse · J7 → moyenne · J3 / J1 → haute · J0 → urgente ·
    RETARD → critique. Une échéance à plus de 30 jours n'a pas encore de
    rappel ("").
    """
    if not date_prevue:
        return ("", 0, "")
    aujourdhui = aujourdhui or timezone.localdate()
    jours = (date_prevue - aujourdhui).days
    if jours < 0:
        return ("RETARD", jours, "critique")
    if jours == 0:
        return ("J0", jours, "urgente")
    if jours == 1:
        return ("J1", jours, "haute")
    if jours <= 3:
        return ("J3", jours, "haute")
    if jours <= 7:
        return ("J7", jours, "moyenne")
    if jours <= 30:
        return ("J30", jours, "basse")
    return ("", jours, "")


def temps_restant(date_prevue, aujourdhui=None):
    """Formule courte du temps restant avant une échéance."""
    if not date_prevue:
        return "—"
    jours = jalon_echeance(date_prevue, aujourdhui)[1]
    if jours < 0:
        return f"En retard de {-jours} j"
    if jours == 0:
        return "Aujourd'hui"
    if jours == 1:
        return "Demain"
    return f"J-{jours}"


def _fin_de_mois(aujourdhui):
    if aujourdhui.month == 12:
        return date(aujourdhui.year, 12, 31)
    return date(aujourdhui.year, aujourdhui.month + 1, 1) - timedelta(days=1)


def groupe_centre(date_prevue, aujourdhui=None):
    """Tranche du centre d'échéances à laquelle appartient une date."""
    if not date_prevue:
        return "À venir"
    aujourdhui = aujourdhui or timezone.localdate()
    jours = (date_prevue - aujourdhui).days
    if jours < 0:
        return "En retard"
    if jours == 0:
        return "Aujourd'hui"
    if jours == 1:
        return "Demain"
    if jours <= 7:
        return "Cette semaine"
    if date_prevue <= _fin_de_mois(aujourdhui):
        return "Ce mois"
    return "À venir"


# ---------------------------------------------------------------------------
# Suivi opérationnel d'un client (espace Clients)
# ---------------------------------------------------------------------------
# Chaînage réel : Client → Projet → Étapes (objectifs) → Tâches → Employé →
# activités (évolutions / livrables) → échéances. La progression du projet est
# calculée à partir des tâches réellement liées (`Tache.projet`).


def _auteur_nom(auteur):
    if auteur is None:
        return ""
    return f"{auteur.prenom} {auteur.nom}".strip()


def _sigle_employe(e):
    return f"{e.prenom[:1]}{e.nom[:1]}".upper()


def convertir_prospection(societe, prospect, type_client_id=None, utilisateur=None):
    """Convertit un prospect gagné en fiche client (traçabilité opérationnelle).

    Crée le ``Client`` lié avec la provenance : source, responsable commercial
    et créateur de la fiche. Le prospect passe à « Gagné » et garde le lien vers
    la fiche convertie (le PDG retrouve l'historique de prospection en ouvrant
    le client). Retourne le client créé, ou ``None`` si la conversion est
    impossible (déjà converti / pas de type de client).
    """
    if prospect is None or prospect.client_id or not type_client_id:
        return None
    type_client = TypeClient.objects.filter(pk=type_client_id).first()
    if type_client is None:
        return None
    client = Client.objects.create(
        societe=societe,
        nom=prospect.nom,
        type_client=type_client,
        email=prospect.email or "",
        telephone_1=prospect.telephone or "",
        ville=prospect.ville or "",
        pays=prospect.pays or "",
        statut="ACTIF",
        source=prospect.source or "AUTRE",
        cree_par=utilisateur,
        responsable=prospect.responsable,
    )
    prospect.client = client
    prospect.statut = "GAGNE"
    prospect.save(update_fields=["client", "statut"])
    return client


def progression_projet(projet):
    """(progression %, nb tâches, nb terminées) depuis les tâches liées."""
    taches = list(projet.taches.all())
    if not taches:
        return 0, 0, 0
    moy = round(sum(t.progres for t in taches) / len(taches))
    terminees = sum(1 for t in taches if t.statut == "TERMINEE")
    return moy, len(taches), terminees


def suivi_client(client, autorises):
    """Bloc « suivi de l'activité » d'un client (dict pour le template).

    Chaque sous-bloc respecte les permissions : projets / taches / employes /
    echeances. ``None`` ou liste vide = module non autorisé (masqué à l'écran).
    """
    acc = {
        "projets": "projets" in autorises,
        "taches": "taches" in autorises,
        "employes": "employes" in autorises,
        "prospection": "prospection" in autorises,
        "echeances": ("echeances" in autorises) or ("paiements" in autorises),
    }
    aujourdhui = timezone.localdate()
    projets = (
        list(
            client.projets.prefetch_related("objectifs", "taches", "chefs").order_by(
                "nom"
            )
        )
        if acc["projets"]
        else []
    )

    projets_info = []
    n_taches_total = 0
    n_terminees_total = 0
    poids_progression = 0
    budget_total = 0
    encaisse_total = 0
    equipe_par_emp = {}
    for p in projets:
        if acc["taches"]:
            taches = list(p.taches.all())
            progres, nb_t, nb_t_term = (
                round(sum(t.progres for t in taches) / len(taches)),
                len(taches),
                sum(1 for t in taches if t.statut == "TERMINEE"),
            ) if taches else (0, 0, 0)
            for t in taches:
                if not t.assignee_id:
                    continue
                ligne = equipe_par_emp.setdefault(
                    t.assignee_id,
                    {"pk": t.assignee_id, "en_cours": 0, "terminees": 0, "total": 0},
                )
                ligne["total"] += 1
                if t.statut == "TERMINEE":
                    ligne["terminees"] += 1
                elif t.statut in ("A_FAIRE", "EN_COURS"):
                    ligne["en_cours"] += 1
        else:
            taches = []
            progres = nb_t = nb_t_term = 0
        n_taches_total += nb_t
        n_terminees_total += nb_t_term
        if taches:
            poids_progression += progres * len(taches)
        budget_total += p.budget or 0
        encaisse_total += sum(
            p.paiements.filter(statut="CONFIRME").values_list(
                "montant", flat=True
            )
        ) if acc["echeances"] else 0

        # Étape en cours : premier objectif non « atteint » (planning du projet).
        objectifs = list(p.objectifs.all())
        etapes_atteintes = sum(1 for o in objectifs if o.statut == "ATTEINT")
        etape_courante = next(
            (o for o in objectifs if o.statut != "ATTEINT"), None
        )

        # Tâche en cours : tâche active la plus avancée (EN_COURS d'abord).
        tache_courante = None
        if taches:
            actives = [t for t in taches if t.statut in ("EN_COURS", "A_FAIRE")]
            if actives:
                actives.sort(
                    key=lambda t: (
                        0 if t.statut == "EN_COURS" else 1,
                        t.echeance or date.max,
                    )
                )
                tc = actives[0]
                tache_courante = {
                    "pk": tc.pk,
                    "titre": tc.titre,
                    "progres": tc.progres,
                    "statut": tc.statut,
                    "echeance": tc.echeance.isoformat() if tc.echeance else "",
                    "assignee_nom": f"{tc.assignee.prenom} {tc.assignee.nom}",
                }

        responsables = []
        if acc["employes"]:
            for c in p.chefs.all():
                if c.principal and c.employe_id:
                    responsables.append(
                        {
                            "pk": c.employe_id,
                            "nom": f"{c.employe.prenom} {c.employe.nom}".strip(),
                            "sigle": _sigle_employe(c.employe),
                            "statut": c.employe.statut,
                        }
                    )

        echeances = None
        echeances_restantes = 0
        if acc["echeances"]:
            ech_items = []
            for e in p.echeances.all():
                jalon, _jours, _prio = jalon_echeance(e.date_prevue, aujourdhui)
                ech_items.append(
                    {
                        "numero": e.numero_echeance,
                        "montant": montant_display(e.montant_prevu),
                        "date_aff": (
                            e.date_prevue.strftime("%d/%m/%Y")
                            if e.date_prevue else "—"
                        ),
                        "statut": e.statut,
                        "statut_label": statut_label(e.statut),
                        "jalon": jalon,
                        "jalon_label": jalon_label(jalon),
                    }
                )
            ech_items.sort(
                key=lambda x: (x["statut"] == "PAYEE", x["date_aff"] == "—")
            )
            echeances = ech_items[:4]
            echeances_restantes = sum(1 for x in ech_items if x["statut"] != "PAYEE")

        projets_info.append(
            {
                "pk": p.pk,
                "nom": p.nom,
                "statut": p.statut,
                "statut_label": statut_label(p.statut),
                "progression": progres,
                "n_taches": nb_t,
                "n_terminees": nb_t_term,
                "budget": montant_display(p.budget),
                "date_debut": p.date_debut.strftime("%d/%m/%Y") if p.date_debut else "—",
                "etapes_totales": len(objectifs),
                "etapes_atteintes": etapes_atteintes,
                "etape_en_cours": (
                    etape_courante.titre
                    if etape_courante is not None
                    else ("Toutes les étapes sont atteintes" if objectifs else "Aucune étape définie")
                ),
                "tache_en_cours": tache_courante,
                "responsables": responsables,
                "echeances": echeances,
                "echeances_restantes": echeances_restantes,
            }
        )

    # Historique (timeline) : mutations faites dans l'espace Employé/Tâches.
    timeline = []
    if acc["taches"]:
        evolution_labels = dict(Tache._meta.get_field("statut").choices)
        evolutions = (
            TacheEvolution.objects.filter(tache__projet__client=client)
            .select_related("tache", "tache__projet", "tache__assignee", "auteur")
            .order_by("-created_at")[:120]
        )
        for ev in evolutions:
            if ev.statut_apres:
                type_ev = "statut"
                texte = (
                    f"{evolution_labels.get(ev.statut_avant, ev.statut_avant or '—')} "
                    f"→ {evolution_labels.get(ev.statut_apres, ev.statut_apres)}"
                )
            elif ev.progres_apres is not None:
                type_ev = "progres"
                texte = (
                    f"Avancement : {ev.progres_avant or 0} % → "
                    f"{ev.progres_apres or 0} %"
                )
            else:
                type_ev = "commentaire"
                texte = ev.commentaire or "Évolution de la tâche"
                if ev.commentaire:
                    type_ev = "fichier" if "Fichier" in ev.commentaire else "commentaire"
            timeline.append(
                {
                    "type": type_ev,
                    "titre": ev.tache.titre,
                    "texte": texte,
                    "auteur": _auteur_nom(ev.auteur),
                    "employe": f"{ev.tache.assignee.prenom} {ev.tache.assignee.nom}",
                    "projet": ev.tache.projet.nom if ev.tache.projet_id else "",
                    "date": ev.created_at,
                }
            )
        livrables = (
            TacheLivrable.objects.filter(tache__projet__client=client)
            .select_related("tache", "tache__projet", "tache__assignee", "employe")
            .order_by("-date_depot")[:60]
        )
        for liv in livrables:
            texte = liv.nom_fichier
            if liv.message:
                texte += f" — {liv.message}"
            if liv.statut != "SOUMIS":
                texte += f" · {liv.get_statut_display()}"
            timeline.append(
                {
                    "type": "document",
                    "titre": liv.tache.titre,
                    "texte": texte,
                    "auteur": _auteur_nom(liv.repondu_par),
                    "employe": f"{liv.employe.prenom} {liv.employe.nom}",
                    "projet": liv.tache.projet.nom if liv.tache.projet_id else "",
                    "date": liv.date_reponse or liv.date_depot,
                }
            )
        timeline.sort(key=lambda e: e["date"], reverse=True)
        for e in timeline:
            e["date_aff"] = e["date"].strftime("%d/%m/%Y %H:%M")

    progression_globale = (
        round(poids_progression / n_taches_total) if n_taches_total else 0
    )

    # Provence de la fiche : d'où vient le client, qui l'a créé, qui le suit.
    provenance = {
        "source": client.source or "",
        "source_label": dict(SOURCE_CLIENT_CHOICES).get(
            client.source, client.source or "—"
        ),
        "date_creation": (
            client.created_at.strftime("%d/%m/%Y") if client.created_at else ""
        ),
        "cree_par": _auteur_nom(client.cree_par),
        "responsable": None,
        "prospection": None,
    }
    if acc["employes"] and client.responsable_id and client.responsable is not None:
        r = client.responsable
        provenance["responsable"] = {
            "pk": r.pk,
            "nom": f"{r.prenom} {r.nom}".strip(),
            "sigle": _sigle_employe(r),
            "statut": r.statut,
            "portefeuille": Client.objects.filter(
                societe=client.societe, responsable=r
            ).count(),
        }
    if acc["prospection"]:
        try:
            prospection = client.prospection
        except (Client.DoesNotExist, AttributeError):
            prospection = None
        if prospection is not None:
            provenance["prospection"] = {
                "pk": prospection.pk,
                "nom": prospection.nom,
                "date_prospection": (
                    prospection.date_prospection.strftime("%d/%m/%Y")
                    if prospection.date_prospection else "—"
                ),
                "statut": prospection.statut,
                "statut_label": prospection.get_statut_display(),
                "responsable_nom": (
                    f"{prospection.responsable.prenom} {prospection.responsable.nom}".strip()
                    if prospection.responsable else ""
                ),
            }

    # Qui travaille sur ce client : employés engagés sur les tâches liées.
    equipe = []
    if acc["taches"] and equipe_par_emp:
        engages = Employe.objects.in_bulk(list(equipe_par_emp))
        lignes = sorted(
            equipe_par_emp.values(), key=lambda l: l["total"], reverse=True
        )
        for l in lignes[:8]:
            emp = engages.get(l["pk"])
            l["nom"] = f"{emp.prenom} {emp.nom}".strip() if emp else "—"
            l["sigle"] = _sigle_employe(emp) if emp else "—"
            l["statut"] = emp.statut if emp else ""
            equipe.append(l)

    return {
        "acces": acc,
        "n_projets": len(projets_info),
        "n_taches": n_taches_total,
        "n_terminees": n_terminees_total,
        "progression": progression_globale,
        "budget_total": montant_display(budget_total),
        "encaisse_total": montant_display(encaisse_total),
        "provenance": provenance,
        "equipe": equipe,
        "projets": projets_info,
        "timeline": timeline[:25],
    }


def registre_echeances(societe):
    """Toutes les échéances suivies de la société (multi-sources).

    Une liste ordonnée de dictionnaires, chaque entrée décrivant un élément à
    surveiller (module, cible, libellé, élément, montant, date, statut, lien).
    Les sources sont les données réelles : échéances de paiement, tâches avec
    échéance, paies prévues, contrats actifs, projets en cours, objectifs et
    documents arrivant à expiration.
    """
    lignes = []

    for e in EcheancePaiement.objects.filter(
        projet__societe=societe
    ).exclude(statut="PAYEE").select_related("projet"):
        lignes.append(
            {
                "module": "echeances",
                "cible": f"ech:{e.pk}",
                "libelle": f"Échéance #{e.numero_echeance} — {e.projet.nom}",
                "element": e.projet.nom,
                "montant": e.montant_prevu,
                "date_prevue": e.date_prevue,
                "statut": e.statut,
                "lien": reverse("gestion:crud", args=["echeances"]),
            }
        )

    for t in Tache.objects.filter(
        societe=societe, echeance__isnull=False
    ).exclude(statut="TERMINEE").select_related("assignee"):
        lignes.append(
            {
                "module": "taches",
                "cible": f"tache:{t.pk}",
                "libelle": t.titre,
                "element": (
                    f"{t.assignee.prenom} {t.assignee.nom}"
                    if t.assignee else "Tâche"
                ),
                "montant": None,
                "date_prevue": t.echeance,
                "statut": t.statut,
                "lien": reverse("gestion:taches"),
            }
        )

    for s in PaiementSalaire.objects.filter(
        employe__societe=societe,
        statut__in=("PREVU", "PARTIEL", "RETARD"),
        date_prevue__isnull=False,
    ).select_related("employe"):
        lignes.append(
            {
                "module": "salaires",
                "cible": f"salaire:{s.pk}",
                "libelle": (
                    f"Paie {s.employe.prenom} {s.employe.nom}"
                    f" — {s.periode_mois:%m/%Y}"
                ),
                "element": f"{s.employe.prenom} {s.employe.nom}",
                "montant": s.montant_du,
                "date_prevue": s.date_prevue,
                "statut": s.statut,
                "lien": reverse("gestion:crud", args=["salaires"]),
            }
        )

    for c in ContratEmploye.objects.filter(
        employe__societe=societe, statut="ACTIF", date_fin__isnull=False
    ).select_related("employe", "type_contrat"):
        lignes.append(
            {
                "module": "contrats",
                "cible": f"contrat:{c.pk}",
                "libelle": (
                    f"Fin de contrat {c.type_contrat.code}"
                    f" — {c.employe.prenom} {c.employe.nom}"
                ),
                "element": f"{c.employe.prenom} {c.employe.nom}",
                "montant": c.salaire_contractuel,
                "date_prevue": c.date_fin,
                "statut": c.statut,
                "lien": reverse("gestion:employes"),
            }
        )

    for p in ProjetClient.objects.filter(
        societe=societe, statut="EN_COURS", date_fin__isnull=False
    ).select_related("client"):
        lignes.append(
            {
                "module": "projets",
                "cible": f"projet:{p.pk}",
                "libelle": f"Fin du projet {p.nom}",
                "element": p.client.nom if p.client else "Projet",
                "montant": p.budget,
                "date_prevue": p.date_fin,
                "statut": p.statut,
                "lien": reverse("gestion:projets"),
            }
        )

    for o in ProjetObjectif.objects.filter(
        projet__societe=societe,
        statut__in=("EN_ATTENTE", "EN_COURS"),
        date_echeance__isnull=False,
    ):
        lignes.append(
            {
                "module": "projets",
                "cible": f"objectif:{o.pk}",
                "libelle": f"Objectif : {o.titre}",
                "element": f"Projet {o.projet.nom}",
                "montant": None,
                "date_prevue": o.date_echeance,
                "statut": o.statut,
                "lien": reverse("gestion:projets"),
            }
        )

    for d in SocieteDocument.objects.filter(
        societe=societe, date_expiration__isnull=False
    ):
        numero = d.numero_document or ""
        lignes.append(
            {
                "module": "documents",
                "cible": f"document:{d.pk}",
                "libelle": (
                    f"{d.type_document}{' — ' + numero if numero else ''}"
                ),
                "element": "Document société",
                "montant": None,
                "date_prevue": d.date_expiration,
                "statut": "ACTIF",
                "lien": reverse("gestion:crud", args=["documents"]),
            }
        )

    lignes.sort(key=lambda ligne: ligne.get("date_prevue") or date.max)
    return lignes


def rappels_visibles(user, societe):
    """Rappels / échéances visibles par ce compte (mêmes permissions modules).

    Les rappels « masqués » (supprimés par l'utilisateur dans la cloche) sont
    exclus : suppression = masquage, sans recréation tant que l'échéance reste
    la même.
    """
    autorises = (
        set(modules_autorises(user, societe))
        if user is not None
        else set(ALL_MODULE_KEYS)
    )
    return societe.rappels.filter(module__in=autorises, masque=False)


def assurer_echeances_registre(societe, user=None):
    """Resynchronise le registre des rappels depuis les données réelles.

    - crée une ligne par échéance suivie (unicité : ``(societe, module,
      cible)``, aucun doublon) ;
    - recalcule date, statut, jalon et priorité à chaque passe ;
    - un changement de jalon (nouvelle étape : J30 → J7 → …) réactive le
      non-lu afin de « re-notifier » ;
    - supprime les lignes dont la cible a disparu (échéance payée, tâche
      terminée, contrat clos…) ;
    - ne crée que les modules autorisés pour ``user`` (le propriétaire voit
      tout) mais ne supprime jamais une ligne à cause des permissions d'un
      employé : le nettoyage s'appuie sur l'existence réelle des cibles.
    """
    if societe is None:
        return
    sources = registre_echeances(societe)
    autorises = (
        set(modules_autorises(user, societe))
        if user is not None
        else None
    )

    actifs = {(s["module"], s["cible"]) for s in sources}
    lignes_autorisees = (
        [s for s in sources if s["module"] in autorises]
        if autorises is not None
        else sources
    )

    for s in lignes_autorisees:
        date_prevue = s.get("date_prevue")
        jalon, _jours, priorite = jalon_echeance(date_prevue)
        row, cree = Rappel.objects.get_or_create(
            societe=societe,
            module=s["module"],
            cible=s["cible"],
            defaults={
                "libelle": (s.get("libelle") or "")[:200],
                "element": (s.get("element") or "")[:200],
                "montant": s.get("montant"),
                "date_prevue": date_prevue,
                "statut": (s.get("statut") or "")[:30],
                "jalon": jalon,
                "priorite": priorite,
                "lien": (s.get("lien") or "")[:200],
                "lue": False,
            },
        )
        if cree:
            continue
        changes = (
            row.date_prevue != date_prevue
            or row.statut != (s.get("statut") or "")
            or row.jalon != jalon
            or row.priorite != priorite
        )
        if not changes:
            continue
        ancien_jalon = row.jalon
        row.libelle = (s.get("libelle") or "")[:200]
        row.element = (s.get("element") or "")[:200]
        row.montant = s.get("montant")
        row.date_prevue = date_prevue
        row.statut = (s.get("statut") or "")[:30]
        row.jalon = jalon
        row.priorite = priorite
        row.lien = (s.get("lien") or "")[:200]
        # Nouvelle étape de rappel → on re-notifie (sauf si masqué : une
        # notification supprimée par l'utilisateur ne revient pas d'elle-même).
        if jalon and jalon != ancien_jalon and not row.masque:
            row.lue = False
        row.save(
            update_fields=[
                "libelle", "element", "montant", "date_prevue", "statut",
                "jalon", "priorite", "lien", "lue", "modifie_le",
            ]
        )

    # Nettoyage : cibles disparues (payées, terminées, supprimées…).
    perimes = Rappel.objects.filter(societe=societe)
    for row in perimes:
        if (row.module, row.cible) not in actifs:
            row.delete()


def _month_bounds(periode):
    """Retourne (début, fin) du mois contenant `periode` (fin exclusive)."""
    debut = periode.replace(day=1)
    if debut.month == 12:
        fin = debut.replace(year=debut.year + 1, month=1, day=1)
    else:
        fin = debut.replace(month=debut.month + 1, day=1)
    return debut, fin


def _month_end(annee, mois):
    """Dernier jour du mois."""
    if mois == 12:
        return date(annee, 12, 31)
    return date(annee, mois + 1, 1) - _one_day()


def _one_day():
    from datetime import timedelta

    return timedelta(days=1)


def recalculer_finances(societe, periode):
    """Met à jour la synthèse financière du mois contenant `periode`."""
    from .models import Finance

    if periode is None:
        return
    finance, _ = Finance.objects.get_or_create(
        societe=societe, periode=periode.replace(day=1)
    )
    finance.recalculer()


def sync_depense_salaire(societe, salaire):
    """Comptabilise un salaire payé en dépense automatiquement.

    - Payé   : crée (ou met à jour) la dépense liée, statut CONFIRME.
    - Non payé : repasse la dépense liée en EN_ATTENTE (retirée des totaux).
    """
    if salaire.statut == "PAYE" and salaire.date_paiement:
        type_salaire, _ = TypeDepense.objects.get_or_create(nom="Salaires")
        nom = (
            f"Salaire — {salaire.employe.prenom} {salaire.employe.nom}"
            f" — {salaire.periode_mois:%m/%Y}"
        )
        DepenseSociete.objects.update_or_create(
            paiement_salaire=salaire,
            defaults={
                "societe": societe,
                "type_depense": type_salaire,
                "nom": nom,
                "montant": salaire.montant_paye or salaire.montant_du,
                "date_depense": salaire.date_paiement,
                "statut": "CONFIRME",
                "employe": salaire.employe,
                "periode_mois": salaire.periode_mois,
            },
        )
        recalculer_finances(societe, salaire.date_paiement)
    else:
        try:
            depense = salaire.depense
        except DepenseSociete.DoesNotExist:
            depense = None
        if depense:
            depense.statut = "EN_ATTENTE"
            depense.save(update_fields=["statut"])
        if salaire.date_paiement:
            recalculer_finances(societe, salaire.date_paiement)
    recalculer_finances(societe, salaire.periode_mois)


def sync_salaire_from_depense(societe, depense):
    """Comptabilise une dépense de type « Salaires » côté paie.

    Une dépense enregistrée dans « Dépenses » avec le type « Salaires » (et
    un employé + une période renseignés) crée ou met à jour le paiement de
    salaire correspondant, pour que l'action se retrouve aussi dans « Salaires ».

    - Dépense CONFIRME  → salaire PAYÉ (date et montant payé = ceux de la dépense).
    - Sinon (en attente / annulé) → salaire repassé en PRÉVU.

    Retour : le PaiementSalaire lié (ou None si la dépense n'est pas un salaire).
    """
    if depense.type_depense_id is None:
        return None
    type_salaire = depense.type_depense
    if not type_salaire.nom.strip().lower().startswith("salaire"):
        return None
    if depense.employe_id is None or depense.periode_mois is None:
        return None

    debut, fin = _month_bounds(depense.periode_mois)
    salaire = PaiementSalaire.objects.filter(
        employe=depense.employe,
        periode_mois__gte=debut,
        periode_mois__lt=fin,
    ).first()
    if salaire is None:
        salaire = PaiementSalaire(
            employe=depense.employe,
            periode_mois=debut,
            montant_du=depense.montant,
            montant_paye=0,
            date_prevue=depense.date_depense,
            statut="PREVU",
        )

    if depense.statut == "CONFIRME":
        salaire.statut = "PAYE"
        salaire.date_paiement = depense.date_depense
        salaire.montant_paye = depense.montant
    else:
        salaire.statut = "PREVU"
        salaire.date_paiement = None
        salaire.montant_paye = 0
    if salaire.pk is None:
        contrat = (
            ContratEmploye.objects.filter(employe=depense.employe, statut="ACTIF")
            .order_by("-date_debut")
            .first()
        )
        salaire.contrat = contrat
    salaire.save()

    # Un salaire payé possède déjà une dépense générée : on la remplace plutôt
    # que de laisser deux dépenses référencer le même salaire (OneToOne).
    try:
        depense_existante = salaire.depense
    except DepenseSociete.DoesNotExist:
        depense_existante = None
    if depense_existante is not None and depense_existante.pk != depense.pk:
        depense_existante.delete()

    depense.paiement_salaire = salaire
    depense.save(update_fields=["paiement_salaire"])
    recalculer_finances(societe, depense.date_depense)
    recalculer_finances(societe, depense.periode_mois)
    return salaire


def montant_du_pour(employe, contrat=None, periode=None):
    """Salaire dû pour la période : contrat actif sinon salaire de l'employé."""
    if contrat is not None:
        return contrat.salaire_contractuel
    contrat = (
        ContratEmploye.objects.filter(employe=employe, statut="ACTIF")
        .order_by("-date_debut")
        .first()
    )
    if contrat:
        return contrat.salaire_contractuel
    return employe.salaire or 0


def date_prevue_pour(employe, periode):
    """Date de paie prévue : jour_paiement de l'employé, sinon dernier jour du mois."""
    annee, mois = periode.year, periode.month
    if mois == 12:
        dernier = 31
    else:
        dernier = (date(annee, mois + 1, 1) - _one_day()).day
    jour = employe.jour_paiement or dernier
    return date(annee, mois, min(jour, dernier))


def generer_salaires_mois(societe, periode, employes=None):
    """Génère les paiements de salaire manquants (statut PREVU) pour le mois.

    - employes : queryset/réstriction optionnelle (défaut : employés ACTIF de la société).
    - Retour : (créés, ignorés_doublons).
    """
    debut, fin = _month_bounds(periode)
    if employes is None:
        employes = societe.employes.filter(statut="ACTIF")

    created = 0
    skipped = 0
    for employe in employes:
        existe = PaiementSalaire.objects.filter(
            employe=employe,
            periode_mois__gte=debut,
            periode_mois__lt=fin,
        ).exists()
        if existe:
            skipped += 1
            continue
        contrat = (
            ContratEmploye.objects.filter(employe=employe, statut="ACTIF")
            .order_by("-date_debut")
            .first()
        )
        PaiementSalaire.objects.create(
            employe=employe,
            contrat=contrat,
            periode_mois=debut,
            montant_du=montant_du_pour(employe, contrat, periode),
            montant_paye=0,
            date_prevue=date_prevue_pour(employe, periode),
            statut="PREVU",
        )
        created += 1
    recalculer_finances(societe, periode)
    return created, skipped


# ---------------------------------------------------------------------------
# Corrélation Échéances (plan) ↔ Paiements clients (recettes)
# ---------------------------------------------------------------------------


def _mode_paiement_defaut(societe):
    """Mode de paiement à utiliser par défaut pour un encaissement automatique."""
    mode = societe.modes_paiement.filter(actif=True).order_by("nom").first()
    if mode is None:
        mode = ModePaiement.objects.filter(actif=True).order_by("nom").first()
    if mode is None:
        mode, _ = ModePaiement.objects.get_or_create(
            code="ESPECES", defaults={"nom": "Espèces"}
        )
    return mode


def recalculer_echeance(societe, echeance):
    """Recalcule le statut d'une échéance à partir de ses paiements confirmés.

    - total confirmé >= montant prévu → PAYEE
    - 0 < total < montant prévu        → PARTIELLE
    - aucun encaissement               → A_VENIR (ou RETARD si dépassée)
    """
    if echeance is None:
        return None
    total = (
        PaiementClient.objects.filter(echeance=echeance, statut="CONFIRME").aggregate(
            total=Sum("montant")
        )["total"]
        or 0
    )
    montant_prevu = echeance.montant_prevu or 0
    if montant_prevu and total >= montant_prevu:
        statut = "PAYEE"
    elif total > 0:
        statut = "PARTIELLE"
    else:
        statut = "A_VENIR" if echeance.date_prevue >= timezone.localdate() else "RETARD"
    if statut != echeance.statut:
        echeance.statut = statut
        echeance.save(update_fields=["statut"])
    return echeance


def sync_paiement_from_echeance(
    societe, echeance, date_paiement=None, mode_paiement=None
):
    """Répercute une échéance payée sur les paiements clients.

    - Échéance PAYEE  → crée / met à jour le paiement confirmé lié (recette).
    - Échéance non payée → repasse les paiements confirmés liés en EN_ATTENTE
      (retirés des recettes), sans les supprimer.
    """
    paiement = PaiementClient.objects.filter(echeance=echeance).order_by("pk").first()
    if echeance.statut == "PAYEE":
        mode = (
            mode_paiement
            or (paiement.mode_paiement if paiement else None)
            or _mode_paiement_defaut(societe)
        )
        if paiement is None:
            paiement = PaiementClient.objects.create(
                projet=echeance.projet,
                echeance=echeance,
                montant=echeance.montant_prevu,
                date_paiement=date_paiement or timezone.localdate(),
                mode_paiement=mode,
                reference=f"Échéance #{echeance.numero_echeance}",
                statut="CONFIRME",
            )
        else:
            paiement.projet = echeance.projet
            paiement.montant = echeance.montant_prevu
            paiement.date_paiement = (
                date_paiement or paiement.date_paiement or timezone.localdate()
            )
            paiement.mode_paiement = mode
            if not paiement.reference:
                paiement.reference = f"Échéance #{echeance.numero_echeance}"
            paiement.statut = "CONFIRME"
            paiement.save(
                update_fields=[
                    "projet",
                    "montant",
                    "date_paiement",
                    "mode_paiement",
                    "reference",
                    "statut",
                ]
            )
        recalculer_finances(societe, paiement.date_paiement)
        return paiement

    confirmes = list(
        PaiementClient.objects.filter(echeance=echeance, statut="CONFIRME")
    )
    for encaissement in confirmes:
        encaissement.statut = "EN_ATTENTE"
        encaissement.save(update_fields=["statut"])
        if encaissement.date_paiement:
            recalculer_finances(societe, encaissement.date_paiement)
    return confirmes[0] if confirmes else paiement


def sync_echeance_from_paiement(societe, paiement):
    """Répercute un paiement client sur son échéance (via `recalculer_echeance`)."""
    if paiement is None or paiement.echeance_id is None:
        return None
    return recalculer_echeance(societe, paiement.echeance)


# ---------------------------------------------------------------------------
# KPay — comptabilisation des opérations Mobile Money confirmées
# ---------------------------------------------------------------------------


def mode_mobile_money():
    """Mode de paiement « Mobile Money » (créé au besoin)."""
    mode, _ = ModePaiement.objects.get_or_create(
        code="MOBILE_MONEY", defaults={"nom": "Mobile Money"}
    )
    return mode


def _derniere_operation_kpay(objet):
    """Dernière opération KPay liée à un paiement / échéance / salaire."""
    if objet is None:
        return None
    related = getattr(objet, "kpay_operations", None)
    if related is None:
        return None
    return related.order_by("-created_at").first()


def finaliser_depot_kpay(societe, operation, utilisateur=None):
    """Comptabilise un encaissement Mobile Money confirmé (webhook/polling).

    - PaiementClient lié → CONFIRME (recette).
    - Échéance liée → PAYEE.
    - Synthèses financières recalculées + journalisation.
    """
    if operation.type_operation != "DEPOSIT":
        return None
    echeance = operation.echeance
    paiement = operation.paiement
    if echeance is None and paiement is None:
        return None
    if paiement is None:
        # Construit le paiement depuis l'échéance (miroir classique).
        if echeance is None:
            return None
        paiement = PaiementClient.objects.create(
            projet=echeance.projet,
            echeance=echeance,
            montant=echeance.montant_prevu,
            date_paiement=timezone.localdate(),
            mode_paiement=mode_mobile_money(),
            reference=operation.reference or f"Échéance #{echeance.numero_echeance}",
            statut="CONFIRME",
        )
        operation.paiement = paiement
        operation.save(update_fields=["paiement"])
    else:
        paiement.statut = "CONFIRME"
        paiement.date_paiement = timezone.localdate()
        paiement.mode_paiement = mode_mobile_money()
        paiement.reference = operation.reference or paiement.reference
        paiement.save(
            update_fields=[
                "statut", "date_paiement", "mode_paiement", "reference",
            ]
        )
    if echeance is not None and echeance.statut != "PAYEE":
        echeance.statut = "PAYEE"
        echeance.save(update_fields=["statut"])
    recalculer_finances(societe, paiement.date_paiement)
    if utilisateur is not None:
        journaliser(
            societe,
            "PAIEMENT",
            "echeances",
            str(echeance) if echeance else str(paiement),
            f"Encaissement Mobile Money confirmé : {paiement.montant}",
            utilisateur,
        )
    return paiement


def finaliser_retrait_kpay(societe, operation, utilisateur=None):
    """Comptabilise un retrait Mobile Money (salaire) confirmé.

    - PaiementSalaire lié → PAYE (date + montant payé).
    - Dépense « Salaires » générée (comptabilisation automatique).
    - Synthèses financières recalculées + journalisation.
    """
    if operation.type_operation != "PAYOUT":
        return None
    salaire = operation.salaire
    if salaire is None or salaire.statut == "PAYE":
        return salaire
    salaire.statut = "PAYE"
    salaire.date_paiement = timezone.localdate()
    if not salaire.montant_paye:
        salaire.montant_paye = salaire.montant_du
    if salaire.mode_paiement_id is None:
        salaire.mode_paiement = mode_mobile_money()
    salaire.save(
        update_fields=[
            "statut", "date_paiement", "montant_paye", "mode_paiement",
        ]
    )
    sync_depense_salaire(societe, salaire)
    if utilisateur is not None:
        journaliser(
            societe,
            "VALIDATION",
            "salaires",
            f"{salaire.employe.prenom} {salaire.employe.nom}",
            f"Virement Mobile Money confirmé : {salaire.montant_paye}",
            utilisateur,
        )
    return salaire


# ---------------------------------------------------------------------------
# Facturation
# ---------------------------------------------------------------------------


def prochain_numero_facture(societe, jour=None):
    """Numéro suivant pour l'année : FAC-2026-0001, FAC-2026-0002…"""
    from .models import Facture

    jour = jour or timezone.localdate()
    prefixe = f"FAC-{jour.year}-"
    nums = Facture.objects.filter(societe=societe, numero__startswith=prefixe).values_list("numero", flat=True)
    dernier = 0
    for n in nums:
        try:
            dernier = max(dernier, int(n.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefixe}{dernier + 1:04d}"


def payer_facture(societe, facture, date_paiement=None):
    """Passe la facture en PAYEE et enregistre la recette dans Paiements.

    - Facture liée à une échéance : l'échéance est soldée (paiement lié créé / confirmé).
    - Facture liée à un projet seulement : un paiement client confirmé est créé.
    - Sans projet : seul le statut change (aucune recette possible sans projet).
    """
    date_paiement = date_paiement or timezone.localdate()
    facture.statut = "PAYEE"
    facture.date_paiement = date_paiement
    paiement = None
    if facture.echeance_id:
        ech = facture.echeance
        ech.statut = "PAYEE"
        ech.save(update_fields=["statut"])
        paiement = sync_paiement_from_echeance(societe, ech, date_paiement=date_paiement)
    elif facture.projet_id:
        paiement = facture.paiement
        if paiement is None:
            paiement = PaiementClient.objects.create(
                projet=facture.projet,
                montant=facture.total_ttc,
                date_paiement=date_paiement,
                mode_paiement=_mode_paiement_defaut(societe),
                reference=facture.numero,
                statut="CONFIRME",
            )
        else:
            paiement.montant = facture.total_ttc
            paiement.date_paiement = date_paiement
            paiement.statut = "CONFIRME"
            paiement.save(update_fields=["montant", "date_paiement", "statut"])
        recalculer_finances(societe, date_paiement)
    facture.paiement = paiement if paiement is not None and hasattr(paiement, "pk") else facture.paiement
    facture.save(update_fields=["statut", "date_paiement", "paiement", "updated_at"])
    return paiement


def annuler_paiement_facture(societe, facture):
    """Repasse le paiement lié en attente quand une facture payée est rouverte/annulée."""
    p = facture.paiement
    if p is not None and p.statut == "CONFIRME" and not facture.echeance_id:
        p.statut = "EN_ATTENTE"
        p.save(update_fields=["statut"])
        recalculer_finances(societe, p.date_paiement)
    if facture.echeance_id and facture.echeance.statut == "PAYEE":
        facture.echeance.statut = "A_VENIR"
        facture.echeance.save(update_fields=["statut"])
        sync_paiement_from_echeance(societe, facture.echeance)
