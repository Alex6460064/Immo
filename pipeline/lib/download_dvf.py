"""Telechargement du DVF brut DGFiP (data.gouv.fr) filtre sur les communes ciblees.

Source verifiee en direct via l'API data.gouv.fr le 2026-08-25 (pas depuis la memoire
du modele, voir CLAUDE.md priorite #1 : exactitude des donnees) :

- Dataset "Demandes de valeurs foncieres" (DGFiP), id 5c4ae55a634f4117716d5656,
  https://www.data.gouv.fr/api/1/datasets/5c4ae55a634f4117716d5656/
  organisation "Ministeres economiques et financiers" -> c'est le fichier officiel
  brut DGFiP retenu par ADR 0002.
- PAS "Demandes de valeurs foncieres geolocalisees" (id 5cc1b94a634f4165e96436c1,
  organisation "data.gouv.fr") : c'est geo-dvf Etalab, deja geolocalise/normalise,
  explicitement rejete par ADR 0002 (masquerait le travail de geocodage vise par
  le portfolio).
- Chaque ressource du dataset officiel est un fichier "Valeurs foncieres <annee>"
  au format txt.zip (texte separateur "|"), fenetre glissante de 5 ans (2021-2025
  constate au 2026-08-25, mise a jour semestrielle avril/octobre) -- voir
  `description`/`temporal_coverage` du dataset. Pas de decoupage par departement :
  chaque fichier couvre la France entiere (hors Alsace/Moselle/Mayotte). Le
  telechargement HTTP recupere donc necessairement un fichier national, mais
  seules les lignes des communes ciblees (config/communes.py) sont ecrites sur
  disque dans data/raw/ -- voir pipeline/download_dvf.py.

Ce module ne contient que la logique pure (parsing de la reponse API, decision
"faut-il telecharger"), testable sans reseau. Le telechargement HTTP, l'extraction
zip et le filtrage DuckDB sont dans pipeline/download_dvf.py (I/O, pas de tests
unitaires directs -- voir tests d'integration sur le script lui-meme).
"""

from __future__ import annotations

import re
from pathlib import Path

DATASET_API_URL = "https://www.data.gouv.fr/api/1/datasets/5c4ae55a634f4117716d5656/"

# Format des ressources du dataset officiel : le seul format de donnees (les autres
# resources sont des documents annexes -- FAQ, CGU, notice -- en pdf).
DVF_RESOURCE_FORMAT = "txt.zip"

_YEAR_RE = re.compile(r"(20\d{2})")


def parse_resource_year(title: str) -> int | None:
    """Extrait le millesime d'un titre de ressource data.gouv.fr.

    Exemple : "Valeurs foncieres 2025" -> 2025. None si aucune annee sur 4 chiffres
    commencant par "20" n'est trouvee (cas des documents annexes sans millesime).
    """
    match = _YEAR_RE.search(title)
    if match is None:
        return None
    return int(match.group(1))


def select_dvf_resources(resources: list[dict]) -> list[dict]:
    """Filtre les resources JSON de l'API data.gouv.fr aux fichiers DVF par millesime.

    Ignore tout ce qui n'est pas au format `DVF_RESOURCE_FORMAT` ou dont le titre ne
    contient pas d'annee identifiable (FAQ, CGU, notice descriptive, ...).

    Retourne une liste de {"year": int, "url": str, "title": str}, triee par annee
    croissante.
    """
    selected = []
    for resource in resources:
        if resource.get("format") != DVF_RESOURCE_FORMAT:
            continue
        year = parse_resource_year(resource.get("title") or "")
        if year is None:
            continue
        url = resource.get("url")
        if not url:
            continue
        selected.append({"year": year, "url": url, "title": resource.get("title")})
    return sorted(selected, key=lambda r: r["year"])


def output_path_for_year(year: int, data_dir: str | Path) -> Path:
    """Chemin du fichier filtre (communes ciblees uniquement) pour un millesime donne."""
    return Path(data_dir) / f"dvf_brut_{year}.parquet"


def should_download(year: int, data_dir: str | Path) -> bool:
    """True si le fichier filtre de ce millesime n'est pas deja en cache.

    Idempotence : un millesime deja telecharge et filtre n'est jamais retelecharge
    silencieusement -- voir CLAUDE.md, "ne jamais relancer un telechargement complet
    sans raison explicite".
    """
    return not output_path_for_year(year, data_dir).exists()
