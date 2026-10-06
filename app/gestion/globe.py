"""Globe 3D : agrégation générique des points géographiques.

Architecture « source générique » :
toute donnée géolocalisable est poussée dans ``PointGeo``, quelle que soit son
origine — module interne (``app:clients``, ``app:finances``) **ou connecteur**
(``connecteur:<pk>`` via :func:`alimenter_connecteur`). Le globe 3D ne
dépend que de ``PointGeo`` : il ne change jamais quand on ajoute une source.

Le globe n'exporte que des **agrégats** (pays → région → ville), jamais de
libellé privé. L'accès est bridé par société et par permission de module :
- propriétaire : toutes les sources ;
- employé : uniquement les sources des modules autorisés.
"""

import datetime

from django.db.models import Q

from . import services
from .geographie import resoudre


MESURES = ["clients", "commandes", "prospects", "ca",
           "publications", "engagements", "abonnes"]
MESURE_LABELS = {
    "clients": "Clients",
    "commandes": "Commandes",
    "prospects": "Prospects",
    "ca": "Chiffre d'affaires",
    "publications": "Publications",
    "engagements": "Engagements",
    "abonnes": "Abonnés",
}
MESURE_COULEURS = {
    "clients": "#38bdf8",
    "commandes": "#a78bfa",
    "prospects": "#fbbf24",
    "ca": "#34d399",
    "publications": "#ec4899",
    "engagements": "#f97316",
    "abonnes": "#22c55e",
}
#: Normalisation des mesures stockées au singulier vers les clés d'agrégat.
MESURE_ALIASES = {"client": "clients", "commande": "commandes", "prospect": "prospects",
                  "publication": "publications", "engagement": "engagements",
                  "abonne": "abonnes"}
#: Mesures agrégées par **somme** des ``valeur`` (les autres sont des compteurs).
MESURES_SOMME = {"ca", "engagements", "abonnes"}
#: Mesures liées à l'activité des réseaux sociaux (affichées dans la vue
#: « Réseaux sociaux » ; exclues de la vue « Plateforme »).
MESURES_RESEAUX = {"publications", "engagements", "abonnes"}
#: Modes d'affichage du globe, en phase avec le sélecteur du template.
MODES_GLOBE = {"tous": "Global", "plateforme": "Plateforme", "sociaux": "Réseaux sociaux"}


def _mesure_canon(mesure):
    return MESURE_ALIASES.get(mesure, mesure if mesure in MESURES else "commande")


def source_module(module):
    return f"app:{module}"


def source_connecteur(connecteur):
    return f"connecteur:{connecteur.pk}"


def _resoudre_coords(pays, ville):
    """Retourne (lat, lng) via la géographie embarquée, ou (None, None)."""
    info = resoudre(pays, ville)
    if not info:
        return None, None
    return float(info[0]), float(info[1])


# ---------------------------------------------------------------------------
# Alimentation interne (modules de l'application)
# ---------------------------------------------------------------------------

def alimenter_app(societe):
    """Reconstruit les points des modules internes (clients, CA, commandes).

    Idempotent : remplace toute la source ``app:*`` de la société par un
    instantané propre à l'instant de l'appel.
    """
    from .models import Client, PaiementClient, PointGeo

    PointGeo.objects.filter(societe=societe, source=source_module("clients")).delete()
    PointGeo.objects.filter(societe=societe, source=source_module("finances")).delete()

    for client in Client.objects.filter(societe=societe):
        lat, lng = _resoudre_coords(client.pays, client.ville)
        PointGeo.objects.create(
            societe=societe,
            source=source_module("clients"),
            mesure="prospect" if client.statut != "ACTIF" else "client",
            pays=(client.pays or "").strip()[:120],
            region="",
            ville=(client.ville or "").strip()[:120],
            latitude=lat,
            longitude=lng,
        )

    paiements = PaiementClient.objects.filter(
        projet__client__societe=societe, statut="CONFIRME"
    ).select_related("projet__client")
    for paiement in paiements:
        client = paiement.projet.client
        lat, lng = _resoudre_coords(client.pays, client.ville)
        PointGeo.objects.create(
            societe=societe,
            source=source_module("finances"),
            mesure="ca",
            pays=(client.pays or "").strip()[:120],
            region="",
            ville=(client.ville or "").strip()[:120],
            latitude=lat,
            longitude=lng,
            valeur=paiement.montant,
            date_evenement=paiement.date_paiement,
        )
        PointGeo.objects.create(
            societe=societe,
            source=source_module("finances"),
            mesure="commande",
            pays=(client.pays or "").strip()[:120],
            region="",
            ville=(client.ville or "").strip()[:120],
            latitude=lat,
            longitude=lng,
            date_evenement=paiement.date_paiement,
        )


