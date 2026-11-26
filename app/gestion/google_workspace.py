"""Automatisations Google Workspace (compte Google de la société).

Repose sur le connecteur « google_meet » (OAuth, scopes Agenda + e-mail) :
le propriétaire connecte UN compte Google ; tous les membres autorisés en
profitent. Fonctions :

- réunions Meet : création / déplacement / suppression dans Google Agenda ;
- invitations e-mail aux participants (option « invitations ») ;
- échéances de paiement et dates limites de tâches poussées dans l'agenda
  (options « echeances » et « taches ») ;
- lecture des événements de l'agenda pour la page Réunions (option
  « calendrier »).

Le jeton d'accès est rafraîchi automatiquement (refresh token) quand Google
répond 401. Les appels réseau sont courts et ne bloquent jamais une page :
en cas d'échec, l'erreur est notée sur le connecteur et l'action locale
continue.
"""

import threading
import uuid
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TYPE = "google_meet"
OPTIONS_DEFAUT = {
    "invitations": False,
    "echeances": True,
    "taches": True,
    "calendrier": True,
}
OPTIONS_LIBELLES = {
    "invitations": "Envoyer les invitations Google Agenda par e-mail aux participants",
    "echeances": "Ajouter les échéances de paiement dans Google Agenda",
    "taches": "Ajouter les dates limites des tâches dans Google Agenda",
    "calendrier": "Afficher les événements de Google Agenda dans la page Réunions",
}
DELAI = 15


# ---------------------------------------------------------------------------
# Connecteur, options, requêtes authentifiées
# ---------------------------------------------------------------------------


def connecteur(societe):
    """Connecteur Google connecté de la société (ou None)."""
    if societe is None:
        return None
    if "connecteurs" in getattr(settings, "MODULES_DESACTIVES", ()):
        return None
    return societe.connecteurs.filter(type_connecteur=TYPE, statut="CONNECTE").first()


def options(conn):
    conf = (getattr(conn, "configuration", None) or {}).get("workspace") or {}
    return {cle: bool(conf.get(cle, defaut)) for cle, defaut in OPTIONS_DEFAUT.items()}


def enregistrer_options(conn, valeurs):
    conf = dict(conn.configuration or {})
    conf["workspace"] = {cle: bool(valeurs.get(cle)) for cle in OPTIONS_DEFAUT}
    conn.configuration = conf
    conn.save(update_fields=["configuration", "modifie_le"])


def _classe():
    from .connecteurs.providers import GoogleMeet

    return GoogleMeet


def _requete(conn, methode, url, **kwargs):
    """Requête Google avec rafraîchissement automatique du jeton (401)."""
    if conn is None:
        raise ValueError("Google Workspace n'est pas connecté.")
    kwargs.setdefault("timeout", DELAI)
    base = dict(kwargs.pop("headers", None) or {})
    resp = None
    for tentative in range(2):
        jeton = (conn.jetons() or {}).get("access_token", "")
        entetes = dict(base, Authorization=f"Bearer {jeton}")
        resp = requests.request(methode, url, headers=entetes, **kwargs)
        if resp.status_code != 401 or tentative:
            return resp
        try:
            _classe().rafraichir(conn)
        except Exception:
            return resp
    return resp


def _noter_erreur(conn, message):
    if conn is None:
        return
    conn.derniere_erreur = (message or "")[:500]
    conn.save(update_fields=["derniere_erreur", "modifie_le"])


def _message(resp):
    texte = f"Google a répondu {resp.status_code}."
    try:
        detail = (resp.json().get("error") or {}).get("message")
        if detail:
            texte += " " + str(detail)[:200]
    except ValueError:
        pass
    return texte


def _envoi(conn):
    return "all" if options(conn)["invitations"] else "none"


