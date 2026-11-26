/* =====================================================================
   Tableau des tâches façon Trello : glisser-déposer entre colonnes.
   - Souris : le glissement démarre après 5 px de déplacement.
   - Tactile : appui long (~250 ms) puis glisser ; un simple balayage fait défiler.
   - Au dépôt dans une autre colonne, le statut est enregistré (AJAX) ;
     en cas d'erreur la carte revient à sa place.
   ===================================================================== */
(function () {
    "use strict";

    function init() {
        var board = document.getElementById("taches-board");
        if (!board || board.__trello) return;
        board.__trello = true;

        var url = board.getAttribute("data-url");
        var createur = board.getAttribute("data-createur") === "1";
        var LIBELLES = {};
        board.querySelectorAll("[data-col]").forEach(function (c) {
            var nom = c.querySelector(".taches-col-nom");
            LIBELLES[c.getAttribute("data-col")] = nom ? nom.textContent.trim() : c.getAttribute("data-col");
        });

        var INTERACTIF = "a, button, input, select, textarea, label, summary, details[open] .tache-plus-corps, form";
        var etat = null; // { carte, debutX, debutY, pointeur, actif, fantome, place, origine, suivant, decX, decY, timer }

        function csrf() {
            var m = document.cookie.match(/csrftoken=([^;]+)/);
            if (m) return decodeURIComponent(m[1]);
            var i = document.querySelector("input[name=csrfmiddlewaretoken]");
            return i ? i.value : "";
        }

        /* ---------- Toast ---------- */
        var toastEl = null, toastT = null;
        function toast(texte, type) {
            if (!toastEl) {
                toastEl = document.createElement("div");
                toastEl.className = "tk-toast";
                toastEl.setAttribute("role", "status");
                document.body.appendChild(toastEl);
            }
            toastEl.className = "tk-toast " + (type || "ok");
            toastEl.textContent = texte;
            requestAnimationFrame(function () { toastEl.classList.add("on"); });
            clearTimeout(toastT);
            toastT = setTimeout(function () { toastEl.classList.remove("on"); }, 2600);
        }

        function majCompteurs() {
            board.querySelectorAll("[data-col]").forEach(function (col) {
                var n = col.querySelectorAll(".tache-card").length;
                var nb = col.querySelector(".taches-nb");
                if (nb) nb.textContent = n;
            });
        }

        function colonneSous(x, y) {
            var el = document.elementFromPoint(x, y);
            var col = el && el.closest("[data-col]");
            if (!col || !board.contains(col)) return null;
            if (!createur && col.getAttribute("data-col") === "ANNULEE") return null;
            return col;
        }

        function placerDans(corps, y) {
            var cartes = Array.prototype.filter.call(corps.querySelectorAll(".tache-card"), function (c) {
                return c !== etat.carte;
            });
            var avant = null;
            for (var i = 0; i < cartes.length; i++) {
                var r = cartes[i].getBoundingClientRect();
                if (y < r.top + r.height / 2) { avant = cartes[i]; break; }
            }
            var vide = corps.querySelector(".tache-vide-col");
            if (avant) corps.insertBefore(etat.place, avant);
            else corps.insertBefore(etat.place, vide || null);
        }

        /* ---------- Démarrage / déplacement / fin ---------- */
        function demarrer() {
            var c = etat.carte;
            var r = c.getBoundingClientRect();
            etat.actif = true;
            etat.decX = etat.debutX - r.left;
            etat.decY = etat.debutY - r.top;
            etat.origine = c.parentNode;
            etat.suivant = c.nextSibling;
            etat.colOrigine = c.closest("[data-col]");

            var place = document.createElement("div");
            place.className = "tache-place";
            place.style.height = r.height + "px";
            etat.place = place;
            c.parentNode.insertBefore(place, c);

            var f = c.cloneNode(true);
            f.classList.add("tache-fantome");
            f.removeAttribute("data-tache-id");
            f.style.width = r.width + "px";
            f.style.height = r.height + "px";
            f.style.left = r.left + "px";
            f.style.top = r.top + "px";
            (board.closest("#dash") || document.body).appendChild(f);
            etat.fantome = f;

            c.classList.add("tache-source");
            document.documentElement.classList.add("tk-glisse");
            board.classList.add("en-glisse");
            if (navigator.vibrate && etat.pointeur === "touch") { try { navigator.vibrate(12); } catch (e) { } }
        }

        var defile = null;
        function autoDefile(x, y) {
            var vx = 0, vy = 0, marge = 60;
            var rb = board.getBoundingClientRect();
            if (x < rb.left + marge) vx = -14; else if (x > rb.right - marge) vx = 14;
            if (y < 80) vy = -14; else if (y > window.innerHeight - 60) vy = 14;
            if (!vx && !vy) { cancelAnimationFrame(defile); defile = null; return; }
            if (defile) return;
            (function boucle() {
                if (!etat || !etat.actif) { defile = null; return; }
                board.scrollLeft += vx;
                window.scrollBy(0, vy);
                defile = requestAnimationFrame(boucle);
            })();
        }

        function deplacer(x, y) {
            etat.dernierX = x; etat.dernierY = y;
            var f = etat.fantome;
            var dx = x - etat.decX, dy = y - etat.decY;
            var incl = Math.max(-6, Math.min(6, (x - (etat.precX || x)) * 0.6));
            etat.precX = x;
            f.style.transform = "translate(" + (dx - parseFloat(f.style.left)) + "px," + (dy - parseFloat(f.style.top)) + "px) rotate(" + (3 + incl) + "deg)";
            board.querySelectorAll(".taches-col.cible").forEach(function (c) { c.classList.remove("cible"); });
            var col = colonneSous(x, y);
            if (col) {
                col.classList.add("cible");
                placerDans(col.querySelector("[data-col-corps]"), y);
            }
            autoDefile(x, y);
        }

        function terminer(annule) {
            var e = etat;
            etat = null;
            cancelAnimationFrame(defile); defile = null;
            document.documentElement.classList.remove("tk-glisse");
            board.classList.remove("en-glisse");
            board.querySelectorAll(".taches-col.cible").forEach(function (c) { c.classList.remove("cible"); });
            if (!e || !e.actif) return;

            var carte = e.carte;
            var dest = annule ? null : e.place.closest("[data-col]");
            var cible = (dest || e.colOrigine).getAttribute("data-col");
            var source = e.colOrigine.getAttribute("data-col");

            // Animation du fantôme vers la place finale
            var r = e.place.getBoundingClientRect();
            if (annule) {
                e.origine.insertBefore(e.place, e.suivant);
                r = e.place.getBoundingClientRect();
            }
            var f = e.fantome;
            f.classList.add("depose");
            f.style.transform = "translate(" + (r.left - parseFloat(f.style.left)) + "px," + (r.top - parseFloat(f.style.top)) + "px) rotate(0deg)";
            setTimeout(function () {
                e.place.parentNode.insertBefore(carte, e.place);
                e.place.remove();
                f.remove();
                carte.classList.remove("tache-source");
                carte.classList.add("tache-pose");
                setTimeout(function () { carte.classList.remove("tache-pose"); }, 450);
                majCompteurs();
            }, 190);

            if (annule || cible === source) return;
            enregistrer(carte, cible, source, e.origine, e.suivant);
        }

        function enregistrer(carte, cible, source, origine, suivant) {
            carte.classList.add("tache-sauve");
            var fd = new FormData();
            fd.append("csrfmiddlewaretoken", csrf());
            fd.append("evo_tache_id", carte.getAttribute("data-tache-id"));
            fd.append("statut", cible);
            fetch(url, {
                method: "POST", body: fd, credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf() }
            })
                .then(function (r) { return r.json().catch(function () { return { ok: false }; }); })
                .then(function (d) {
                    carte.classList.remove("tache-sauve");
                    if (!d || !d.ok) throw new Error((d && d.erreur) || "Échec");
                    carte.setAttribute("data-statut", d.statut);
                    var sel = carte.querySelector(".tache-actions select[name=statut]");
                    if (sel) sel.value = d.statut;
                    if (typeof d.progres !== "undefined") {
                        var b = carte.querySelector(".barre > i"); if (b) b.style.width = d.progres + "%";
                        var p = carte.querySelector(".tache-pct"); if (p) p.textContent = d.progres + "%";
                    }
                    toast("« " + (carte.querySelector(".tache-titre") || {}).textContent + " » → " + (d.statut_label || LIBELLES[cible]), "ok");
                })
                .catch(function (err) {
                    carte.classList.remove("tache-sauve");
                    origine.insertBefore(carte, suivant && suivant.parentNode === origine ? suivant : origine.querySelector(".tache-vide-col"));
                    majCompteurs();
                    toast(err && err.message && err.message !== "Échec" ? err.message : "Impossible de déplacer la tâche.", "err");
                });
        }

        /* ---------- Écouteurs ---------- */
        board.addEventListener("pointerdown", function (ev) {
            if (ev.button !== 0 || etat) return;
            var carte = ev.target.closest(".tache-card[data-draggable]");
            if (!carte || ev.target.closest(INTERACTIF)) return;
            etat = { carte: carte, debutX: ev.clientX, debutY: ev.clientY, pointeur: ev.pointerType, actif: false, id: ev.pointerId };
            if (ev.pointerType === "touch") {
                etat.timer = setTimeout(function () {
                    if (etat && !etat.actif) { demarrer(); deplacer(etat.debutX, etat.debutY); }
                }, 260);
            }
        });

        window.addEventListener("pointermove", function (ev) {
            if (!etat || ev.pointerId !== etat.id) return;
            var dist = Math.abs(ev.clientX - etat.debutX) + Math.abs(ev.clientY - etat.debutY);
            if (!etat.actif) {
                if (etat.pointeur === "touch") {
                    if (dist > 10) { clearTimeout(etat.timer); etat = null; } // défilement normal
                    return;
                }
                if (dist < 5) return;
                demarrer();
            }
            ev.preventDefault();
            deplacer(ev.clientX, ev.clientY);
        }, { passive: false });

        // Bloque le défilement tactile pendant le glissement
        window.addEventListener("touchmove", function (ev) {
            if (etat && etat.actif) ev.preventDefault();
        }, { passive: false });

        function fin(ev) {
            if (!etat || (ev && ev.pointerId !== etat.id)) return;
            clearTimeout(etat.timer);
            if (!etat.actif) { etat = null; return; }
            terminer(ev && ev.type === "pointercancel");
        }
        window.addEventListener("pointerup", fin);
        window.addEventListener("pointercancel", fin);
        window.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && etat && etat.actif) terminer(true);
        });
        // Évite le clic « fantôme » après un glissement
        board.addEventListener("click", function (ev) {
            if (document.documentElement.classList.contains("tk-glisse")) { ev.preventDefault(); ev.stopPropagation(); }
        }, true);
        board.addEventListener("dragstart", function (ev) {
            if (ev.target.closest && ev.target.closest(".tache-card")) ev.preventDefault();
        });

        majCompteurs();
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
