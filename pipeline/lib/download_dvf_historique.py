"""Telechargement du DVF brut DGFiP historique (millesimes 2016-2020), hors fenetre
glissante officielle de data.gouv.fr -- voir Rechercheavant2021.md pour la recherche
de source et docs/adr/0005-source-historique-dvf-2016-2020.md pour la decision.

Source : le miroir communautaire `data.cquest.org/dgfip_dvf/` (Christian Quest,
contributeur reconnu de l'open data francais) archive chaque edition semestrielle
DGFiP. Un millesime est republie a chaque edition tant qu'il reste dans la fenetre
glissante, et s'y complete (enregistrements tardifs) : sa 1re publication est
sous-estimee (2020 dans l'edition 202104 : ~moitie des lignes, voir #45). Chaque
millesime est donc pris dans la **derniere** edition qui le contient (verifie en
direct le 2026-09-26, voir HISTORICAL_SOURCES).

Format pipe-delimited quasi identique au fichier officiel actuel (voir
pipeline/lib/download_dvf.py) : les editions anciennes nomment `Code service CH` la
colonne `Identifiant de document` -- alias gere ici, jamais silencieusement ignore.
Les editions jusqu'a 202404 servent des .txt non compresses, les suivantes des
.txt.zip.

Ce module ne contient que la logique pure (URL par millesime, millesimes couverts,
alias de colonne), testable sans reseau. `output_path_for_year`/`should_download`
sont reutilises tels quels depuis pipeline/lib/download_dvf.py (meme convention de
nommage `dvf_brut_{year}.parquet` dans data/raw/, pas de duplication).
"""

from __future__ import annotations

# Reexportes pour l'usage du script d'I/O (pipeline/download_dvf_historique.py) --
# meme convention de cache/nommage que le flux officiel, pas de logique dupliquee.
from pipeline.lib.download_dvf import output_path_for_year, should_download  # noqa: F401

CQUEST_BASE_URL = "http://data.cquest.org/dgfip_dvf"

# Millesime -> (edition, extension) : derniere edition cquest contenant le millesime
# (#45). Seule source de verite sur les bornes du lot historique.
HISTORICAL_SOURCES: dict[int, tuple[str, str]] = {
    2016: ("202110", "txt"),
    2017: ("202204", "txt"),
    2018: ("202304", "txt"),
    2019: ("202404", "txt"),
    2020: ("202504", "txt.zip"),
}
HISTORICAL_YEARS: tuple[int, ...] = tuple(sorted(HISTORICAL_SOURCES))

# Difference de schema constatee entre le miroir historique et le fichier officiel
# actuel (voir docstring du module) : alias applique a l'ecriture du parquet, jamais
# silencieux.
HISTORICAL_COLUMN_ALIASES: dict[str, str] = {"Code service CH": "Identifiant de document"}

# Colonnes attendues dans l'en-tete du fichier source, presentes AVANT alias des
# deux cotes (miroir historique et fichier officiel). Sert a distinguer un vrai
# fichier DVF d'une page d'erreur HTML / d'une redirection renvoyee par le miroir.
_HEADER_SENTINELS: tuple[str, ...] = (
    "Date mutation",
    "Nature mutation",
    "Valeur fonciere",
    "Code departement",
    "Code commune",
)


def validate_historical_header(header_line: str) -> None:
    """Verifie que la premiere ligne du fichier telecharge est bien un en-tete DVF.

    Le miroir communautaire cquest n'offre aucune garantie de disponibilite
    (voir docs/adr/0005) : s'il renvoie une page d'erreur HTML, un stub de
    redirection ou un format inattendu, on veut un echec explicite ici plutot
    qu'une binder error DuckDB opaque ou un silencieux "0 ligne retenue".

    Leve ValueError si la ligne n'est pas pipe-delimitee ou si une colonne
    sentinelle (_HEADER_SENTINELS) manque.
    """
    if "|" not in header_line:
        raise ValueError(
            "Le fichier telecharge n'est pas pipe-delimite -- page d'erreur HTML ou "
            f"redirection renvoyee par le miroir ? Debut recu : {header_line[:120]!r}"
        )

    columns = {c.strip() for c in header_line.split("|")}
    missing = [s for s in _HEADER_SENTINELS if s not in columns]
    if missing:
        raise ValueError(
            f"En-tete DVF historique inattendu : colonnes sentinelles absentes {missing}. "
            f"Colonnes vues : {sorted(columns)}"
        )


