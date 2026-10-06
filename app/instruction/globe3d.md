# Globe 3D — architecture, alimentation et permissions

Carte du monde interactive : points lumineux par client, commande, CA et
prospect, avec descente **pays → région → ville**. Cette page documente
l'architecture et **comment connecteurs et modules alimentent le globe** sans
rien modifier dans l'interface.

## Vue d'ensemble

```
gestion/
  models.py                 PointGeo (point géolocalisé, table point_geo)
  geographie.py             géocodage hors-ligne (pays/villes, ISO-2, lat/lng)
  globe.py                  alimentation, agrégation, permissions
  views.py                  globe (page) + globe_donnees (JSON)
  static/gestion/globe.js   composant Globe.GL (BusinessGlobe)
  static/gestion/vendor/    globe.gl.min.js + textures + géodonnées pays
templates/gestion/globe.html   coquille de la page
instruction/globe3d.md      ce document
```

Cycle de vie d'un point : un module (applications) ou un connecteur écrit un
« point » via `PointGeo` → `globe.aggreger()` produit une hiérarchie
pays/région/ville → `globe_donnees` renvoie ce JSON → `globe.js` l'affiche.

## Modèle de données

Un point possède :

- `societe` + `source` : `app:clients`, `app:finances` ou `connecteur:<pk>` ;
- `mesure` (stockée au singulier) : `client`, `commande`, `ca`, `prospect` ;
- `paye`, `region`, `ville` (libres) ;
- `latitude` / `longitude` (Decimal(9,6), facultatifs : sinon géocodage auto) ;
- `valeur` : montant (pour `ca`) ;
- `date_evenement` : date ISO de l'événement (ex. date de commande) ;
- `metadonnees` : JSON libre (numéro de commande, id externe, …) ;
- `connecteur` : nullable, FK vers le connecteur qui a émis le point.

L'agrégation compte **un point par occurrence** (1 client = 1 point, 1 commande
= 1 point) et somme `valeur` pour mesurer le CA.

## Alimenter le globe

### Depuis un module applicatif

`globe.alimenter_app(societe)` reconstruit (idempotent) les sources internes :

- `app:clients` : un point `client` par client, `prospect` si statut INACTIF ;
- `app:finances` : pour chaque paiement confirmé, un point `ca` (valeur =
  montant) **et** un point `commande`.

### Depuis un connecteur (le plus simple)

Importer dans `providers.py` et appeler pendant `synchroniser` / `traiter_webhook`
ou toute méthode du provider :

```python
from ..globe import alimenter_connecteur

alimenter_connecteur(connecteur, [
    {
        "mesure": "commande",
        "pays": "France", "region": "Île-de-France", "ville": "Paris",
        "metadonnees": {"reference": "CMD-123"},
        "date_evenement": "2026-09-15T10:30:00Z",
    },
])
```

Le point `ca` suit le même format avec `"valeur": 1200.50`.

Règles de `alimenter_connecteur(connecteur, points, remplacer=False)` :

- **sans télécharger le modèle** : des points `dict` suffisent ;
- `mesure` est normalisé automatiquement (`commande`, `commandes`, `Commande`,
  …) vers la forme stockée ;
- si `latitude`/`longitude` sont absents, `geographie.resoudre(pays, ville)`
  géocode hors-ligne (pays par nom ou code ISO-2 : `FR`, `BF`, `CG`…) ;
- `date_evenement` accepte `date`, `datetime` ou chaîne ISO ;
- `remplace=True` vide d'abord les points du connecteur puis réinscrit tout
  (mode « synchronisation ») ; `False` ajoute (mode « webhook ») ;
- le **créateur** déconnecte → `vider_connecteur(connecteur)` purge ses points.

### Traitement des webhooks

`SiteBoutique.traiter_webhook` (providers.py) montre le patron : il reconnaît
les événements de commande (WooCommerce `order.created`, `order.updated`, …),
extrait l'adresse de facturation (pays, ville) et le total, puis pousse un
point `commande` + un point `ca` vers le globe. Les outils CRM/voyage peuvent
pousser des points `client`/`prospect` de la même façon.

## Permissions

- **Page** : la route `/gestion/globe/` exige le module `globe`
  (`gestion/perm.py`). Sans lui : redirection vers le tableau de bord.
