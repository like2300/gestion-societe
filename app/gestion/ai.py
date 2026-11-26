"""Assistant IA : autorisations, contexte société et appels Groq."""

import requests

from django.conf import settings


def user_module_keys(user, societe):
    """Modules accessibles par l'IA selon les autorisations de l'utilisateur.

    Un super-utilisateur ou le créateur de la société accède à tous les
    modules ; un compte employé est borné à ``Employe.permissions``.
    """
    from .services import modules_autorises

    return modules_autorises(user, societe)


def get_module_stats(societe, modules):
    """Stats par module (ordonnées) pour le prompt IA et le rapport PDF."""
    from .models import (
        ContratEmploye,
        EcheancePaiement,
        PaiementClient,
        PaiementSalaire,
    )
    from django.db.models import Sum

    mk = set(modules)
    data = {}
    if "dashboard" in mk:
        solde = sum(societe.finances.values_list("solde", flat=True))
        data["dashboard"] = {
            "label": "Tableau de bord",
            "lines": [f"Solde financier global : {solde}",
                      f"{societe.employes.count()} employés",
                      f"{societe.clients.count()} clients",
                      f"{societe.projets.count()} projets"],
        }
    if "employes" in mk:
        emp = societe.employes
        data["employes"] = {
            "label": "Employés",
            "lines": [f"{emp.count()} employés au total",
                      f"{emp.filter(statut='ACTIF').count()} actifs",
                      f"{sum(1 for e in emp.only('id') if not e.contrats.exists())} sans contrat"],
        }
    if "clients" in mk:
        cli = societe.clients
        total_encaisse = PaiementClient.objects.filter(
            projet__societe=societe
        ).aggregate(t=Sum("montant"))["t"] or 0
        data["clients"] = {
            "label": "Clients",
            "lines": [f"{cli.count()} clients",
                      f"{cli.filter(statut='ACTIF').count()} actifs",
                      f"{cli.filter(projets__isnull=False).distinct().count()} avec projets"]
                     + ([f"Total encaissé clients : {total_encaisse}"]
                        if {"finances", "paiements"} & set(mk) else []),
        }
    if "projets" in mk:
        proj = societe.projets
        data["projets"] = {
            "label": "Projets",
            "lines": [f"{proj.count()} projets",
                      f"{proj.filter(statut='EN_COURS').count()} en cours"],
        }
    if "finances" in mk:
        fin = societe.finances
        data["finances"] = {
            "label": "Finances",
            "lines": [f"{fin.count()} relevés",
                      f"Solde cumulé : {sum(fin.values_list('solde', flat=True))}"],
        }
    if "depenses" in mk:
        dep = societe.depenses
        total = dep.aggregate(t=Sum("montant"))["t"] or 0
        data["depenses"] = {
            "label": "Dépenses",
            "lines": [f"{dep.count()} dépenses",
                      f"Total dépenses : {total}"],
        }
    if "salaires" in mk:
        sal = PaiementSalaire.objects.filter(employe__societe=societe)
        total = sal.aggregate(t=Sum("montant_paye"))["t"] or 0
        data["salaires"] = {
            "label": "Salaires",
            "lines": [f"{sal.count()} paiements de salaire",
                      f"Total payé : {total}"],
        }
    if "contrats" in mk:
        con = ContratEmploye.objects.filter(employe__societe=societe)
        data["contrats"] = {
            "label": "Contrats",
            "lines": [f"{con.count()} contrats",
                      f"{con.filter(statut='ACTIF').count()} actifs"],
        }
    if "echeances" in mk:
        ech = EcheancePaiement.objects.filter(projet__societe=societe)
        data["echeances"] = {
            "label": "Échéances",
            "lines": [f"{ech.count()} échéances",
                      f"{ech.filter(statut='A_VENIR').count()} à venir"],
        }
    if "paiements" in mk:
        pai = PaiementClient.objects.filter(projet__societe=societe)
        total = pai.aggregate(t=Sum("montant"))["t"] or 0
        data["paiements"] = {
            "label": "Paiements",
            "lines": [f"{pai.count()} paiements clients",
                      f"Total encaissé : {total}"],
        }
    if "roles" in mk:
        data["roles"] = {
            "label": "Rôles & Permissions",
            "lines": [f"{societe.roles.count()} rôles"],
        }
    if "fonctions" in mk:
        data["fonctions"] = {
            "label": "Fonctions",
            "lines": [f"{societe.fonctions.count()} fonctions"],
        }
    if "documents" in mk:
        data["documents"] = {
            "label": "Documents",
            "lines": [f"{societe.documents.count()} documents"],
        }
    if "connecteurs" in mk:
        actifs = societe.connecteurs.filter(statut="CONNECTE")
        noms = ", ".join(
            sorted({(c.nom or c.type_connecteur) for c in actifs})
        ) or "aucun"
        data["connecteurs"] = {
            "label": "Connecteurs",
            "lines": [
                f"{societe.connecteurs.count()} connecteurs configurés",
                f"{actifs.count()} actifs",
                f"Services actifs : {noms}",
            ],
        }
    if "societe" in mk:
        data["societe"] = {
            "label": "Ma société",
            "lines": [f"Nom : {societe.nom}",
                      f"Pays : {societe.pays}",
                      f"Type : {societe.type_societe}"],
        }
    return data


