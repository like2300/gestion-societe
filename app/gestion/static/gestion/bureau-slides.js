/* =====================================================================
   Présentations : vignettes, scène éditable (texte brut), mises en page,
   thèmes, notes, réorganisation, mode présentation plein écran.
   ===================================================================== */
(function () {
    "use strict";
    var data = JSON.parse(document.getElementById("bx-contenu").textContent || "{}");
    data.theme = data.theme || "accent";
    data.slides = (data.slides && data.slides.length) ? data.slides : [{ layout: "titre", titre: "", texte: "" }];
    var cur = 0;
    var vign = document.getElementById("sl-vignettes");
    var scene = document.getElementById("sl-scene");
    var notes = document.getElementById("sl-notes");


    var PLACE = {
        titre: ["Titre de la présentation", "Sous-titre"],
        contenu: ["Titre de la diapositive", "Un point par ligne"],
        deux: ["Titre de la diapositive", "Colonne de gauche (un point par ligne)", "Colonne de droite"],
        section: ["Titre de section", "Description courte"],
        citation: ["Auteur de la citation", "Votre citation ici"]
    };
    function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
    function puces(t) { return String(t || "").split("\n").map(function (l) { return l.trim(); }).filter(Boolean); }
    var POSITIONS = ["droite", "centre", "fond"];
    function posImage(s) { return POSITIONS.indexOf(s.image_pos) !== -1 ? s.image_pos : "droite"; }
    function classesImage(s) { return s.image ? " avec-img img-" + posImage(s) : ""; }
    function baliseImage(s) { return s.image ? '<img class="sl-img img-' + posImage(s) + '" src="' + esc(s.image) + '" alt="" draggable="false" />' : ""; }

    /* Rendu (lecture seule) d'une diapositive : vignettes et projection */
    function rendu(s) {
        var lay = s.layout || "contenu", h = baliseImage(s) + '<div class="sl-in l-' + lay + classesImage(s) + '">';
        if (lay === "titre" || lay === "section") {
            h += "<h1>" + esc(s.titre) + "</h1><p>" + esc(s.texte) + "</p>";
        } else if (lay === "citation") {
            h += "<blockquote>« " + esc(s.texte) + " »</blockquote><cite>" + esc(s.titre) + "</cite>";
        } else {
            h += "<h2>" + esc(s.titre) + "</h2>";
            var col = function (t) { return "<ul>" + puces(t).map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ul>"; };
            h += lay === "deux" ? '<div class="sl-cols">' + col(s.texte) + col(s.texte2) + "</div>" : col(s.texte);
        }
        return h + '<span class="sl-pied">' + esc(window.BX_SOCIETE || "") + "</span></div>";
    }

    /* Scène éditable */
    function champ(cle, cls, tag) {
        var s = data.slides[cur], el = document.createElement(tag || "div");
        el.className = "sl-champ " + cls;
        el.contentEditable = "plaintext-only";
        if (el.contentEditable !== "plaintext-only") el.contentEditable = "true";
        el.setAttribute("data-place", (PLACE[s.layout] || PLACE.contenu)[cle === "titre" ? 0 : cle === "texte" ? 1 : 2]);
        el.innerText = s[cle] || "";
        el.addEventListener("input", function () {
            s[cle] = el.innerText.replace(/\n$/, "");
            majVignette(cur);
            Bureau.modifie();
        });
        el.addEventListener("paste", function (e) {
            e.preventDefault();
            document.execCommand("insertText", false, (e.clipboardData || window.clipboardData).getData("text/plain"));
        });
        return el;
    }
    function rendreScene() {
        var s = data.slides[cur];
        scene.className = "bx-slide grand th-" + data.theme;
        scene.innerHTML = baliseImage(s);
        var inner = document.createElement("div");
        inner.className = "sl-in l-" + (s.layout || "contenu") + classesImage(s);
        if (s.layout === "titre" || s.layout === "section") {
            inner.appendChild(champ("titre", "t-h1"));
            inner.appendChild(champ("texte", "t-sous"));
        } else if (s.layout === "citation") {
            inner.appendChild(champ("texte", "t-cit"));
            inner.appendChild(champ("titre", "t-auteur"));
        } else {
            inner.appendChild(champ("titre", "t-h2"));
            if (s.layout === "deux") {
                var cols = document.createElement("div");
                cols.className = "sl-cols";
                cols.appendChild(champ("texte", "t-puces"));
                cols.appendChild(champ("texte2", "t-puces"));
                inner.appendChild(cols);
            } else inner.appendChild(champ("texte", "t-puces"));
        }
        var pied = document.createElement("span");
        pied.className = "sl-pied";
        pied.textContent = (window.BX_SOCIETE || "") + "  ·  " + (cur + 1) + " / " + data.slides.length;
        inner.appendChild(pied);
        scene.appendChild(inner);
        notes.value = s.notes || "";
        document.querySelectorAll("#sl-layouts [data-layout]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-layout") === (s.layout || "contenu")); });
        document.querySelectorAll("#sl-themes [data-theme]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-theme") === data.theme); });
        document.getElementById("sl-img-options").hidden = !s.image;
        document.querySelectorAll("#sl-img-pos [data-pos]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-pos") === posImage(s)); });
    }
    function rendreVignettes() {
        vign.innerHTML = data.slides.map(function (s, i) {
            return '<button type="button" class="sl-vig' + (i === cur ? " on" : "") + '" data-i="' + i + '" draggable="true" aria-label="Diapositive ' + (i + 1) + '">' +
                '<span class="sl-num">' + (i + 1) + '</span><span class="bx-slide mini th-' + data.theme + '">' + rendu(s) + "</span></button>";
        }).join("");
    }
    function majVignette(i) {
        var b = vign.querySelector('[data-i="' + i + '"] .bx-slide');
        if (b) b.innerHTML = rendu(data.slides[i]);
    }
    function choisir(i) {
        cur = Math.max(0, Math.min(data.slides.length - 1, i));
        rendreVignettes(); rendreScene();
        var v = vign.querySelector('[data-i="' + cur + '"]');
        if (v) v.scrollIntoView({ block: "nearest" });
    }
    function tout() { rendreVignettes(); rendreScene(); Bureau.modifie(); }

    // Version reçue d'un partenaire : on remplace les diapositives sans marquer de modification locale
    Bureau.init({
        url: window.BX_SAUVER,
        lire: function () { return data; },
        appliquer: function (c) {
            if (!c || !c.slides || !c.slides.length) return;
            data.theme = c.theme || "accent"; data.slides = c.slides;
            cur = Math.min(cur, data.slides.length - 1);
            rendreVignettes(); rendreScene();
        }
    });

    vign.addEventListener("click", function (e) { var b = e.target.closest(".sl-vig"); if (b) choisir(+b.getAttribute("data-i")); });
    // Glisser-déposer des vignettes pour réordonner
    var depart = null;
    vign.addEventListener("dragstart", function (e) { var b = e.target.closest(".sl-vig"); if (b) { depart = +b.getAttribute("data-i"); e.dataTransfer.effectAllowed = "move"; } });
    vign.addEventListener("dragover", function (e) { if (depart !== null) e.preventDefault(); });
    vign.addEventListener("drop", function (e) {
        var b = e.target.closest(".sl-vig");
        if (depart === null || !b) return;
        e.preventDefault();
        var cible = +b.getAttribute("data-i"), s = data.slides.splice(depart, 1)[0];
        data.slides.splice(cible, 0, s);
        cur = cible; depart = null; tout();
    });

    notes.addEventListener("input", function () { data.slides[cur].notes = notes.value; Bureau.modifie(); });
    document.getElementById("sl-ajouter").addEventListener("click", function () {
        data.slides.splice(cur + 1, 0, { layout: "contenu", titre: "", texte: "" });
        cur++; tout();
        var t = scene.querySelector(".sl-champ"); if (t) t.focus();
    });
    document.getElementById("sl-dupliquer").addEventListener("click", function () {
        data.slides.splice(cur + 1, 0, JSON.parse(JSON.stringify(data.slides[cur]))); cur++; tout();
    });
    document.getElementById("sl-supprimer").addEventListener("click", function () {
        if (data.slides.length === 1) { data.slides[0] = { layout: "titre", titre: "", texte: "" }; }
        else data.slides.splice(cur, 1);
        cur = Math.min(cur, data.slides.length - 1); tout();
    });
    document.getElementById("sl-monter").addEventListener("click", function () {
        if (cur === 0) return;
        var s = data.slides.splice(cur, 1)[0]; data.slides.splice(cur - 1, 0, s); cur--; tout();
    });
    document.getElementById("sl-descendre").addEventListener("click", function () {
        if (cur >= data.slides.length - 1) return;
        var s = data.slides.splice(cur, 1)[0]; data.slides.splice(cur + 1, 0, s); cur++; tout();
    });
    document.querySelectorAll("#sl-layouts [data-layout]").forEach(function (b) {
        b.addEventListener("click", function () { data.slides[cur].layout = b.getAttribute("data-layout"); tout(); });
    });
    document.querySelectorAll("#sl-themes [data-theme]").forEach(function (b) {
        b.addEventListener("click", function () { data.theme = b.getAttribute("data-theme"); tout(); });
    });

    /* Images : compressées dans le navigateur (max 1600 px) puis stockées dans la diapositive */
    var IMG_MAX = 1600, IMG_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
    function alerte(msg) { if (window.showToast) window.showToast("error", msg); else window.alert(msg); }
    function lireImage(fichier, cb) {
        if (!fichier || IMG_TYPES.indexOf(fichier.type) === -1) { alerte("Format non pris en charge (PNG, JPG, WebP ou GIF)."); return; }
        if (fichier.size > 15 * 1024 * 1024) { alerte("Image trop lourde (15 Mo maximum)."); return; }
        var url = URL.createObjectURL(fichier), img = new Image();
        img.onload = function () {
            var r = Math.min(1, IMG_MAX / Math.max(img.naturalWidth, img.naturalHeight));
            var c = document.createElement("canvas");
            c.width = Math.max(1, Math.round(img.naturalWidth * r));
            c.height = Math.max(1, Math.round(img.naturalHeight * r));
            c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
            URL.revokeObjectURL(url);
            // PNG conservé (transparence), le reste en JPEG
            cb(fichier.type === "image/png" ? c.toDataURL("image/png") : c.toDataURL("image/jpeg", 0.85));
        };
        img.onerror = function () { URL.revokeObjectURL(url); alerte("Impossible de lire cette image."); };
        img.src = url;
    }
    function poserImage(fichier) {
        var i = cur;
        lireImage(fichier, function (src) {
            data.slides[i].image = src;
            if (!data.slides[i].image_pos) data.slides[i].image_pos = "droite";
            cur = i; tout();
        });
    }
    var inputImg = document.getElementById("sl-img-fichier");
    document.getElementById("sl-image").addEventListener("click", function () { inputImg.value = ""; inputImg.click(); });
    inputImg.addEventListener("change", function () { if (inputImg.files && inputImg.files[0]) poserImage(inputImg.files[0]); });
    document.getElementById("sl-img-retirer").addEventListener("click", function () {
        delete data.slides[cur].image; delete data.slides[cur].image_pos; tout();
    });
    document.querySelectorAll("#sl-img-pos [data-pos]").forEach(function (b) {
        b.addEventListener("click", function () { data.slides[cur].image_pos = b.getAttribute("data-pos"); tout(); });
    });
    // Glisser-déposer ou coller une image directement sur la diapositive
    scene.addEventListener("dragover", function (e) {
        if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types, "Files") !== -1) { e.preventDefault(); scene.classList.add("depot"); }
    });
    scene.addEventListener("dragleave", function () { scene.classList.remove("depot"); });
    scene.addEventListener("drop", function (e) {
        scene.classList.remove("depot");
        var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) { e.preventDefault(); poserImage(f); }
    });
    scene.addEventListener("paste", function (e) {
        var items = (e.clipboardData && e.clipboardData.items) || [];
        for (var k = 0; k < items.length; k++) {
            if (items[k].kind === "file" && items[k].type.indexOf("image/") === 0) {
                e.preventDefault(); e.stopImmediatePropagation(); poserImage(items[k].getAsFile()); return;
            }
        }
    }, true);

    /* Mode présentation */
    var proj = document.getElementById("sl-projection"), projSlide = document.getElementById("sl-proj-slide"), pi = 0;
    function montrer(i) {
        pi = Math.max(0, Math.min(data.slides.length - 1, i));
        projSlide.className = "bx-slide projection th-" + data.theme + " entree";
        projSlide.innerHTML = rendu(data.slides[pi]);
        void projSlide.offsetWidth;
        projSlide.classList.remove("entree");
        document.getElementById("sl-compteur").textContent = (pi + 1) + " / " + data.slides.length;
    }
    function presenter() {
        proj.hidden = false;
        montrer(cur);
        if (proj.requestFullscreen) proj.requestFullscreen().catch(function () {});
    }
    function quitter() {
        proj.hidden = true;
        if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () {});
        choisir(pi);
    }
    document.getElementById("bx-presenter").addEventListener("click", presenter);
    document.getElementById("sl-prec").addEventListener("click", function () { montrer(pi - 1); });
    document.getElementById("sl-suiv").addEventListener("click", function () { montrer(pi + 1); });
    document.getElementById("sl-quitter").addEventListener("click", quitter);
    projSlide.addEventListener("click", function () { montrer(pi + 1); });
    document.addEventListener("fullscreenchange", function () { if (!document.fullscreenElement && !proj.hidden) quitter(); });
    document.addEventListener("keydown", function (e) {
        if (!proj.hidden) {
            if (["ArrowRight", "ArrowDown", "PageDown", " ", "Enter"].indexOf(e.key) !== -1) { e.preventDefault(); montrer(pi + 1); }
            else if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace"].indexOf(e.key) !== -1) { e.preventDefault(); montrer(pi - 1); }
            else if (e.key === "Escape") quitter();
            else if (e.key === "Home") montrer(0);
            else if (e.key === "End") montrer(data.slides.length - 1);
            return;
        }
        if (e.key === "F5") { e.preventDefault(); presenter(); }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "m") { e.preventDefault(); document.getElementById("sl-ajouter").click(); }
        var dansChamp = e.target.closest && e.target.closest(".sl-champ, textarea, input");
        if (!dansChamp && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); choisir(cur + (e.key === "ArrowDown" ? 1 : -1)); }
    });

    choisir(0);
})();
