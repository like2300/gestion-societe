"""Registre de configuration du CRUD générique du dashboard.

Chaque entrée décrit un module : modèle, formulaire, colonnes de table et
construction des lignes (cellules + données pour le drawer).
"""

from django.conf import settings
from django.utils.safestring import mark_safe

from . import forms, models


def _money(v):
    try:
        return f"{float(v):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _date(d, fmt="%d/%m/%Y"):
    return d.strftime(fmt) if d else "—"


def _link_document(type_, pk):
    """Lien de téléchargement protégé (permissions vérifiées) d'un document confidentiel."""
    from .fichiers_prives import url

    return mark_safe(
        f'<a href="{url(type_, pk)}" target="_blank" rel="noopener" '
        f'style="color:var(--accent);font-weight:600;text-decoration:none">'
        f"Télécharger</a>"
    )


def _kpay_info(ops):
    """(statut, pk, type) de la dernière opération KPay d'une liste (triage -created_at)."""
    op = ops[0] if ops else None
    if op is None:
        return "", "", ""
    return op.statut, op.pk, op.type_operation



_MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
            "août", "septembre", "octobre", "novembre", "décembre"]

CRUD_CONFIG = {
    "depenses": {
        "model": models.DepenseSociete,
        "form": forms.DepenseForm,
        "title": "Dépenses",
        "singular": "une dépense",
        "wide": {"description"},
        "template": "gestion/crud_depenses.html",
        "extra": {
            "employes": lambda soc: [
                {
                    "pk": e.pk,
                    "label": f"{e.prenom} {e.nom}",
                    "salaire": str(e.salaire) if e.salaire is not None else "",
                }
                for e in soc.employes.all().order_by("nom", "prenom")
            ],
        },
        "columns": [
            {"label": "Dépense"},
            {"label": "Type"},
            {"label": "Montant"},
            {"label": "Date"},
            {"label": "Statut", "badge": True},
        ],
        "queryset": lambda soc: soc.depenses.select_related("type_depense"),
        "rows": lambda soc: [
            {
                "pk": d.pk,
                "del_name": d.nom,
                "cells": [
                    d.nom,
                    d.type_depense.nom if d.type_depense else "—",
                    _money(d.montant),
                    _date(d.date_depense),
                    d.statut,
                ],
                "data": {
                    "type_depense": d.type_depense_id or "",
                    "nom": d.nom,
                    "montant": str(d.montant or ""),
                    "date_depense": d.date_depense.isoformat() if d.date_depense else "",
                    "description": d.description or "",
                    "statut": d.statut,
                    "employe": d.employe_id or "",
                    "periode_mois": d.periode_mois.isoformat() if d.periode_mois else "",
                },
            }
            for d in soc.depenses.select_related("type_depense")
        ],
    },
    "salaires": {
        "model": models.PaiementSalaire,
        "form": forms.SalaireForm,
        "title": "Salaires",
        "singular": "un paiement de salaire",
        "wide": set(),
        "template": "gestion/crud_salaires.html",
        "payable": True,
        "extra": {
            "employes": lambda soc: [
                {
                    "pk": e.pk,
                    "label": f"{e.prenom} {e.nom}",
                    "salaire": str(e.salaire) if e.salaire is not None else "",
                    "jour_paiement": e.jour_paiement or "",
                }
                for e in soc.employes.all()
            ],
        },
        "columns": [
            {"label": "Employé"},
            {"label": "Contrat"},
            {"label": "Période"},
            {"label": "Dû"},
            {"label": "Payé"},
            {"label": "Statut", "badge": True},
        ],
        "queryset": lambda soc: models.PaiementSalaire.objects.filter(
            employe__societe=soc
        ).select_related("employe", "contrat"),
        "rows": lambda soc: [
            {
                "pk": s.pk,
                "del_name": f"Paie {s.employe} ({s.periode_mois:%m/%Y})",
                "paye": s.statut == "PAYE",
                "date_paiement": s.date_paiement.isoformat() if s.date_paiement else "",
                "telephone": s.employe.telephone_1 or "",
                "kpay_statut": _kpay_info(list(s.kpay_operations.all()))[0],
                "kpay_pk": _kpay_info(list(s.kpay_operations.all()))[1],
                "kpay_type": _kpay_info(list(s.kpay_operations.all()))[2],
                "search": (
                    f"{s.employe.prenom} {s.employe.nom} "
                    f"{s.employe.fonction.nom if s.employe.fonction_id else ''} "
                    f"{s.periode_mois:%m/%Y} {_MOIS_FR[s.periode_mois.month - 1]} {s.periode_mois.year} "
                    f"{s.statut} {s.get_statut_display()}"
                ).lower(),
                "employe_pk": s.employe_id,
                "employe_nom": f"{s.employe.prenom} {s.employe.nom}",
                "fonction": s.employe.fonction.nom if s.employe.fonction_id else "",
                "periode": f"{s.periode_mois:%m/%Y}",
                "periode_label": f"{_MOIS_FR[s.periode_mois.month - 1].capitalize()} {s.periode_mois.year}",
                "statut_label": s.get_statut_display(),
                "montant_du_txt": _money(s.montant_du),
                "cells": [
                    f"{s.employe.prenom} {s.employe.nom}",
                    s.contrat.type_contrat.code if s.contrat else "—",
                    s.periode_mois.strftime("%m/%Y"),
                    _money(s.montant_du),
                    _money(s.montant_paye),
                    s.statut,
                ],
                "data": {
                    "employe": s.employe_id or "",
                    "contrat": s.contrat_id or "",
                    "periode_mois": s.periode_mois.isoformat() if s.periode_mois else "",
                    "montant_du": str(s.montant_du or ""),
                    "montant_paye": str(s.montant_paye or ""),
                    "date_prevue": s.date_prevue.isoformat() if s.date_prevue else "",
                    "date_paiement": s.date_paiement.isoformat() if s.date_paiement else "",
                    "mode_paiement": s.mode_paiement_id or "",
                    "statut": s.statut,
                },
            }
            for s in models.PaiementSalaire.objects.filter(
                employe__societe=soc
            ).select_related("employe", "employe__fonction", "contrat", "contrat__type_contrat").prefetch_related(
                "kpay_operations"
            )
        ],
    },
    "contrats": {
        "model": models.ContratEmploye,
        "form": forms.ContratForm,
        "title": "Contrats",
        "singular": "un contrat",
        "wide": set(),
        "columns": [
            {"label": "Employé"},
            {"label": "Type"},
            {"label": "Début"},
            {"label": "Fin"},
            {"label": "Salaire"},
            {"label": "Statut", "badge": True},
        ],
        "queryset": lambda soc: models.ContratEmploye.objects.filter(
            employe__societe=soc
        ).select_related("employe", "type_contrat"),
        "rows": lambda soc: [
            {
                "pk": c.pk,
                "del_name": f"{c.employe} — {c.type_contrat.code}",
                "cells": [
                    f"{c.employe.prenom} {c.employe.nom}",
                    f"{c.type_contrat.code} — {c.type_contrat.nom}",
                    _date(c.date_debut),
                    _date(c.date_fin),
                    _money(c.salaire_contractuel),
                    c.statut,
                ],
                "data": {
                    "employe": c.employe_id or "",
                    "type_contrat": c.type_contrat_id or "",
                    "date_debut": c.date_debut.isoformat() if c.date_debut else "",
                    "date_fin": c.date_fin.isoformat() if c.date_fin else "",
                    "salaire_contractuel": str(c.salaire_contractuel or ""),
                    "statut": c.statut,
                },
            }
            for c in models.ContratEmploye.objects.filter(
                employe__societe=soc
            ).select_related("employe", "type_contrat")
        ],
    },
    "echeances": {
        "model": models.EcheancePaiement,
        "form": forms.EcheanceForm,
        "title": "Échéances",
        "singular": "une échéance",
        "template": "gestion/crud_echeances.html",
        "wide": set(),
        "columns": [
            {"label": "Projet"},
            {"label": "N°"},
            {"label": "Montant"},
            {"label": "Date prévue"},
            {"label": "Statut", "badge": True},
        ],
        "queryset": lambda soc: models.EcheancePaiement.objects.filter(
            projet__societe=soc
        ).select_related("projet"),
        "rows": lambda soc: [
            {
                "pk": e.pk,
                "del_name": f"Échéance #{e.numero_echeance} — {e.projet.nom}",
                "paye": e.statut == "PAYEE",
                "telephone": (
                    e.projet.client.telephone_1 if e.projet.client_id else ""
                ),
                "kpay_statut": _kpay_info(list(e.kpay_operations.all()))[0],
                "kpay_pk": _kpay_info(list(e.kpay_operations.all()))[1],
                "kpay_type": _kpay_info(list(e.kpay_operations.all()))[2],
                "cells": [
                    e.projet.nom,
                    str(e.numero_echeance),
                    _money(e.montant_prevu),
                    _date(e.date_prevue),
                    e.statut,
                ],
                "data": {
                    "projet": e.projet_id or "",
                    "numero_echeance": str(e.numero_echeance or ""),
                    "montant_prevu": str(e.montant_prevu or ""),
                    "date_prevue": e.date_prevue.isoformat() if e.date_prevue else "",
                    "statut": e.statut,
                },
            }
            for e in models.EcheancePaiement.objects.filter(
                projet__societe=soc
            ).select_related("projet", "projet__client").prefetch_related(
                "kpay_operations"
            )
        ],
    },
    "paiements": {
        "model": models.PaiementClient,
        "form": forms.PaiementForm,
        "title": "Paiements",
        "singular": "un paiement",
        "wide": {"projet", "echeance"},
        "columns": [
            {"label": "Projet"},
            {"label": "Montant"},
            {"label": "Date"},
            {"label": "Mode"},
            {"label": "Référence"},
            {"label": "Statut", "badge": True},
        ],
        "queryset": lambda soc: models.PaiementClient.objects.filter(
            projet__societe=soc
        ).select_related("projet", "mode_paiement"),
        "rows": lambda soc: [
            {
                "pk": p.pk,
                "del_name": f"Paiement {p.projet.nom} ({p.montant})",
                "cells": [
                    p.projet.nom,
                    _money(p.montant),
                    _date(p.date_paiement),
                    p.mode_paiement.nom if p.mode_paiement else "—",
                    p.reference or "—",
                    p.statut,
                ],
                "data": {
                    "projet": p.projet_id or "",
                    "echeance": p.echeance_id or "",
                    "montant": str(p.montant or ""),
                    "date_paiement": p.date_paiement.isoformat() if p.date_paiement else "",
                    "mode_paiement": p.mode_paiement_id or "",
                    "reference": p.reference or "",
                    "statut": p.statut,
                },
            }
            for p in models.PaiementClient.objects.filter(
                projet__societe=soc
            ).select_related("projet", "mode_paiement")
        ],
    },
    "roles": {
        "model": models.Role,
        "form": forms.RoleForm,
        "title": "Rôles & Permissions",
        "singular": "un rôle",
        "wide": {"description"},
        "columns": [
            {"label": "Rôle"},
            {"label": "Description"},
            {"label": "Statut", "badge": True},
        ],
        "queryset": lambda soc: soc.roles.all(),
        "rows": lambda soc: [
            {
                "pk": r.pk,
                "del_name": r.nom,
                "cells": [r.nom, r.description or "—", r.statut],
                "data": {
                    "nom": r.nom,
                    "description": r.description or "",
                    "statut": r.statut,
                },
            }
            for r in soc.roles.all()
        ],
    },
    "fonctions": {
        "model": models.Fonction,
        "form": forms.FonctionForm,
        "title": "Fonctions",
        "singular": "une fonction",
        "wide": {"description"},
        "columns": [
            {"label": "Fonction"},
            {"label": "Description"},
            {"label": "Actif", "badge": True},
        ],
        "queryset": lambda soc: soc.fonctions.all(),
        "rows": lambda soc: [
            {
                "pk": f.pk,
                "del_name": f.nom,
                "cells": [f.nom, f.description or "—", "ACTIF" if f.actif else "INACTIF"],
                "data": {"nom": f.nom, "description": f.description or "", "actif": f.actif},
            }
            for f in soc.fonctions.all()
        ],
    },
    "documents": {
        "model": models.SocieteDocument,
        "form": forms.SocieteDocumentForm,
        "title": "Documents",
        "singular": "un document",
        "wide": set(),
        "columns": [
            {"label": "Document"},
            {"label": "Numéro"},
            {"label": "Fichier"},
            {"label": "Émission"},
            {"label": "Expiration"},
        ],
        "queryset": lambda soc: soc.documents.all(),
        "rows": lambda soc: [
            {
                "pk": d.pk,
                "del_name": f"{d.type_document} — {d.numero_document or ''}".strip(" —"),
                "cells": [
                    d.type_document,
                    d.numero_document or "—",
                    _link_document("societe", d.pk) if d.fichier else "—",
                    _date(d.date_emission),
                    _date(d.date_expiration),
                ],
                "data": {
                    "type_document": d.type_document,
                    "numero_document": d.numero_document or "",
                    "date_emission": d.date_emission.isoformat() if d.date_emission else "",
                    "date_expiration": d.date_expiration.isoformat() if d.date_expiration else "",
                },
            }
            for d in soc.documents.all()
        ],
    },
    "prospection": {
        "model": models.ProspectionClient,
        "form": forms.ProspectionForm,
        "title": "Prospection",
        "singular": "un prospect",
        "wide": {"description"},
        "columns": [
            {"label": "Prospect"},
            {"label": "Contact"},
            {"label": "Source"},
            {"label": "Responsable"},
            {"label": "Statut", "badge": True},
            {"label": "Budget"},
            {"label": "Prospection"},
        ],
        "queryset": lambda soc: soc.prospections.select_related("responsable"),
        "rows": lambda soc: [
            {
                "pk": pr.pk,
                "del_name": pr.nom,
                "cells": [
                    pr.nom,
                    pr.contact or "—",
                    pr.get_source_display(),
                    (
                        f"{pr.responsable.prenom} {pr.responsable.nom}".strip()
                        if pr.responsable else "—"
                    ),
                    pr.statut,
                    _money(pr.budget_estime) if pr.budget_estime else "—",
                    _date(pr.date_prospection),
                ],
                "data": {
                    "nom": pr.nom,
                    "contact": pr.contact or "",
                    "source": pr.source,
                    "responsable": pr.responsable_id or "",
                    "email": pr.email or "",
                    "telephone": pr.telephone or "",
                    "ville": pr.ville or "",
                    "pays": pr.pays or "",
                    "budget_estime": str(pr.budget_estime or ""),
                    "statut": pr.statut,
                    "date_prospection": (
                        pr.date_prospection.isoformat()
                        if pr.date_prospection else ""
                    ),
                    "description": pr.description or "",
                    "type_client": pr.type_client_id or "",
                },
            }
            for pr in soc.prospections.select_related("responsable")
        ],
    },
}