def build_system_prompt(societe, modules):
    """Prompt système envoyé à Groq, borné aux modules autorisés."""
    stats = get_module_stats(societe, modules)
    contexte = []
    for key in modules:
        blk = stats.get(key)
        if blk:
            contexte.append(f"- {blk['label']} : " + "; ".join(blk["lines"]))
    # Blocs dérivés d'un module autorisé.
    for key, blk in stats.items():
        if key not in modules and blk:
            contexte.append(f"- {blk['label']} : " + "; ".join(blk["lines"]))
    return (
        "Tu es l'assistant IA du 'Gestionnaire de société' pour l'entreprise "
        f"« {societe.nom} » ({societe.pays}). "
        "Tu aides l'administrateur à gérer sa société et à générer des rapports. "
        "Réponds en français, de façon concise et professionnelle, sans inventer "
        "de chiffres. Données actuelles de la société, uniquement sur les modules "
        "autorisés pour ce compte :\n"
        + "\n".join(contexte)
        + "\nSi une question porte sur un module non listé, explique que vous n'avez "
        "pas accès à ce module. Concernant les connecteurs, tu ne peux consulter "
        "que leur nom et leur statut : tu ne dois jamais demander, afficher ou "
        "manipuler de mot de passe, clé d'API ou jeton d'accès."
    )


def call_groq(messages, model=None, key=None):
    """Appelle l'API Groq (chat completions). Lève une exception en cas d'erreur."""
    model = model or getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    key = key or getattr(settings, "GROQ_API_KEY", "")
    if not key:
        raise ValueError("GROQ_API_KEY manquante (configurer app/.env).")
    url = getattr(settings, "GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 1024,
            },
            timeout=90,
        )
    except requests.Timeout:
        raise ValueError("Groq a mis trop de temps à répondre (délai dépassé).")
    except requests.RequestException as exc:
        raise ValueError(f"Réseau indisponible vers Groq : {exc}")
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = (resp.json().get("error") or {}).get("message") or ""
        except Exception:
            pass
        libelles = {
            401: "clé API Groq invalide (401 Unauthorized)",
            403: "clé API Groq non autorisée (403 Forbidden) — vérifiez GROQ_API_KEY dans app/.env",
            429: "limite de débit Groq atteinte (429), réessayez dans un instant",
            400: "requête Groq refusée (400) : modèle indisponible",
        }
        base = libelles.get(resp.status_code, f"Groq a répondu {resp.status_code}")
        raise ValueError(f"{base}." + (f" {detail}" if detail else ""))
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


_LABELS_STATUT_CLIENT = {
    "ACTIF": "actif",
    "INACTIF": "inactif",
    "SUSPENDU": "suspendu",
}