# ---------------------------------------------------------------------------
# Alimentation par connecteur (API générique)
# ---------------------------------------------------------------------------

def alimenter_connecteur(connecteur, points, remplacer=False):
    """Alimente le globe avec les points fournis par ``connecteur``.

    ``points`` : itérable de dicts, chacun pouvant contenir
    ``mesure`` (clients|commandes|prospects|ca), ``pays``, ``region``, ``ville``,
    ``latitude``, ``longitude``, ``valeur``, ``date_evenement``.

    - ``remplacer=True`` (synchronisation complète) : purge puis réécrit ;
    - sinon (webhook, événement) : ajoute des points sans tout réécrire.

    Utilisable depuis n'importe quel fournisseur de données (Shopify,
    WooCommerce, CRM…) sans toucher au globe ni au template.
    """
    from .models import PointGeo

    if remplacer:
        vider_connecteur(connecteur)
    for brut in points:
        point = dict(brut)
        mesure = _mesure_canon(point.get("mesure") or "commande")
        lat = point.get("latitude")
        lng = point.get("longitude")
        if lat is None or lng is None:
            lat, lng = _resoudre_coords(point.get("pays"), point.get("ville"))
        date_evenement = point.get("date_evenement")
        if isinstance(date_evenement, str) and date_evenement:
            try:
                date_evenement = datetime.date.fromisoformat(date_evenement[:10])
            except ValueError:
                date_evenement = None
        PointGeo.objects.create(
            societe=connecteur.societe,
            connecteur=connecteur,
            source=source_connecteur(connecteur),
            mesure=mesure,
            pays=(point.get("pays") or "").strip()[:120],
            region=(point.get("region") or "").strip()[:120],
            ville=(point.get("ville") or "").strip()[:120],
            latitude=lat,
            longitude=lng,
            valeur=point.get("valeur"),
            date_evenement=date_evenement,
            metadonnees=point.get("metadonnees") or {},
        )
    return PointGeo.objects.filter(
        societe=connecteur.societe, source=source_connecteur(connecteur)
    ).count()


def vider_connecteur(connecteur):
    """Supprime les points du globe d'un connecteur (déconnexion, sync…)."""
    from .models import PointGeo

    return PointGeo.objects.filter(
        societe=connecteur.societe, source=source_connecteur(connecteur)
    ).delete()[0]


def _sources_sociales(societe):
    """Ensemble des sources ``connecteur:<pk>`` des réseaux sociaux.

    Permet de dissocier l'activité des réseaux sociaux de celle de la
    plateforme dans le globe (modes ``sociaux`` / ``plateforme``).
    """
    from .connecteurs.providers import ReseauSocial
    from .models import Connecteur

    sources = set()
    for c in Connecteur.objects.filter(societe=societe):
        if isinstance(c.classe, type) and issubclass(c.classe, ReseauSocial):
            sources.add(f"connecteur:{c.pk}")
    return sources


# ---------------------------------------------------------------------------
# Restriction par permission
# ---------------------------------------------------------------------------

def points_pour_utilisateur(user, societe, mode=None):
    """QuerySet de points visibles, filtré par permission de module et mode.

    ``mode`` : ``tous`` (défaut), ``plateforme`` (tout sauf réseaux sociaux)
    ou ``sociaux`` (uniquement l'activité des réseaux sociaux). Les permissions
    s'appliquent toujours après le filtre de mode.
    """
    from .models import PointGeo

    qs = PointGeo.objects.filter(societe=societe)
    if mode == "sociaux":
        qs = qs.filter(source__in=_sources_sociales(societe))
    elif mode == "plateforme":
        sociales = _sources_sociales(societe)
        if sociales:
            qs = qs.exclude(source__in=sociales)
    if services.est_createur(user, societe) or getattr(user, "is_superuser", False):
        return qs
    modules = set(services.modules_autorises(user, societe))
    conditions = Q(pk__in=[])
    if "clients" in modules:
        conditions |= Q(source=source_module("clients"))
    if "finances" in modules:
        conditions |= Q(source=source_module("finances"))
    if "connecteurs" in modules:
        conditions |= Q(source__startswith="connecteur:")
    return qs.filter(conditions)


# ---------------------------------------------------------------------------
# Agrégation pays → région → ville
# ---------------------------------------------------------------------------

def _ajoute(cible, mesure, valeur):
    if mesure in MESURES_SOMME:
        cible[mesure] += float(valeur or 0)
    elif mesure in cible:
        cible[mesure] += 1


