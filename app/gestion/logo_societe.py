"""Logo de la société pour les documents générés (PDF ReportLab, Excel).

Le logo (champ ``Societe.logo``, stocké via default_storage) est converti une
fois en PNG (Pillow) pour être accepté partout : WEBP, JPG, GIF, PNG transparent.
Le SVG n'est pas pris en charge par ReportLab/Pillow : il est alors ignoré.
"""

import io
import os

from django.core.files.storage import default_storage

_CACHE = {}


def _chemin(societe):
    nom = getattr(societe, "logo", None) or ""
    if not nom:
        return None
    try:
        chemin = default_storage.path(nom)
    except Exception:
        return None
    return chemin if os.path.isfile(chemin) else None


def logo_png(societe, taille_max=600):
    """Octets PNG du logo (ou None). Mis en cache selon le fichier et sa date."""
    chemin = _chemin(societe)
    if not chemin or chemin.lower().endswith(".svg"):
        return None
    cle = (chemin, os.path.getmtime(chemin))
    if cle in _CACHE:
        return _CACHE[cle]
    try:
        from PIL import Image

        with Image.open(chemin) as im:
            im = im.convert("RGBA")
            # Rogne les marges transparentes pour un rendu net
            boite = im.getbbox()
            if boite:
                im = im.crop(boite)
            im.thumbnail((taille_max, taille_max))
            sortie = io.BytesIO()
            im.save(sortie, format="PNG")
            donnees = sortie.getvalue()
    except Exception:
        donnees = None
    _CACHE.clear()
    _CACHE[cle] = donnees
    return donnees


def logo_reader(societe):
    """(ImageReader ReportLab, ratio largeur/hauteur) ou (None, 0)."""
    donnees = logo_png(societe)
    if not donnees:
        return None, 0
    from reportlab.lib.utils import ImageReader

    lecteur = ImageReader(io.BytesIO(donnees))
    w, h = lecteur.getSize()
    return lecteur, (w / h if h else 1)


def dessiner(canvas, lecteur, ratio, x, y, h_max, w_max, aligne="gauche"):
    """Dessine le logo dans une boîte (x, y bas-gauche) en respectant ses proportions."""
    if not lecteur:
        return 0
    h = h_max
    w = h * ratio
    if w > w_max:
        w = w_max
        h = w / ratio
    if aligne == "droite":
        x = x - w
    canvas.drawImage(lecteur, x, y + (h_max - h) / 2, width=w, height=h, mask="auto")
    return w