def _detail_clients(societe, limite=12):
    """Lignes par client : nom, statut, ville/pays, projets et total payé.

    Données réelles de la société ; borné à l'appelant (module « clients »).
    """
    from .models import Client
    from django.db.models import Count, Sum

    qs = (
        Client.objects.filter(societe=societe, nom__isnull=False)
        .annotate(
            nb_projets=Count("projets", distinct=True),
            total_paye=Sum("projets__paiements__montant"),
        )
        .order_by("nom")[:limite]
    )
    lignes = []
    for c in qs:
        loc = c.ville or c.pays or ""
        label = _LABELS_STATUT_CLIENT.get(c.statut, "statut inconnu")
        nb = c.nb_projets
        proj_label = "projet" if nb == 1 else "projets"
        ligne = f"{c.nom} — {label}"
        if loc:
            ligne += f" ({loc})"
        ligne += f" — {nb} {proj_label} — total payé : {int(c.total_paye or 0)}"
        lignes.append(ligne)
    return lignes


def _liste_prospects(societe, limite=15):
    """Prospects (pipeline) de la société, du plus récent au plus ancien."""
    _L = {"NOUVEAU": "nouveau", "CONTACTE": "contacté",
          "EN_NEGOCIATION": "en négociation", "GAGNE": "gagné", "PERDU": "perdu"}
    lignes = []
    for p in societe.prospections.order_by("-id")[:limite]:
        loc = p.ville or p.pays or ""
        lignes.append(f"{p.nom} — {_L.get(p.statut, p.statut)}"
                      + (f" ({loc})" if loc else ""))
    return lignes


def _liste_employes(societe, limite=15):
    """Employés triés par nom (statut, fonction, salaire)."""
    from .models import Employe

    lignes = []
    for e in Employe.objects.filter(societe=societe).order_by("nom", "prenom")[:limite]:
        extra = ""
        if e.fonction_id:
            extra += f" · {e.fonction.nom}"
        if e.salaire is not None:
            extra += f" · salaire {e.salaire}"
        lignes.append(f"{e.prenom} {e.nom} — {e.statut.lower()}{extra}")
    return lignes


def _liste_taches(societe, limite=15):
    """Tâches (titre, statut, avancement, attributaire, échéance)."""
    _L = {"A_FAIRE": "à faire", "EN_COURS": "en cours",
          "TERMINEE": "terminée", "ANNULEE": "annulée"}
    lignes = []
    for t in societe.taches.select_related("assignee").order_by("-echeance")[:limite]:
        ech = t.echeance or "—"
        lignes.append(
            f"{t.titre} — {_L.get(t.statut, t.statut)} ({t.progres}%) — "
            f"{t.assignee.prenom} {t.assignee.nom} — {ech}"
        )
    return lignes


def _liste_projets(societe, limite=15):
    """Projets clients (statut, budget, client)."""
    _L = {"EN_COURS": "en cours", "TERMINE": "terminé",
          "SUSPENDU": "suspendu", "ANNULE": "annulé"}
    lignes = []
    for p in societe.projets.select_related("client").order_by("-date_debut")[:limite]:
        cli = p.client.nom if p.client_id else "sans client"
        lignes.append(
            f"{p.nom} — {_L.get(p.statut, p.statut)} — budget {p.budget} — {cli}"
        )
    return lignes


def _liste_echeances(societe, limite=15):
    """Échéances (projet, numéro, montant, statut, date prévue)."""
    from .models import EcheancePaiement

    _L = {"A_VENIR": "à venir", "PARTIELLE": "partielle",
          "PAYEE": "payée", "RETARD": "en retard"}
    lignes = []
    qs = EcheancePaiement.objects.filter(projet__societe=societe) \
        .select_related("projet__client").order_by("date_prevue")[:limite]
    for e in qs:
        lignes.append(
            f"{e.projet.nom} — échéance #{e.numero_echeance} — {e.montant_prevu} — "
            f"{_L.get(e.statut, e.statut)} — {e.date_prevue:%d/%m/%Y}"
        )
    return lignes


