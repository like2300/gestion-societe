/* =====================================================================
   rappels.js — rappels du planning sur toutes les pages
   ---------------------------------------------------------------------
   Sonde /gestion/planning/rappels/ (chaque minute et au retour sur l'onglet) :
   - rendez-vous : alerte à l'heure du rappel choisie (toast + notification
     du navigateur si autorisée), une seule fois par rendez-vous ;
   - tâches en retard / du jour : résumé une fois par jour.
   Diffuse les données (évènement « rappels:maj ») pour la carte
   « À ne pas oublier » du planning.
   ===================================================================== */
(function () {
    "use strict";
    var URL_RAPPELS = window.RAPPELS_URL;
    if (!URL_RAPPELS || !window.fetch) return;

    function deja(cle) { try { return localStorage.getItem(cle) === "1"; } catch (e) { return false; } }
    function marquer(cle) { try { localStorage.setItem(cle, "1"); } catch (e) { /* stockage indisponible */ } }
    function toast(type, msg) { if (window.showToast) window.showToast(type, msg); }
    function notifier(titre, corps, lien) {
        if (!("Notification" in window) || Notification.permission !== "granted") return;
        try {
            var n = new Notification(titre, { body: corps, tag: titre + corps });
            n.onclick = function () { window.focus(); if (lien) location.href = lien; n.close(); };
        } catch (e) { /* notifications indisponibles (ex. mobile sans service worker) */ }
    }

    function traiter(d) {
        var maintenant = Date.now();
        (d.rendez_vous || []).forEach(function (r) {
            if (!r.rappel) return;
            var debut = new Date(r.debut).getTime(), rappel = new Date(r.rappel).getTime();
            var cle = "rap:ev:" + r.id + ":" + r.debut;
            // Fenêtre : de l'heure du rappel jusqu'à 10 min après le début (rattrapage si l'app était fermée)
            if (maintenant < rappel || maintenant > debut + 600000 || deja(cle)) return;
            marquer(cle);
            var mins = Math.round((debut - maintenant) / 60000);
            var quand = mins > 1 ? "dans " + mins + " min" : (mins >= -1 ? "maintenant" : "a commencé");
            var msg = "Rappel : « " + r.titre + " » " + quand + (r.heure ? " (" + r.heure + ")" : "") + (r.lieu ? " — " + r.lieu : "");
            toast("info", msg);
            notifier("Rendez-vous " + quand, r.titre + (r.heure ? " à " + r.heure : "") + (r.lieu ? " — " + r.lieu : ""), d.planning);
        });
        var retard = 0, jour = 0;
        (d.taches || []).forEach(function (t) { if (t.etat === "retard") retard++; else if (t.etat === "jour") jour++; });
        var cleJour = "rap:taches:" + new Date().toISOString().slice(0, 10);
        if ((retard || jour) && !deja(cleJour)) {
            marquer(cleJour);
            var morceaux = [];
            if (retard) morceaux.push(retard + " tâche" + (retard > 1 ? "s" : "") + " en retard");
            if (jour) morceaux.push(jour + " à terminer aujourd'hui");
            toast(retard ? "error" : "info", "N'oubliez pas : " + morceaux.join(" et ") + ".");
            notifier("Tâches à ne pas oublier", morceaux.join(" et "), d.taches_url);
        }
    }

    var enCours = false;
    function sonder() {
        if (enCours || document.hidden) return;
        enCours = true;
        fetch(URL_RAPPELS, { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                window.Rappels.dernier = d;
                traiter(d);
                document.dispatchEvent(new CustomEvent("rappels:maj", { detail: d }));
            })
            .catch(function () { /* hors ligne : nouvel essai à la prochaine minute */ })
            .then(function () { enCours = false; });
    }
    window.Rappels = { dernier: null, actualiser: sonder };
    setTimeout(sonder, 1500);
    setInterval(sonder, 60000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) sonder(); });
})();
