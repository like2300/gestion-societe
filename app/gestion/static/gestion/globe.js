/* Globe 3D premium — BusinessGlobe.
 *
 * Composant Web générique : consomme un payload JSON d'agrégats géographiques
 * (pays → région → ville) fourni par « gestion/globe.py » et rend une vraie
 * Terre 3D réaliste via la bibliothèque open-source **Globe.GL** (Three.js / WebGL) :
 *   - texture satellite (blue marble), relief (bump), océans brillants (specular) ;
 *   - atmosphère lumineuse + ciel étoilé, éclairage directionnel (ombre/termineur) ;
 *   - marqueurs lumineux proportionnels, halos pulsants, pays teintés par les données ;
 *   - rotation automatique qui cède la main à l'utilisateur (souris + tactile + zoom) ;
 *   - infobulles et clic : pays → région → ville (seulement si les données existent).
 *
 * Séparation stricte : le rendu 3D, les données (JSON), les filtres et la logique
 * métier sont des couches distinctes du composant. Aucune source précise n'est
 * connue ici : connecteur, module interne, tout peut alimenter le même globe.
 */

const FORMAT_NOMBRE = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const FORMAT_COMPACT = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1, notation: "compact" });
const FORMAT_EURO = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

/* Mesures propres aux réseaux sociaux : le serveur tronque le payload
   (mesures + données) selon le mode demandé via ``?mode=``. */
const MESURES_RESEAUX = new Set(["publications", "engagements", "abonnes"]);

/* ------------------------------------------------------------------------ *
 * Utilitaires
 * ------------------------------------------------------------------------ */

function afficherNombre(valeur) {
  const n = Number(valeur || 0);
  return Math.abs(n) >= 10000 ? FORMAT_COMPACT.format(n) : FORMAT_NOMBRE.format(n);
}