def _liste_depenses(societe, limite=15):
    """Dépenses (libellé, montant, date, statut, type)."""
    _L = {"CONFIRME": "confirmée", "EN_ATTENTE": "en attente", "ANNULE": "annulée"}
    lignes = []
    for d in societe.depenses.select_related("type_depense") \
            .order_by("-date_depense")[:limite]:
        typ = f" — {d.type_depense.nom}" if d.type_depense_id else ""
        lignes.append(
            f"{d.nom} — {d.montant} — {d.date_depense:%d/%m/%Y} — "
            f"{_L.get(d.statut, d.statut)}{typ}"
        )
    return lignes


def _liste_contrats(societe, limite=15):
    """Contrats employés (type, statut, période, salaire contractuel)."""
    from .models import ContratEmploye

    _L = {"ACTIF": "actif", "TERMINE": "terminé", "RESILIE": "résilié"}
    lignes = []
    qs = ContratEmploye.objects.filter(employe__societe=societe) \
        .select_related("employe", "type_contrat").order_by("-date_debut")[:limite]
    for c in qs:
        typ = c.type_contrat.nom or c.type_contrat.code
        fin = c.date_fin.strftime("%d/%m/%Y") if c.date_fin else "sans fin"
        lignes.append(
            f"{c.employe.prenom} {c.employe.nom} — {typ} — "
            f"{_L.get(c.statut, c.statut)} — {c.date_debut:%d/%m/%Y} → {fin}, "
            f"{c.salaire_contractuel}"
        )
    return lignes


def _liste_salaires(societe, limite=15):
    """Paiements de salaire (employé, mois, montant payé, statut)."""
    from .models import PaiementSalaire

    _L = {"PREVU": "prévu", "PARTIEL": "partiel", "PAYE": "payé", "RETARD": "en retard"}
    lignes = []
    qs = PaiementSalaire.objects.filter(employe__societe=societe) \
        .select_related("employe").order_by("-periode_mois")[:limite]
    for s in qs:
        lignes.append(
            f"{s.employe.prenom} {s.employe.nom} — {s.periode_mois:%m/%Y} — "
            f"payé {s.montant_paye} — {_L.get(s.statut, s.statut)}"
        )
    return lignes


def _liste_paiements(societe, limite=15):
    """Paiements clients (client, projet, montant, date, mode, statut)."""
    from .models import PaiementClient

    _L = {"CONFIRME": "confirmé", "EN_ATTENTE": "en attente", "ANNULE": "annulé"}
    lignes = []
    qs = PaiementClient.objects.filter(projet__societe=societe) \
        .select_related("projet__client", "mode_paiement") \
        .order_by("-date_paiement")[:limite]
    for p in qs:
        pre = ""
        if p.projet_id and p.projet.client_id:
            pre = f"{p.projet.client.nom} — "
        mode = f" — {p.mode_paiement.nom}" if p.mode_paiement_id else ""
        lignes.append(
            f"{pre}{p.projet.nom} — {p.montant} — {p.date_paiement:%d/%m/%Y}"
            f"{mode} — {_L.get(p.statut, p.statut)}"
        )
    return lignes


def _liste_reunions(societe, limite=15):
    """Réunions (titre, date, heure, durée)."""
    lignes = []
    for r in societe.reunions.order_by("-date", "-heure")[:limite]:
        lignes.append(f"{r.titre} — {r.date:%d/%m/%Y} à {r.heure:%H:%M} ({r.duree} min)")
    return lignes