def _note_coord(coords, cle, lat, lng):
    if lat is None or lng is None:
        return
    if coords.get(cle) is None:
        coords[cle] = (float(lat), float(lng))


def _noeud_geo(pays, ville, lat, lng):
    if lat is None or lng is None:
        lat, lng = _resoudre_coords(pays, ville)
    return lat, lng


def aggreger(points):
    """Agrège des points en pays → région → ville.

    Chaque nœud expose ``totaux`` = {clients, commandes, prospects, ca} où
    ``ca`` est la somme des valeurs et les autres des compteurs.
    """
    totaux_pays, totaux_regions, totaux_villes = {}, {}, {}
    coords_pays, coords_regions, coords_villes = {}, {}, {}

    for p in points.iterator():
        pays = (p.pays or "Inconnu")[:120]
        region = (p.region or "").strip()[:120]
        ville = (p.ville or "").strip()[:120]
        mesure = _mesure_canon(p.mesure)

        _ajoute(totaux_pays.setdefault(pays, {m: 0 for m in MESURES}), mesure, p.valeur)
        _note_coord(coords_pays, pays, p.latitude, p.longitude)

        if region:
            cle = (pays, region)
            _ajoute(totaux_regions.setdefault(cle, {m: 0 for m in MESURES}), mesure, p.valeur)
            _note_coord(coords_regions, cle, p.latitude, p.longitude)
        if ville:
            cle = (pays, region, ville)
            _ajoute(totaux_villes.setdefault(cle, {m: 0 for m in MESURES}), mesure, p.valeur)
            _note_coord(coords_villes, cle, p.latitude, p.longitude)

    liste_pays = []
    for pays, totaux in totaux_pays.items():
        lat = lng = iso2 = None
        centre = resoudre(pays, "")
        if centre:
            lat, lng, iso2 = float(centre[0]), float(centre[1]), str(centre[2])
        if lat is None and coords_pays.get(pays):
            lat, lng = coords_pays[pays]
        liste_pays.append({
            "nom": pays, "lat": lat, "lng": lng, "iso2": iso2, "totaux": totaux,
        })

    liste_regions = []
    for (pays, region), totaux in totaux_regions.items():
        lat = lng = None
        if coords_regions.get((pays, region)):
            lat, lng = coords_regions[(pays, region)]
        if lat is None:
            lat, lng = _noeud_geo(pays, region, None, None)
        liste_regions.append({"pays": pays, "nom": region, "lat": lat, "lng": lng, "totaux": totaux})

    liste_villes = []
    for (pays, region, ville), totaux in totaux_villes.items():
        lat = lng = None
        if coords_villes.get((pays, region, ville)):
            lat, lng = coords_villes[(pays, region, ville)]
        if lat is None:
            lat, lng = _noeud_geo(pays, ville, None, None)
        liste_villes.append({"pays": pays, "region": region, "nom": ville,
                             "lat": lat, "lng": lng, "totaux": totaux})

    total = {m: 0 for m in MESURES}
    for totaux in totaux_pays.values():
        for m in MESURES:
            total[m] += totaux[m]

    return {
        "mesures": [
            {"cle": m, "label": MESURE_LABELS[m], "couleur": MESURE_COULEURS[m],
             "somme": m in MESURES_SOMME, "format_ca": m == "ca"}
            for m in MESURES
        ],
        "total": total,
        "pays": liste_pays,
        "regions": liste_regions,
        "villes": liste_villes,
    }


def payload_pour(user, societe, mode=None):
    """Payload JSON du globe, respectant les permissions du compte et le mode."""
    qs = points_pour_utilisateur(user, societe, mode=mode)
    agr = aggreger(qs)
    libelles = {
        "app:clients": "Clients (application)",
        "app:finances": "Paiements & chiffre d'affaires (application)",
    }
    connecteur_pks = set()
    for valeur in qs.values_list("source", flat=True).distinct():
        if valeur.startswith("connecteur:"):
            connecteur_pks.add(int(valeur.split(":", 1)[1]))
    from .models import Connecteur
    noms = {
        c.pk: (c.nom or c.type_connecteur or "Connecteur")
        for c in Connecteur.objects.filter(pk__in=connecteur_pks)
    }
    sources = []
    for valeur in qs.order_by("source").values_list("source", flat=True).distinct():
        if valeur.startswith("connecteur:"):
            pk = int(valeur.split(":", 1)[1])
            sources.append({"cle": valeur, "label": noms.get(pk) or "Connecteur"})
        else:
            sources.append({"cle": valeur, "label": libelles.get(valeur, "Application")})
    return agr, sources