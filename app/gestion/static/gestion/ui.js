/* Interactions du design system : bascule clair/sombre + recherche rapide de modules. */
(function () {
    "use strict";
    var root = document.documentElement;

    /* ---------- Thème clair / sombre ---------- */
    var toggle = document.getElementById("ui-theme-toggle");
    if (toggle) {
        toggle.addEventListener("click", function () {
            var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
            root.setAttribute("data-theme", next);
            try { localStorage.setItem("ui-theme", next); } catch (e) { /* stockage indisponible */ }
        });
    }

    /* ---------- Onglets soulignés (composant tabs.html, mode boutons) ---------- */
    Array.prototype.forEach.call(document.querySelectorAll("[data-ui-tabs]"), function (barre) {
        barre.addEventListener("click", function (e) {
            var b = e.target.closest ? e.target.closest("button.ui-tab") : null;
            if (!b || !barre.contains(b)) return;
            Array.prototype.forEach.call(barre.querySelectorAll(".ui-tab"), function (t) {
                t.classList.toggle("is-active", t === b);
                t.setAttribute("aria-selected", t === b ? "true" : "false");
            });
            barre.dispatchEvent(new CustomEvent("ui-tabs:change", { bubbles: true, detail: { value: b.getAttribute("data-value") || "" } }));
        });
    });

    /* ---------- Recherche rapide (modules de la barre latérale) ---------- */
    var input = document.getElementById("ui-search-input");
    var box = document.getElementById("ui-search-results");
    if (!input || !box) return;

    var entries = [];
    var links = document.querySelectorAll(".dash-nav a[href]");
    for (var i = 0; i < links.length; i++) {
        var label = (links[i].textContent || "").replace(/\s+/g, " ").trim();
        if (label) entries.push({ label: label, href: links[i].getAttribute("href") });
    }

    function norm(s) {
        return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    }

    var selected = -1;
    function render(q) {
        var n = norm(q.trim());
        box.innerHTML = "";
        selected = -1;
        if (!n) { box.hidden = true; return; }
        var hits = entries.filter(function (e) { return norm(e.label).indexOf(n) !== -1; }).slice(0, 7);
        if (!hits.length) {
            var none = document.createElement("div");
            none.className = "none";
            none.textContent = "Aucun module trouvé";
            box.appendChild(none);
        }
        hits.forEach(function (h) {
            var a = document.createElement("a");
            a.href = h.href;
            a.textContent = h.label;
            box.appendChild(a);
        });
        box.hidden = false;
    }

    function highlight(delta) {
        var items = box.querySelectorAll("a");
        if (!items.length) return;
        selected = (selected + delta + items.length) % items.length;
        for (var k = 0; k < items.length; k++) items[k].classList.toggle("sel", k === selected);
    }

    input.addEventListener("input", function () { render(input.value); });
    input.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown") { e.preventDefault(); highlight(1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); highlight(-1); }
        else if (e.key === "Enter") {
            var items = box.querySelectorAll("a");
            var target = items[selected] || items[0];
            if (target) { e.preventDefault(); window.location.href = target.href; }
        } else if (e.key === "Escape") { box.hidden = true; input.blur(); }
    });
    document.addEventListener("click", function (e) {
        if (!box.contains(e.target) && e.target !== input) box.hidden = true;
    });
    document.addEventListener("keydown", function (e) {
        var tag = (e.target && e.target.tagName) || "";
        if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA" && !e.target.isContentEditable) {
            e.preventDefault();
            input.focus();
        }
    });
})();

/* Raccourci « ?nouveau=1 » : ouvre directement le formulaire d'ajout de la page. */
(function () {
    try {
        var params = new URLSearchParams(window.location.search);
        if (params.get("nouveau") !== "1") return;
        window.addEventListener("load", function () {
            var btn = document.querySelector("[data-crud-add]");
            if (btn) btn.click();
            params.delete("nouveau");
            var q = params.toString();
            history.replaceState(null, "", window.location.pathname + (q ? "?" + q : "") + window.location.hash);
        });
    } catch (e) { /* navigateur sans URLSearchParams : on ignore */ }
})();