# Colonnes lues par pipeline/02_clean_dvf.py (_RAW_SELECT_QUERY) apres alias
# historique. Verifier leur presence des le telechargement transforme un echec
# aval silencieux (0 ligne, ou binder error dans 02_clean_dvf) en erreur explicite
# a la source.
_DOWNSTREAM_REQUIRED_COLUMNS: tuple[str, ...] = (
    "Identifiant de document",
    "No disposition",
    "Date mutation",
    "Nature mutation",
    "Valeur fonciere",
    "No voie",
    "B/T/Q",
    "Type de voie",
    "Voie",
    "Code postal",
    "Commune",
    "Code departement",
    "Code commune",
    "Type local",
    "Nombre pieces principales",
    "Surface reelle bati",
)


def require_downstream_columns(columns: list[str]) -> None:
    """Verifie que toutes les colonnes consommees en aval par 02_clean_dvf.py sont
    presentes dans `columns` (l'en-tete du fichier historique, apres alias).

    Leve ValueError listant les colonnes manquantes -- un drift de schema du miroir
    (delimiteur, noms de colonnes) doit echouer ici, pas se traduire par un parquet
    aval vide.
    """
    present = set(columns)
    missing = [c for c in _DOWNSTREAM_REQUIRED_COLUMNS if c not in present]
    if missing:
        raise ValueError(
            f"Colonnes requises par 02_clean_dvf.py absentes du fichier historique "
            f"(apres alias) : {missing}. Colonnes presentes : {sorted(present)}"
        )


def historical_years() -> list[int]:
    """Millesimes du lot historique, tries par annee croissante."""
    return list(HISTORICAL_YEARS)


def historical_url_for_year(year: int) -> str:
    """URL du fichier (.txt ou .txt.zip) du miroir cquest pour un millesime donne.

    Leve ValueError si `year` n'est pas dans HISTORICAL_SOURCES -- mieux vaut un
    echec explicite qu'une URL construite pour un millesime qu'aucune edition
    retenue ne contient (chaque edition ne couvre que sa fenetre glissante).
    """
    if year not in HISTORICAL_SOURCES:
        raise ValueError(
            f"Millesime {year} hors du lot historique cquest "
            f"(millesimes disponibles : {historical_years()})"
        )
    edition, extension = HISTORICAL_SOURCES[year]
    return f"{CQUEST_BASE_URL}/{edition}/valeursfoncieres-{year}.{extension}"


def alias_historical_columns(columns: list[str]) -> list[str]:
    """Renomme les colonnes du miroir historique vers les noms du fichier officiel.

    Seule la colonne listee dans HISTORICAL_COLUMN_ALIASES est renommee ; toutes
    les autres colonnes (identiques entre les deux sources) sont laissees telles
    quelles.

    Leve ValueError si le fichier source contient a la fois une colonne a aliaser
    et sa cible : le renommage produirait deux colonnes de meme nom, ambigues a
    l'ecriture du parquet -- schema source a revoir plutot qu'a deviner.
    """
    for source, target in HISTORICAL_COLUMN_ALIASES.items():
        if source in columns and target in columns:
            raise ValueError(
                f"Collision d'alias : le fichier source contient a la fois {source!r} et "
                f"sa cible {target!r}. Schema source inattendu, alias ambigu."
            )
    return [HISTORICAL_COLUMN_ALIASES.get(c, c) for c in columns]
