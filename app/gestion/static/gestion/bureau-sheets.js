/* =====================================================================
   Tableur intégré : grille, sélection, édition, formules, mise en forme,
   copier/coller, annuler/rétablir, redimension des colonnes, autosave.
   ===================================================================== */
(function () {
    "use strict";
    var data = JSON.parse(document.getElementById("bx-contenu").textContent || "{}");
    data.cells = data.cells || {};
    data.nrows = data.nrows || 60;
    data.ncols = data.ncols || 16;
    data.cols = data.cols || {};

    var table = document.getElementById("sh-table");
    var zone = document.getElementById("sh-zone");
    var editeur = document.getElementById("sh-edit");
    var barreFx = document.getElementById("sh-formule");
    var refEl = document.getElementById("sh-ref");
    var statsEl = document.getElementById("sh-stats");

    Bureau.init({ url: window.BX_SAUVER, lire: function () { return data; } });

    /* ---------- Références ---------- */
    function lettre(n) { var s = ""; n++; while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; }
    function colIndex(l) { var n = 0; for (var i = 0; i < l.length; i++) n = n * 26 + (l.charCodeAt(i) - 64); return n - 1; }
    function ref(r, c) { return lettre(c) + (r + 1); }
    function parseRef(s) { var m = /^([A-Z]{1,2})(\d+)$/.exec(s); return m ? { r: +m[2] - 1, c: colIndex(m[1]) } : null; }

    /* ---------- Formules ---------- */
    var FONCTIONS = {
        SUM: function (a) { return plat(a).reduce(function (x, y) { return x + num(y); }, 0); },
        AVERAGE: function (a) { var v = plat(a).filter(estNum); return v.length ? v.reduce(function (x, y) { return x + num(y); }, 0) / v.length : 0; },
        MIN: function (a) { var v = plat(a).filter(estNum).map(num); return v.length ? Math.min.apply(null, v) : 0; },
        MAX: function (a) { var v = plat(a).filter(estNum).map(num); return v.length ? Math.max.apply(null, v) : 0; },
        COUNT: function (a) { return plat(a).filter(estNum).length; },
        COUNTA: function (a) { return plat(a).filter(function (x) { return x !== "" && x != null; }).length; },
        ROUND: function (a) { var p = Math.pow(10, num(a[1] || 0)); return Math.round(num(a[0]) * p) / p; },
        ABS: function (a) { return Math.abs(num(a[0])); },
        IF: function (a) { return a[0] ? (a.length > 1 ? a[1] : true) : (a.length > 2 ? a[2] : false); },
        CONCAT: function (a) { return plat(a).join(""); }
    };
    var ALIAS = { SOMME: "SUM", MOYENNE: "AVERAGE", NB: "COUNT", NBVAL: "COUNTA", ARRONDI: "ROUND", SI: "IF", CONCATENER: "CONCAT" };
    function plat(a) { return [].concat.apply([], a.map(function (x) { return Array.isArray(x) ? plat(x) : [x]; })); }
    function estNum(x) { return typeof x === "number" || (typeof x === "string" && x.trim() !== "" && !isNaN(Number(x.replace(/\s/g, "").replace(",", ".")))); }
    function num(x) { if (typeof x === "number") return x; if (typeof x === "boolean") return x ? 1 : 0; var n = Number(String(x || "").replace(/\s/g, "").replace(",", ".")); return isNaN(n) ? 0 : n; }

    var cache = {}, pile = {};
    function valeur(r) {
        if (r in cache) return cache[r];
        var c = data.cells[r];
        var v = c ? c.v : "";
        if (typeof v === "string" && v.charAt(0) === "=") {
            if (pile[r]) return "#CIRC";
            pile[r] = true;
            try { v = evaluer(v.slice(1)); } catch (e) { v = e && e.message && e.message.charAt(0) === "#" ? e.message : "#ERR"; }
            delete pile[r];
        } else if (estNum(v)) {
            v = num(v);
        }
        cache[r] = v;
        return v;
    }
    function plage(a, b) {
        var p = parseRef(a), q = parseRef(b), out = [];
        for (var r = Math.min(p.r, q.r); r <= Math.max(p.r, q.r); r++)
            for (var c = Math.min(p.c, q.c); c <= Math.max(p.c, q.c); c++) out.push(valeur(ref(r, c)));
        return out;
    }
    function evaluer(expr) {
        var jetons = expr.match(/"[^"]*"|[A-Z]{1,2}\d+:[A-Z]{1,2}\d+|[A-Za-zÀ-ÿ]+(?=\s*\()|[A-Z]{1,2}\d+|\d+(?:[.,]\d+)?%?|<=|>=|<>|[-+*/^(),;<>=&]|\s+|./g) || [];
        var code = "", pileP = [], fonctionAvant = false;
        jetons.forEach(function (t) {
            if (/^\s+$/.test(t)) return;
            var m, fn = false;
            if (t.charAt(0) === '"') code += JSON.stringify(t.slice(1, -1));
            else if ((m = /^([A-Z]{1,2}\d+):([A-Z]{1,2}\d+)$/.exec(t))) code += "P(" + JSON.stringify(m[1]) + "," + JSON.stringify(m[2]) + ")";
            else if (/^[A-Z]{1,2}\d+$/.test(t)) code += "V(" + JSON.stringify(t) + ")";
            else if (/^[A-Za-zÀ-ÿ]+$/.test(t)) {
                var f = t.toUpperCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
                f = ALIAS[f] || f;
                if (!FONCTIONS[f]) throw new Error("#NOM?");
                code += "F." + f; fn = true;
            }
            else if (/^\d/.test(t)) code += t.slice(-1) === "%" ? "(" + t.slice(0, -1).replace(",", ".") + "/100)" : t.replace(",", ".");
            else if (t === "(") { pileP.push(fonctionAvant); code += fonctionAvant ? "([" : "("; }
            else if (t === ")") { code += pileP.pop() ? "])" : ")"; }
            else if (t === "^") code += "**";
            else if (t === "<>") code += "!=";
            else if (t === "=") code += "==";
            else if (t === ";" || t === ",") code += ",";
            else if (t === "&") code += "+''+";
            else if ("+-*/<>".indexOf(t) !== -1 || t === "<=" || t === ">=") code += t;
            else throw new Error("#ERR");
            fonctionAvant = fn;
        });
        if (pileP.length) throw new Error("#ERR");
        var res = new Function("F", "V", "P", "return (" + code + ");")(FONCTIONS, function (r) {
            var v = valeur(r);
            if (typeof v === "string" && v.charAt(0) === "#") throw new Error(v);
            return v === "" ? 0 : (estNum(v) ? num(v) : v);
        }, plage);
        if (typeof res === "number" && !isFinite(res)) return "#DIV/0";
        return res;
    }

    /* ---------- Affichage ---------- */
    function formater(v, c) {
        if (typeof v === "boolean") return v ? "VRAI" : "FAUX";
        if (typeof v === "number") {
            var fmt = c && c.fmt;
            if (fmt === "money") return Math.round(v).toLocaleString("fr-FR") + " FCFA";
            if (fmt === "pct") return (v * 100).toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " %";
            if (fmt === "num") return v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            return Math.abs(v) >= 1000 ? v.toLocaleString("fr-FR", { maximumFractionDigits: 6 }) : String(Math.round(v * 1e9) / 1e9).replace(".", ",");
        }
        return v == null ? "" : String(v);
    }
    var tds = {};
    function construire() {
        table.innerHTML = "";
        tds = {};
        var colg = document.createElement("colgroup");
        var c0 = document.createElement("col"); c0.style.width = "46px"; colg.appendChild(c0);
        for (var c = 0; c < data.ncols; c++) {
            var col = document.createElement("col");
            col.style.width = (data.cols[lettre(c)] || 110) + "px";
            colg.appendChild(col);
        }
        table.appendChild(colg);
        var thead = document.createElement("thead"), tr = document.createElement("tr");
        tr.appendChild(Object.assign(document.createElement("th"), { className: "coin" }));
        for (c = 0; c < data.ncols; c++) {
            var th = document.createElement("th");
            th.textContent = lettre(c);
            th.dataset.col = c;
            var poignee = document.createElement("span");
            poignee.className = "bx-redim";
            th.appendChild(poignee);
            tr.appendChild(th);
        }
        thead.appendChild(tr);
        table.appendChild(thead);
        var tbody = document.createElement("tbody"), frag = document.createDocumentFragment();
        for (var r = 0; r < data.nrows; r++) {
            var ligne = document.createElement("tr");
            var tn = document.createElement("th");
            tn.textContent = r + 1;
            tn.dataset.row = r;
            ligne.appendChild(tn);
            for (c = 0; c < data.ncols; c++) {
                var td = document.createElement("td");
                td.dataset.r = r; td.dataset.c = c;
                tds[ref(r, c)] = td;
                ligne.appendChild(td);
            }
            frag.appendChild(ligne);
        }
        tbody.appendChild(frag);
        table.appendChild(tbody);
        rendre();
    }
    function rendre() {
        cache = {};
        Object.keys(tds).forEach(function (k) {
            var td = tds[k], c = data.cells[k];
            if (!c) { if (td.textContent || td.className) { td.textContent = ""; td.className = ""; td.removeAttribute("style"); } return; }
            var v = valeur(k);
            td.textContent = formater(v, c);
            var cls = [];
            if (c.b) cls.push("b"); if (c.i) cls.push("i"); if (c.u) cls.push("u");
            if (c.al) cls.push("al-" + c.al); else if (typeof v === "number") cls.push("al-r");
            if (typeof v === "string" && v.charAt(0) === "#") cls.push("err");
            td.className = cls.join(" ");
            td.style.background = c.bg || "";
        });
        marquerSelection();
    }

    /* ---------- Sélection ---------- */
    var sel = { r: 0, c: 0, r2: 0, c2: 0 };
    function bornes() { return { r1: Math.min(sel.r, sel.r2), r2: Math.max(sel.r, sel.r2), c1: Math.min(sel.c, sel.c2), c2: Math.max(sel.c, sel.c2) }; }
    function marquerSelection() {
        table.querySelectorAll(".sel, .actif").forEach(function (td) { td.classList.remove("sel", "actif"); });
        table.querySelectorAll("th.on").forEach(function (th) { th.classList.remove("on"); });
        var b = bornes();
        for (var r = b.r1; r <= b.r2; r++) for (var c = b.c1; c <= b.c2; c++) { var td = tds[ref(r, c)]; if (td) td.classList.add("sel"); }
        var a = tds[ref(sel.r, sel.c)];
        if (a) a.classList.add("actif");
        for (c = b.c1; c <= b.c2; c++) { var h = table.querySelector('thead th[data-col="' + c + '"]'); if (h) h.classList.add("on"); }
        for (r = b.r1; r <= b.r2; r++) { var n = table.querySelector('tbody th[data-row="' + r + '"]'); if (n) n.classList.add("on"); }
        var k = ref(sel.r, sel.c);
        refEl.textContent = (b.r1 !== b.r2 || b.c1 !== b.c2) ? ref(b.r1, b.c1) + ":" + ref(b.r2, b.c2) : k;
        if (document.activeElement !== barreFx) barreFx.value = data.cells[k] ? data.cells[k].v : "";
        var c0 = data.cells[k] || {};
        document.querySelector('[data-cmd="fmt"]').value = c0.fmt || "";
        ["b", "i", "u"].forEach(function (x) { document.querySelector('[data-cmd="' + x + '"]').classList.toggle("on", !!c0[x]); });
        statistiques(b);
    }
    function statistiques(b) {
        var vals = [];
        for (var r = b.r1; r <= b.r2; r++) for (var c = b.c1; c <= b.c2; c++) { var v = valeur(ref(r, c)); if (typeof v === "number") vals.push(v); }
        if (vals.length > 1 || (b.r1 !== b.r2 || b.c1 !== b.c2)) {
            var s = vals.reduce(function (x, y) { return x + y; }, 0);
            statsEl.innerHTML = "Somme : <b>" + formater(s) + "</b> · Moyenne : <b>" + formater(vals.length ? s / vals.length : 0) + "</b> · Nb : <b>" + vals.length + "</b>";
        } else statsEl.textContent = "";
    }
    function aller(r, c, etendre) {
        r = Math.max(0, Math.min(data.nrows - 1, r));
        c = Math.max(0, Math.min(data.ncols - 1, c));
        if (etendre) { sel.r2 = r; sel.c2 = c; } else { sel.r = sel.r2 = r; sel.c = sel.c2 = c; }
        marquerSelection();
        var td = tds[ref(etendre ? sel.r2 : r, etendre ? sel.c2 : c)];
        if (td) td.scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    /* ---------- Historique ---------- */
    var passe = [], futur = [];
    function memoriser() { passe.push(JSON.stringify(data.cells)); if (passe.length > 100) passe.shift(); futur = []; }
    function annuler() { if (!passe.length) return; futur.push(JSON.stringify(data.cells)); data.cells = JSON.parse(passe.pop()); rendre(); Bureau.modifie(); }
    function retablir() { if (!futur.length) return; passe.push(JSON.stringify(data.cells)); data.cells = JSON.parse(futur.pop()); rendre(); Bureau.modifie(); }

    function ecrire(k, v, sansMemo) {
        if (!sansMemo) memoriser();
        var c = data.cells[k] || {};
        c.v = v;
        if (!c.v && Object.keys(c).length === 1) delete data.cells[k]; else data.cells[k] = c;
    }

    /* ---------- Édition ---------- */
    var edition = null;
    function commencer(texte) {
        var td = tds[ref(sel.r, sel.c)];
        if (!td) return;
        var k = ref(sel.r, sel.c);
        edition = k;
        var rz = zone.getBoundingClientRect(), rt = td.getBoundingClientRect();
        editeur.style.left = (rt.left - rz.left + zone.scrollLeft) + "px";
        editeur.style.top = (rt.top - rz.top + zone.scrollTop) + "px";
        editeur.style.width = Math.max(rt.width, 120) + "px";
        editeur.style.height = rt.height + "px";
        editeur.hidden = false;
        editeur.value = texte != null ? texte : (data.cells[k] ? data.cells[k].v : "");
        editeur.focus();
        var n = editeur.value.length;
        editeur.setSelectionRange(n, n);
        barreFx.value = editeur.value;
    }
    function valider(dr, dc) {
        if (!edition) return;
        var k = edition;
        edition = null;
        editeur.hidden = true;
        var ancien = data.cells[k] ? data.cells[k].v : "";
        if (editeur.value !== ancien) { ecrire(k, editeur.value); rendre(); Bureau.modifie(); }
        zone.focus({ preventScroll: true });
        aller(sel.r + (dr || 0), sel.c + (dc || 0));
    }
    function abandonner() { edition = null; editeur.hidden = true; zone.focus({ preventScroll: true }); marquerSelection(); }

    editeur.addEventListener("input", function () { barreFx.value = editeur.value; });
    editeur.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); valider(e.shiftKey ? -1 : 1, 0); }
        else if (e.key === "Tab") { e.preventDefault(); valider(0, e.shiftKey ? -1 : 1); }
        else if (e.key === "Escape") { e.preventDefault(); abandonner(); }
    });
    editeur.addEventListener("blur", function () { if (edition) valider(0, 0); });

    barreFx.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
            e.preventDefault();
            var k = ref(sel.r, sel.c);
            ecrire(k, barreFx.value); rendre(); Bureau.modifie();
            zone.focus(); aller(sel.r + 1, sel.c);
        } else if (e.key === "Escape") { zone.focus(); marquerSelection(); }
    });

    /* ---------- Souris ---------- */
    var glisse = false;
    table.addEventListener("mousedown", function (e) {
        var td = e.target.closest("td");
        if (td) {
            if (edition) valider(0, 0);
            e.preventDefault();
            zone.focus({ preventScroll: true });
            aller(+td.dataset.r, +td.dataset.c, e.shiftKey);
            glisse = true;
            return;
        }
        var th = e.target.closest("thead th[data-col]");
        if (th && !e.target.classList.contains("bx-redim")) { sel = { r: 0, c: +th.dataset.col, r2: data.nrows - 1, c2: +th.dataset.col }; marquerSelection(); return; }
        var tr = e.target.closest("tbody th[data-row]");
        if (tr) { sel = { r: +tr.dataset.row, c: 0, r2: +tr.dataset.row, c2: data.ncols - 1 }; marquerSelection(); }
    });
    table.addEventListener("mouseover", function (e) {
        if (!glisse) return;
        var td = e.target.closest("td");
        if (td) { sel.r2 = +td.dataset.r; sel.c2 = +td.dataset.c; marquerSelection(); }
    });
    document.addEventListener("mouseup", function () { glisse = false; });
    table.addEventListener("dblclick", function (e) { if (e.target.closest("td")) commencer(); });

    // Redimension des colonnes
    table.addEventListener("mousedown", function (e) {
        if (!e.target.classList.contains("bx-redim")) return;
        e.preventDefault(); e.stopPropagation();
        var th = e.target.parentNode, c = +th.dataset.col, x0 = e.clientX;
        var col = table.querySelectorAll("col")[c + 1], w0 = col.getBoundingClientRect().width || 110;
        function bouge(ev) { col.style.width = Math.max(40, w0 + ev.clientX - x0) + "px"; }
        function fin(ev) {
            document.removeEventListener("mousemove", bouge); document.removeEventListener("mouseup", fin);
            data.cols[lettre(c)] = Math.round(Math.max(40, w0 + ev.clientX - x0)); Bureau.modifie();
        }
        document.addEventListener("mousemove", bouge); document.addEventListener("mouseup", fin);
    }, true);

    /* ---------- Clavier ---------- */
    zone.addEventListener("keydown", function (e) {
        if (edition) return;
        var k = e.key, ctrl = e.ctrlKey || e.metaKey;
        var dr = { ArrowUp: -1, ArrowDown: 1 }[k] || 0, dc = { ArrowLeft: -1, ArrowRight: 1 }[k] || 0;
        if (dr || dc) { e.preventDefault(); aller((e.shiftKey ? sel.r2 : sel.r) + dr, (e.shiftKey ? sel.c2 : sel.c) + dc, e.shiftKey); return; }
        if (k === "Enter") { e.preventDefault(); e.shiftKey ? aller(sel.r - 1, sel.c) : commencer(); return; }
        if (k === "Tab") { e.preventDefault(); aller(sel.r, sel.c + (e.shiftKey ? -1 : 1)); return; }
        if (k === "F2") { e.preventDefault(); commencer(); return; }
        if (k === "Delete" || k === "Backspace") { e.preventDefault(); commande("effacer"); return; }
        if (ctrl && k.toLowerCase() === "z") { e.preventDefault(); annuler(); return; }
        if (ctrl && k.toLowerCase() === "y") { e.preventDefault(); retablir(); return; }
        if (ctrl && ["b", "i", "u"].indexOf(k.toLowerCase()) !== -1) { e.preventDefault(); commande(k.toLowerCase()); return; }
        if (ctrl && k.toLowerCase() === "a") { e.preventDefault(); sel = { r: 0, c: 0, r2: data.nrows - 1, c2: data.ncols - 1 }; marquerSelection(); return; }
        if (!ctrl && !e.altKey && k.length === 1) { e.preventDefault(); commencer(k); }
    });

    /* ---------- Copier / coller (TSV, compatible Excel) ---------- */
    zone.addEventListener("copy", function (e) {
        if (edition) return;
        var b = bornes(), lignes = [];
        for (var r = b.r1; r <= b.r2; r++) {
            var l = [];
            for (var c = b.c1; c <= b.c2; c++) { var x = data.cells[ref(r, c)]; l.push(x ? formater(valeur(ref(r, c)), x) : ""); }
            lignes.push(l.join("\t"));
        }
        e.clipboardData.setData("text/plain", lignes.join("\n"));
        e.preventDefault();
    });
    zone.addEventListener("cut", function (e) { zone.dispatchEvent(new ClipboardEvent("copy", { clipboardData: e.clipboardData })); commande("effacer"); });
    zone.addEventListener("paste", function (e) {
        if (edition) return;
        var t = (e.clipboardData || window.clipboardData).getData("text/plain");
        if (!t) return;
        e.preventDefault();
        memoriser();
        var lignes = t.replace(/\r/g, "").replace(/\n$/, "").split("\n");
        lignes.forEach(function (l, i) {
            l.split("\t").forEach(function (v, j) {
                var r = sel.r + i, c = sel.c + j;
                if (r >= data.nrows) data.nrows = r + 1;
                if (c >= data.ncols) data.ncols = Math.min(52, c + 1);
                if (c < 52) ecrire(ref(r, c), v, true);
            });
        });
        sel.r2 = sel.r + lignes.length - 1;
        sel.c2 = sel.c + lignes[0].split("\t").length - 1;
        construire(); Bureau.modifie();
    });

    /* ---------- Barre d'outils ---------- */
    function pourSelection(fn) {
        memoriser();
        var b = bornes();
        for (var r = b.r1; r <= b.r2; r++) for (var c = b.c1; c <= b.c2; c++) {
            var k = ref(r, c), cell = data.cells[k] || { v: "" };
            fn(cell);
            if (!cell.v && Object.keys(cell).filter(function (x) { return cell[x]; }).length <= 1 && !cell.bg) delete data.cells[k];
            else data.cells[k] = cell;
        }
        rendre(); Bureau.modifie();
    }
    function commande(cmd, val) {
        var c0 = data.cells[ref(sel.r, sel.c)] || {};
        if (cmd === "annuler") return annuler();
        if (cmd === "retablir") return retablir();
        if (cmd === "b" || cmd === "i" || cmd === "u") { var on = !c0[cmd]; return pourSelection(function (c) { if (on) c[cmd] = 1; else delete c[cmd]; }); }
        if (cmd === "al") return pourSelection(function (c) { if (c.al === val) delete c.al; else c.al = val; });
        if (cmd === "bg") return pourSelection(function (c) { if (val) c.bg = val; else delete c.bg; });
        if (cmd === "fmt") return pourSelection(function (c) { if (val) c.fmt = val; else delete c.fmt; });
        if (cmd === "effacer") return pourSelection(function (c) { c.v = ""; });
        if (cmd === "lignes") { data.nrows = Math.min(2000, data.nrows + 20); construire(); Bureau.modifie(); return; }
        if (cmd === "colonne") { if (data.ncols < 52) { data.ncols++; construire(); Bureau.modifie(); } return; }
        if (cmd === "somme") {
            var b = bornes(), cible;
            if (b.r1 === b.r2 && b.c1 === b.c2) {
                // Cellule seule : somme des nombres au-dessus
                var r = sel.r - 1; while (r >= 0 && typeof valeur(ref(r, sel.c)) === "number") r--;
                if (r === sel.r - 1) return;
                memoriser(); ecrire(ref(sel.r, sel.c), "=SOMME(" + ref(r + 1, sel.c) + ":" + ref(sel.r - 1, sel.c) + ")", true);
            } else {
                cible = Math.min(b.r2 + 1, data.nrows - 1);
                memoriser();
                for (var c = b.c1; c <= b.c2; c++) ecrire(ref(cible, c), "=SOMME(" + ref(b.r1, c) + ":" + ref(b.r2, c) + ")", true);
            }
            rendre(); Bureau.modifie();
        }
    }
    document.querySelectorAll(".bx-outils [data-cmd]").forEach(function (b) {
        if (b.tagName === "SELECT") b.addEventListener("change", function () { commande("fmt", b.value); zone.focus(); });
        else b.addEventListener("click", function () { commande(b.getAttribute("data-cmd"), b.getAttribute("data-val")); zone.focus({ preventScroll: true }); });
    });

    construire();
    zone.focus({ preventScroll: true });
    marquerSelection();
})();