# Registre des listes : mots-clés (sans accents, en minuscules), libellé,
# constructeur et compteur. Servi au répondeur hors-ligne uniquement pour les
# modules autorisés du compte.
_LISTES_IA = {
    "employes": (["employ", "personnel", "equipe", "effectif"],
                 "Employés", _liste_employes, lambda s: s.employes.count()),
    "taches": (["tache"], "Tâches", _liste_taches, lambda s: s.taches.count()),
    "clients": (["client"], "Clients", _detail_clients, lambda s: s.clients.count()),
    "prospection": (["prospect"], "Prospects", _liste_prospects,
                    lambda s: s.prospections.count()),
    "projets": (["projet"], "Projets", _liste_projets, lambda s: s.projets.count()),
    "echeances": (["echeance", "facture", "impaye", "creance"], "Échéances",
                  _liste_echeances,
                  lambda s: __import__("gestion.models", fromlist=["EcheancePaiement"])
                  .EcheancePaiement.objects.filter(projet__societe=s).count()),
    "depenses": (["depense"], "Dépenses", _liste_depenses, lambda s: s.depenses.count()),
    "contrats": (["contrat"], "Contrats", _liste_contrats,
                 lambda s: __import__("gestion.models", fromlist=["ContratEmploye"])
                 .ContratEmploye.objects.filter(employe__societe=s).count()),
    "salaires": (["salaire", "paie"], "Salaires", _liste_salaires,
                 lambda s: __import__("gestion.models", fromlist=["PaiementSalaire"])
                 .PaiementSalaire.objects.filter(employe__societe=s).count()),
    "paiements": (["paiement"], "Paiements clients", _liste_paiements,
                  lambda s: __import__("gestion.models", fromlist=["PaiementClient"])
                  .PaiementClient.objects.filter(projet__societe=s).count()),
    "reunions": (["reunion"], "Réunions", _liste_reunions, lambda s: s.reunions.count()),
}


def _repondre_liste(societe, modules, q, salutation):
    """Réponse « liste » pour le module demandé, ou None si la question n'en
    demande pas. Borné aux modules autorisés (``modules``).
    """
    intend = any(
        m in q for m in
        ("liste", "list", "affiche", "detail", "donne moi", "quels",
         "qui sont", "tous les", "recapitulatif", "recap", "montre", "enumer")
    )
    if not intend:
        return None
    paires = []
    for mod, (mots, _label, _fn, _cnt) in _LISTES_IA.items():
        if mod not in modules:
            continue
        for mot in mots:
            if mot in q:
                paires.append((len(mot), mod))
    if not paires:
        return None
    plus_long = max(l for l, _ in paires)
    cibles = sorted({m for l, m in paires if l == plus_long})
    blocs = []
    for mod in cibles:
        _mots, label, fn, cnt = _LISTES_IA[mod]
        blocs.append((label, fn(societe), cnt(societe)))
    entete = "Voici "
    if len(blocs) == 1:
        label, lignes, total = blocs[0]
        entete += f"les {label.lower()} de « {societe.nom} » ({total} au total) :"
    else:
        entete += "les éléments demandés de « {societe.nom} » :"
    vues = set()
    sorties = []
    for _label, lignes, total in blocs:
        for l in lignes:
            if l not in vues:
                vues.add(l)
                sorties.append(l)
    if not sorties:
        return (salutation or "") + entete + "\n\nAucun élément enregistré."
    return (salutation or "") + entete + "\n\n" + "\n".join(
        f"• {l}" for l in sorties[:30]
    )


