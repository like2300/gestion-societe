"""Fichiers robots.txt, sitemap.xml et image de partage du site public."""

from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape
from PIL import Image, ImageDraw

from .models import ImageSite

OG_BASE = settings.BASE_DIR / "gestion" / "static" / "vitrine" / "og" / "og-image.png"
LOGO_DEFAUT = settings.BASE_DIR / "gestion" / "static" / "vitrine" / "favicon-180.png"


def og_image(request):
    """Image WhatsApp : capture du site avec le logo chargé dans le back-office."""
    fond = Image.open(OG_BASE).convert("RGBA")
    chemin_logo = LOGO_DEFAUT
    objet = ImageSite.objects.filter(code="logo_app").first()
    if objet and objet.image:
        try:
            candidat = Path(objet.image.path)
            if candidat.is_file():
                chemin_logo = candidat
        except (ValueError, OSError):
            pass

    try:
        logo = Image.open(chemin_logo).convert("RGBA")
    except (OSError, ValueError):
        logo = None

    if logo is not None:
        logo.thumbnail((260, 96), Image.LANCZOS)
        marge = 18
        panneau = Image.new("RGBA", (logo.width + 2 * marge, logo.height + 2 * marge), (255, 255, 255, 0))
        dessin = ImageDraw.Draw(panneau)
        dessin.rounded_rectangle(
            (0, 0, panneau.width - 1, panneau.height - 1), radius=14,
            fill=(255, 255, 255, 240),
        )
        fond.alpha_composite(panneau, (48, 48))
        fond.alpha_composite(logo, (48 + marge, 48 + marge))

    sortie = BytesIO()
    fond.convert("RGB").save(sortie, format="PNG", optimize=True)
    reponse = HttpResponse(sortie.getvalue(), content_type="image/png")
    reponse["Cache-Control"] = "public, max-age=3600"
    return reponse


def robots(request):
    lignes = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /accounts/",
        "Disallow: /abonnement/",
        "Disallow: /backoffice/",
        "Disallow: /admin/",
        "Disallow: /gestion/",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lignes) + "\n", content_type="text/plain; charset=utf-8")


def sitemap(request):
    date = timezone.localdate().isoformat()
    url = f"{settings.SITE_URL}/"
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <url><loc>{escape(url)}</loc><lastmod>{date}</lastmod>"
        '<changefreq>weekly</changefreq><priority>1.0</priority></url>',
        "</urlset>",
    ]
    return HttpResponse("\n".join(xml) + "\n", content_type="application/xml; charset=utf-8")
