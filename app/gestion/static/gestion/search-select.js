(function () {
    "use strict";

    // Sélecteur <select> avec recherche instantanée.
    // SearchSelect.enhance(selectEl) -> { refresh(), close() }
    // Se déclenche automatiquement sur tout <select data-searchable>.
    //
    // Création rapide : lorsque la recherche ne donne aucun résultat, un bouton
    // « Créer … » remplace le message « Aucun résultat ». Il ouvre une petite
    // popup « Nom » qui envoie un POST JSON vers un endpoint déclaré par :
    //   - data-create-url      : URL qui reçoit « nom » et renvoie {ok, pk, label}
    //   - data-create-label    : libellé du bouton (ex. « Créer une fonction »)
    //   - data-create-title    : titre de la popup (ex. « Nouvelle fonction »)
    // Le sélecteur peut aussi définir un handler personnalisé :
    //   select.__msAddHandler = fn(terme, done)  (+ optionnel select.__msAddLabel)
    //
    // Suggestions enrichies (composant réutilisable, s'adapte au contexte) — attributs d'<option> :
    //   data-sub    : 2e ligne (client, date, fonction…)       data-meta  : étiquette à droite (montant…)
    //   data-color  : pastille de couleur (statut…)            data-fill  : JSON {champ: valeur} pré-rempli au choix
    //   data-parent : valeur attendue du champ parent (voir data-depends-on)
    // Attributs du <select> :
    //   data-depends-on="projet"  : ne montre que les options dont data-parent = valeur du champ « projet »
    //                               (le parent est aussi choisi automatiquement quand on prend une option)
    //   data-depends-label="…"   : texte affiché tant que le parent est vide
    //   data-plain               : ne pas transformer ce select
    // Tous les <select> des panneaux latéraux (.drawer-body) sont transformés automatiquement.
    function norm(s) {
        s = String(s || "");
        return s.normalize
            ? s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
            : s.toLowerCase();
    }

    // -------------------------------------------------------------------------
    // Popup générique de création (partagée entre tous les sélecteurs).
    // -------------------------------------------------------------------------
    var popupOverlay = null;
    var popupTitle = null;
    var popupSub = null;
    var popupForm = null;
    var popupInput = null;
    var popupErr = null;
    var popupOk = null;
    var popupOwner = null;

    function ensurePopup() {
        if (popupOverlay) return;
        popupOverlay = document.createElement("div");
        popupOverlay.className = "ms-popup-overlay";
        popupOverlay.hidden = true;
        popupOverlay.innerHTML =
            '<div class="ms-popup" role="dialog" aria-modal="true">' +
            '<h4 class="ms-popup-title"></h4>' +
            '<p class="ms-popup-sub"></p>' +
            '<form class="ms-popup-form" novalidate>' +
            '<label>Nom</label>' +
            '<input type="text" autocomplete="off" />' +
            '<p class="ms-popup-err" hidden></p>' +
            "</form>" +
            '<div class="ms-popup-actions">' +
            '<button type="button" class="ms-popup-cancel">Annuler</button>' +
            '<button type="button" class="ms-popup-ok">Créer</button>' +
            "</div>" +
            "</div>";
        document.body.appendChild(popupOverlay);
        popupTitle = popupOverlay.querySelector(".ms-popup-title");
        popupSub = popupOverlay.querySelector(".ms-popup-sub");
        popupForm = popupOverlay.querySelector(".ms-popup-form");
        popupInput = popupOverlay.querySelector("input");
        popupErr = popupOverlay.querySelector(".ms-popup-err");
        popupOk = popupOverlay.querySelector(".ms-popup-ok");

        popupOverlay.addEventListener("click", function (ev) {
            if (ev.target === popupOverlay) closeCreatePopup();
        });
        popupOverlay.querySelector(".ms-popup-cancel").addEventListener("click", closeCreatePopup);
        popupForm.addEventListener("submit", function (ev) {
            ev.preventDefault();
            submitCreate();
        });
        popupOk.addEventListener("click", function () { submitCreate(); });
        popupInput.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape") {
                ev.preventDefault();
                closeCreatePopup();
            }
        });
    }

    function csrfParam() {
        var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return input ? "&csrfmiddlewaretoken=" + encodeURIComponent(input.value) : "";
    }

    function errorMsg(errors) {
        if (typeof errors === "string") return errors;
        var keys = Object.keys(errors || {});
        for (var i = 0; i < keys.length; i++) {
            var arr = errors[keys[i]];
            if (arr && arr[0] && arr[0].message) return arr[0].message;
        }
        return "";
    }

    function showCreateError(msg) {
        popupErr.textContent = msg;
        popupErr.hidden = false;
    }

    function closeCreatePopup() {
        if (popupOverlay) popupOverlay.hidden = true;
    }

    function submitCreate() {
        var owner = popupOwner;
        if (!owner) return;
        var label = popupInput.value.trim();
        if (!label) {
            showCreateError("Le nom est obligatoire.");
            return;
        }
        popupOk.disabled = true;
        popupErr.hidden = true;
        fetch(owner.url, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest"
            },
            credentials: "same-origin",
            body: "nom=" + encodeURIComponent(label) + csrfParam()
        })
            .then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, data: d }; });
            })
            .then(function (res) {
                var data = res.data || {};
                if (res.ok && data.ok) {
                    var nom = data.label || data.nom || label;
                    closeCreatePopup();
                    owner.done(String(data.pk), String(nom));
                    window.showToast && window.showToast("success", "« " + nom + " » a été ajouté.");
                } else {
                    showCreateError(
                        data.message || errorMsg(data.errors) || "Impossible de créer l'élément."
                    );
                }
            })
            .catch(function () {
                showCreateError("Erreur réseau. Réessayez.");
            })
            .finally(function () { popupOk.disabled = false; });
    }

    // -------------------------------------------------------------------------
    // Enhancement d'un <select>
    // -------------------------------------------------------------------------
    var valueDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
    var nativeGet = valueDesc.get, nativeSet = valueDesc.set;

    function enhance(select) {
        if (!select || select.__msEnhanced) return select && select.__msApi || null;
        select.__msEnhanced = true;
        if (!select.hasAttribute("data-searchable")) select.setAttribute("data-searchable", "");

        var wrap = document.createElement("div");
        wrap.className = "ms-wrap";
        select.parentNode.insertBefore(wrap, select);
        wrap.appendChild(select);
        select.classList.add("ms-native");

        var control = document.createElement("button");
        control.type = "button";
        control.className = "ms-control";
        control.setAttribute("aria-haspopup", "listbox");
        control.setAttribute("aria-expanded", "false");
        control.innerHTML =
            '<span class="ms-value"></span>' +
            '<svg class="ms-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="m6 9 6 6 6-6" /></svg>';
        wrap.appendChild(control);

        var panel = document.createElement("div");
        panel.className = "ms-panel";
        panel.hidden = true;
        panel.innerHTML =
            '<div class="ms-search">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></svg>' +
            '<input type="text" class="ms-input" placeholder="Rechercher…" ' +
            'autocomplete="off" aria-label="Rechercher" />' +
            "</div>" +
            '<ul class="ms-list" role="listbox"></ul>' +
            '<div class="ms-empty" hidden>' +
            '<span class="ms-empty-text">Aucun résultat.</span>' +
            '<button type="button" class="ms-add" hidden></button>' +
            "</div>";
        wrap.appendChild(panel);

        var valueEl = control.querySelector(".ms-value");
        var input = panel.querySelector(".ms-input");
        var list = panel.querySelector(".ms-list");
        var emptyEl = panel.querySelector(".ms-empty");
        var emptyText = panel.querySelector(".ms-empty-text");
        var addBtn = panel.querySelector(".ms-add");
        var options = [];
        var filtered = [];
        var activeIndex = 0;
        var emptyLabel = "";

        var createUrl = select.getAttribute("data-create-url") || "";
        var hasCustom = typeof select.__msAddHandler === "function";
        var canCreate = !!(createUrl || hasCustom);

        function collect() {
            options = [];
            var opts = select.options;
            for (var i = 0; i < opts.length; i++) {
                var op = opts[i], grp = op.parentNode && op.parentNode.tagName === "OPTGROUP" ? op.parentNode.label : "";
                options.push({
                    value: op.value,
                    label: (op.textContent || "").trim(),
                    sub: op.getAttribute("data-sub") || "",
                    meta: op.getAttribute("data-meta") || "",
                    color: op.getAttribute("data-color") || "",
                    parent: op.getAttribute("data-parent"),
                    fill: op.getAttribute("data-fill") || "",
                    group: grp,
                    disabled: op.disabled
                });
            }
            if (options.length && options[0].value === "") emptyLabel = options[0].label;
        }

        function currentLabel() {
            for (var i = 0; i < options.length; i++) {
                if (options[i].value === select.value) return options[i].label;
            }
            return emptyLabel || "";
        }

        function refresh() {
            collect();
            riche = options.some(function (o) { return o.sub || o.meta || o.color; });
            var pv = parentValue();
            var attente = pv === "" && !select.value && select.getAttribute("data-depends-label");
            valueEl.textContent = attente ? select.getAttribute("data-depends-label") : currentLabel();
            control.classList.toggle("is-empty", !select.value);
            control.classList.toggle("ms-attente", !!attente);
            var choisi = null;
            for (var i = 0; i < options.length; i++) if (options[i].value === select.value && select.value !== "") choisi = options[i];
            var dot = control.querySelector(".ms-dot");
            if (choisi && choisi.color) {
                if (!dot) { dot = document.createElement("span"); dot.className = "ms-dot"; control.insertBefore(dot, valueEl); }
                dot.style.setProperty("--c", choisi.color);
            } else if (dot) dot.remove();
            var meta = control.querySelector(".ms-meta-val");
            if (choisi && choisi.meta) {
                if (!meta) { meta = document.createElement("span"); meta.className = "ms-meta-val"; control.insertBefore(meta, control.querySelector(".ms-caret")); }
                meta.textContent = choisi.meta;
            } else if (meta) meta.remove();
        }

        function setActive(idx) {
            var items = list.querySelectorAll(".ms-opt");
            for (var i = 0; i < items.length; i++) items[i].classList.toggle("is-active", i === idx);
            activeIndex = idx;
            if (items[idx] && items[idx].scrollIntoView) {
                items[idx].scrollIntoView({ block: "nearest" });
            }
        }

        function addBtnLabel(term) {
            if (select.__msAddLabel) return select.__msAddLabel;
            var custom = select.getAttribute("data-create-label") || "";
            if (custom) return custom;
            return term ? "Créer « " + term + " »…" : "Créer…";
        }

        function parentField() {
            var nom = select.getAttribute("data-depends-on");
            if (!nom || !select.form) return null;
            return select.form.querySelector('[name="' + nom + '"]');
        }
        function parentValue() { var p = parentField(); return p ? p.value : null; }
        function visible(o) {
            var pv = parentValue();
            return pv === null || o.value === "" || o.parent === null || !pv || o.parent === pv;
        }
        function initiales(t) {
            var p = String(t || "").replace(/[—–-].*$/, "").split(/\s+/).filter(Boolean);
            return ((p[0] || "?")[0] + (p[1] ? p[1][0] : "")).toUpperCase();
        }
        function teinte(t) { var h = 0; t = String(t || ""); for (var i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) % 360; return "hsl(" + h + " 60% 48%)"; }
        var riche = false;

        function render(rawQ) {
            var term = (rawQ || "").trim();
            var mots = norm(term).split(/\s+/).filter(Boolean);
            filtered = [];
            var emptyOpt = null;
            for (var i = 0; i < options.length; i++) {
                var o = options[i];
                if (o.value === "") { emptyOpt = o; continue; }
                if (!visible(o)) continue;
                var texte = norm(o.label + " " + o.sub + " " + o.meta + " " + o.group);
                if (mots.every(function (m) { return texte.indexOf(m) !== -1; })) filtered.push(o);
            }
            if (emptyOpt && !mots.length) filtered.unshift(emptyOpt);

            list.innerHTML = "";
            var dernierGroupe = null;
            for (var j = 0; j < filtered.length; j++) {
                (function (o, idx) {
                    if (o.group && o.group !== dernierGroupe) {
                        dernierGroupe = o.group;
                        var g = document.createElement("li");
                        g.className = "ms-groupe"; g.textContent = o.group;
                        list.appendChild(g);
                    }
                    var li = document.createElement("li");
                    li.className = "ms-opt" + (o.value === select.value ? " is-selected" : "") + (o.value === "" ? " ms-opt-vide" : "") + (riche ? " ms-riche" : "");
                    li.setAttribute("role", "option");
                    var pastille = "";
                    if (riche && o.value !== "") {
                        pastille = o.color
                            ? '<span class="ms-dot" style="--c:' + o.color + '"></span>'
                            : '<span class="ms-av" style="background:' + teinte(o.label) + '"></span>';
                    }
                    li.innerHTML = pastille +
                        '<span class="ms-opt-txt"><span class="ms-opt-label"></span><small class="ms-opt-sub"></small></span>' +
                        '<span class="ms-opt-meta"></span>' +
                        '<svg class="ms-check" width="14" height="14" viewBox="0 0 24 24" ' +
                        'fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" ' +
                        'stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>';
                    li.querySelector(".ms-opt-label").textContent = o.label;
                    var sub = li.querySelector(".ms-opt-sub"); if (o.sub) sub.textContent = o.sub; else sub.remove();
                    var meta = li.querySelector(".ms-opt-meta"); if (o.meta) meta.textContent = o.meta; else meta.remove();
                    var av = li.querySelector(".ms-av"); if (av) av.textContent = initiales(o.label);
                    li.addEventListener("click", function () { choose(o.value); });
                    li.addEventListener("mousemove", function () { setActive(idx); });
                    li.__idx = idx;
                    list.appendChild(li);
                })(filtered[j], j);
            }

            emptyEl.hidden = filtered.length !== 0;
            if (filtered.length === 0) {
                var pv = parentValue();
                emptyText.textContent = (pv === "" && select.getAttribute("data-depends-label")) ? select.getAttribute("data-depends-label") : "Aucun résultat.";
                emptyText.style.display = canCreate ? "none" : "";
                addBtn.hidden = !canCreate;
                if (canCreate) addBtn.textContent = addBtnLabel(term);
            }
            setActive(0);
        }

        var remplis = []; // champs pré-remplis par ce sélecteur (vidés si le choix est annulé par le contexte)
        function viderRemplis() {
            remplis.forEach(function (c) {
                if (c.__msAuto) { c.value = ""; c.__msAuto = false; c.dispatchEvent(new Event("input", { bubbles: true })); }
            });
            remplis = [];
        }
        function choose(value) {
            var o = null;
            for (var i = 0; i < options.length; i++) if (options[i].value === value) o = options[i];
            nativeSet.call(select, value);
            refresh();
            close();
            // Contexte : choisir l'enfant renseigne le parent (ex. échéance → projet)
            var p = parentField();
            if (o && p && o.parent && p.value !== o.parent) {
                p.value = o.parent;
                p.dispatchEvent(new Event("change", { bubbles: true }));
            }
            // Pré-remplissage (ex. montant restant dû)
            if (o && o.fill && select.form) {
                try {
                    var f = JSON.parse(o.fill);
                    Object.keys(f).forEach(function (nom) {
                        var champ = select.form.querySelector('[name="' + nom + '"]');
                        if (!champ || (champ.value && !champ.__msAuto)) return;
                        champ.value = f[nom]; champ.__msAuto = true;
                        if (remplis.indexOf(champ) === -1) remplis.push(champ);
                        champ.dispatchEvent(new Event("input", { bubbles: true }));
                        champ.dispatchEvent(new Event("change", { bubbles: true }));
                        champ.classList.add("ms-rempli");
                        setTimeout(function () { champ.classList.remove("ms-rempli"); }, 900);
                    });
                } catch (e) { /* JSON invalide : ignoré */ }
            }
            select.dispatchEvent(new Event("change", { bubbles: true }));
        }

        function addOption(value, label) {
            for (var i = 0; i < select.options.length; i++) {
                if (select.options[i].value === String(value)) {
                    select.value = String(value);
                    return;
                }
            }
            var opt = document.createElement("option");
            opt.value = String(value);
            opt.textContent = label;
            select.appendChild(opt);
            select.value = String(value);
        }

        function done(value, label) {
            if (value != null) addOption(value, label);
            refresh();
            close();
            select.dispatchEvent(new Event("change", { bubbles: true }));
        }

        function handleAdd() {
            var term = input.value.trim();
            if (typeof select.__msAddHandler === "function") {
                select.__msAddHandler(term, done);
                return;
            }
            openCreatePopup(term, createUrl);
        }

        function openCreatePopup(term, url) {
            ensurePopup();
            popupOwner = { done: done, url: url };
            popupErr.hidden = true;
            popupTitle.textContent = select.getAttribute("data-create-title") || "Ajouter un élément";
            popupSub.textContent = select.getAttribute("data-create-subtitle") || "";
            popupInput.value = term;
            popupOk.disabled = false;
            popupOverlay.hidden = false;
            setTimeout(function () { popupInput.focus(); popupInput.select(); }, 0);
        }

        function open() {
            refresh();
            // Recherche visible seulement si la liste est longue
            panel.querySelector(".ms-search").hidden = options.filter(visible).length <= 7 && !canCreate;
            panel.hidden = false;
            control.setAttribute("aria-expanded", "true");
            wrap.classList.add("open");
            input.value = "";
            render("");
            var recherche = !panel.querySelector(".ms-search").hidden;
            setTimeout(function () { (recherche ? input : control).focus(); }, 0);
        }

        function close() {
            panel.hidden = true;
            control.setAttribute("aria-expanded", "false");
            wrap.classList.remove("open");
        }

        control.addEventListener("click", function (ev) {
            ev.stopPropagation();
            if (panel.hidden) open(); else close();
        });
        input.addEventListener("input", function () { render(input.value); });
        function clavier(ev) {
            if (panel.hidden) {
                if (ev.target === control && (ev.key === "ArrowDown" || ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); open(); }
                return;
            }
            // Saisie au clavier alors que la recherche est masquée : on l'affiche
            if (ev.target === control && ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey) {
                var zone = panel.querySelector(".ms-search");
                if (zone.hidden) { ev.preventDefault(); zone.hidden = false; input.value = ev.key; input.focus(); render(input.value); return; }
            }
            if (ev.key === "ArrowDown") {
                ev.preventDefault();
                if (activeIndex < filtered.length - 1) setActive(activeIndex + 1);
            } else if (ev.key === "ArrowUp") {
                ev.preventDefault();
                if (activeIndex > 0) setActive(activeIndex - 1);
            } else if (ev.key === "Enter") {
                ev.preventDefault();
                if (filtered[activeIndex]) choose(filtered[activeIndex].value);
            } else if (ev.key === "Escape") {
                ev.preventDefault();
                close();
                control.focus();
            } else if (ev.key === "Tab") {
                close();
            }
        }
        input.addEventListener("keydown", clavier);
        control.addEventListener("keydown", clavier);
        if (canCreate) addBtn.addEventListener("click", handleAdd);
        document.addEventListener("click", function (ev) {
            if (!wrap.contains(ev.target)) close();
        });

        // Les scripts des pages modifient souvent select.value (ouverture d'un formulaire d'édition) :
        // on intercepte pour garder l'affichage synchronisé.
        try {
            Object.defineProperty(select, "value", {
                configurable: true,
                get: function () { return nativeGet.call(select); },
                set: function (v) { nativeSet.call(select, v); refresh(); }
            });
            var idxDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "selectedIndex");
            Object.defineProperty(select, "selectedIndex", {
                configurable: true,
                get: function () { return idxDesc.get.call(select); },
                set: function (v) { idxDesc.set.call(select, v); refresh(); }
            });
        } catch (e) { /* navigateur ancien : on garde l'écoute « change » */ }
        select.addEventListener("change", refresh);
        if (select.form) select.form.addEventListener("input", function (ev) { if (ev.isTrusted && ev.target.__msAuto) ev.target.__msAuto = false; });
        if (select.form) select.form.addEventListener("reset", function () { remplis.forEach(function (c) { c.__msAuto = false; }); remplis = []; });
        if (select.form) select.form.addEventListener("reset", function () { setTimeout(refresh, 0); });
        if (window.MutationObserver) new MutationObserver(refresh).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled"] });
        // Enfant d'un parent : se met à jour (et se vide si besoin) quand le parent change
        var pf = parentField();
        if (pf) pf.addEventListener("change", function () {
            collect();
            var cur = null;
            for (var i = 0; i < options.length; i++) if (options[i].value === select.value) cur = options[i];
            if (cur && cur.value !== "" && cur.parent && pf.value && cur.parent !== pf.value) {
                nativeSet.call(select, "");
                viderRemplis();
                select.dispatchEvent(new Event("change", { bubbles: true }));
            }
            refresh();
        });

        refresh();
        select.__msApi = { refresh: refresh, close: close };
        return select.__msApi;
    }

    function enhanceAll(scope) {
        var root = scope || document;
        var selects = root.querySelectorAll("select[data-searchable], .drawer-body select:not([multiple]):not([data-plain]):not([size])");
        for (var i = 0; i < selects.length; i++) enhance(selects[i]);
    }

    window.SearchSelect = { enhance: enhance, enhanceAll: enhanceAll };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { enhanceAll(); });
    } else {
        enhanceAll();
    }
    // Selects ajoutés plus tard dans un panneau (formsets, contenus chargés en AJAX…)
    if (window.MutationObserver) {
        var attente = null;
        new MutationObserver(function () { clearTimeout(attente); attente = setTimeout(function () { enhanceAll(); }, 80); })
            .observe(document.documentElement, { childList: true, subtree: true });
    }
})();