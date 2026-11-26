/* =====================================================================
   ui-forms.js — champs « style Google » dans tous les panneaux latéraux
   ---------------------------------------------------------------------
   Transforme automatiquement tous les .ffield du tableau de bord (pages, panneaux, modales)
   en champs à libellé flottant (même rendu que components/gfield.html) :
   - texte, nombre, date, e-mail… : libellé dans le champ, qui remonte ;
   - select / select recherchable : libellé fixé en haut du champ ;
   - textarea : libellé en haut, zone plus aérée ;
   - fichier : zone de glisser-déposer avec aperçu (image) ou nom ;
   - cases multiples : puces cochables ; case unique : interrupteur.
   Aucune modification des templates : les valeurs, noms et scripts existants
   restent inchangés. Désactivable par champ : data-gf="off" sur le .ffield.
   ===================================================================== */
(function () {
    "use strict";

    var TEXTES = "input:not([type]),input[type=text],input[type=email],input[type=number],input[type=tel],input[type=url],input[type=password],input[type=search],input[type=date],input[type=time],input[type=datetime-local],input[type=month]";

    function controleUnique(champ) {
        // Les champs internes d'un select recherchable (search-select.js) ne comptent pas.
        return Array.prototype.filter.call(
            champ.querySelectorAll("input:not([type=hidden]),select,textarea"),
            function (el) { return el.tagName === "SELECT" || !el.closest(".ms-wrap, .ms-panel"); }
        );
    }

    function zoneDepot(champ, input, label) {
        if (input.closest(".dz")) return;
        var dz = document.createElement("label");
        dz.className = "dz dz-auto";
        if (input.id) dz.setAttribute("for", input.id);
        dz.innerHTML = '<span class="dz-apercu"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3"/></svg></span>' +
            '<span class="dz-texte"><b>' + (label ? label.textContent.replace(/\s*\*\s*$/, "").trim() : "Fichier") + '</b><small>Glissez-déposez un fichier ici ou <u>parcourez</u></small></span>';
        input.parentNode.insertBefore(dz, input);
        dz.appendChild(input);
        if (label) label.classList.add("gf-titre-dz");
        var titre = dz.querySelector("b"), sous = dz.querySelector("small"), apercu = dz.querySelector(".dz-apercu");
        function montrer(f) {
            if (!f) return;
            titre.textContent = f.name;
            sous.textContent = Math.max(1, Math.round(f.size / 1024)) + " Ko — prêt à être envoyé";
            dz.classList.add("a-fichier");
            if (/^image\//.test(f.type)) {
                var r = new FileReader();
                r.onload = function (e) { apercu.innerHTML = '<img src="' + e.target.result + '" alt="" />'; };
                r.readAsDataURL(f);
            }
        }
        input.addEventListener("change", function () { montrer(input.files && input.files[0]); });
        ["dragenter", "dragover"].forEach(function (t) { dz.addEventListener(t, function (e) { e.preventDefault(); dz.classList.add("survol"); }); });
        ["dragleave", "drop"].forEach(function (t) { dz.addEventListener(t, function (e) { e.preventDefault(); dz.classList.remove("survol"); }); });
        dz.addEventListener("drop", function (e) {
            var f = e.dataTransfer && e.dataTransfer.files[0];
            if (!f) return;
            try { var dt = new DataTransfer(); dt.items.add(f); input.files = dt.files; input.dispatchEvent(new Event("change", { bubbles: true })); } catch (err) { montrer(f); }
        });
    }

    function ameliorer(champ) {
        if (champ.__gf || champ.getAttribute("data-gf") === "off" || champ.classList.contains("gf")) return;
        var label = champ.querySelector(":scope > label");
        var ctrls = controleUnique(champ);
        if (!ctrls.length) return;

        // Cases à cocher / boutons radio
        var cases = champ.querySelectorAll("input[type=checkbox],input[type=radio]");
        if (cases.length && cases.length === ctrls.length) {
            champ.__gf = true;
            if (cases.length === 1 && cases[0].type === "checkbox") champ.classList.add("gf-switch");
            else champ.classList.add("gf-chips");
            return;
        }
        if (ctrls.length !== 1 || !label) return;
        var c = ctrls[0];
        if (c.tagName === "SELECT" && c.hasAttribute("data-searchable") && !champ.querySelector(".ms-wrap")) return; // pas encore amélioré : on réessaiera
        champ.__gf = true;

        if (c.type === "file") { champ.classList.add("gf-file"); zoneDepot(champ, c, label); return; }

        var cible = c;
        if (c.tagName === "SELECT") {
            champ.classList.add("gf", "gf-auto", "gf-select");
            var ms = champ.querySelector(".ms-wrap");
            if (ms) { champ.classList.add("gf-ms"); cible = ms; while (cible.parentNode !== champ) cible = cible.parentNode; }
        } else if (c.tagName === "TEXTAREA") {
            champ.classList.add("gf", "gf-auto", "gf-area");
        } else if (c.matches(TEXTES)) {
            champ.classList.add("gf", "gf-auto");
            if (!c.getAttribute("placeholder")) c.setAttribute("placeholder", " ");
            else if (c.getAttribute("placeholder").trim()) champ.classList.add("gf-fixe");
            if (/^(date|time|datetime-local|month)$/.test(c.type)) champ.classList.add("gf-fixe");
        } else { return; }
        c.classList.add("gf-input");
        cible.parentNode.insertBefore(label, cible.nextSibling);
        var err = champ.querySelector(":scope > ul.errors");
        if (err) champ.classList.add("has-err");
    }

    function init(racine) {
        // Style par défaut : tous les .ffield du tableau de bord (pages, panneaux, modales).
        var zones = (racine || document).querySelectorAll("#dash .ffield, .modal .ffield, [data-gf-zone] .ffield");
        Array.prototype.forEach.call(zones, ameliorer);
    }

    window.UiForms = { init: init };
    function demarrer() { setTimeout(function () { init(); }, 0); }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer); else demarrer();
    window.addEventListener("load", function () { init(); });
    // Champs ajoutés dynamiquement dans un panneau (formsets, popups…)
    if (window.MutationObserver) {
        var minuterie;
        new MutationObserver(function () { clearTimeout(minuterie); minuterie = setTimeout(function () { init(); }, 60); })
            .observe(document.body, { childList: true, subtree: true });
    }
})();