# ---------------------------------------------------------------------------
# Réunions Meet
# ---------------------------------------------------------------------------


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def creer_reunion(conn, reunion):
    """Crée l'événement + lien Meet. Retourne (ok, lien, evenement_id, message)."""
    debut = datetime.combine(reunion.date, reunion.heure)
    fin = debut + timedelta(minutes=reunion.duree or 60)
    corps = {
        "summary": (reunion.titre or "Réunion")[:160],
        "description": reunion.description or "Réunion interne",
        "start": {"dateTime": _iso(debut), "timeZone": settings.TIME_ZONE},
        "end": {"dateTime": _iso(fin), "timeZone": settings.TIME_ZONE},
        "conferenceData": {
            "createRequest": {
                "requestId": uuid.uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    emails = [p.email for p in reunion.participants.all() if p.email]
    if emails:
        corps["attendees"] = [{"email": e} for e in emails]
    try:
        resp = _requete(
            conn, "POST", API,
            params={"conferenceDataVersion": 1, "sendUpdates": _envoi(conn)},
            json=corps,
        )
    except (requests.RequestException, ValueError) as exc:
        return False, "", "", f"Réseau indisponible : {exc}"
    if resp.status_code not in (200, 201):
        return False, "", "", _message(resp)
    data = resp.json() if resp.content else {}
    lien = data.get("hangoutLink") or ""
    if not lien:
        for ep in (data.get("conferenceData") or {}).get("entryPoints") or []:
            if ep.get("entryPointType") == "video" and ep.get("uri"):
                lien = ep["uri"]
                break
    return bool(lien), lien, data.get("id") or "", (
        "Réunion créée." if lien else "Lien Meet introuvable dans la réponse."
    )


def deplacer_reunion(conn, reunion, nouvelle_date):
    debut = datetime.combine(nouvelle_date, reunion.heure)
    fin = debut + timedelta(minutes=reunion.duree or 60)
    try:
        resp = _requete(
            conn, "PATCH", f"{API}/{reunion.evenement_google_id}",
            params={"sendUpdates": _envoi(conn)},
            json={
                "start": {"dateTime": _iso(debut), "timeZone": settings.TIME_ZONE},
                "end": {"dateTime": _iso(fin), "timeZone": settings.TIME_ZONE},
            },
        )
    except (requests.RequestException, ValueError) as exc:
        return False, f"Réseau indisponible : {exc}"
    if resp.status_code not in (200, 201):
        return False, _message(resp)
    return True, "Réunion déplacée dans Google Agenda."


def supprimer_evenement(conn, evenement_id):
    try:
        resp = _requete(
            conn, "DELETE", f"{API}/{evenement_id}", params={"sendUpdates": _envoi(conn)}
        )
    except (requests.RequestException, ValueError) as exc:
        return False, f"Réseau indisponible : {exc}"
    if resp.status_code not in (200, 204, 404, 410):
        return False, _message(resp)
    return True, "Événement supprimé."


# ---------------------------------------------------------------------------
# Échéances et tâches -> Google Agenda (événements « journée entière »)
# ---------------------------------------------------------------------------


def _evenement_echeance(e):
    projet = getattr(e, "projet", None)
    montant = f"{float(e.montant_prevu or 0):,.0f}".replace(",", " ")
    return {
        "summary": f"💰 Échéance n°{e.numero_echeance} — {getattr(projet, 'nom', 'Projet')} ({montant})",
        "description": (
            f"Paiement attendu pour le projet « {getattr(projet, 'nom', '')} ».\n"
            f"Montant prévu : {montant}\nStatut : {e.get_statut_display()}\n\n"
            "Ajouté automatiquement par le Gestionnaire de société."
        ),
        "start": {"date": e.date_prevue.isoformat()},
        "end": {"date": (e.date_prevue + timedelta(days=1)).isoformat()},
        "colorId": "5",
        "transparency": "transparent",
    }


def _evenement_tache(t):
    qui = ""
    if getattr(t, "assignee_id", None):
        a = t.assignee
        qui = f"{getattr(a, 'prenom', '')} {getattr(a, 'nom', '')}".strip()
    return {
        "summary": f"✅ Tâche : {t.titre}" + (f" ({qui})" if qui else ""),
        "description": (
            (t.description or "") + "\n\n"
            f"Priorité : {t.get_priorite_display()} · Statut : {t.get_statut_display()}\n"
            "Ajouté automatiquement par le Gestionnaire de société."
        ).strip(),
        "start": {"date": t.echeance.isoformat()},
        "end": {"date": (t.echeance + timedelta(days=1)).isoformat()},
        "colorId": "2",
        "transparency": "transparent",
    }


def _a_pousser(objet_type, obj):
    if objet_type == "echeance":
        return obj.date_prevue and obj.statut not in ("PAYEE", "ANNULEE", "PAYE")
    if objet_type == "tache":
        return obj.echeance and obj.statut not in ("TERMINEE", "ANNULEE")
    return False


def pousser(conn, societe, objet_type, obj):
    """Crée / met à jour (ou retire) l'événement Google de l'objet."""
    from .models import EvenementGoogle

    lien = EvenementGoogle.objects.filter(
        societe=societe, objet_type=objet_type, objet_id=obj.pk
    ).first()
    if not _a_pousser(objet_type, obj):
        if lien:
            supprimer_evenement(conn, lien.evenement_id)
            lien.delete()
        return "retire" if lien else "ignore"
    corps = _evenement_echeance(obj) if objet_type == "echeance" else _evenement_tache(obj)
    if lien:
        resp = _requete(conn, "PATCH", f"{API}/{lien.evenement_id}",
                        params={"sendUpdates": "none"}, json=corps)
        if resp.status_code in (200, 201):
            lien.save(update_fields=["maj_le"])
            return "maj"
        if resp.status_code not in (404, 410):
            raise ValueError(_message(resp))
        lien.delete()
    resp = _requete(conn, "POST", API, params={"sendUpdates": "none"}, json=corps)
    if resp.status_code not in (200, 201):
        raise ValueError(_message(resp))
    EvenementGoogle.objects.update_or_create(
        societe=societe, objet_type=objet_type, objet_id=obj.pk,
        defaults={"evenement_id": resp.json().get("id", "")},
    )
    return "cree"


def retirer(conn, societe, objet_type, objet_id):
    from .models import EvenementGoogle

    for lien in EvenementGoogle.objects.filter(
        societe=societe, objet_type=objet_type, objet_id=objet_id
    ):
        supprimer_evenement(conn, lien.evenement_id)
        lien.delete()


def _societe_de(objet_type, obj):
    if objet_type == "echeance":
        return getattr(getattr(obj, "projet", None), "societe", None)
    return getattr(obj, "societe", None)


def planifier(objet_type, obj, suppression=False):
    """Appelé par les signaux : synchronise en arrière-plan après la transaction."""
    societe = _societe_de(objet_type, obj)
    conn = connecteur(societe)
    if conn is None:
        return
    opt = options(conn)
    if (objet_type == "echeance" and not opt["echeances"]) or (
        objet_type == "tache" and not opt["taches"]
    ):
        return
    societe_id, conn_id, pk = societe.pk, conn.pk, obj.pk

    def tache_de_fond():
        from django.db import close_old_connections

        from .models import Connecteur, EcheancePaiement, Societe, Tache

        close_old_connections()
        try:
            soc = Societe.objects.get(pk=societe_id)
            c = Connecteur.objects.get(pk=conn_id)
            if suppression:
                retirer(c, soc, objet_type, pk)
            else:
                modele = EcheancePaiement if objet_type == "echeance" else Tache
                o = modele.objects.filter(pk=pk).first()
                if o is not None:
                    pousser(c, soc, objet_type, o)
        except Exception as exc:  # jamais bloquant pour l'utilisateur
            try:
                _noter_erreur(Connecteur.objects.get(pk=conn_id), f"Agenda : {exc}")
            except Exception:
                pass
        finally:
            close_old_connections()

    transaction.on_commit(
        lambda: threading.Thread(target=tache_de_fond, daemon=True).start()
    )


def synchroniser_tout(conn):
    """Pousse toutes les échéances et tâches à venir. Retourne (nombre, message)."""
    from .models import EcheancePaiement, Tache

    societe = conn.societe
    opt = options(conn)
    aujourdhui = timezone.localdate()
    total, erreurs = 0, 0
    lots = []
    if opt["echeances"]:
        lots.append(("echeance", EcheancePaiement.objects.filter(
            projet__societe=societe, date_prevue__gte=aujourdhui - timedelta(days=30)
        ).select_related("projet")))
    if opt["taches"]:
        lots.append(("tache", Tache.objects.filter(
            societe=societe, echeance__isnull=False,
            echeance__gte=aujourdhui - timedelta(days=30),
        ).select_related("assignee")))
    for objet_type, qs in lots:
        for obj in qs[:300]:
            try:
                if pousser(conn, societe, objet_type, obj) in ("cree", "maj"):
                    total += 1
            except Exception:
                erreurs += 1
    cache.delete(f"gw-agenda-{societe.pk}")
    message = f"{total} élément(s) synchronisé(s) avec Google Agenda"
    if erreurs:
        message += f", {erreurs} erreur(s)"
    return total, message + "."


# ---------------------------------------------------------------------------
# Lecture de l'agenda (page Réunions)
# ---------------------------------------------------------------------------


def evenements_agenda(conn, jours_avant=60, jours_apres=180):
    """Événements Google Agenda hors réunions / échéances / tâches déjà liées."""
    from .models import EvenementGoogle

    societe = conn.societe
    cle = f"gw-agenda-{societe.pk}"
    en_cache = cache.get(cle)
    if en_cache is not None:
        return en_cache
    maintenant = timezone.now()
    params = {
        "timeMin": (maintenant - timedelta(days=jours_avant)).isoformat(),
        "timeMax": (maintenant + timedelta(days=jours_apres)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 250,
    }
    resp = _requete(conn, "GET", API, params=params)
    if resp.status_code != 200:
        raise ValueError(_message(resp))
    connus = set(
        societe.reunions.exclude(evenement_google_id="").values_list(
            "evenement_google_id", flat=True
        )
    ) | set(EvenementGoogle.objects.filter(societe=societe).values_list("evenement_id", flat=True))
    sortie = []
    for ev in resp.json().get("items", []):
        if ev.get("id") in connus or ev.get("status") == "cancelled":
            continue
        debut, fin = ev.get("start") or {}, ev.get("end") or {}
        if debut.get("dateTime"):
            d = datetime.fromisoformat(debut["dateTime"].replace("Z", "+00:00"))
            d = timezone.localtime(d) if timezone.is_aware(d) else d
            f = datetime.fromisoformat((fin.get("dateTime") or debut["dateTime"]).replace("Z", "+00:00"))
            f = timezone.localtime(f) if timezone.is_aware(f) else f
            date, heure, heure_fin = d.date().isoformat(), d.strftime("%H:%M"), f.strftime("%H:%M")
            duree = int((f - d).total_seconds() // 60)
        else:
            date, heure, heure_fin, duree = debut.get("date", ""), "Journée", "", 0
        if not date:
            continue
        sortie.append({
            "id": "g-" + ev.get("id", uuid.uuid4().hex),
            "google": True,
            "titre": ev.get("summary") or "(Sans titre)",
            "date": date,
            "heure": heure,
            "fin": heure_fin,
            "duree": duree,
            "description": (ev.get("description") or "")[:1000],
            "lien": ev.get("hangoutLink") or "",
            "agenda_url": ev.get("htmlLink") or "",
            "passee": date < timezone.localdate().isoformat(),
            "participants": [
                a.get("displayName") or a.get("email") or ""
                for a in (ev.get("attendees") or [])[:20]
            ],
            "cree_par": (ev.get("organizer") or {}).get("email", ""),
        })
    cache.set(cle, sortie, 300)
    return sortie
