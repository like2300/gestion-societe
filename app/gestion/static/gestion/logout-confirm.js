/* =====================================================================
   logout-confirm.js — fenêtre de confirmation avant la déconnexion.
   S'applique automatiquement à tout formulaire dont l'action pointe vers
   la déconnexion (…/logout/) et à tout élément [data-confirm-logout].
   Autonome (styles injectés) : fonctionne dans le tableau de bord comme sur
   les pages d'authentification. Échap / clic sur le fond = annuler.
   ===================================================================== */
(function () {
    "use strict";
    if (window.__deconnexionConfirmee) return; // script déjà chargé sur la page
    window.__deconnexionConfirmee = true;
    var CSS = '' +
        '.lc-voile{position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;padding:16px;' +
        'background:rgba(15,23,42,.45);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);animation:lc-f .18s ease}' +
        '.lc-boite{width:100%;max-width:400px;padding:28px 26px 22px;border-radius:20px;text-align:center;font-family:inherit;' +
        'background:var(--ui-card,#fff);color:var(--ui-text,#0f172a);border:1px solid var(--ui-border,#e2e8f0);' +
        'box-shadow:0 30px 80px -20px rgba(15,23,42,.45);animation:lc-z .22s cubic-bezier(.2,.8,.2,1)}' +
        '.lc-ico{width:56px;height:56px;margin:0 auto 14px;border-radius:16px;display:flex;align-items:center;justify-content:center;' +
        'color:#e11d48;background:color-mix(in srgb,#e11d48 12%,transparent)}' +
        '.lc-ico svg{width:26px;height:26px}' +
        '.lc-titre{margin:0;font-size:1.15rem;font-weight:700;letter-spacing:-.01em}' +
        '.lc-texte{margin:.45rem 0 1.4rem;font-size:.9rem;line-height:1.5;color:var(--ui-muted,#64748b)}' +
        '.lc-actions{display:flex;gap:.6rem}' +
        '.lc-actions button{flex:1;height:44px;border-radius:12px;font:inherit;font-size:.9rem;font-weight:600;cursor:pointer;transition:filter .15s,background .15s,border-color .15s}' +
        '.lc-annuler{border:1px solid var(--ui-border,#e2e8f0);background:var(--ui-card,#fff);color:var(--ui-text,#0f172a)}' +
        '.lc-annuler:hover{border-color:var(--accent,#0284c7);color:var(--accent,#0284c7)}' +
        '.lc-ok{border:0;background:#e11d48;color:#fff;box-shadow:0 10px 22px -12px #e11d48}' +
        '.lc-ok:hover{filter:brightness(1.07)}' +
        '.lc-ok[disabled]{opacity:.7;cursor:progress}' +
        '.lc-actions button:focus{outline:none}.lc-actions button:focus-visible{outline:2px solid var(--accent,#0284c7);outline-offset:2px}' +
        '@keyframes lc-f{from{opacity:0}to{opacity:1}}@keyframes lc-z{from{opacity:0;transform:translateY(8px) scale(.97)}to{opacity:1;transform:none}}';

    function styles() {
        if (document.getElementById("lc-styles")) return;
        var s = document.createElement("style");
        s.id = "lc-styles";
        s.textContent = CSS;
        document.head.appendChild(s);
    }

    function confirmer(valider) {
        styles();
        var precedent = document.activeElement;
        var voile = document.createElement("div");
        voile.className = "lc-voile";
        voile.innerHTML =
            '<div class="lc-boite" role="alertdialog" aria-modal="true" aria-labelledby="lc-titre" aria-describedby="lc-texte">' +
            '<div class="lc-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/></svg></div>' +
            '<h2 class="lc-titre" id="lc-titre">Se déconnecter ?</h2>' +
            '<p class="lc-texte" id="lc-texte">Vous allez quitter votre session. Les modifications non enregistrées seront perdues.</p>' +
            '<div class="lc-actions"><button type="button" class="lc-annuler">Annuler</button>' +
            '<button type="button" class="lc-ok">Se déconnecter</button></div></div>';
        document.body.appendChild(voile);
        var ok = voile.querySelector(".lc-ok"), annuler = voile.querySelector(".lc-annuler");
        function fermer() {
            document.removeEventListener("keydown", clavier, true);
            voile.remove();
            if (precedent && precedent.focus) precedent.focus();
        }
        function clavier(e) {
            if (e.key === "Escape") { e.preventDefault(); fermer(); }
            if (e.key === "Tab") { // garde le focus dans la fenêtre
                e.preventDefault();
                (document.activeElement === ok ? annuler : ok).focus();
            }
        }
        annuler.addEventListener("click", fermer);
        voile.addEventListener("click", function (e) { if (e.target === voile) fermer(); });
        ok.addEventListener("click", function () {
            ok.disabled = true;
            ok.textContent = "Déconnexion…";
            valider();
        });
        document.addEventListener("keydown", clavier, true);
        annuler.focus();
    }

    function estDeconnexion(form) {
        // La page /logout/ d'allauth est déjà une confirmation : pas de double demande.
        if (/\/logout\/?$/.test(window.location.pathname)) return false;
        var a = form.getAttribute("action") || "";
        return form.hasAttribute("data-confirm-logout") || /\/logout\/?(\?|$)/.test(a);
    }

    document.addEventListener("submit", function (e) {
        var form = e.target;
        if (!form || form.tagName !== "FORM" || !estDeconnexion(form) || form.__lcOk) return;
        e.preventDefault();
        confirmer(function () { form.__lcOk = true; HTMLFormElement.prototype.submit.call(form); });
    }, true);

    document.addEventListener("click", function (e) {
        var lien = e.target.closest && e.target.closest("a[data-confirm-logout], a[href*='/logout']");
        if (!lien || lien.__lcOk) return;
        e.preventDefault();
        confirmer(function () { window.location.href = lien.href; });
    }, true);

    window.confirmerDeconnexion = confirmer;
})();