def repondre_hors_ligne(societe, modules, question):
    """Réponse locale (sans API ni réseau) à partir des données réelles.

    Utilisée quand Groq est indisponible (clé absente/invalide, réseau coupé).
    Reste bornée aux modules autorisés du compte.
    """
    stats = get_module_stats(societe, modules)
    q = " ".join((question or "").lower().split())
    q_sans = q.replace("é", "e").replace("è", "e").replace("ê", "e").replace(
        "à", "a").replace("ô", "o").replace("î", "i").replace("ï", "i").replace(
        "ç", "c").replace("ù", "u")

    def has(*mots):
        return any(m in q_sans for m in mots)

    # Salutation / aide (réponse générale, sans dump de données)
    salutation = None
    if has("bonjour", "salut", "bonsoir", "hello", "coucou", "hey", "bonsoir"):
        salutation = (
            f"Bonjour ! Je suis l'assistant de « {societe.nom} » : je réponds "
            "avec les données actuelles de la société. "
        )
    elif has("aide", "help", "que peux-tu", "que sais-tu", "comment", "fonctionne"):
        salutation = (
            f"Je suis l'assistant de « {societe.nom} » : je réponds avec les "
            "données actuelles de la société, sur les seuls modules autorisés. "
        )

    # Liste détaillée demandée (ex. « liste les employés / projets / échéances… »)
    liste = _repondre_liste(societe, modules, q_sans, salutation)
    if liste is not None:
        return liste

    # Thème(s) demandé(s) -> blocs de statistiques pertinents
    routes = []
    if has("financ", "solde", "tresor", "argent", "caisse", "budget",
           "depense", "revenu", "recette", "encaiss", "bilan", "wallet"):
        routes += ["finances", "paiements", "depenses"]
    if has("employ", "personnel", "equipe", "effectif", "recrut", "contrat"):
        routes += ["employes", "contrats"]
    if has("client"):
        routes += ["clients"]
    if has("projet"):
        routes += ["projets"]
    if has("echeance", "facture", "impaye", "creance", "a venir", "regle"):
        routes += ["echeances", "paiements"]
    if has("salaire", "salair", "paie"):
        routes += ["salaires"]
    if has("connecteur", "integration"):
        routes += ["connecteurs"]
    if has("document", "fichier", "archive"):
        routes += ["documents"]
    if has("synthese", "resume", "rapport", "etat de la societe",
           "vue d'ensemble", "vuedensemble", "global"):
        routes += ["dashboard", "societe"]

    intro = (
        f"Assistant de « {societe.nom} » · réponse générée à partir des "
        f"données actuelles de la société ({societe.pays})."
    )

    # Aucun thème reconnu -> orientation, pas de dump de données
    if not routes:
        dispo = " · ".join(blk["label"] for blk in stats.values()) or "aucun"
        if salutation:
            return salutation + "Je peux vous aider sur : " + dispo + "."
        return (
            intro
            + "\n\nCe thème est hors de mes données. "
            f"Je peux en revanche vous aider sur : {dispo}."
        )

    # Blocs accessibles correspondant au thème
    blocs = []
    vus = set()
    for key in routes:
        if key in stats and key not in vus:
            vus.add(key)
            blocs.append((key, stats[key]))

    if not blocs:
        dispo = " · ".join(blk["label"] for blk in stats.values()) or "aucun"
        return (
            intro
            + "\n\nAccès refusé : le thème de votre question ne fait pas partie "
            f"de vos autorisations. Vous pouvez consulter : {dispo}."
        )

    lignes = []
    for _k, blk in blocs:
        for ligne in blk["lines"]:
            if ligne not in lignes:
                lignes.append(ligne)
    corps = "\n".join(f"• {l}" for l in lignes)
    return (salutation or "") + intro + "\n\n" + corps + (
        "\n\nConseil : utilisez le bouton « Télécharger le rapport PDF » "
        "pour exporter cette synthèse."
    )


# ---------------------------------------------------------------------------
# Commandes : l'assistant peut créer des enregistrements (ex. clients)
# ---------------------------------------------------------------------------

_SOURCES_CLIENT = {
    "recommandation": "RECOMMANDATION",
    "site web": "SITE_WEB",
    "internet": "SITE_WEB",
    "reseaux sociaux": "RESEAUX_SOCIAUX",
    "facebook": "RESEAUX_SOCIAUX",
    "evenement": "EVENEMENT",
    "salon": "EVENEMENT",
    "demarchage": "DEMARCHAGE",
    "partenaire": "PARTENAIRE",
    "autre": "AUTRE",
}

_STATUTS_CLIENT = {
    "actif": "ACTIF",
    "inactif": "INACTIF",
    "suspendu": "SUSPENDU",
}


def _norm_commande(texte):
    t = " ".join((texte or "").lower().split())
    for a, b in {
        "é": "e", "è": "e", "ê": "e", "ë": "e", "à": "a", "â": "a",
        "ô": "o", "î": "i", "ï": "i", "ç": "c", "ù": "u", "û": "u",
    }.items():
        t = t.replace(a, b)
    return t


