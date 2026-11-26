/* =====================================================================
   Planning : calendrier FullCalendar (MIT) + mini-calendrier + équipe
   + tiroir « Rendez-vous / Tâche ».
   ===================================================================== */
(function () {
    "use strict";
    var PL = window.PL || {};
    var EMP = JSON.parse(document.getElementById("pl-employes").textContent || "[]");
    var el = document.getElementById("pl-calendrier");
    if (!el || !window.FullCalendar) return;

    function csrf() { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
    function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
    function norm(t) { return String(t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
    function couleur(n) { var h = 0; for (var i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) % 360; return "hsl(" + h + " 62% 48%)"; }
    function init(n) { return String(n || "?").split(/\s+/).filter(Boolean).slice(0, 2).map(function (x) { return x[0]; }).join("").toUpperCase(); }
    function pad(n) { return String(n).padStart(2, "0"); }
    function jour(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
    function heure(d) { return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
    function toast(type, msg) { if (window.showToast) window.showToast(type, msg); }
    function poster(corps) {
        return fetch(PL.sauver, {
            method: "POST", credentials: "same-origin", body: JSON.stringify(corps),
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" }
        }).then(function (r) { return r.json().then(function (d) { if (!r.ok || !d.ok) throw new Error(d.erreur || "Erreur"); return d; }); });
    }
    function fermerTiroir() { var b = document.querySelector("[data-drawer-close]"); if (b) b.click(); }
    var ICO_CHECK = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';

    /* ---------- Filtres ---------- */
    var quiSel = document.getElementById("pl-qui");
    function qui() { return quiSel ? quiSel.value : "moi"; }
    function couches() {
        return Array.prototype.map.call(document.querySelectorAll("[data-couche]:checked"), function (c) { return c.getAttribute("data-couche"); }).join(",");
    }

    /* ---------- Calendrier ---------- */
    var JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
    var cal = new FullCalendar.Calendar(el, {
        locale: "fr",
        initialView: window.innerWidth < 760 ? "listWeek" : "timeGridWeek",
        headerToolbar: false,
        height: "100%",
        firstDay: 1,
        nowIndicator: true,
        selectable: true,
        selectMirror: true,
        editable: true,
        dayMaxEvents: 3,
        slotMinTime: "07:00:00",
        slotMaxTime: "21:00:00",
        scrollTime: "08:00:00",
        slotDuration: "00:30:00",
        slotLabelFormat: { hour: "2-digit", minute: "2-digit", hour12: false },
        businessHours: { daysOfWeek: [1, 2, 3, 4, 5], startTime: "08:00", endTime: "18:00" },
        allDayText: "Tâches",
        eventTimeFormat: { hour: "2-digit", minute: "2-digit", hour12: false },
        dayHeaderContent: function (arg) {
            if (arg.view.type.indexOf("timeGrid") !== 0) return true;
            return { html: '<span class="pl-jn">' + arg.date.getDate() + '</span><span class="pl-jw">' + JOURS[arg.date.getDay()] + "</span>" };
        },
        events: function (info, ok, ko) {
            var u = PL.flux + "?start=" + encodeURIComponent(info.startStr) + "&end=" + encodeURIComponent(info.endStr) +
                "&qui=" + encodeURIComponent(qui()) + "&couches=" + encodeURIComponent(couches());
            fetch(u, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(ok).catch(ko);
        },
        datesSet: function (info) {
            document.getElementById("pl-periode").textContent = info.view.title;
            document.querySelectorAll("[data-vue]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-vue") === info.view.type); });
            mini.voir(cal.getDate());
        },
        select: function (info) { ouvrir(null, info); cal.unselect(); },
        eventClick: function (info) {
            var p = info.event.extendedProps;
            info.jsEvent.preventDefault();
            if (p.masque) {
                toast("info", "Créneau occupé" + (p.participants_noms && p.participants_noms.length ? " — " + p.participants_noms.join(", ") : "") + ". Les détails sont privés.");
                return;
            }
            if (p.source === "tache") { ouvrirTache(info.event); return; }
            if (p.source !== "agenda") { if (p.lien) location.href = p.lien; return; }
            ouvrir(info.event);
        },
        eventDrop: deplacer,
        eventResize: deplacer,
        eventDidMount: function (info) {
            var p = info.event.extendedProps, t = [info.event.title];
            info.el.style.setProperty("--c", info.event.backgroundColor || "#3b82f6");
            info.el.classList.add("pl-carte-ev");
            if (p.source === "tache") t.push("Tâche · " + p.statut_label + " · priorité " + String(p.priorite_label).toLowerCase() + (p.assignee ? " · " + p.assignee : ""));
            if (p.lieu) t.push("Lieu : " + p.lieu);
            if (p.participants_noms && p.participants_noms.length) t.push("Avec : " + p.participants_noms.join(", "));
            if (p.couche) t.push(p.couche + (p.description ? " — " + p.description : ""));
            info.el.title = t.join("\n");
        },
        eventContent: function (arg) {
            var p = arg.event.extendedProps, liste = arg.view.type.indexOf("list") === 0;
            if (p.source === "tache") {
                var fait = p.statut === "TERMINEE";
                var h = '<div class="pl-ev pl-ev-tache' + (fait ? " fait" : "") + '"><span class="pl-coche">' + (fait ? ICO_CHECK : "") + "</span><b>" + esc(arg.event.title) + "</b>";
                if (p.priorite === "HAUTE") h += '<span class="pl-prio">!</span>';
                if (p.assignee && !p.mine || (PL.admin && p.assignee)) h += '<i class="pl-mini-av" style="background:' + couleur(p.assignee) + '" title="' + esc(p.assignee) + '">' + esc(init(p.assignee)) + "</i>";
                return { html: h + "</div>" };
            }
            if (liste || p.source !== "agenda") return true;
            if (p.masque) {
                var noms = (p.participants_noms || []).join(", ");
                return { html: '<div class="pl-ev"><b>Occupé</b>' + (noms && arg.view.type !== "dayGridMonth" ? '<span class="pl-ev-l">' + esc(noms) + "</span>" : "") + "</div>" };
            }
            var h2 = '<div class="pl-ev"><b>' + esc(arg.event.title) + "</b>";
            if (arg.timeText && !arg.event.allDay) h2 += '<span class="pl-ev-h">' + esc(arg.timeText) + "</span>";
            var duree = arg.event.end ? (arg.event.end - arg.event.start) / 60000 : 60;
            if (p.lieu && arg.view.type !== "dayGridMonth" && duree > 60) h2 += '<span class="pl-ev-l">' + esc(p.lieu) + "</span>";
            if (p.image && arg.view.type !== "dayGridMonth" && duree >= 90) h2 += '<img class="pl-ev-img" src="' + esc(p.image) + '" alt="" loading="lazy" />';
            if (p.participants_noms && p.participants_noms.length && arg.view.type !== "dayGridMonth") {
                var n = p.participants_noms;
                h2 += '<span class="pl-ev-av">' + n.slice(0, 3).map(function (x) { return '<i style="background:' + couleur(x) + '">' + esc(init(x)) + "</i>"; }).join("") +
                    (n.length > 3 ? "<em>+" + (n.length - 3) + "</em>" : "") + "</span>";
            }
            return { html: h2 + "</div>" };
        },
        eventsSet: function () { majProchains(); majJour(); mini.points(); }
    });

    /* ---------- Mini-calendrier ---------- */
    var mini = (function () {
        var box = document.getElementById("pl-mini");
        var mois = new Date(); mois.setDate(1);
        var choisi = jour(new Date());
        var MOIS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];
        function rendre() {
            if (!box) return;
            var vue = cal.view, d0 = vue ? vue.activeStart : null, d1 = vue ? vue.activeEnd : null;
            var debut = new Date(mois); var dec = (debut.getDay() + 6) % 7; debut.setDate(1 - dec);
            var auj = jour(new Date()), h = "";
            h += '<div class="pl-mini-tete"><b>' + MOIS[mois.getMonth()] + " " + mois.getFullYear() + "</b>" +
                '<span><button type="button" data-m="-1" aria-label="Mois précédent">‹</button><button type="button" data-m="1" aria-label="Mois suivant">›</button></span></div>';
            h += '<div class="pl-mini-grille">' + ["L", "M", "M", "J", "V", "S", "D"].map(function (x) { return "<em>" + x + "</em>"; }).join("");
            for (var i = 0; i < 42; i++) {
                var d = new Date(debut); d.setDate(debut.getDate() + i);
                var k = jour(d), cls = [];
                if (d.getMonth() !== mois.getMonth()) cls.push("hors");
                if (k === auj) cls.push("auj");
                if (k === choisi) cls.push("choisi");
                if (d0 && vue.type !== "dayGridMonth" && d >= d0 && d < d1) cls.push("vue");
                h += '<button type="button" data-j="' + k + '" class="' + cls.join(" ") + '">' + d.getDate() + "</button>";
            }
            box.innerHTML = h + "</div>";
            points();
        }
        function points() {
            if (!box) return;
            var avec = {};
            cal.getEvents().forEach(function (e) { avec[jour(e.start)] = true; });
            box.querySelectorAll("[data-j]").forEach(function (b) { b.classList.toggle("pt", !!avec[b.getAttribute("data-j")]); });
        }
        if (box) box.addEventListener("click", function (e) {
            var m = e.target.closest("[data-m]");
            if (m) { mois.setMonth(mois.getMonth() + (+m.getAttribute("data-m"))); rendre(); return; }
            var j = e.target.closest("[data-j]");
            if (j) { choisi = j.getAttribute("data-j"); cal.gotoDate(choisi); rendre(); majJour(); }
        });
        return {
            voir: function (d) { if (d.getMonth() !== mois.getMonth() || d.getFullYear() !== mois.getFullYear()) { mois = new Date(d); mois.setDate(1); } rendre(); },
            points: points,
            choisi: function () { return choisi; }
        };
    })();

    cal.render();

    document.querySelectorAll("[data-pl]").forEach(function (b) {
        b.addEventListener("click", function () { cal[b.getAttribute("data-pl")](); });
    });
    document.querySelectorAll("[data-vue]").forEach(function (b) {
        b.addEventListener("click", function () { cal.changeView(b.getAttribute("data-vue")); });
    });
    document.querySelectorAll("[data-couche]").forEach(function (c) { c.addEventListener("change", function () { cal.refetchEvents(); }); });

    /* ---------- Équipe (administration) ---------- */
    var equipe = document.getElementById("pl-equipe");
    if (equipe) {
        equipe.querySelectorAll("[data-av]").forEach(function (a) {
            var n = a.getAttribute("data-av"); a.textContent = init(n); a.style.background = couleur(n);
        });
        equipe.addEventListener("click", function (e) {
            var li = e.target.closest("li[data-qui]"); if (!li) return;
            quiSel.value = li.getAttribute("data-qui");
            equipe.querySelectorAll("li").forEach(function (x) { x.classList.toggle("on", x === li); });
            var t = document.getElementById("pl-qui-txt"); if (t) t.textContent = li.querySelector("b").textContent;
            cal.refetchEvents();
        });
        var eq = document.getElementById("pl-equipe-q");
        if (eq) eq.addEventListener("input", function () {
            var m = norm(eq.value).trim().split(/\s+/).filter(Boolean);
            equipe.querySelectorAll("li[data-nom]").forEach(function (li) {
                var t = norm(li.getAttribute("data-nom"));
                li.hidden = !m.every(function (w) { return t.indexOf(w) !== -1; });
            });
        });
    }

    /* ---------- Groupes : agenda partagé + planifier avec tout le groupe ---------- */
    var GRP = JSON.parse((document.getElementById("pl-groupes-js") || {}).textContent || "[]");
    var grpUl = document.getElementById("pl-groupes");
    function choisirQui(valeur, libelle) {
        if (!quiSel) return;
        quiSel.value = valeur;
        document.querySelectorAll("#pl-groupes li[data-qui], #pl-equipe li[data-qui]").forEach(function (x) {
            x.classList.toggle("on", x.getAttribute("data-qui") === valeur);
        });
        var t = document.getElementById("pl-qui-txt"); if (t) t.textContent = valeur === "moi" ? "" : "Vue : " + libelle;
        cal.refetchEvents();
    }
    if (equipe) equipe.addEventListener("click", function (e) {
        // La liste Équipe et la liste Groupes partagent le même filtre : on désélectionne les groupes
        if (e.target.closest("li[data-qui]") && grpUl) grpUl.querySelectorAll("li").forEach(function (x) { x.classList.remove("on"); });
    });
    if (grpUl) {
        grpUl.querySelectorAll("[data-av]").forEach(function (a) {
            var n = a.getAttribute("data-av"); a.textContent = init(n); a.style.background = couleur(n);
        });
        grpUl.addEventListener("click", function (e) {
            var plus = e.target.closest("[data-planifier]");
            if (plus) {
                e.stopPropagation();
                var g = GRP.filter(function (x) { return x.pk === +plus.getAttribute("data-planifier"); })[0];
                if (!g) return;
                ouvrir(null);
                participants = g.membres.slice();
                rendreChips();
                f.titre.value = "Réunion — " + g.titre;
                entete("Rendez-vous de groupe", "Tous les membres de « " + g.titre + " » sont invités.");
                return;
            }
            var li = e.target.closest("li[data-qui]"); if (!li) return;
            choisirQui(li.getAttribute("data-qui"), li.querySelector("b").textContent);
        });
    }

    /* ---------- « À ne pas oublier » : données du sondage global (rappels.js) ---------- */
    var oubli = document.getElementById("pl-oubli"), oubliUl = document.getElementById("pl-oubli-liste");
    var ETATS = { retard: "En retard", jour: "Aujourd'hui", demain: "Demain" };
    function majOubli(d) {
        if (!oubli || !d) return;
        var items = [];
        (d.taches || []).forEach(function (t) {
            items.push('<li class="pl-ob t-' + t.etat + '" data-ob-tache="' + t.id + '"><i></i><span><b>' + esc(t.titre) + "</b><small>Tâche · " + ETATS[t.etat] + "</small></span></li>");
        });
        (d.rendez_vous || []).forEach(function (r) {
            var deb = new Date(r.debut), auj = jour(deb) === jour(new Date());
            var quand = r.en_cours ? "En cours" : (auj ? "Aujourd'hui" : "Demain") + (r.heure ? " à " + r.heure : "");
            items.push('<li class="pl-ob r" data-ob-ev="ev-' + r.id + '" data-ob-date="' + esc(r.debut) + '"><i></i><span><b>' + esc(r.titre) + "</b><small>" + esc(quand + (r.lieu ? " · " + r.lieu : "")) + "</small></span></li>");
        });
        oubli.hidden = !items.length;
        oubliUl.innerHTML = items.join("");
    }
    document.addEventListener("rappels:maj", function (e) { majOubli(e.detail); });
    if (window.Rappels && window.Rappels.dernier) majOubli(window.Rappels.dernier);
    if (oubliUl) oubliUl.addEventListener("click", function (e) {
        var t = e.target.closest("[data-ob-tache]");
        if (t) {
            var ev = cal.getEventById("tache-" + t.getAttribute("data-ob-tache"));
            if (ev) { cal.gotoDate(ev.start); ouvrirTache(ev); }
            else if (window.Rappels && window.Rappels.dernier) location.href = window.Rappels.dernier.taches_url;
            return;
        }
        var r = e.target.closest("[data-ob-ev]");
        if (r) {
            cal.gotoDate(new Date(r.getAttribute("data-ob-date")));
            setTimeout(function () { var x = cal.getEventById(r.getAttribute("data-ob-ev")); if (x) ouvrir(x); }, 400);
        }
    });
    var notifBtn = document.getElementById("pl-notif-btn");
    if (notifBtn && "Notification" in window && Notification.permission === "default") {
        notifBtn.hidden = false;
        notifBtn.addEventListener("click", function () {
            Notification.requestPermission().then(function (p) {
                notifBtn.hidden = true;
                toast(p === "granted" ? "success" : "info", p === "granted" ? "Alertes activées : vous serez prévenu avant vos rendez-vous." : "Alertes du navigateur refusées : les rappels s'afficheront dans l'application.");
            });
        });
    }

    function deplacer(info) {
        var e = info.event;
        poster({ action: "deplacer", pk: e.extendedProps.pk, debut: e.startStr, fin: e.endStr || null, journee: e.allDay })
            .then(function () { toast("success", "Rendez-vous déplacé."); majProchains(); })
            .catch(function (err) { info.revert(); toast("error", err.message); });
    }

    function majProchains() {
        var ul = document.getElementById("pl-prochains");
        if (!ul) return;
        var maintenant = new Date();
        var evs = cal.getEvents().filter(function (e) {
            return e.extendedProps.source === "agenda" && (e.end || e.start) >= maintenant;
        }).sort(function (a, b) { return a.start - b.start; }).slice(0, 5);
        if (!evs.length) { ul.innerHTML = '<li class="pl-vide">Aucun rendez-vous à venir sur cette période.</li>'; return; }
        ul.innerHTML = evs.map(function (e) {
            var d = e.start, auj = jour(d) === jour(maintenant);
            var quand = (auj ? "Aujourd'hui" : d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" })) + (e.allDay ? "" : " · " + heure(d));
            return '<li data-id="' + esc(e.id) + '" style="--c:' + esc(e.backgroundColor) + '"><i></i><span><b>' + esc(e.title) + "</b><small>" + esc(quand) + "</small></span></li>";
        }).join("");
    }
    document.getElementById("pl-prochains").addEventListener("click", function (ev) {
        var li = ev.target.closest("li[data-id]");
        if (!li) return;
        var e = cal.getEventById(li.getAttribute("data-id"));
        if (e) { cal.gotoDate(e.start); ouvrir(e); }
    });

    /* ---------- Ma journée (employé) : tâches + rendez-vous du jour choisi ---------- */
    function majJour() {
        var ul = document.getElementById("pl-jour");
        if (!ul) return;
        var k = mini.choisi(), d = new Date(k + "T12:00:00");
        var items = cal.getEvents().filter(function (e) {
            var p = e.extendedProps;
            if (p.source !== "agenda" && !(p.source === "tache" && p.mine)) return false;
            var fin = e.end || e.start;
            return jour(e.start) <= k && (e.allDay ? jour(new Date(fin.getTime() - 1)) >= k : jour(fin) >= k);
        }).sort(function (a, b) { return (a.allDay ? 0 : 1) - (b.allDay ? 0 : 1) || a.start - b.start; });
        var titre = jour(new Date()) === k ? "Aujourd'hui" : d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
        var h = '<li class="pl-jour-titre">' + esc(titre) + "</li>";
        if (!items.length) h += '<li class="pl-vide">Rien de prévu. Cliquez sur « Nouveau » pour ajouter une tâche.</li>';
        h += items.map(function (e) {
            var p = e.extendedProps;
            if (p.source === "tache") {
                var fait = p.statut === "TERMINEE";
                return '<li class="pl-jt' + (fait ? " fait" : "") + '" style="--c:' + esc(e.backgroundColor) + '"><button type="button" class="pl-coche" data-cocher="' + p.pk + '" aria-label="' + (fait ? "Rouvrir" : "Marquer terminée") + '">' + (fait ? ICO_CHECK : "") + '</button>' +
                    '<span data-ouvrir="' + esc(e.id) + '"><b>' + esc(e.title) + "</b><small>" + esc(p.statut_label + " · priorité " + String(p.priorite_label).toLowerCase()) + "</small></span></li>";
            }
            return '<li class="pl-jr" style="--c:' + esc(e.backgroundColor) + '"><i></i><span data-ouvrir="' + esc(e.id) + '"><b>' + esc(e.title) + "</b><small>" + (e.allDay ? "Toute la journée" : heure(e.start)) + "</small></span></li>";
        }).join("");
        ul.innerHTML = h;
    }
    var jourUl = document.getElementById("pl-jour");
    if (jourUl) jourUl.addEventListener("click", function (e) {
        var c = e.target.closest("[data-cocher]");
        if (c) {
            var ev = cal.getEventById("tache-" + c.getAttribute("data-cocher"));
            var statut = ev && ev.extendedProps.statut === "TERMINEE" ? "A_FAIRE" : "TERMINEE";
            poster({ action: "tache_statut", pk: +c.getAttribute("data-cocher"), statut: statut }).then(function () {
                toast("success", statut === "TERMINEE" ? "Tâche terminée, bravo !" : "Tâche rouverte.");
                cal.refetchEvents();
            }).catch(function (err) { toast("error", err.message); });
            return;
        }
        var o = e.target.closest("[data-ouvrir]");
        if (o) { var x = cal.getEventById(o.getAttribute("data-ouvrir")); if (x) (x.extendedProps.source === "tache" ? ouvrirTache : ouvrir)(x); }
    });

    /* ---------- Tiroir : bascule Rendez-vous / Tâche ---------- */
    var evForm = document.getElementById("ev-form"), tkForm = document.getElementById("tk-form");
    var modes = document.getElementById("ev-modes");
    function mode(m, verrou) {
        evForm.hidden = m !== "rdv"; tkForm.hidden = m !== "tache";
        modes.querySelectorAll("[data-mode]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-mode") === m); });
        modes.hidden = !!verrou;
    }
    modes.addEventListener("click", function (e) {
        var b = e.target.closest("[data-mode]"); if (!b) return;
        var m = b.getAttribute("data-mode");
        if (m === "tache") { var d = f.dj.value; ouvrirTache(null, d, true); } else { mode("rdv"); entete("Nouveau rendez-vous", "Planifiez un rendez-vous, une réunion ou un appel."); }
    });
    function entete(t, sous) { document.getElementById("ev-titre-p").textContent = t; document.getElementById("ev-sous").textContent = sous; }

    /* ---------- Tiroir rendez-vous ---------- */
    var f = {
        pk: document.getElementById("ev-pk"), titre: document.getElementById("ev-titre"), type: document.getElementById("ev-type"),
        journee: document.getElementById("ev-journee"), dj: document.getElementById("ev-debut-j"), dh: document.getElementById("ev-debut-h"),
        fj: document.getElementById("ev-fin-j"), fh: document.getElementById("ev-fin-h"), client: document.getElementById("ev-client"),
        lieu: document.getElementById("ev-lieu"), desc: document.getElementById("ev-desc"), rappel: document.getElementById("ev-rappel")
    };
    var msClient = window.SearchSelect && window.SearchSelect.enhance(f.client);
    var participants = [], couleurChoisie = "";

    function majJournee() {
        document.querySelectorAll(".ev-heure").forEach(function (h) { h.hidden = f.journee.checked; });
        document.getElementById("ev-durees").hidden = f.journee.checked;
    }
    f.journee.addEventListener("change", majJournee);
    document.querySelectorAll("#ev-durees [data-min]").forEach(function (b) {
        b.addEventListener("click", function () {
            var d = new Date(f.dj.value + "T" + (f.dh.value || "09:00"));
            d = new Date(d.getTime() + (+b.getAttribute("data-min")) * 60000);
            f.fj.value = jour(d); f.fh.value = heure(d);
        });
    });
    f.dh.addEventListener("change", function () {
        if (!f.dj.value) return;
        var fin = new Date(f.fj.value + "T" + (f.fh.value || "10:00"));
        var deb = new Date(f.dj.value + "T" + f.dh.value);
        if (fin <= deb) { var n = new Date(deb.getTime() + 3600000); f.fj.value = jour(n); f.fh.value = heure(n); }
    });
    document.querySelectorAll("#ev-couleurs [data-c]").forEach(function (b) {
        b.addEventListener("click", function () {
            couleurChoisie = b.getAttribute("data-c");
            document.querySelectorAll("#ev-couleurs [data-c]").forEach(function (x) { x.classList.toggle("on", x === b); });
        });
    });

    // Participants (puces + suggestions)
    var q = document.getElementById("ev-part-q"), liste = document.getElementById("ev-part-liste"), chips = document.getElementById("ev-chips");
    function rendreChips() {
        chips.innerHTML = participants.map(function (pk) {
            var e = EMP.find(function (x) { return x.pk === pk; }); if (!e) return "";
            return '<span class="ev-chip"><i style="background:' + couleur(e.nom) + '">' + esc(init(e.nom)) + "</i>" + esc(e.nom) +
                '<button type="button" data-retirer="' + pk + '" aria-label="Retirer ' + esc(e.nom) + '">×</button></span>';
        }).join("");
    }
    var options = [];
    function rendreListe() {
        var m = norm(q.value).trim().split(/\s+/).filter(Boolean);
        options = EMP.filter(function (e) {
            return participants.indexOf(e.pk) === -1 && m.every(function (w) { return norm(e.nom + " " + e.fonction).indexOf(w) !== -1; });
        }).slice(0, 7);
        liste.innerHTML = options.length ? options.map(function (e, i) {
            return '<li class="sal-sugg-opt" data-i="' + i + '"><span class="sal-av" style="background:' + couleur(e.nom) + '">' + esc(init(e.nom)) +
                '</span><span class="sal-sugg-txt"><b>' + esc(e.nom) + "</b><small>" + esc(e.fonction || "Sans fonction") + "</small></span></li>";
        }).join("") : '<li class="sal-sugg-vide">Aucun employé à ajouter.</li>';
        liste.hidden = false;
    }
    q.addEventListener("focus", rendreListe);
    q.addEventListener("input", rendreListe);
    q.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); if (options[0]) { participants.push(options[0].pk); q.value = ""; rendreChips(); rendreListe(); } }
        if (e.key === "Escape") liste.hidden = true;
    });
    liste.addEventListener("mousedown", function (e) {
        var li = e.target.closest(".sal-sugg-opt"); if (!li) return;
        e.preventDefault(); participants.push(options[+li.getAttribute("data-i")].pk); q.value = ""; rendreChips(); rendreListe();
    });
    chips.addEventListener("click", function (e) {
        var b = e.target.closest("[data-retirer]"); if (!b) return;
        participants = participants.filter(function (p) { return p !== +b.getAttribute("data-retirer"); }); rendreChips();
    });
    document.addEventListener("click", function (e) { if (!e.target.closest(".ev-part")) liste.hidden = true; });

    var modifiable = true;
    function ouvrir(ev, sel) {
        evForm.reset();
        mode("rdv", !!ev);
        couleurChoisie = "";
        document.querySelectorAll("#ev-couleurs [data-c]").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-c") === ""); });
        var p = ev ? ev.extendedProps : {};
        modifiable = !ev || p.modifiable;
        f.pk.value = ev ? p.pk : "";
        f.titre.value = ev ? ev.title : "";
        f.type.value = ev ? p.type : "RDV";
        var debut = ev ? ev.start : (sel ? sel.start : arrondi(new Date()));
        var fin = ev ? (ev.end || ev.start) : (sel ? sel.end : new Date(debut.getTime() + 3600000));
        var journee = ev ? ev.allDay : (sel ? sel.allDay : false);
        if (journee && fin > debut) fin = new Date(fin.getTime() - 86400000); // fin exclusive → incluse
        f.journee.checked = journee;
        f.dj.value = jour(debut); f.dh.value = journee ? "09:00" : heure(debut);
        f.fj.value = jour(fin); f.fh.value = journee ? "10:00" : heure(fin);
        f.client.value = ev ? String(p.client_id || "") : "";
        if (msClient) msClient.refresh();
        f.lieu.value = ev ? (p.lieu || "") : "";
        f.desc.value = ev ? (p.description || "") : "";
        f.rappel.value = ev ? String(p.rappel || "") : "";
        if (ev && p.couleur) {
            couleurChoisie = p.couleur;
            document.querySelectorAll("#ev-couleurs [data-c]").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-c") === p.couleur); });
        }
        participants = ev ? (p.participants || []).slice() : (PL.moi && !PL.admin ? [PL.moi] : []);
        rendreChips();
        majJournee();
        imageNouvelle = null; imageSupprimer = false;
        afficherImage(ev ? p.image : "");
        entete(ev ? (modifiable ? "Modifier le rendez-vous" : "Rendez-vous") : "Nouveau",
            ev ? (p.type_label + (p.client ? " · " + p.client : "")) : "Ajoutez un rendez-vous ou une tâche à votre planning.");
        var org = document.getElementById("ev-org");
        org.hidden = !ev || !p.organisateur;
        org.textContent = ev && p.organisateur ? "Organisé par " + p.organisateur + (modifiable ? "" : " — seul l'organisateur peut le modifier.") : "";
        document.getElementById("ev-suppr").hidden = !ev || !modifiable;
        document.getElementById("ev-enregistrer").hidden = !modifiable;
        evForm.querySelectorAll("input, select, textarea").forEach(function (x) { x.disabled = !modifiable; });
        imgBtn.hidden = !modifiable;
        if (!modifiable) imgRetirer.hidden = true;
        if (window.openDrawer) window.openDrawer();
        setTimeout(function () { if (modifiable) f.titre.focus(); }, 80);
    }
    function arrondi(d) { var x = new Date(d); x.setMinutes(Math.ceil(x.getMinutes() / 30) * 30, 0, 0); return x; }

    /* ---------- Image du rendez-vous (compressée dans le navigateur, max 1600 px) ---------- */
    var imageNouvelle = null, imageSupprimer = false;
    var imgApercu = document.getElementById("ev-image-apercu"), imgBtn = document.getElementById("ev-image-btn"),
        imgRetirer = document.getElementById("ev-image-retirer"), imgFichier = document.getElementById("ev-image-fichier"),
        imgLib = document.getElementById("ev-image-lib");
    function afficherImage(src) {
        imgApercu.hidden = !src;
        if (src) imgApercu.src = src; else imgApercu.removeAttribute("src");
        imgRetirer.hidden = !src;
        imgLib.textContent = src ? "Changer l'image" : "Ajouter une image";
    }
    imgBtn.addEventListener("click", function () { imgFichier.value = ""; imgFichier.click(); });
    imgRetirer.addEventListener("click", function () { imageNouvelle = null; imageSupprimer = true; afficherImage(""); });
    imgFichier.addEventListener("change", function () {
        var fichier = imgFichier.files && imgFichier.files[0];
        if (!fichier) return;
        if (["image/png", "image/jpeg", "image/webp", "image/gif"].indexOf(fichier.type) === -1) { toast("error", "Format non pris en charge (PNG, JPG, WebP ou GIF)."); return; }
        if (fichier.size > 15 * 1024 * 1024) { toast("error", "Image trop lourde (15 Mo maximum)."); return; }
        var url = URL.createObjectURL(fichier), img = new Image();
        img.onload = function () {
            var r = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight)), c = document.createElement("canvas");
            c.width = Math.max(1, Math.round(img.naturalWidth * r)); c.height = Math.max(1, Math.round(img.naturalHeight * r));
            c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
            URL.revokeObjectURL(url);
            imageNouvelle = fichier.type === "image/png" ? c.toDataURL("image/png") : c.toDataURL("image/jpeg", 0.85);
            imageSupprimer = false;
            afficherImage(imageNouvelle);
        };
        img.onerror = function () { URL.revokeObjectURL(url); toast("error", "Impossible de lire cette image."); };
        img.src = url;
    });

    document.getElementById("pl-nouveau").addEventListener("click", function () { ouvrir(null); });
    evForm.addEventListener("submit", function (e) {
        e.preventDefault();
        if (!modifiable) return;
        if (!f.titre.value.trim()) { toast("error", "Donnez un titre au rendez-vous."); f.titre.focus(); return; }
        var j = f.journee.checked;
        var corps = {
            pk: f.pk.value || null, titre: f.titre.value, type: f.type.value, journee: j,
            debut: j ? f.dj.value : f.dj.value + "T" + (f.dh.value || "09:00"),
            fin: j ? (f.fj.value || f.dj.value) : (f.fj.value || f.dj.value) + "T" + (f.fh.value || "10:00"),
            client: f.client.value, lieu: f.lieu.value, description: f.desc.value, rappel: f.rappel.value,
            couleur: couleurChoisie, participants: participants,
            image: imageNouvelle || "", image_supprimer: imageSupprimer
        };
        poster(corps).then(function () {
            toast("success", f.pk.value ? "Rendez-vous mis à jour." : "Rendez-vous ajouté au planning.");
            fermerTiroir();
            cal.refetchEvents();
        }).catch(function (err) { toast("error", err.message); });
    });
    document.getElementById("ev-suppr").addEventListener("click", function () {
        if (!f.pk.value || !confirm("Supprimer ce rendez-vous ?")) return;
        poster({ action: "supprimer", pk: f.pk.value }).then(function () {
            toast("success", "Rendez-vous supprimé.");
            fermerTiroir();
            cal.refetchEvents();
        }).catch(function (err) { toast("error", err.message); });
    });

    /* ---------- Tiroir tâche ---------- */
    var t = {
        pk: document.getElementById("tk-pk"), titre: document.getElementById("tk-titre"), desc: document.getElementById("tk-desc"),
        debut: document.getElementById("tk-debut"), fin: document.getElementById("tk-fin"), prio: document.getElementById("tk-prio"),
        assignee: document.getElementById("tk-assignee")
    };
    var msAssignee = t.assignee && window.SearchSelect && window.SearchSelect.enhance(t.assignee);
    var tacheOuverte = null;
    t.debut.addEventListener("change", function () { if (!t.fin.value || t.fin.value < t.debut.value) t.fin.value = t.debut.value; });
    function ouvrirTache(ev, jourDefaut, dejaOuvert) {
        tkForm.reset();
        tacheOuverte = ev;
        var p = ev ? ev.extendedProps : {};
        var ok = !ev || p.modifiable;
        mode("tache", !!ev);
        t.pk.value = ev ? p.pk : "";
        t.titre.value = ev ? ev.title : "";
        t.desc.value = ev ? (p.description || "") : "";
        var j0 = ev ? jour(ev.start) : (jourDefaut || mini.choisi() || jour(new Date()));
        t.debut.value = j0;
        t.fin.value = ev ? (p.echeance || j0) : j0;
        t.prio.value = ev ? p.priorite : "MOYENNE";
        if (t.assignee) {
            t.assignee.value = ev ? String(p.assignee_id || "") : (qui().indexOf("emp:") === 0 ? qui().slice(4) : "");
            if (msAssignee) msAssignee.refresh();
        }
        var st = document.getElementById("tk-statut");
        st.hidden = !ev || !ok;
        st.querySelectorAll("[data-statut]").forEach(function (b) { b.classList.toggle("on", ev && b.getAttribute("data-statut") === p.statut); });
        var info = document.getElementById("tk-info");
        info.hidden = !ev;
        info.textContent = ev ? ("Assignée à " + (p.assignee || "—") + (p.projet ? " · Projet " + p.projet : "") + " · avancement " + p.progres + " %" + (ok ? "" : " — lecture seule.")) : "";
        document.getElementById("tk-ouvrir").hidden = !ev;
        document.getElementById("tk-enregistrer").hidden = !ok;
        tkForm.querySelectorAll("input, select, textarea").forEach(function (x) { x.disabled = !ok; });
        entete(ev ? (ok ? "Modifier la tâche" : "Tâche") : "Nouveau", ev ? (p.statut_label + " · priorité " + String(p.priorite_label).toLowerCase()) : "Ajoutez un rendez-vous ou une tâche à votre planning.");
        if (!dejaOuvert && window.openDrawer) window.openDrawer();
        setTimeout(function () { if (ok) t.titre.focus(); }, 80);
    }
    document.getElementById("tk-statut").addEventListener("click", function (e) {
        var b = e.target.closest("[data-statut]"); if (!b || !tacheOuverte) return;
        var statut = b.getAttribute("data-statut");
        poster({ action: "tache_statut", pk: tacheOuverte.extendedProps.pk, statut: statut }).then(function () {
            toast("success", "Statut mis à jour : " + b.textContent.trim() + ".");
            fermerTiroir(); cal.refetchEvents();
        }).catch(function (err) { toast("error", err.message); });
    });
    tkForm.addEventListener("submit", function (e) {
        e.preventDefault();
        if (!t.titre.value.trim()) { toast("error", "Donnez un titre à la tâche."); t.titre.focus(); return; }
        if (!t.fin.value) { toast("error", "Choisissez le jour de la tâche."); t.fin.focus(); return; }
        if (t.assignee && !t.assignee.value) { toast("error", "Choisissez l'employé à qui attribuer la tâche."); return; }
        poster({
            action: "tache", pk: t.pk.value || null, titre: t.titre.value, description: t.desc.value,
            debut: t.debut.value, echeance: t.fin.value, priorite: t.prio.value, assignee: t.assignee ? t.assignee.value : null
        }).then(function () {
            toast("success", t.pk.value ? "Tâche mise à jour." : "Tâche ajoutée au planning.");
            fermerTiroir();
            cal.refetchEvents();
        }).catch(function (err) { toast("error", err.message); });
    });

    var params = new URLSearchParams(location.search);
    if (params.get("nouveau")) ouvrir(null);
    if (params.get("tache")) ouvrirTache(null);
})();
