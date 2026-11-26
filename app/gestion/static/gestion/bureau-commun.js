/* Applications intégrées : enregistrement automatique + titre + exports + collaboration (commun aux 3 éditeurs).
   window.Bureau.init({ url, lire: () => contenu, appliquer: (contenu) => void }) puis Bureau.modifie() à chaque changement.

   Collaboration « quasi temps réel » :
   - chaque enregistrement incrémente la version du fichier côté serveur ;
   - toutes les ~2,5 s l'éditeur signale sa présence et récupère la version la plus récente ;
   - si vous n'avez rien en attente, la version du partenaire s'affiche aussitôt ;
   - sinon un bandeau propose de charger sa version ou de garder la vôtre. */
(function () {
    "use strict";
    var cfg = null, minuterie = null, enCours = false, aRefaire = false, sale = false;
    var etat = document.getElementById("bx-etat");
    var titre = document.getElementById("bx-titre");
    var C = {};
    try { C = JSON.parse((document.getElementById("bx-collab") || {}).textContent || "{}") || {}; } catch (e) { C = {}; }
    var version = C.version || 0;
    var conflit = null; // { version, maj_par }
    var reference = null; // dernier contenu connu du serveur (JSON) : évite d'enregistrer sans vrai changement
    function empreinte() { try { return JSON.stringify(cfg.lire()); } catch (e) { return null; } }

    function csrf() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        if (m) return decodeURIComponent(m[1]);
        var i = document.querySelector("input[name=csrfmiddlewaretoken]");
        return i ? i.value : "";
    }
    function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
    function afficher(e, texte) {
        if (!etat) return;
        etat.setAttribute("data-etat", e);
        etat.querySelector("span").textContent = texte;
    }
    function poster(url, corps) {
        return fetch(url, {
            method: "POST", credentials: "same-origin", body: JSON.stringify(corps),
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" }
        }).then(function (r) {
            return r.json().then(function (d) {
                if (!r.ok || !d.ok) { var err = new Error(d.erreur || "Erreur"); err.donnees = d; throw err; }
                return d;
            });
        });
    }
    function envoyer(corps) { return poster(cfg.url, corps); }

    function sauver(forcer) {
        clearTimeout(minuterie);
        if (!sale) return Promise.resolve();
        if (conflit && !forcer) return Promise.resolve(); // on attend la décision de l'utilisateur
        if (enCours) { aRefaire = true; return Promise.resolve(); }
        var contenu = cfg.lire(), json = JSON.stringify(contenu);
        if (json === reference && !forcer) { sale = false; afficher("ok", "À jour"); return Promise.resolve(); }
        enCours = true; sale = false;
        afficher("encours", "Enregistrement…");
        var corps = { contenu: contenu, base: version };
        if (forcer) corps.forcer = true;
        return envoyer(corps)
            .then(function (d) {
                if (d.version) version = d.version;
                reference = json;
                afficher("ok", "Enregistré " + d.maj);
            })
            .catch(function (e) {
                sale = true;
                var d = e.donnees || {};
                if (d.conflit) { montrerConflit({ version: d.version, maj_par: d.maj_par }); afficher("erreur", "Conflit de modification"); }
                else afficher("erreur", "Non enregistré — " + e.message);
            })
            .then(function () { enCours = false; if (aRefaire && !conflit) { aRefaire = false; sale = true; sauver(); } });
    }
    function modifie() {
        sale = true;
        afficher("attente", "Modifications…");
        clearTimeout(minuterie);
        minuterie = setTimeout(sauver, 900);
    }

    if (titre) {
        var dernier = titre.value;
        var majTitre = function () {
            var t = titre.value.trim() || "Sans titre";
            if (t === dernier) return;
            dernier = t;
            document.title = t + " — " + document.title.split(" — ").slice(-1)[0];
            envoyer({ titre: t }).then(function (d) { afficher("ok", "Enregistré " + d.maj); }).catch(function () {});
        };
        titre.addEventListener("change", majTitre);
        titre.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); titre.blur(); } });
        titre.addEventListener("blur", majTitre);
    }
    // Exports : on enregistre d'abord pour exporter la dernière version
    document.querySelectorAll("[data-bx-export]").forEach(function (a) {
        a.addEventListener("click", function (e) {
            if (!sale && !enCours) return;
            e.preventDefault();
            sauver().then(function () {
                if (a.target === "_blank") window.open(a.href, "_blank"); else location.href = a.href;
            });
        });
    });
    window.addEventListener("beforeunload", function (e) {
        if (sale || enCours) { sauver(); e.preventDefault(); e.returnValue = ""; }
    });
    window.addEventListener("pagehide", function () {
        if (!C.etat || !navigator.sendBeacon) return;
        var fd = new FormData(); fd.append("quitter", "1"); fd.append("csrfmiddlewaretoken", csrf());
        try { navigator.sendBeacon(C.etat, fd); } catch (e) {}
    });
    document.addEventListener("keydown", function (e) {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); sale = true; sauver(); }
    });

    /* ---------------- Collaboration ---------------- */
    var bandeau = document.getElementById("bx-conflit");
    function montrerConflit(c) {
        conflit = c;
        if (!bandeau) return;
        document.getElementById("bx-conflit-txt").textContent =
            (c.maj_par || "Un partenaire") + " a modifié ce fichier pendant que vous écriviez.";
        bandeau.hidden = false;
    }
    function cacherConflit() { conflit = null; if (bandeau) bandeau.hidden = true; }
    function appliquer(contenu, v, par) {
        if (!cfg || !cfg.appliquer) return;
        try { cfg.appliquer(contenu); } catch (e) { console.error(e); return; }
        version = v; sale = false;
        setTimeout(function () { reference = empreinte(); }, 400);
        afficher("ok", par ? "Mis à jour par " + par : "À jour");
    }
    if (bandeau) {
        document.getElementById("bx-conflit-charger").addEventListener("click", function () {
            clearTimeout(minuterie);
            fetch(C.etat + "?v=1&tout=1", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
                if (d.contenu) appliquer(d.contenu, d.version, d.maj_par);
                cacherConflit();
            });
        });
        document.getElementById("bx-conflit-garder").addEventListener("click", function () {
            cacherConflit(); sale = true; sauver(true);
        });
    }

    var presents = document.getElementById("bx-presents");
    function rendrePresents(liste) {
        if (!presents) return;
        liste = liste || [];
        var autres = liste.filter(function (p) { return !p.moi; });
        var tous = liste.filter(function (p) { return p.moi; }).concat(autres);
        presents.innerHTML = tous.slice(0, 5).map(function (p) {
            return '<span class="bx-av' + (p.moi ? " moi" : "") + '" style="--c:' + esc(p.c) + '" title="' + esc(p.moi ? p.nom + " (vous)" : p.nom + " est dans ce fichier") + '">' + esc(p.ini) + "</span>";
        }).join("") + (tous.length > 5 ? '<span class="bx-av plus">+' + (tous.length - 5) + "</span>" : "");
        presents.classList.toggle("actif", autres.length > 0);
    }

    var delai = 2500, sondage = null;
    function sonder() {
        clearTimeout(sondage);
        if (!C.etat) return;
        fetch(C.etat + "?v=" + version, { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (r) { if (r.status === 404 || r.status === 403) { delai = 0; throw new Error("accès"); } return r.json(); })
            .then(function (d) {
                rendrePresents(d.presents);
                majPartage(d);
                if (titre && d.titre && document.activeElement !== titre && d.titre !== titre.value) { titre.value = d.titre; }
                if (d.version > version && d.contenu) {
                    if (!sale && !enCours && !conflit) appliquer(d.contenu, d.version, d.maj_par_moi ? "" : d.maj_par);
                    else if (!conflit && !d.maj_par_moi) montrerConflit({ version: d.version, maj_par: d.maj_par });
                }
            })
            .catch(function () {})
            .then(function () { if (delai) sondage = setTimeout(sonder, document.hidden ? 10000 : delai); });
    }
    document.addEventListener("visibilitychange", function () { if (!document.hidden) sonder(); });

    /* ---------------- Partage ---------------- */
    var modal = document.getElementById("bx-partage");
    var EMP = C.employes || [];
    var choisis = (C.partenaires || []).slice();
    var nbBadge = document.getElementById("bx-partager-nb");
    function couleur(n) { var h = 0; for (var i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) % 360; return "hsl(" + h + " 62% 48%)"; }
    function init2(n) { var p = n.split(/\s+/).filter(Boolean); return ((p[0] || "?")[0] + (p[1] ? p[1][0] : "")).toUpperCase(); }
    function norm(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
    function majBadge() {
        if (!nbBadge) return;
        var n = (C.partenaires || []).length;
        nbBadge.hidden = !n;
        nbBadge.textContent = n;
        var b = document.getElementById("bx-partager");
        if (b) b.classList.toggle("prive", !!C.prive);
    }
    function majPartage(d) {
        if (!d || !("partenaires" in d)) return;
        C.partenaires = d.partenaires; C.prive = d.prive; C.peut_partager = d.peut_partager;
        majBadge();
    }
    if (modal) {
        var q = document.getElementById("bx-part-q"), liste = document.getElementById("bx-part-liste"),
            membres = document.getElementById("bx-part-membres"), prive = document.getElementById("bx-prive"),
            info = document.getElementById("bx-partage-info"), ok = document.getElementById("bx-partage-ok");
        var options = [];
        var rendreMembres = function () {
            var lecture = !C.peut_partager;
            membres.innerHTML = choisis.length ? choisis.map(function (pk) {
                var e = EMP.find(function (x) { return x.pk === pk; }); if (!e) return "";
                return '<li><span class="sal-av" style="background:' + couleur(e.nom) + '">' + esc(init2(e.nom)) + '</span><span class="bx-part-txt"><b>' + esc(e.nom) + "</b><small>" +
                    esc(e.fonction || "Employé") + (e.compte ? "" : " · sans compte de connexion") + "</small></span>" +
                    '<span class="bx-part-role">Peut modifier</span>' +
                    (lecture ? "" : '<button type="button" data-retirer="' + pk + '" aria-label="Retirer ' + esc(e.nom) + '">×</button>') + "</li>";
            }).join("") : '<li class="bx-part-vide">Aucun partenaire pour l\'instant. Ajoutez des employés pour modifier ce fichier à plusieurs.</li>';
        };
        var rendreListe = function () {
            var m = norm(q.value).trim().split(/\s+/).filter(Boolean);
            options = EMP.filter(function (e) {
                return choisis.indexOf(e.pk) === -1 && m.every(function (w) { return norm(e.nom + " " + e.fonction).indexOf(w) !== -1; });
            }).slice(0, 7);
            liste.innerHTML = options.length ? options.map(function (e, i) {
                return '<li class="sal-sugg-opt" data-i="' + i + '"><span class="sal-av" style="background:' + couleur(e.nom) + '">' + esc(init2(e.nom)) +
                    '</span><span class="sal-sugg-txt"><b>' + esc(e.nom) + "</b><small>" + esc(e.fonction || "Sans fonction") + (e.compte ? "" : " · sans compte") + "</small></span></li>";
            }).join("") : '<li class="sal-sugg-vide">Aucun employé à ajouter.</li>';
            liste.hidden = false;
        };
        var ajouter = function (e) { if (e && choisis.indexOf(e.pk) === -1) choisis.push(e.pk); q.value = ""; rendreMembres(); rendreListe(); q.focus(); };
        q.addEventListener("focus", rendreListe);
        q.addEventListener("input", rendreListe);
        q.addEventListener("blur", function () { setTimeout(function () { liste.hidden = true; }, 120); });
        q.addEventListener("keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); ajouter(options[0]); }
            if (e.key === "Escape") { liste.hidden = true; }
        });
        liste.addEventListener("mousedown", function (e) {
            var li = e.target.closest(".sal-sugg-opt"); if (!li) return;
            e.preventDefault(); ajouter(options[+li.getAttribute("data-i")]);
        });
        membres.addEventListener("click", function (e) {
            var b = e.target.closest("[data-retirer]"); if (!b) return;
            var pk = +b.getAttribute("data-retirer");
            choisis = choisis.filter(function (x) { return x !== pk; }); rendreMembres();
        });
        var ouvrir = function () {
            choisis = (C.partenaires || []).slice();
            prive.checked = !!C.prive;
            var lecture = !C.peut_partager;
            prive.disabled = lecture; q.parentNode.hidden = lecture; ok.hidden = lecture;
            info.hidden = !lecture;
            if (lecture) info.textContent = "Seul " + (C.createur ? C.createur + " (créateur)" : "le créateur") + " ou l'administration peut modifier le partage.";
            var nom = document.getElementById("bx-partage-nom"); if (nom && titre) nom.textContent = titre.value;
            rendreMembres();
            modal.hidden = false;
            requestAnimationFrame(function () { modal.classList.add("ouvert"); });
            if (!lecture) setTimeout(function () { q.focus(); }, 80);
        };
        var fermer = function () { modal.classList.remove("ouvert"); setTimeout(function () { modal.hidden = true; liste.hidden = true; }, 180); };
        document.getElementById("bx-partager").addEventListener("click", ouvrir);
        modal.addEventListener("click", function (e) { if (e.target.closest("[data-bx-fermer]")) fermer(); });
        document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !modal.hidden) fermer(); });
        ok.addEventListener("click", function () {
            ok.disabled = true;
            poster(C.partage, { prive: prive.checked, partenaires: choisis })
                .then(function (d) {
                    majPartage(d); fermer();
                    if (window.showToast) window.showToast("success", choisis.length ? "Partage enregistré : " + choisis.length + " partenaire(s) peuvent modifier ce fichier." : "Partage mis à jour.");
                })
                .catch(function (e) { if (window.showToast) window.showToast("error", e.message); })
                .then(function () { ok.disabled = false; });
        });
    }
    majBadge();

    window.Bureau = {
        init: function (c) { cfg = c; reference = empreinte(); if (C.etat) setTimeout(sonder, 600); },
        modifie: modifie,
        sauver: function () { sale = true; return sauver(); }
    };
})();