def _extraire_nom_client(q):
    id = q.find("client")
    if id == -1:
        return ""
    reste = q[id + len("client"):].lstrip(" :,;-")
    for pre in ("avec le nom ", "avec nom ", "qui s'appelle ", "appele ",
                "appelle ", "nomme ", "au nom de ", "un ", "une ", "le ", "la "):
        if reste.startswith(pre):
            reste = reste[len(pre):]
            break
    coupe = len(reste)
    for kw in (" email ", " mail ", " tel ", " telephone ", " numero ",
               " ville ", " pays ", " type ", " source ", " statut ",
               " responsable ", " avec "):
        i = reste.find(kw)
        if i != -1 and i < coupe:
            coupe = i
    for sep in (",", ";"):
        i = reste.find(sep)
        if i != -1 and i < coupe:
            coupe = i
    return reste[:coupe].strip(" :,-;").title()


def _extraire_email(q):
    import re
    m = re.search(r"([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})", q)
    return m.group(1) if m else ""


def _extraire_telephone(q):
    import re
    m = re.search(
        r"(?:tel|telephone|numero|num)\s*[: ]\s*(\+?[0-9][0-9 .\-]{6,15})", q
    )
    return re.sub(r"[^0-9+]", "", m.group(1)) if m else ""


def _champ_apres(motif, q):
    debut = q.find(motif)
    if debut == -1:
        return ""
    reste = q[debut + len(motif):].strip(" :,-;")
    if not reste:
        return ""
    coupe = len(reste)
    for kw in (" email ", " mail ", " tel ", " telephone ", " numero ",
               " ville ", " pays ", " type ", " source ", " statut ",
               " responsable "):
        i = reste.find(kw)
        if i != -1 and i < coupe:
            coupe = i
    for sep in (",", ";", " et "):
        i = reste.find(sep)
        if i != -1 and i < coupe:
            coupe = i
    return reste[:coupe].strip(" -;,").title()


def _parse_commande_ajout_client(q):
    """Extrait les champs d'une demande d'ajout de client, ou None si le
    message ne demande aucun ajout."""
    intend = any(
        mot in q
        for mot in ("ajouter ", "ajoute ", "ajout", "creer un ", "cree un ",
                    "cree le client", "nouveau client", "enregistre un client",
                    "enregistre le client", "inscrire un client")
    )
    if not intend or "client" not in q:
        return None
    nom = _extraire_nom_client(q).strip()
    if not nom:
        return {}
    champs = {
        "nom": nom,
        "telephone": _extraire_telephone(q),
        "email": _extraire_email(q) or None,
        "ville": _champ_apres(" ville ", q) or None,
        "pays": _champ_apres(" pays ", q) or None,
        "type": _champ_apres(" type ", q).lower(),
        "statut": "ACTIF",
        "source": "AUTRE",
    }
    for nom_statut, code in _STATUTS_CLIENT.items():
        if nom_statut in q:
            champs["statut"] = code
            break
    for mot, code in _SOURCES_CLIENT.items():
        if mot in q:
            champs["source"] = code
            break
    return champs


