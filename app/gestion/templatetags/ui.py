"""Balises de template du design system (composants réutilisables)."""

from django import template

register = template.Library()


def _nombres(values):
    out = []
    for v in values or []:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


@register.inclusion_tag("gestion/components/sparkline.html")
def sparkline(values, uid="sp", color="var(--accent)", width=240, height=54):
    """Mini-courbe SVG lissée à partir d'une liste de nombres.

    Usage : {% sparkline series uid="emp" %}
    """
    vals = _nombres(values)
    pad = 6
    if len(vals) < 2:
        vals = (vals or [0.0]) * 2
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = i * width / (n - 1)
        if hi == lo:
            y = height / 2
        else:
            y = pad + (height - 2 * pad) * (1 - (v - lo) / span)
        pts.append((x, y))

    # Lissage de type Catmull-Rom -> courbes de Bézier.
    path = "M{:.1f},{:.1f}".format(*pts[0])
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        path += " C{:.1f},{:.1f} {:.1f},{:.1f} {:.1f},{:.1f}".format(*c1, *c2, *p2)
    area = path + " L{:.1f},{} L0,{} Z".format(pts[-1][0], height, height)
    return {
        "uid": uid,
        "color": color,
        "width": width,
        "height": height,
        "line": path,
        "area": area,
    }


@register.filter
def dollars(montant):
    """Montant d'abonnement (forfaits en USD) : « 49 $ », « 1 470 $ », « 0 $ »."""
    from gestion.models import format_prix

    return format_prix(montant, "USD") if montant else "0 $"


@register.simple_tag
def nb_demandes_offre():
    """Nombre de demandes d'offre en attente (cloche du tableau de bord d'administration)."""
    from gestion.models import AbonnementSociete

    return AbonnementSociete.objects.filter(statut="EN_ATTENTE").count()


@register.filter
def en_devise(montant, devise="USD"):
    """Montant USD affiché dans la devise choisie (taux settings.TAUX_USD)."""
    from django.conf import settings

    from gestion.models import format_prix

    valeur = float(montant or 0)
    if devise != "USD":
        valeur *= float(settings.TAUX_USD.get(devise, 1))
    return format_prix(round(valeur, 2), devise) if valeur else ("0 $" if devise == "USD" else f"0 {devise}")
