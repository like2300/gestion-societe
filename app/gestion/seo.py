"""Fichiers robots.txt et sitemap.xml du site public."""

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape


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