def _creer_client_depuis(societe, user, champs):
    """Crée le client depuis un dict de champs (nom + téléphone requis).

    Mêmes droits que la page Clients : un compte sans le module « clients »
    reçoit un refus. Retourne le texte de confirmation détaillé.
    """
    from .models import Client, TypeClient
    from .services import journaliser, modules_autorises

    if "clients" not in set(modules_autorises(user, societe)):
        return "Accès refusé : vous ne disposez pas du module « Clients », ajout impossible."

    nom = (champs.get("nom") or "").strip()
    telephone = champs.get("telephone") or ""
    if not nom:
        return (
            "Je n'ai pas compris le nom du client. Exemple : "
            "« ajoute le client Acme SARL, tel 06851234, email contact@acme.com, "
            "ville Douala, type Entreprise »."
        )
    if not telephone:
        return (
            f"Pour créer le client « {nom} », il me faut au moins un numéro de "
            "téléphone. Exemple : « tel 06851234 »."
        )

    typ = (champs.get("type") or "").lower()
    type_client = None
    if typ:
        type_client = TypeClient.objects.filter(nom__icontains=typ).first()
    if type_client is None:
        type_client = TypeClient.objects.filter(nom__iexact="Entreprise").first()
    if type_client is None:
        type_client = TypeClient.objects.first()
    if type_client is None:
        type_client = TypeClient.objects.create(
            nom="Entreprise", description="Type créé automatiquement par l'assistant."
        )

    client = Client.objects.create(
        societe=societe,
        nom=nom,
        type_client=type_client,
        email=champs.get("email") or None,
        telephone_1=telephone,
        ville=champs.get("ville") or None,
        pays=champs.get("pays") or None,
        statut=champs.get("statut") or "ACTIF",
        source=champs.get("source") or "AUTRE",
        cree_par=user if getattr(user, "pk", None) else None,
    )
    journaliser(societe, "CREATION", "clients", client.nom, "", user)

    lignes = [
        f"Client « {client.nom} » ajouté avec succès (n° {client.pk}).",
        f"Type : {type_client.nom} · Statut : {client.statut.lower()}",
        f"Téléphone : {client.telephone_1}",
    ]
    if client.email:
        lignes.append(f"Email : {client.email}")
    if client.ville:
        lignes.append(f"Ville : {client.ville}")
    if client.pays:
        lignes.append(f"Pays : {client.pays}")
    return "\n".join(lignes)


def exec_commande_ajout_client(societe, user, message):
    """Crée un client si le message le demande (retourne le texte, sinon None)."""
    q = _norm_commande(message)
    champs = _parse_commande_ajout_client(q)
    if champs is None:
        return None
    return _creer_client_depuis(societe, user, champs)


def _ressemble_a_un_telephone(message):
    import re

    chiffres = re.sub(r"\D", "", (message or ""))
    return len(chiffres) >= 7


def completer_ajout_client(societe, user, message, conversation):
    """Deuxième étape d'un ajout de client : l'utilisateur ne répond que le
    numéro demandé. Reprend la dernière demande d'ajout en attente de la
    conversation et crée le client. Retourne le texte, ou None si inapplicable.
    """
    import re

    if conversation is None or not _ressemble_a_un_telephone(message):
        return None
    for m in conversation.messages.filter(role="user").order_by("-id"):
        champs = _parse_commande_ajout_client(_norm_commande(m.contenu))
        if champs is None:
            continue
        if champs.get("telephone"):
            # La demande a déjà reçu son téléphone : ne pas recréer.
            return None
        if not champs.get("nom"):
            continue
        champs = dict(champs)
        champs["telephone"] = re.sub(r"\D", "", message)
        return _creer_client_depuis(societe, user, champs)
    return None


# ---------------------------------------------------------------------------
# Persistance des conversations (IaConversation / IaMessage)
# ---------------------------------------------------------------------------


def employe_pour_utilisateur(user, societe):
    """Fiche Employe du compte dans la société (None si absente)."""
    if user is None or not getattr(user, "pk", None):
        return None
    employe = getattr(user, "employe_profil", None)
    if employe is not None and employe.societe_id == getattr(societe, "pk", None):
        return employe
    return None


def conversations_ia(user, societe):
    """Conversations IA accessibles au compte dans la société.

    Un compte relié à une fiche employé voit ses propres conversations ;
    un créateur/propriétaire (sans fiche) voit les siennes (employe vide).
    """
    from .models import IaConversation

    if user is None or societe is None:
        return IaConversation.objects.none()
    employe = employe_pour_utilisateur(user, societe)
    if employe is not None:
        return IaConversation.objects.filter(employe=employe)
    if getattr(societe, "createur_id", None) == getattr(user, "pk", None):
        return IaConversation.objects.filter(
            societe=societe, employe__isnull=True
        )
    return IaConversation.objects.none()


def titre_conversation(message):
    """Titre court dérivé du premier message utilisateur."""
    premiere_ligne = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    return (premiere_ligne[:70] + "…") if len(premiere_ligne) > 70 else premiere_ligne