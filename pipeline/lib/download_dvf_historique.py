"""Telechargement du DVF brut DGFiP historique (millesimes 2016-2020), hors fenetre
glissante officielle de data.gouv.fr -- voir Rechercheavant2021.md pour la recherche
de source et docs/adr/0005-source-historique-dvf-2016-2020.md pour la decision.

Source verifiee en direct (curl) le 2026-08-26 : le miroir communautaire
`data.cquest.org/dgfip_dvf/202104/` (Christian Quest, contributeur reconnu de
l'open data francais) archive l'edition DGFiP d'avril 2021 -- la derniere edition
avant que la fenetre glissante officielle n'exclue 2016. Cette edition couvre les
millesimes 2016 a 2020 complets, au format pipe-delimited quasi identique au fichier
officiel actuel (voir pipeline/lib/download_dvf.py) : une seule difference de schema
constatee, la colonne `Code service CH` (miroir historique) remplace `Identifiant de
document` (fichier officiel) -- alias gere ici, jamais silencieusement ignore.

Contrairement au flux officiel (.txt.zip), ces fichiers sont des .txt non compresses
et non decoupes par departement -- meme volume national a filtrer, pas de zip a
extraire.

Ce module ne contient que la logique pure (URL par millesime, millesimes couverts,
alias de colonne), testable sans reseau. `output_path_for_year`/`should_download`
sont reutilises tels quels depuis pipeline/lib/download_dvf.py (meme convention de
nommage `dvf_brut_{year}.parquet` dans data/raw/, pas de duplication).
"""

from __future__ import annotations

# Reexportes pour l'usage du script d'I/O (pipeline/download_dvf_historique.py) --
# meme convention de cache/nommage que le flux officiel, pas de logique dupliquee.
from pipeline.lib.download_dvf import output_path_for_year, should_download  # noqa: F401

# Edition cquest d'avril 2021 : derniere edition de la fenetre glissante officielle
# a couvrir 2016 (voir Rechercheavant2021.md section 2a, verifie en direct).
HISTORICAL_EDITION_URL = "http://data.cquest.org/dgfip_dvf/202104"

# Millesimes couverts par cette edition -- seule source de verite sur ces bornes,
# aucune autre valeur codee en dur ailleurs dans le pipeline pour ce lot historique.
HISTORICAL_YEARS: tuple[int, ...] = (2016, 2017, 2018, 2019, 2020)

# Difference de schema constatee entre le miroir historique et le fichier officiel
# actuel (voir docstring du module) : alias applique a l'ecriture du parquet, jamais
# silencieux.
HISTORICAL_COLUMN_ALIASES: dict[str, str] = {"Code service CH": "Identifiant de document"}


def historical_years() -> list[int]:
    """Millesimes disponibles sur l'edition cquest utilisee, tries par annee croissante."""
    return sorted(HISTORICAL_YEARS)


def historical_url_for_year(year: int) -> str:
    """URL du fichier .txt du miroir cquest pour un millesime donne.

    Leve ValueError si `year` n'est pas couvert par HISTORICAL_EDITION_URL --
    mieux vaut un echec explicite qu'une URL construite pour un millesime que
    l'edition ne contient pas (voir Rechercheavant2021.md : chaque edition ne
    couvre que sa propre fenetre glissante).
    """
    if year not in HISTORICAL_YEARS:
        raise ValueError(
            f"Millesime {year} non couvert par l'edition cquest {HISTORICAL_EDITION_URL} "
            f"(millesimes disponibles : {historical_years()})"
        )
    return f"{HISTORICAL_EDITION_URL}/valeursfoncieres-{year}.txt"


def alias_historical_columns(columns: list[str]) -> list[str]:
    """Renomme les colonnes du miroir historique vers les noms du fichier officiel.

    Seule la colonne listee dans HISTORICAL_COLUMN_ALIASES est renommee ; toutes
    les autres colonnes (identiques entre les deux sources) sont laissees telles
    quelles.
    """
    return [HISTORICAL_COLUMN_ALIASES.get(c, c) for c in columns]
