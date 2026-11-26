/* =====================================================================
   wa-picker.js — sélecteur de membres « style WhatsApp »
   (templates/gestion/snippets/wa_picker.html)
   - recherche instantanée (sans accents, nom / fonction / e-mail) ;
   - puces des membres sélectionnés (avatar + ×) ;
   - compteur « N sélectionné(s) » ; les sélectionnés remontent en tête.
   API : WaPicker.refresh(racine?) après un cochage par script ou un reset().
   ===================================================================== */
(function () {
    "use strict";
    if (window.WaPicker) return;
    function norm(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim(); }

    function sync(p) {
        var items = p.querySelectorAll(".wa-item"), chips = p.querySelector("[data-wa-chips]");
        var n = 0, html = "";
        Array.prototype.forEach.call(items, function (it) {
            var cb = it.querySelector("input");
            it.classList.toggle("on", cb.checked);
            if (!cb.checked) return;
            n++;
            var av = it.querySelector(".wa-av").cloneNode(true);
            var online = av.querySelector(".wa-online"); if (online) online.remove();
            html += '<button type="button" class="wa-chip" data-wa-retirer="' + cb.value + '" title="Retirer">' +
                av.outerHTML + "<span>" + it.getAttribute("data-wa-nom").split(" ")[0] + "</span><em>×</em></button>";
        });
        chips.innerHTML = html;
        chips.hidden = n === 0;
        var compte = p.querySelector("[data-wa-compte]");
        compte.textContent = n ? n + " sélectionné" + (n > 1 ? "s" : "") + " sur " + items.length : items.length + " au total";
        p.dispatchEvent(new CustomEvent("wa:change", { bubbles: true, detail: { total: n } }));
    }

    function filtrer(p) {
        var q = norm(p.querySelector("[data-wa-q]").value), vus = 0;
        Array.prototype.forEach.call(p.querySelectorAll(".wa-item"), function (it) {
            var ok = !q || norm(it.getAttribute("data-wa-nom") + " " + it.getAttribute("data-wa-sub")).indexOf(q) !== -1;
            it.hidden = !ok;
            if (ok) vus++;
        });
        var aucun = p.querySelector("[data-wa-aucun]");
        aucun.hidden = vus > 0;
        aucun.querySelector("span").textContent = p.querySelector("[data-wa-q]").value;
        p.querySelector("[data-wa-clear]").hidden = !q;
    }

    function init(p) {
        if (p.__wa) return;
        p.__wa = true;
        var q = p.querySelector("[data-wa-q]");
        q.addEventListener("input", function () { filtrer(p); });
        q.addEventListener("keydown", function (e) {
            if (e.key === "Enter") { // Entrée : coche le premier résultat
                e.preventDefault();
                var premier = p.querySelector(".wa-item:not([hidden]) input");
                if (premier) { premier.checked = !premier.checked; sync(p); q.select(); }
            }
        });
        p.querySelector("[data-wa-clear]").addEventListener("click", function () { q.value = ""; filtrer(p); q.focus(); });
        p.addEventListener("change", function (e) { if (e.target.matches(".wa-item input")) sync(p); });
        p.querySelector("[data-wa-chips]").addEventListener("click", function (e) {
            var b = e.target.closest("[data-wa-retirer]"); if (!b) return;
            var cb = p.querySelector('.wa-item input[value="' + b.getAttribute("data-wa-retirer") + '"]');
            if (cb) { cb.checked = false; sync(p); }
        });
        sync(p);
    }

    function refresh(racine) {
        Array.prototype.forEach.call((racine || document).querySelectorAll("[data-wa-picker]"), function (p) {
            init(p);
            var q = p.querySelector("[data-wa-q]"); q.value = "";
            filtrer(p); sync(p);
        });
    }

    window.WaPicker = { refresh: refresh };
    function demarrer() { refresh(); }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer); else demarrer();
    // reset() d'un formulaire contenant un sélecteur : resynchronise après coup.
    document.addEventListener("reset", function (e) { setTimeout(function () { refresh(e.target); }, 0); }, true);
})();
