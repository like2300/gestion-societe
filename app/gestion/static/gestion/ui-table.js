/* =====================================================================
   Composant « tableau de données » réutilisable — ui-table.js
   ---------------------------------------------------------------------
   S'applique automatiquement à tout <table class="crud-table"> (et à tout
   tableau portant l'attribut data-ui-table) des pages du dashboard :

   - barre d'outils : recherche instantanée (toutes colonnes ou une seule),
     filtres déroulants générés à partir des colonnes (statuts, types…) ;
   - tri en cliquant sur les en-têtes (texte, nombres, dates jj/mm/aaaa) ;
   - lignes alternées, défilement horizontal sur mobile ;
   - pied : nombre d'enregistrements, pagination, choix de la page.

   Options (attributs sur la balise <table>) :
     data-ui-table="off"        désactive le composant
     data-page-size="10"        lignes par page (défaut 10)
     data-filters="Statut,Type" colonnes filtrables (noms d'en-têtes) ;
                                sinon détection automatique
     data-ui-search="off"       masque la recherche (si la page a la sienne)
     data-tabs="Statut"          colonne affichée en onglets soulignés ("off" : aucun)
     data-no-sort               désactive le tri
   Sur un <th> : data-no-sort, data-no-filter.
   Les lignes « détail » (1re cellule en colspan) restent attachées à la
   ligne qui les précède. Les lignes masquées par un autre script
   (attribut hidden) sont respectées.
   ===================================================================== */