function normaliser(texte) {
  return String(texte == null ? "" : texte)
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function _hexVersRgb(hex) {
  const h = String(hex || "").replace("#", "");
  if (h.length === 3) {
    return [parseInt(h[0] + h[0], 16), parseInt(h[1] + h[1], 16), parseInt(h[2] + h[2], 16)];
  }
  const n = parseInt(h.slice(0, 6), 16);
  if (Number.isNaN(n)) return [56, 189, 248];
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function escapeHtml(texte) {
  return String(texte == null ? "" : texte).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* Mesures agrégées par somme de valeurs (√ pour la taille 3D) : le CA,
   les engagements sociaux et les abonnés. À maintenir en phase avec
   gestion/globe.py → MESURES_SOMME. */
const MESURES_SOMME = new Set(["ca", "engagements", "abonnes"]);

function poidsNoeud(node, actifs) {
  const t = node.totaux || {};
  let p = 0;
  for (const cle of actifs) {
    if (MESURES_SOMME.has(cle)) p += Math.sqrt(Math.abs(t[cle] || 0));
    else p += Number(t[cle] || 0);
  }
  return p;
}

function distanceDeg(lat1, lng1, lat2, lng2) {
  const a = lat1 * Math.PI / 180, b = lat2 * Math.PI / 180;
  const dl = (lng2 - lng1) * Math.PI / 180;
  const h = Math.sin((b - a) / 2) ** 2 + Math.cos(a) * Math.cos(b) * Math.sin(dl / 2) ** 2;
  return 2 * Math.asin(Math.min(1, Math.sqrt(h))) * 180 / Math.PI;
}

/* ------------------------------------------------------------------------ *
 * Composant
 * ------------------------------------------------------------------------ */

export class BusinessGlobe {

  constructor(config) {
    this.container = config.container;
    this.url = config.url;
    this.accent = config.accent || "#0284c7";
    this.loader = config.loader || null;
    this.detail = config.detail || null;
    this.filtres = config.filtres || null;
    this.legende = config.legende || null;
    this.sources = config.sources || null;
    this.totaux = config.totaux || null;
    this.bouton = config.bouton || null;
    this.assets = config.assets || {};
    this.controlesMode = config.controlesMode || null;
    this._loaderHtml = null;

    this.mesures = [];
    this.actifs = new Set();
    this.donnees = null;
    this.niveau = "pays";
    this.filtre = null;             // { pays?, region? } pour le niveau courant
    this.monde = null;              // instance globe.gl
    this.rayonGlobe = 100;
    this._polygones = [];
    this._paysParIso = {};
    this._paysParNom = {};
    this._polySurvol = null;
    this._pointSurvol = null;
    this._temporisateurRotation = null;
    this._dernierClic = 0;
    this.panneauNoeud = null;
    this.panneauEnfants = [];
    this.initialise = false;
    this._configPrete = false;
    this.mode = config.mode || "tous";
  }

  /* ------------------------------------------------------------------ *
   * Cycle de vie du composant (rendu 3D)
   * ------------------------------------------------------------------ */

  async initialiserScene() {
    const Globe = window.Globe;
    if (!Globe) {
      throw new Error("Bibliothèque Globe.GL introuvable (window.Globe).");
    }
    const largeur = this.container.clientWidth || 800;
    const hauteur = this.container.clientHeight || 520;

    this.monde = new Globe(this.container, { waitForGlobeReady: false, animateIn: true })
      .globeImageUrl(this._asset("terre"))
      .bumpImageUrl(this._asset("relief"))
      .backgroundImageUrl(this._asset("ciel"))
      .globeCurvatureResolution(4)
      .showAtmosphere(true)
      .atmosphereColor("#7ec8f7")
      .atmosphereAltitude(0.22);

    this.monde.width(largeur).height(hauteur);
    try {
      this.monde.renderer().setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    } catch (e) { /* non bloquant */ }

    if (typeof this.monde.getGlobeRadius === "function") {
      this.rayonGlobe = this.monde.getGlobeRadius();
    }

    const mat = this.monde.globeMaterial && this.monde.globeMaterial();
    if (mat) {
      try { mat.bumpScale = 9; } catch (e) { /* non bloquant */ }
      this._chargerSpeculaire(mat);
    }
    this._reglerLumieres();

    const ctr = this.monde.controls();
    ctr.enableDamping = true;
    ctr.dampingFactor = 0.08;
    ctr.rotateSpeed = 0.5;
    ctr.enablePan = false;
    ctr.minDistance = this.rayonGlobe * 1.02;
    ctr.maxDistance = this.rayonGlobe * 4.2;
    ctr.autoRotate = true;
    ctr.autoRotateSpeed = 0.35;

    this.monde.pointOfView({ lat: 18, lng: 14, altitude: 2.1 }, 0);

    this._polygones = await this._chargementPays();
    this._lierEvenements();
  }

  _asset(nom) {
    return this.assets && this.assets[nom] ? this.assets[nom] : null;
  }

  /* Matériau : relief + océans brillants (reflet du ciel) */
  _chargerSpeculaire(mat) {
    const url = this._asset("eau");
    if (!url || this._speculaireFait) return;
    /* La texture de la Terre (blue marble) est chargée en asynchrone :
       mat.map peut être vide à la création du globe. On retente quelques fois. */
    if (mat.map) {
      this._speculaireFait = true;
      this._construireSpeculaire(mat, url);
    } else {
      let essais = 0;
      const timer = setInterval(() => {
        essais += 1;
        if (mat.map) {
          clearInterval(timer);
          this._speculaireFait = true;
          this._construireSpeculaire(mat, url);
        } else if (essais >= 10) {
          clearInterval(timer);
        }
      }, 250);
    }
  }

  _construireSpeculaire(mat, url) {
    const img = new Image();
    img.onload = () => {
      try {
        const c = document.createElement("canvas");
        c.width = 1024; c.height = 512;
        const cx = c.getContext("2d");
        cx.drawImage(img, 0, 0, c.width, c.height);
        const Tex = mat.map.constructor;
        const tex = new Tex(c);
        tex.wrapS = mat.map.wrapS;
        tex.wrapT = mat.map.wrapT;
        tex.colorSpace = mat.map.colorSpace || "srgb";
        mat.specularMap = tex;
        const Couleur = mat.specular && mat.specular.constructor;
        mat.specular = Couleur ? new Couleur("grey") : mat.specular;
        mat.shininess = 18;
        mat.needsUpdate = true;
      } catch (e) { /* non bloquant */ }
    };
    img.onerror = () => { /* non bloquant */ };
    img.src = url;
  }

  /* Éclairage réaliste : jour/nuit naturel sans ombre portée coûteuse */
  _reglerLumieres() {
    try {
      for (const l of this.monde.lights()) {
        if (l.type === "AmbientLight") l.intensity = 0.7;
        if (l.type === "DirectionalLight") {
          l.position.set(6, 4, 5);
          l.intensity = 1.9;
        }
      }
    } catch (e) { /* non bloquant */ }
  }

  async _chargementPays() {
    const url = this._asset("pays");
    if (!url) return [];
    try {
      const resp = await fetch(url);
      if (!resp.ok) return [];
      const geo = await resp.json();
      return (geo.features || []).filter(f => f && f.properties && f.geometry &&
        (f.geometry.type === "Polygon" || f.geometry.type === "MultiPolygon"));
    } catch (e) {
      return [];
    }
  }

  /* ------------------------------------------------------------------ *
   * Polygones pays (teintés par les données, survol + clic)
   * ------------------------------------------------------------------ */

  _configurerPolygones() {
    if (!this.monde || !this._polygones.length) return;
    this.monde
      .polygonsData(this._polygones)
      .polygonGeoJsonGeometry(f => f.geometry)
      .polygonAltitude(f => (f === this._polySurvol ? 0.02 : 0.005))
      .polygonCapColor(f => this._couleurPays(f))
      .polygonSideColor(() => "rgba(2, 20, 40, 0.12)")
      .polygonStrokeColor(f => (this._infoPays(f) ? "rgba(202, 226, 255, 0.35)" : "rgba(148, 163, 184, 0.08)"))
      .polygonsTransitionDuration(250)
      .polygonLabel(f => this._htmlPays(f));
    this.monde.onPolygonHover((p, prev) => {
      if (p !== prev) {
        this._polySurvol = p;
        this._rafraichirPolygones();
        this._curseur(p ? "pointer" : "grab");
      }
    });
    this.monde.onPolygonClick((f) => {
      this._dernierClic = performance.now();
      const node = this._infoPays(f);
      if (node) this._plonger(node);
      else this._afficherAucuneDonnee(f);
    });
  }

  _infoPays(f) {
    if (!f || !f.properties) return null;
    const iso = String(f.properties.ISO_A2 || "");
    if (/^[a-z]{2}$/i.test(iso)) {
      const node = this._paysParIso[iso.toLowerCase()];
      if (node) return node;
    }
    const nom = normaliser(f.properties.ADMIN || f.properties.NAME || "");
    return this._paysParNom[nom] || null;
  }

  _couleurPays(f) {
    const node = this._infoPays(f);
    if (!node) return "rgba(100, 120, 145, 0.06)";
    const [r, g, b] = this._melanger(node);
    const alpha = f === this._polySurvol ? 0.5 : 0.27;
    return `rgba(${r | 0},${g | 0},${b | 0},${alpha})`;
  }

  _rafraichirPolygones() {
    if (!this.monde || !this._polygones.length) return;
    this.monde
      .polygonAltitude(f => (f === this._polySurvol ? 0.02 : 0.005))
      .polygonCapColor(f => this._couleurPays(f))
      .polygonStrokeColor(f => (this._infoPays(f) ? "rgba(202, 226, 255, 0.35)" : "rgba(148, 163, 184, 0.08)"));
  }

  /* ------------------------------------------------------------------ *
   * Données
   * ------------------------------------------------------------------ */

  async chargement() {
    const sep = this.url.includes("?") ? "&" : "?";
    const resp = await fetch(this.url + sep + "mode=" + encodeURIComponent(this.mode),
      { headers: { "X-Requested-With": "XMLHttpRequest" } });
    if (!resp.ok) throw new Error("Erreur HTTP " + resp.status);
    return await resp.json();
  }

  async lancer() {
    const donnees = await this.chargement();
    await this._hydrater(donnees);
    this._actualiserBoutonsMode();
  }

  /* Bascule de vue : rejoue le payload dans le mode demandé (le serveur
     filtre données + mesures), sans réinitialiser la scène 3D. */
  async changerMode(mode) {
    this.mode = mode;
    this._actualiserBoutonsMode();
    if (this.loader) {
      if (this._loaderHtml === null) this._loaderHtml = this.loader.innerHTML;
      this.loader.innerHTML = this._loaderHtml;
      this.loader.style.color = "";
      this.loader.style.display = "flex";
    }
    try {
      await this.lancer();
    } catch (err) {
      if (this.loader) {
        this.loader.innerHTML = "Impossible de charger cette vue : " + String((err && err.message) || err);
        this.loader.style.color = "#fca5a5";
      }
    }
  }

  _actualiserBoutonsMode() {
    if (!this.controlesMode) return;
    const container = this.controlesMode;
    for (const b of container.querySelectorAll("button[data-mode]")) {
      b.classList.toggle("on", b.dataset.mode === this.mode);
    }
  }

  async _hydrater(donnees) {
    this.donnees = donnees;
    this.mesures = donnees.mesures || [];
    this.actifs = new Set(this.mesures.map(m => m.cle));
    this._indexerPays();
    if (!this.initialise) {
      await this.initialiserScene();
      this.initialise = true;
    }
    this._construireHud();
    this.niveau = "pays";
    this.filtre = null;
    if (!this._configPrete) {
      this._configurerPolygones();
      this._configPrete = true;
    }
    this._rendreCouches();
    this._rafraichirPolygones();
    this._afficherPanneauDepart();
    if (this.loader) this.loader.style.display = "none";
  }

  _indexerPays() {
    this._paysParIso = {};
    this._paysParNom = {};
    for (const p of (this.donnees.pays || [])) {
      if (p.iso2) this._paysParIso[String(p.iso2).toLowerCase()] = p;
      this._paysParNom[normaliser(p.nom || "")] = p;
    }
  }

  /* ------------------------------------------------------------------ *
   * Couches 3D : points lumineux + halos pulsants
   * ------------------------------------------------------------------ */

  _noeudsCourants() {
    const d = this.donnees || { pays: [], regions: [], villes: [] };
    if (this.niveau === "pays") return d.pays || [];
    if (this.niveau === "regions" && this.filtre) {
      return (d.regions || []).filter(r => r.pays === this.filtre.pays);
    }
    if (this.niveau === "villes") {
      if (this.filtre && this.filtre.region) {
        return (d.villes || []).filter(v => v.pays === this.filtre.pays && v.region === this.filtre.region);
      }
      if (this.filtre) return (d.villes || []).filter(v => v.pays === this.filtre.pays);
    }
    return [];
  }

  _rendreCouches() {
    if (!this.monde) return;
    const noeuds = this._noeudsCourants().filter(n =>
      Number.isFinite(Number(n.lat)) && Number.isFinite(Number(n.lng)));
    const wmax = noeuds.reduce((m, n) => Math.max(m, poidsNoeud(n, this.actifs)), 0) || 1;
    const merge = noeuds.length > 160;

    this.monde
      .pointsData(noeuds)
      .pointLat(n => Number(n.lat))
      .pointLng(n => Number(n.lng))
      .pointColor(n => this._couleurHex(n))
      .pointAltitude(n => this._altitudeNoeud(n, wmax))
      .pointRadius(n => this._rayonNoeud(n, wmax))
      .pointResolution(16)
      .pointsMerge(merge)
      .pointsTransitionDuration(400)
      .pointLabel(n => this._htmlNoeud(n));

    const anneaux = noeuds
      .filter(n => poidsNoeud(n, this.actifs) > 0)
      .sort((a, b) => poidsNoeud(b, this.actifs) - poidsNoeud(a, this.actifs))
      .slice(0, 36);
    this.monde
      .ringsData(anneaux)
      .ringLat(n => Number(n.lat))
      .ringLng(n => Number(n.lng))
      .ringColor(n => this._couleurHex(n))
      .ringAltitude(n => this._altitudeNoeud(n, wmax))
      .ringMaxRadius(n => this._rayonNoeud(n, wmax) * 2.3)
      .ringPropagationSpeed(3)
      .ringRepeatPeriod(1300);

    const plausibleHover = noeuds.length <= 60;
    this.monde.onPointHover((p, prev) => {
      if (p === prev) return;
      this._curseur(p ? "pointer" : "grab");
      if (!plausibleHover) return;
      this._pointSurvol = p;
      this.monde.pointAltitude(n => (n === this._pointSurvol
        ? this._altitudeNoeud(n, wmax) + 0.05
        : this._altitudeNoeud(n, wmax)));
    });
    this.monde.onPointClick((p) => {
      this._dernierClic = performance.now();
      if (p) this._plonger(p);
    });
    this.monde.onGlobeClick((coords) => {
      if (performance.now() - this._dernierClic < 400) return;
      const proche = this._noeudPlusProche(coords);
      if (proche) this._plonger(proche);
    });
  }

  _noeudPlusProche(coords) {
    let meilleur = null;
    let dist = 6;
    for (const n of this._noeudsCourants()) {
      if (!Number.isFinite(Number(n.lat)) || !Number.isFinite(Number(n.lng))) continue;
      const d = distanceDeg(Number(n.lat), Number(n.lng), coords.lat, coords.lng);
      if (d < dist) { dist = d; meilleur = n; }
    }
    return meilleur;
  }

  _melanger(node) {
    const t = node.totaux || {};
    let r = 0, g = 0, b = 0, total = 0;
    for (const cle of this.actifs) {
      const p = MESURES_SOMME.has(cle) ? Math.sqrt(Math.abs(t[cle] || 0)) : Number(t[cle] || 0);
      if (!p) continue;
      const m = this.mesures.find(me => me.cle === cle);
      const [cr, cg, cb] = m ? _hexVersRgb(m.couleur) : [56, 189, 248];
      r += cr * p; g += cg * p; b += cb * p; total += p;
    }
    if (!total) return [100, 116, 139];
    return [r / total, g / total, b / total];
  }

  _couleurHex(node) {
    const [r, g, b] = this._melanger(node);
    const h = v => { const s = (v | 0).toString(16); return s.length === 1 ? "0" + s : s; };
    return "#" + h(r) + h(g) + h(b);
  }

  _altitudeNoeud(node, wmax) {
    return 0.05 + 0.03 * Math.sqrt(poidsNoeud(node, this.actifs) / wmax);
  }

  _rayonNoeud(node, wmax) {
    const w = poidsNoeud(node, this.actifs);
    return Math.min(1.95, 0.45 + 1.5 * Math.sqrt(w / wmax));
  }

  /* ------------------------------------------------------------------ *
   * HUD : chips, légende, sources, totaux
   * ------------------------------------------------------------------ */

  _construireHud() {
    if (this.filtres) {
      this.filtres.innerHTML = "";
      for (const m of this.mesures) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "gl-chip on";
        b.dataset.cle = m.cle;
        b.style.borderColor = m.couleur;
        b.innerHTML = `<span class="gl-puce" style="background:${m.couleur}"></span>${m.label}`;
        b.addEventListener("click", () => {
          if (this.actifs.has(m.cle)) { this.actifs.delete(m.cle); b.classList.remove("on"); b.style.borderColor = "rgba(148,163,184,0.25)"; }
          else { this.actifs.add(m.cle); b.classList.add("on"); b.style.borderColor = m.couleur; }
          if (!this.actifs.size) { this.actifs.add(m.cle); b.classList.add("on"); }
          this._regenererEclairage();
        });
        this.filtres.appendChild(b);
      }
    }
    if (this.legende) {
      this.legende.innerHTML = "";
      for (const m of this.mesures) {
        const s = document.createElement("span");
        s.innerHTML = `<span class="gl-puce" style="background:${m.couleur}"></span>${m.label}`;
        this.legende.appendChild(s);
      }
    }
    if (this.sources) {
      this.sources.innerHTML = "";
      for (const src of (this.donnees.sources || [])) {
        const s = document.createElement("span");
        s.className = "gl-src";
        s.textContent = src.label;
        this.sources.appendChild(s);
      }
    }
    if (this.totaux) {
      this.totaux.innerHTML = "";
      const total = this.donnees.total || {};
      for (const m of this.mesures) {
        const c = document.createElement("span");
        c.style.cssText = "background:rgba(241,245,249,0.9); border:1px solid #e2e8f0; color:#334155; border-radius:12px; padding:0.5rem 0.9rem; font-size:0.8rem;";
        c.innerHTML = `<b style="color:${m.couleur}">${this._valeurMesure(m, total[m.cle] || 0)}</b> <span style="color:#64748b">${m.label}</span>`;
        this.totaux.appendChild(c);
      }
      if (this.donnees.derniere_maj) {
        const maj = document.createElement("span");
        maj.className = "gl-maj";
        maj.textContent = "Mise à jour " + new Date(this.donnees.derniere_maj).toLocaleString("fr-FR");
        this.totaux.appendChild(maj);
      }
    }
  }

  _valeurMesure(m, valeur) {
    const fmtCa = m.format_ca || m.cle === "ca";
    return fmtCa ? FORMAT_EURO.format(Number(valeur || 0)) : afficherNombre(valeur);
  }

  _regenererEclairage() {
    this._rendreCouches();
    this._rafraichirPolygones();
    if (this.panneauNoeud) this._afficherPanneau(this.panneauNoeud, this.panneauEnfants);
  }

  /* ------------------------------------------------------------------ *
   * Exploration : clic pays → région → ville
   * ------------------------------------------------------------------ */

  _plonger(node) {
    const d = this.donnees || { regions: [], villes: [] };
    const lat = Number(node.lat), lng = Number(node.lng);
    if (this.niveau === "pays") {
      const regionsF = (d.regions || []).filter(r => r.pays === node.nom);
      const villesF = (d.villes || []).filter(v => v.pays === node.nom);
      if (regionsF.length) {
        this.filtre = { pays: node.nom };
        this.niveau = "regions";
      } else if (villesF.length) {
        this.filtre = { pays: node.nom };
        this.niveau = "villes";
      }
      this._rendreCouches();
      this._afficherPanneau(node, regionsF.length ? regionsF : villesF);
    } else if (this.niveau === "regions") {
      const villesR = (d.villes || []).filter(v => v.pays === this.filtre.pays && v.region === node.nom);
      this.filtre = { pays: this.filtre.pays, region: node.nom };
      this.niveau = "villes";
      this._rendreCouches();
      this._afficherPanneau(node, villesR.length ? villesR : []);
    } else {
      this._afficherPanneau(node, []);
    }
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      const altitude = this.niveau === "pays" ? 1.7 : 1.35;
      this.monde.pointOfView({ lat, lng, altitude }, 700);
    }
  }

  _afficherAucuneDonnee(f) {
    if (!this.detail) return;
    const props = (f && f.properties) || {};
    const nom = props.ADMIN || props.NAME || "Ce pays";
    this.panneauNoeud = null;
    this.panneauEnfants = [];
    this.detail.innerHTML = `
      <div class="gl-chemin">${this._cheminHtml()}</div>
      <h3>${escapeHtml(nom)}</h3>
      <div class="gl-ligne"><span class="gl-desact">Aucune donnée Business pour ce pays pour l'instant.</span></div>`;
    this.detail.classList.add("on");
    this._lierChemin();
  }

  /* Panneau latéral */

  _cheminHtml() {
    const buttons = [`<button type="button" data-niveau="pays">Tous les pays</button>`];
    if (this.filtre && this.filtre.pays) {
      buttons.push(`<button type="button" data-niveau="filtre-pays" data-pays="${escapeHtml(this.filtre.pays)}">${escapeHtml(this.filtre.pays)}</button>`);
    }
    if (this.filtre && this.filtre.region) {
      buttons.push(`<em>${escapeHtml(this.filtre.region)}</em>`);
    }
    return buttons.join('<span style="opacity:.6">›</span>');
  }

  _afficherPanneauDepart() {
    if (!this.detail) return;
    const d = this.donnees || {};
    const total = d.total || {};
    const vide = this.mesures.length === 0 || this.mesures.every(m => !total[m.cle]);
    const indiceMode = this.mode === "sociaux"
      ? "Connectez un réseau social puis synchronisez-le depuis l'espace Connecteurs."
      : this.mode === "plateforme"
        ? "Ajoutez des clients ou des paiements pour voir l'activité de la plateforme."
        : "";
    this.panneauNoeud = null;
    this.panneauEnfants = [];
    this.detail.innerHTML = `
      <div class="gl-chemin">${this._cheminHtml()}</div>
      <h3>Cliquez un point lumineux ou un pays</h3>
      ${this._lignesTotaux(total, true)}
      ${vide && indiceMode ? `<div class="gl-ligne"><span class="gl-desact">${indiceMode}</span></div>` : ""}
      <div class="gl-sous" style="border-top:none;padding-top:0;">
        ${(d.pays || []).slice(0, 8).map(p => `<div><span>${escapeHtml(p.nom)}</span><b>${afficherNombre(poidsNoeud(p, this.actifs))}</b></div>`).join("") || ""}
      </div>`;
    this.detail.classList.add("on");
    this._lierChemin();
  }

  _afficherPanneau(node, enfants) {
    if (!this.detail) return;
    this.panneauNoeud = node;
    this.panneauEnfants = enfants || [];
    const t = node.totaux || {};
    const sous = this.panneauEnfants.slice(0, 12).map(e =>
      `<div><span>${escapeHtml(e.nom)}</span><b>${afficherNombre(poidsNoeud(e, this.actifs))}</b></div>`).join("");
    this.detail.innerHTML = `
      <div class="gl-chemin">${this._cheminHtml()}</div>
      <h3>${escapeHtml(node.nom)}</h3>
      ${this._lignesTotaux(t, false)}
      ${sous ? `<div class="gl-sous">${sous}</div>` : ""}`;
    this.detail.classList.add("on");
    this._lierChemin();
  }

  _lignesTotaux(t, globale) {
    const lignes = this.mesures.map(m => {
      const actif = this.actifs.has(m.cle);
      const valeur = this._valeurMesure(m, t[m.cle] || 0);
      return `<div class="gl-ligne"><span ${!actif ? 'class="gl-desact"' : ""}><span class="gl-puce" style="background:${m.couleur}; width:0.45rem; height:0.45rem; margin-right:0.35rem; display:inline-block;"></span>${m.label}</span><b ${!actif ? 'class="gl-desact"' : ""}>${valeur}</b></div>`;
    }).join("");
    if (globale) {
      return `<div style="margin-top:0.3rem; max-height:180px; overflow:auto;">${lignes}</div>`;
    }
    return lignes;
  }

  _lierChemin() {
    if (!this.detail) return;
    this.detail.querySelectorAll("button[data-niveau]").forEach(b => {
      b.addEventListener("click", () => {
        const niveau = b.dataset.niveau;
        if (niveau === "pays") {
          this.niveau = "pays"; this.filtre = null;
          this._rendreCouches();
          this._rafraichirPolygones();
          this._afficherPanneauDepart();
        } else if (niveau === "filtre-pays") {
          const pays = b.dataset.pays;
          const regionsF = (this.donnees.regions || []).filter(r => r.pays === pays);
          const villesF = (this.donnees.villes || []).filter(v => v.pays === pays);
          this.filtre = { pays };
          this.niveau = regionsF.length ? "regions" : "villes";
          this._rendreCouches();
          this._afficherPanneauDepart();
        }
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * Infobulles
   * ------------------------------------------------------------------ */

  _htmlNoeud(node) {
    const t = node.totaux || {};
    const lignes = this.mesures.map(m => {
      if (!this.actifs.has(m.cle)) return "";
      const valeur = this._valeurMesure(m, t[m.cle] || 0);
      return `<div class="tt-ligne"><span class="gl-puce" style="background:${m.couleur};width:0.45rem;height:0.45rem;border-radius:50%;display:inline-block"></span>${escapeHtml(m.label)}<span class="tt-valeur">${valeur}</span></div>`;
    }).join("");
    return `<div class="tt-titre">${escapeHtml(node.nom || "—")}</div>${lignes || '<div class="tt-ligne tt-vide">Aucune mesure active</div>'}`;
  }

  _htmlPays(f) {
    const props = (f && f.properties) || {};
    const nom = props.ADMIN || props.NAME || "";
    const node = this._infoPays(f);
    if (!node) {
      return `<div class="tt-titre">${escapeHtml(nom)}</div><div class="tt-ligne tt-vide">Aucune donnée Business</div>`;
    }
    return this._htmlNoeud(node);
  }

  /* ------------------------------------------------------------------ *
   * Événements / dimensions / cycle
   * ------------------------------------------------------------------ */

  _curseur(mode) {
    this.container.style.cursor = mode;
  }

  _lierEvenements() {
    let el;
    try { el = this.monde.renderer().domElement; } catch (e) { return; }
    el.style.touchAction = "none";

    const reprise = () => this._reprendreRotation();
    el.addEventListener("pointerdown", reprise);
    el.addEventListener("pointerup", reprise);
    el.addEventListener("wheel", reprise);
    if (this.monde.onZoom) this.monde.onZoom(() => this._reprendreRotation());

    let temporisateurResize;
    window.addEventListener("resize", () => {
      clearTimeout(temporisateurResize);
      temporisateurResize = setTimeout(() => this._mesurer(), 120);
    });

    if (this.bouton) {
      this.bouton.addEventListener("click", () => this.lancer());
    }

    if (this.controlesMode) {
      this.controlesMode.addEventListener("click", (ev) => {
        const b = ev.target.closest("button[data-mode]");
        if (b) this.changerMode(b.dataset.mode);
      });
    }
  }

  _reprendreRotation() {
    if (!this.monde) return;
    try { this.monde.controls().autoRotate = false; } catch (e) { return; }
    clearTimeout(this._temporisateurRotation);
    this._temporisateurRotation = setTimeout(() => {
      if (!this.monde) return;
      try { this.monde.controls().autoRotate = true; } catch (e) { /* non bloquant */ }
    }, 3500);
  }

  _mesurer() {
    if (!this.monde) return;
    const largeur = this.container.clientWidth || 800;
    const hauteur = this.container.clientHeight || 520;
    try {
      this.monde.width(largeur).height(hauteur);
      this.monde.renderer().setSize(largeur, hauteur);
    } catch (e) { /* non bloquant */ }
  }

  /* Libération propre (masquage du composant, mémoire GPU) */
  detruire() {
    clearTimeout(this._temporisateurRotation);
    if (this.monde) {
      try { this.monde._destructor(); } catch (e) { /* non bloquant */ }
      this.monde = null;
    }
    if (this.container) {
      const cv = this.container.querySelector("canvas");
      if (cv) cv.remove();
    }
    this.initialise = false;
  }
}