- **Données** : `globe.points_pour_utilisateur(user, societe)` n'expose que les
  sources autorisées — créateur/superuser : tout ; employé : selon ses modules
  (clients → `app:clients`, finances → `app:finances`,
  connecteurs → `connecteur:*`), toujours limité à `societe`.
- Les groupes pays/région/ville sont construits listé depuis ces points ; un
  employé avec les seuls droits « finances » ne voit ni clients ni prospects.
- Les nœuds pays portent aussi `iso2` (code ISO-2 résolu par `geographie`) :
  c'est ce qui permet au front-end de teinter la **forme réelle** de chaque pays
  sur la sphère (voir « Polygones pays » ci-dessous).

## Front-end (Globe.GL)

`gestion/static/gestion/globe.js` (module ES) charge **Globe.GL** — la librairie
open-source (`vasturiano/globe.gl`, MIT) — depuis une copie locale :

- **`gestion/static/gestion/vendor/globe.gl/globe.gl.min.js`** : build UMD
  v2.46.2 (self-contained, expose `window.Globe`, embarque three.js) ; chargé
  dans `globe.html` **avant** le module `globe.js`. Pas de CDN ni de réseau au
  chargement : tout est servie par Django.
- Les fichiers `globe.gl.mjs` et `globe.gl.d.ts` (vendoriés à part) sont de la
  **référence** (l'ESM exige un bundler, il n'est pas utilisé).

Le rendu est une **Terre réaliste** :

- `globeImageUrl` → `vendor/img/earth-blue-marble.jpg` (continents/océans),
  `bumpImageUrl` → `earth-topology.png` (relief, `bumpScale = 9`) ;
- `backgroundImageUrl` → `night-sky.png` (champ d'étoiles) ;
- atmosphère bleue (`#7ec8f7`, altitude 0.22) et lumières naturelles (ambiant
  0.7 + directionnelle 1.9) ;
- **océans brillants** : un `specularMap` est reconstruit depuis
  `earth-water.png` sur un canvas (reflet du ciel), sans importer three.js
  directement (le constructeur du matériau vient de `mat.map.constructor`) ;
  appliqué dès que la texture de la Terre est prête (petite retente 2,5 s).

L'accroche (pivot, HTML, taille, assets, filtres, légende) se passe exactement
comme avant par le constructeur `BusinessGlobe` :

```js
new BusinessGlobe(conteneur, {
  pivot: "#carte-globe",
  lang: "fr",
  filtres: ["clients", "commandes", "prospects", "ca"],  // depuis le JSON
  urlDonnees: "donnees",
  urlSocle: "...",
  assets: { terre, relief, eau, ciel, pays },  // résolus par {% static %}
});
```

Couches rendues :

- **points lumineux** dimensionnés par la racine carrée de la charge (rayon
  0.45–1.95), altitude 0.05–0.08, fusionnés (`pointsMerge`) si très nombreux ;
- **halos pulsants** sur les moteurs principaux (top 36, période 1,3 s) ;
- **polygones pays** : `vendor/geojson/ne_110m_admin_0_countries.geojson`
  (177 pays, dataset officiel de globe.gl), affichés sous les points avec une
  teinte translucide **proportionnelle aux données** par pays, matching par
  `ISO_A2` (fallback nom normalisé) — pays sans données : exempts, clic →
  « Aucune donnée Business… » sans rien inventer ;
- **tooltips** au survol des points/pays (noms, totaux, EUR pour le CA) ;
- **clic : pays → région → ville** quand les données existent (région sautée si
  absente) ; clic sur le globe nu = nœud le plus proche.

Comportement :

- rotation automatique (0.35), **pause dès interaction** (glisser, molette,
  zoom), reprise après 3,5 s d'inactivité ;
- zoom libre (min = 1.02 × rayon, max = 4.2 ×) via les contrôles OrbitControls
  exposés par `world.controls()` (`enableDamping`, `enablePan = false`) ;
- pixel ratio plafonné à 2 (performances) ; `resize` gère la taille ;
- `detruire()` libère la scène (contrôles, anneaux, canvas).

L'actualisation se fait via le bouton « Actualiser » (re-fetch du endpoint
JSON) ; la liste des sources affichées provient de `sources`.