(function () {
    "use strict";

    var TAILLES = [10, 25, 50, 100];
    var MAX_FILTRES = 3;

    function norm(s) {
        return String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();
    }
    function texte(el) {
        return (el && el.textContent || "").replace(/\s+/g, " ").trim();
    }
    function valeurCellule(td) {
        if (!td) return "";
        var badge = td.querySelector(".badge-status, .ui-badge");
        return badge ? texte(badge) : texte(td);
    }
    function enNombre(s) {
        var t = String(s).replace(/[\s  ]/g, "").replace(/[^\d,.\-]/g, "");
        if (!t || !/\d/.test(t)) return null;
        if (t.indexOf(",") !== -1 && t.indexOf(".") === -1) t = t.replace(",", ".");
        else t = t.replace(/,/g, "");
        var n = parseFloat(t);
        return isNaN(n) ? null : n;
    }
    function enDate(s) {
        var m = String(s).match(/(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?/);
        if (!m) return null;
        return +m[3] * 1e8 + +m[2] * 1e6 + +m[1] * 1e4 + (+m[4] || 0) * 100 + (+m[5] || 0);
    }
    function lire(cle, defaut) {
        try { var v = localStorage.getItem(cle); return v === null ? defaut : v; } catch (e) { return defaut; }
    }
    function ecrire(cle, v) {
        try { localStorage.setItem(cle, v); } catch (e) { /* stockage indisponible */ }
    }
    function esc(s) {
        return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html != null) e.innerHTML = html;
        return e;
    }
    var ICO_RECH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>';

    function DataTable(table, index) {
        this.table = table;
        this.id = "uit" + index;
        this.thead = table.tHead;
        this.tbody = table.tBodies[0];
        if (!this.thead || !this.tbody) return;
        this.ths = Array.prototype.slice.call(this.thead.rows[this.thead.rows.length - 1].cells);
        this.taille = parseInt(table.getAttribute("data-page-size") || lire("ui-table-taille", "10"), 10) || 10;
        this.page = 1;
        this.requete = "";
        this.colonne = -1;
        this.filtres = {};
        this.tri = { col: -1, sens: 1 };
        this.collecter();
        if (!this.lignes.length) return;
        this.construire();
        this.observer();
        this.rendre();
    }

    DataTable.prototype.estActions = function (i) {
        var th = this.ths[i];
        return !th || /^actions?$/i.test(texte(th)) || texte(th) === "";
    };

    DataTable.prototype.collecter = function () {
        var self = this;
        this.lignes = [];
        var courante = null;
        Array.prototype.forEach.call(this.tbody.rows, function (tr) {
            var c0 = tr.cells[0];
            var detail = tr.cells.length === 1 || (c0 && c0.colSpan > 1 && courante);
            if (detail && courante) {
                courante.details.push(tr);
                return;
            }
            var cellules = Array.prototype.map.call(tr.cells, valeurCellule);
            courante = {
                tr: tr,
                details: [],
                cellules: cellules,
                recherche: norm((tr.getAttribute("data-search") || "") + " " + texte(tr)),
                ordre: self.lignes.length,
            };
            self.lignes.push(courante);
        });
    };

    DataTable.prototype.colonnesFiltrables = function () {
        var self = this, voulues = this.table.getAttribute("data-filters"), cols = [];
        if (voulues) {
            var noms = voulues.split(",").map(norm);
            this.ths.forEach(function (th, i) { if (noms.indexOf(norm(texte(th))) !== -1) cols.push(i); });
            return cols;
        }
        var n = this.lignes.length;
        this.ths.forEach(function (th, i) {
            if (cols.length >= MAX_FILTRES || self.estActions(i) || th.hasAttribute("data-no-filter")) return;
            var valeurs = {}, nombres = 0, badges = 0;
            self.lignes.forEach(function (l) {
                var v = l.cellules[i] || "";
                if (v && v !== "—") valeurs[v] = 1;
                if (enNombre(v) !== null && /^[\d\s .,\-+]+(\s?[A-Za-z€$%]{0,6})?$/.test(v)) nombres++;
                if (l.tr.cells[i] && l.tr.cells[i].querySelector(".badge-status, .ui-badge")) badges++;
            });
            var distincts = Object.keys(valeurs).length;
            if (nombres > n / 2) return;
            if (badges >= n / 2 && distincts >= 2) { cols.push(i); return; }
            if (distincts >= 2 && distincts <= 8 && distincts <= Math.max(2, n / 2)) cols.push(i);
        });
        return cols;
    };

    DataTable.prototype.valeursColonne = function (i) {
        var valeurs = {};
        this.lignes.forEach(function (l) { var v = l.cellules[i]; if (v && v !== "—") valeurs[v] = (valeurs[v] || 0) + 1; });
        return valeurs;
    };

    // Colonne affichée en onglets soulignés (statut…) : data-tabs="Nom" / "off", sinon auto.
    DataTable.prototype.colonneOnglets = function (cols) {
        var voulu = this.table.getAttribute("data-tabs"), self = this;
        if (voulu === "off") return -1;
        if (voulu) {
            for (var i = 0; i < this.ths.length; i++) if (norm(texte(this.ths[i])) === norm(voulu)) return i;
            return -1;
        }
        for (var c = 0; c < this.ths.length; c++) {
            if (self.estActions(c) || this.ths[c].hasAttribute("data-no-filter")) continue;
            var n = Object.keys(self.valeursColonne(c)).length;
            if (/statut|etat/.test(norm(texte(this.ths[c]))) && n >= 1 && n <= 6) return c;
        }
        return -1;
    };

    DataTable.prototype.construireOnglets = function (i) {
        var self = this, valeurs = this.valeursColonne(i);
        var barre = el("div", "ui-tabs ui-dt-tabs");
        barre.setAttribute("role", "tablist");
        barre.setAttribute("aria-label", "Filtrer par " + texte(this.ths[i]));
        this.onglets = [];
        var ajouter = function (lbl, valeur, nb) {
            var b = el("button", "ui-tab" + (valeur === "" ? " is-active" : ""), esc(lbl) + ' <span class="ui-tab-count">' + nb + "</span>");
            b.type = "button";
            b.setAttribute("role", "tab");
            b.setAttribute("aria-selected", valeur === "" ? "true" : "false");
            b.addEventListener("click", function () { self.choisirOnglet(i, valeur); });
            b.__valeur = valeur;
            self.onglets.push(b);
            barre.appendChild(b);
        };
        ajouter("Tous", "", this.lignes.length);
        Object.keys(valeurs).sort(function (a, b) { return valeurs[b] - valeurs[a]; }).forEach(function (v) { ajouter(v, v, valeurs[v]); });
        return barre;
    };

    DataTable.prototype.choisirOnglet = function (i, valeur) {
        if (valeur) this.filtres[i] = valeur; else delete this.filtres[i];
        (this.onglets || []).forEach(function (b) {
            var actif = b.__valeur === valeur;
            b.classList.toggle("is-active", actif);
            b.setAttribute("aria-selected", actif ? "true" : "false");
        });
        this.page = 1;
        this.rendre();
    };

    DataTable.prototype.construire = function () {
        var self = this, t = this.table;
        this.table.classList.add("ui-dt");
        // Défilement horizontal
        var scroll = el("div", "ui-dt-scroll");
        t.parentNode.insertBefore(scroll, t);
        scroll.appendChild(t);

        var nb = this.lignes.length;
        var avecOutils = nb >= 1 && this.table.getAttribute("data-ui-toolbar") !== "off";
        this.barre = el("div", "ui-dt-bar");
        if (avecOutils) {
            var cols = this.colonnesFiltrables();
            var colOnglets = this.colonneOnglets(cols);
            if (colOnglets >= 0) {
                cols = cols.filter(function (c) { return c !== colOnglets; });
                this.barre.appendChild(this.construireOnglets(colOnglets));
            }
            var l1 = el("div", "ui-dt-row");
            if (t.getAttribute("data-ui-search") !== "off") {
                var grp = el("div", "ui-dt-search");
                grp.innerHTML = ICO_RECH;
                this.champ = el("input");
                this.champ.type = "search";
                this.champ.placeholder = "Rechercher…";
                this.champ.setAttribute("aria-label", "Rechercher dans le tableau");
                grp.appendChild(this.champ);
                this.selCol = el("select", "ui-dt-col");
                this.selCol.setAttribute("aria-label", "Colonne de recherche");
                this.selCol.appendChild(new Option("Toutes les colonnes", "-1"));
                this.ths.forEach(function (th, i) {
                    if (!self.estActions(i)) self.selCol.appendChild(new Option(texte(th), String(i)));
                });
                grp.appendChild(this.selCol);
                l1.appendChild(grp);
                var minuterie;
                this.champ.addEventListener("input", function () {
                    clearTimeout(minuterie);
                    minuterie = setTimeout(function () { self.requete = norm(self.champ.value); self.page = 1; self.rendre(); }, 120);
                });
                this.selCol.addEventListener("change", function () { self.colonne = +self.selCol.value; self.page = 1; self.rendre(); });
            }
            cols.forEach(function (i) {
                var valeurs = self.valeursColonne(i);
                var sel = el("select", "ui-dt-select");
                sel.setAttribute("aria-label", "Filtrer par " + texte(self.ths[i]));
                sel.appendChild(new Option(texte(self.ths[i]) + " : tous", ""));
                Object.keys(valeurs).sort(function (a, b) { return a.localeCompare(b, "fr"); }).forEach(function (v) {
                    sel.appendChild(new Option(v + " (" + valeurs[v] + ")", v));
                });
                sel.addEventListener("change", function () {
                    if (sel.value) self.filtres[i] = sel.value; else delete self.filtres[i];
                    sel.classList.toggle("on", !!sel.value);
                    self.page = 1;
                    self.rendre();
                });
                l1.appendChild(sel);
            });
            this.btnReset = el("button", "ui-dt-reset", "Réinitialiser");
            this.btnReset.type = "button";
            this.btnReset.hidden = true;
            this.btnReset.addEventListener("click", function () { self.reinitialiser(); });
            l1.appendChild(this.btnReset);
            l1.appendChild(el("span", "ui-dt-sp"));
            this.selTaille = el("select", "ui-dt-select ui-dt-size");
            this.selTaille.setAttribute("aria-label", "Lignes par page");
            TAILLES.forEach(function (n) {
                var o = new Option(n + " lignes", String(n));
                if (n === self.taille) o.selected = true;
                self.selTaille.appendChild(o);
            });
            this.selTaille.addEventListener("change", function () {
                self.taille = +self.selTaille.value;
                ecrire("ui-table-taille", self.taille);
                self.page = 1;
                self.rendre();
            });
            l1.appendChild(this.selTaille);
            this.barre.appendChild(l1);
            scroll.parentNode.insertBefore(this.barre, scroll);
        }

        // Tri
        if (!t.hasAttribute("data-no-sort")) {
            this.ths.forEach(function (th, i) {
                if (self.estActions(i) || th.hasAttribute("data-no-sort")) return;
                th.classList.add("ui-dt-sortable");
                th.setAttribute("tabindex", "0");
                th.setAttribute("aria-sort", "none");
                var go = function () {
                    if (self.tri.col === i) self.tri.sens = -self.tri.sens; else self.tri = { col: i, sens: 1 };
                    self.trier();
                    self.rendre();
                };
                th.addEventListener("click", go);
                th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
            });
        }

        // Pied
        this.pied = el("div", "ui-dt-foot");
        this.compte = el("span", "ui-dt-count");
        this.pages = el("div", "ui-dt-pages");
        this.selPage = el("select", "ui-dt-select ui-dt-pagesel");
        this.selPage.setAttribute("aria-label", "Aller à la page");
        this.selPage.addEventListener("change", function () { self.page = +self.selPage.value; self.rendre(); });
        this.pied.appendChild(this.compte);
        this.pied.appendChild(this.pages);
        this.pied.appendChild(this.selPage);
        scroll.parentNode.insertBefore(this.pied, scroll.nextSibling);

        // Ligne « aucun résultat »
        this.vide = el("tr", "ui-dt-empty");
        var td = el("td", "", "Aucun résultat pour cette recherche ou ces filtres.");
        td.colSpan = this.ths.length;
        this.vide.appendChild(td);
    };

    DataTable.prototype.reinitialiser = function () {
        this.filtres = {};
        this.requete = "";
        this.colonne = -1;
        if (this.champ) this.champ.value = "";
        if (this.selCol) this.selCol.value = "-1";
        Array.prototype.forEach.call(this.barre.querySelectorAll("select.on"), function (s) { s.value = ""; s.classList.remove("on"); });
        (this.onglets || []).forEach(function (b) {
            b.classList.toggle("is-active", b.__valeur === "");
            b.setAttribute("aria-selected", b.__valeur === "" ? "true" : "false");
        });
        this.page = 1;
        this.rendre();
    };

    DataTable.prototype.trier = function () {
        var c = this.tri.col, s = this.tri.sens;
        this.ths.forEach(function (th, i) {
            th.classList.remove("asc", "desc");
            if (th.classList.contains("ui-dt-sortable")) th.setAttribute("aria-sort", i === c ? (s > 0 ? "ascending" : "descending") : "none");
        });
        if (c < 0) return;
        this.ths[c].classList.add(s > 0 ? "asc" : "desc");
        this.lignes.sort(function (a, b) {
            var x = a.cellules[c] || "", y = b.cellules[c] || "";
            var dx = enDate(x), dy = enDate(y);
            if (dx !== null && dy !== null) return (dx - dy) * s;
            var nx = enNombre(x), ny = enNombre(y);
            if (nx !== null && ny !== null && /\d/.test(x) && /\d/.test(y)) return (nx - ny) * s || (a.ordre - b.ordre);
            return x.localeCompare(y, "fr", { numeric: true, sensitivity: "base" }) * s || (a.ordre - b.ordre);
        });
        var corps = this.tbody;
        this.lignes.forEach(function (l) {
            corps.appendChild(l.tr);
            l.details.forEach(function (d) { corps.appendChild(d); });
        });
    };

    DataTable.prototype.correspond = function (l) {
        if (l.tr.hidden) return false; // masquée par un filtre propre à la page
        for (var k in this.filtres) {
            if (l.cellules[k] !== this.filtres[k]) return false;
        }
        if (this.requete) {
            var cible = this.colonne >= 0 ? norm(l.cellules[this.colonne]) : l.recherche;
            var mots = this.requete.split(" ");
            for (var i = 0; i < mots.length; i++) if (cible.indexOf(mots[i]) === -1) return false;
        }
        return true;
    };

    DataTable.prototype.rendre = function () {
        var self = this;
        this._enRendu = true;
        var visibles = this.lignes.filter(function (l) { return self.correspond(l); });
        var total = this.lignes.filter(function (l) { return !l.tr.hidden; }).length;
        var nbPages = Math.max(1, Math.ceil(visibles.length / this.taille));
        if (this.page > nbPages) this.page = nbPages;
        var debut = (this.page - 1) * this.taille, fin = debut + this.taille;
        var affichees = {};
        visibles.slice(debut, fin).forEach(function (l, k) { affichees[l.ordre] = k; });
        this.lignes.forEach(function (l) {
            var montre = Object.prototype.hasOwnProperty.call(affichees, l.ordre);
            l.tr.classList.toggle("ui-dt-out", !montre && !l.tr.hidden);
            l.tr.classList.toggle("ui-dt-alt", montre && affichees[l.ordre] % 2 === 1);
            l.details.forEach(function (d) { d.classList.toggle("ui-dt-out", !montre); });
        });
        if (!visibles.length) this.tbody.appendChild(this.vide); else if (this.vide.parentNode) this.vide.remove();

        // Pied
        var filtre = this.requete || Object.keys(this.filtres).length;
        this.compte.textContent = filtre
            ? visibles.length + " résultat" + (visibles.length > 1 ? "s" : "") + " sur " + total
            : total + " enregistrement" + (total > 1 ? "s" : "");
        if (this.btnReset) this.btnReset.hidden = !filtre;
        this.pages.innerHTML = "";
        this.selPage.innerHTML = "";
        // Pagination toujours affichée (même sur une seule page) pour une interface homogène.
        var paginer = visibles.length > 0;
        this.pages.hidden = !paginer;
        this.selPage.hidden = !paginer;
        this.pied.hidden = false;
        if (paginer) {
            var ajouter = function (lbl, p, actif, desactive) {
                var b = el("button", "ui-dt-pg" + (actif ? " on" : ""), lbl);
                b.type = "button";
                if (desactive) b.disabled = true;
                else b.addEventListener("click", function () { self.page = p; self.rendre(); self.haut(); });
                if (actif) b.setAttribute("aria-current", "page");
                self.pages.appendChild(b);
            };
            ajouter("Précédent", this.page - 1, false, this.page === 1);
            var numeros = [];
            for (var p = 1; p <= nbPages; p++) {
                if (p === 1 || p === nbPages || Math.abs(p - this.page) <= 1) numeros.push(p);
                else if (numeros[numeros.length - 1] !== "…") numeros.push("…");
            }
            numeros.forEach(function (p) {
                if (p === "…") self.pages.appendChild(el("span", "ui-dt-dots", "…"));
                else ajouter(String(p), p, p === self.page, false);
            });
            ajouter("Suivant", this.page + 1, false, this.page === nbPages);
            for (var q = 1; q <= nbPages; q++) {
                var o = new Option("Page " + q, String(q));
                if (q === this.page) o.selected = true;
                this.selPage.appendChild(o);
            }
        }
        var self2 = this;
        setTimeout(function () { self2._enRendu = false; }, 0);
    };

    DataTable.prototype.haut = function () {
        var cible = this.barre && this.barre.parentNode ? this.barre : this.table;
        var r = cible.getBoundingClientRect();
        if (r.top < 70) window.scrollBy({ top: r.top - 90, behavior: "smooth" });
    };

    DataTable.prototype.observer = function () {
        // Respecte les filtres propres à la page (lignes masquées via « hidden »).
        if (!window.MutationObserver) return;
        var self = this, minuterie;
        var obs = new MutationObserver(function () {
            if (self._enRendu) return;
            clearTimeout(minuterie);
            minuterie = setTimeout(function () { self.page = 1; self.rendre(); }, 30);
        });
        this.lignes.forEach(function (l) { obs.observe(l.tr, { attributes: true, attributeFilter: ["hidden"] }); });
    };

    function initialiser(racine) {
        var tables = (racine || document).querySelectorAll("table.crud-table, table[data-ui-table]");
        Array.prototype.forEach.call(tables, function (t, i) {
            if (t.getAttribute("data-ui-table") === "off" || t.__uiTable) return;
            if (t.closest && t.closest(".drawer, .ui-dt-skip")) return;
            t.__uiTable = new DataTable(t, i);
        });
    }

    window.UiTable = { init: initialiser };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { initialiser(); });
    else initialiser();
})();
