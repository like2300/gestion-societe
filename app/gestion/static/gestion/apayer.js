/* =====================================================================
   Panneau « à payer / à encaisser » (Salaires, Échéances) — réutilisable.
   <section class="panel apayer" data-apayer data-url="…json…" data-mois="AAAA-MM"
       data-phrase="{n} employé(s) restent à payer pour {mois}."
       data-phrase-vide="Tous les salaires de {mois} sont réglés."
       data-bouton="Payer" data-hint="À générer">
   La réponse JSON : {mois, total, nb, pdf, lignes:[{employe, fonction, telephone, statut,
   date_prevue, montant_du, montant_paye, reste, payer_url, anterieure?}]}
   ===================================================================== */
(function () {
    "use strict";
    var STAT = {
        PREVU: ["Prévu", "prevu"], A_VENIR: ["À venir", "prevu"], PARTIEL: ["Partiel", "partiel"],
        PARTIELLE: ["Partielle", "partiel"], RETARD: ["En retard", "retard"], NON_GENERE: ["Sans fiche", "nongen"]
    };
    var MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

    function esc(t) {
        return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }
    function fcfa(v) { return Math.round(Number(v) || 0).toLocaleString("fr-FR") + " FCFA"; }
    function libMois(v) { var p = v.split("-"); return MOIS[+p[1] - 1] + " " + p[0]; }
    function dateFr(iso) { if (!iso) return "—"; var p = iso.split("-"); return p[2] + "/" + p[1] + "/" + p[0].slice(2); }
    function couleur(nom) {
        var h = 0; nom = String(nom || "");
        for (var i = 0; i < nom.length; i++) h = (h * 31 + nom.charCodeAt(i)) % 360;
        return "hsl(" + h + " 62% 48%)";
    }
    function initiales(nom) {
        return String(nom || "?").split(/\s+/).filter(Boolean).slice(0, 2).map(function (x) { return x[0]; }).join("").toUpperCase();
    }
    function csrf() {
        var i = document.querySelector("input[name=csrfmiddlewaretoken]");
        if (i) return i.value;
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : "";
    }
    window.UiAvatar = { couleur: couleur, initiales: initiales, esc: esc };

    function init(ap) {
        if (ap.__apayer) return;
        ap.__apayer = true;
        var url = ap.getAttribute("data-url");
        var champ = ap.querySelector("[data-apayer-mois]");
        var liste = ap.querySelector("[data-apayer-liste]");
        var sous = ap.querySelector("[data-apayer-sous]");
        var plus = ap.querySelector("[data-apayer-plus]");
        var resume = ap.querySelector("[data-apayer-resume]");
        var bouton = ap.getAttribute("data-bouton") || "Payer";
        var hint = ap.getAttribute("data-hint") || "";
        var APERCU = 6, deplie = false, derniere = null;

        function phrase(attr, d, n) {
            return (ap.getAttribute(attr) || "").replace("{n}", n).replace("{mois}", libMois(d.mois));
        }
        function rendre(d) {
            derniere = d;
            var lignes = d.lignes || [];
            var n = function (sel, v) { var el = ap.querySelector(sel); if (el) el.textContent = v; };
            n("[data-apayer-nb]", lignes.length);
            n("[data-apayer-total]", fcfa(d.total));
            n("[data-apayer-retard]", lignes.filter(function (l) { return l.statut === "RETARD"; }).length);
            n("[data-apayer-autre]", lignes.filter(function (l) { return l.statut === "NON_GENERE" || l.anterieure; }).length);
            if (resume) resume.hidden = false;
            sous.textContent = lignes.length ? phrase("data-phrase", d, lignes.length) : phrase("data-phrase-vide", d, 0);
            var pdf = ap.querySelector("[data-apayer-pdf]"), voir = ap.querySelector("[data-apayer-voir]");
            if (pdf) pdf.href = d.pdf + "&dl=1";
            if (voir) voir.href = d.pdf;
            if (!lignes.length) {
                liste.innerHTML = '<li class="apayer-vide"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></svg>' + esc(ap.getAttribute("data-vide") || "Rien en attente pour ce mois.") + "</li>";
                plus.hidden = true;
                return;
            }
            var visibles = deplie ? lignes : lignes.slice(0, APERCU);
            liste.innerHTML = visibles.map(function (l, i) {
                var st = STAT[l.statut] || [l.statut, "prevu"];
                var partiel = Number(l.montant_paye) > 0 ? "<small>sur " + fcfa(l.montant_du) + "</small>" : "";
                var action = l.payer_url
                    ? '<form method="post" action="' + esc(l.payer_url) + '" class="apayer-payer">' +
                      '<input type="hidden" name="csrfmiddlewaretoken" value="' + esc(csrf()) + '">' +
                      '<input type="hidden" name="date_paiement" value="' + new Date().toISOString().slice(0, 10) + '">' +
                      '<button type="submit" title="Valider comme réglé" aria-label="' + esc(bouton + " : " + l.employe) + '">' +
                      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>' + esc(bouton) + "</button></form>"
                    : '<span class="apayer-hint">' + esc(hint) + "</span>";
                return '<li class="apayer-ligne" style="--i:' + i + '">' +
                    '<span class="sal-av" style="background:' + couleur(l.employe) + '">' + esc(initiales(l.employe)) + "</span>" +
                    '<span class="apayer-qui"><b>' + esc(l.employe) + "</b><small>" + esc(l.fonction || "—") + " · prévu le " + dateFr(l.date_prevue) + "</small></span>" +
                    '<span class="apayer-st ' + st[1] + '">' + st[0] + "</span>" +
                    '<span class="apayer-mt"><b>' + fcfa(l.reste) + "</b>" + partiel + "</span>" + action + "</li>";
            }).join("");
            plus.hidden = lignes.length <= APERCU;
            plus.textContent = deplie ? "Réduire la liste" : "Voir la liste complète (" + lignes.length + ")";
        }
        function charger() {
            var mois = champ.value || ap.getAttribute("data-mois");
            ap.classList.add("charge");
            fetch(url + (url.indexOf("?") === -1 ? "?" : "&") + "mois=" + encodeURIComponent(mois),
                { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
                .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
                .then(function (d) { deplie = false; rendre(d); })
                .catch(function () { sous.textContent = "Impossible de charger la liste."; })
                .then(function () { ap.classList.remove("charge"); });
        }
        champ.addEventListener("change", charger);
        ap.querySelectorAll("[data-mois-pas]").forEach(function (b) {
            b.addEventListener("click", function () {
                var p = (champ.value || ap.getAttribute("data-mois")).split("-");
                var d = new Date(+p[0], +p[1] - 1 + (+b.getAttribute("data-mois-pas")), 1);
                champ.value = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
                charger();
            });
        });
        plus.addEventListener("click", function () { deplie = !deplie; if (derniere) rendre(derniere); });
        charger();
    }

    function tout() { document.querySelectorAll("[data-apayer]").forEach(init); }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tout);
    else tout();
})();
