"""Communes ciblees par le projet DVF x DPE Pays Basque.

Source de verite unique (single source of truth) pour le perimetre geographique :
toute etape du pipeline (telechargement, filtrage, agregation) et le dashboard
doivent lire cette liste plutot que hardcoder des noms ou codes INSEE ailleurs.

Codes INSEE verifies le 2026-08-25 via l'API officielle geo.api.gouv.fr
(https://geo.api.gouv.fr/communes?nom=<commune>&fields=code,nom,codeDepartement&boost=population),
pas depuis la memoire du modele — voir CLAUDE.md, priorite #1 : exactitude des donnees.

14 communes du littoral Pays Basque / proche BAB (dept. 64) + 2 communes du dept. 40
(Tarnos, Ondres) incluses comme exception explicite et documentee pour la comparaison
BAB / rive gauche de l'Adour — voir ADR 0001 (docs/adr/0001-communes-hors-dept-64.md).
Le telechargement DVF filtre par code INSEE de commune, jamais par departement entier.
"""

from __future__ import annotations

COMMUNES: list[dict[str, str]] = [
    {"nom": "Anglet", "code_insee": "64024", "departement": "64"},
    {"nom": "Biarritz", "code_insee": "64122", "departement": "64"},
    {"nom": "Bayonne", "code_insee": "64102", "departement": "64"},
    {"nom": "Boucau", "code_insee": "64140", "departement": "64"},
    {"nom": "Saint-Pierre-d'Irube", "code_insee": "64496", "departement": "64"},
    {"nom": "Bassussarry", "code_insee": "64100", "departement": "64"},
    {"nom": "Arcangues", "code_insee": "64038", "departement": "64"},
    {"nom": "Arbonne", "code_insee": "64035", "departement": "64"},
    {"nom": "Bidart", "code_insee": "64125", "departement": "64"},
    {"nom": "Guéthary", "code_insee": "64249", "departement": "64"},
    {"nom": "Saint-Jean-de-Luz", "code_insee": "64483", "departement": "64"},
    {"nom": "Urrugne", "code_insee": "64545", "departement": "64"},
    {"nom": "Hendaye", "code_insee": "64260", "departement": "64"},
    {"nom": "Hasparren", "code_insee": "64256", "departement": "64"},
    # Exception documentee (ADR 0001) : dept. 40, comparaison BAB uniquement.
    {"nom": "Tarnos", "code_insee": "40312", "departement": "40"},
    {"nom": "Ondres", "code_insee": "40209", "departement": "40"},
]


def get_communes(departement: str | None = None) -> list[dict[str, str]]:
    """Retourne les communes ciblees, filtrees par departement si precise."""
    if departement is None:
        return COMMUNES
    return [c for c in COMMUNES if c["departement"] == departement]


def get_codes_insee(departement: str | None = None) -> list[str]:
    """Retourne les codes INSEE des communes ciblees, filtres par departement si precise."""
    return [c["code_insee"] for c in get_communes(departement)]
